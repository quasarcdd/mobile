"""
导出预翻译数据 + 原文数据。

复用上游《贝娜的量角器》的翻译引擎（bena / anne / node_translator / relic_translator），
把结果拍平成一份 JSON：

    {
      "meta":  { 构建信息 },
      "index": [ [type, key, 显示名, 搜索文本], ... ],   # 目录，顺序与 data 一一对应
      "data":  [ [译文树, [原文紧凑JSON字符串, ...]], ... ]
    }

type: 0=常见Buff  1=Buff模板  2=全局Buff  3=肉鸽物品
"""
import os
import sys
import json
import time
import gzip
import argparse

HERE = os.path.dirname(os.path.abspath(__file__))

TYPES = ["buff", "buff_template", "global_buff", "rogue_item"]
TYPE_ID = {name: i for i, name in enumerate(TYPES)}


class _Sink:
    """上游代码会疯狂 print，全部丢掉"""

    def write(self, *a):
        pass

    def flush(self):
        pass

    def isatty(self):
        return False


_real = sys.stdout


def compact(obj):
    return json.dumps(obj, ensure_ascii=False, separators=(",", ":"))


def count_markers(node):
    """统计译文树里的『未翻译』/『翻译失败』节点数"""
    if not isinstance(node, dict):
        return 0, 0
    text = str(node.get("main", "")) + str(node.get("true", "")) + str(node.get("false", ""))
    untranslated = 1 if "未翻译" in text else 0
    failed = 1 if "翻译失败" in text else 0
    for child in (node.get("children") or []):
        a, b = count_markers(child)
        untranslated += a
        failed += b
    return untranslated, failed


def _well_formed(text):
    """每个 '>' 前面都必须有未配对的 '<'。

    bena.translate_buff_name_in_text 取的是「第一个 <」和「第一个 >」，
    一旦出现 '>' 排在 '<' 前面，替换后文本反而变长，会死循环。
    桌面端只在用户点开单条时渲染，这里要一次性跑一万多条，必须先把这种脏数据挡掉。
    """
    depth = 0
    for ch in text:
        if ch == "<":
            depth += 1
        elif ch == ">":
            if depth == 0:
                return False
            depth -= 1
    return True


def polish_text(text):
    """把 <buff_key> 就地翻译成中文名（桌面端是在渲染时做的，这里提前到构建期）"""
    if not isinstance(text, str) or "<" not in text or ">" not in text:
        return text
    if not _well_formed(text):
        return text
    try:
        return bena.translate_buff_name_in_text(text)
    except Exception:
        return text


def polish(node):
    if not isinstance(node, dict):
        return node
    for k in ("main", "description", "true", "false"):
        if k in node:
            node[k] = polish_text(node[k])
    kids = node.get("children")
    if isinstance(kids, list):
        for child in kids:
            polish(child)
    return node


def build(seasons):
    index = []
    data = []
    stats = {t: {"total": 0, "shown": 0, "error": 0, "untranslated": 0, "failed": 0} for t in TYPES}

    def add(type_name, key, display_name, translation, raw_list):
        index.append([TYPE_ID[type_name], key, display_name, display_name + " " + key])
        data.append([translation, raw_list])
        stats[type_name]["shown"] += 1

    def emit(type_name, key, display_name, translate, raw_list):
        try:
            trans = polish(translate())
        except Exception as e:
            trans = {"main": "%s（翻译异常：%s）" % (key, type(e).__name__)}
            stats[type_name]["error"] += 1
        u, f = count_markers(trans)
        stats[type_name]["untranslated"] += u
        stats[type_name]["failed"] += f
        add(type_name, key, display_name, trans, raw_list)

    stats["buff"]["total"] = len(bena.BUFF_KEYS)
    for key in bena.BUFF_KEYS:
        obj = bena.BUFF_TABLE[key]
        emit("buff", key, "[Buff]" + obj.display_name,
             lambda o=obj: anne.translate_whole_buff(o), [compact(obj.buff_data)])

    stats["buff_template"]["total"] = len(bena.BUFF_TEMPLATE_KEYS)
    for key in bena.BUFF_TEMPLATE_KEYS:
        obj = bena.BUFF_TEMPLATE_DATA[key]
        emit("buff_template", key, "[模板]" + obj.display_name,
             lambda o=obj: anne.translate_whole_buff_template(o), [compact(obj.buff_data)])

    stats["global_buff"]["total"] = len(bena.GLOBAL_BUFF_KEYS)
    for key in bena.GLOBAL_BUFF_KEYS:
        obj = bena.GLOBAL_BUFF_DUMMY[key]
        emit("global_buff", key, "[GBuff]" + obj.display_name,
             lambda o=obj: anne.translate_whole_global_buff(o), [compact(obj.prefab_data)])

    stats["rogue_item"]["total"] = len(bena.ROGUELIKE_TOPIC_KEYS)
    for key in bena.ROGUELIKE_TOPIC_KEYS:
        obj = bena.ROGUELIKE_TOPIC_TABLE[key]
        if obj.hidden:  # 与桌面端一致：隐藏项不进目录
            continue
        raw = [compact(obj.item_info)]
        if obj.item_data is not None:
            raw.append(compact(obj.item_data))
        emit("rogue_item", key, "[" + obj.display_type + "]" + obj.display_name,
             lambda o=obj: anne.translate_whole_rogue_item(o), raw)

    return index, data, stats


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", default=os.path.join(HERE, ".src"), help="上游源码目录")
    ap.add_argument("--seasons", default="1,2,3,4,5,6", help="要包含的肉鸽季度，逗号分隔")
    ap.add_argument("-o", "--output", default=os.path.join(HERE, "data.json"))
    ap.add_argument("--gz", default="", help="同时输出 gzip 版本到该路径")
    ap.add_argument("--meta", default="{}", help="附加到 meta 的 JSON 字符串")
    args = ap.parse_args()

    seasons = [int(s) for s in args.seasons.split(",") if s.strip()]

    src = os.path.abspath(args.src)
    if not os.path.isdir(src):
        sys.exit("找不到上游源码目录：%s" % src)

    global bena, anne
    sys.stdout = _Sink()
    try:
        sys.path.insert(0, HERE)
        sys.path.insert(0, src)
        os.chdir(src)

        import bena
        import anne
        import compat
        compat.apply()

        t0 = time.perf_counter()
        bena.load_character_names()
        bena.load_enemy_names()
        bena.load_buff_table()
        bena.load_buff_template_data()
        bena.load_global_buff_dummy()
        for s in seasons:
            bena.load_roguelike_topic_table(s)
        load_seconds = time.perf_counter() - t0

        t1 = time.perf_counter()
        index, data, stats = build(seasons)
        build_seconds = time.perf_counter() - t1
    finally:
        sys.stdout = _real

    meta = {
        "builtAt": time.strftime("%Y-%m-%d %H:%M:%S"),
        "seasons": seasons,
        "types": TYPES,
        "count": len(index),
    }
    try:
        meta.update(json.loads(args.meta))
    except Exception:
        pass

    blob = json.dumps({"meta": meta, "index": index, "data": data},
                      ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    with open(args.output, "wb") as f:
        f.write(blob)

    gz = gzip.compress(blob, 9)
    if args.gz:
        with open(args.gz, "wb") as f:
            f.write(gz)

    print("载入 %.2fs | 翻译 %.2fs | 导出 %d 条" % (load_seconds, build_seconds, len(index)))
    for t in TYPES:
        s = stats[t]
        print("  %-14s 总 %5d  收录 %5d  整条异常 %2d  未翻译节点 %5d  失败节点 %3d"
              % (t, s["total"], s["shown"], s["error"], s["untranslated"], s["failed"]))
    print("data.json %.2f MB | gzip %.2f MB | 压缩率 %.1f%%"
          % (len(blob) / 1048576, len(gz) / 1048576, len(gz) * 100.0 / max(len(blob), 1)))


if __name__ == "__main__":
    main()
