"""
导出预翻译数据 + 原文数据。

复用上游《贝娜的量角器》的翻译引擎（bena / anne），把结果拍平成一份 JSON：

    {
      "meta":  { 构建信息 },
      "index": [ [type, key, 显示名, 搜索文本, 子分类], ... ],   # 目录，顺序与 data 一一对应
      "data":  [ [译文树, [原文紧凑JSON字符串, ...]], ... ]
    }

译文树节点：{main, description?, true?, false?, children?, style_closed?}
文本字段平时是字符串；出现 <Category|key> 交叉引用时变成
[[文本, 跳转目标或 null], ...]，由前端渲染成可点标签。

type 下标见 TYPES。子分类用于「肉鸽季度 / 卫戍协议类别 / 全息关卡」这类二级筛选，
具体标签由 meta.subs 描述，前端据此生成筛选按钮。
"""
import os
import re
import sys
import json
import time
import gzip
import argparse

HERE = os.path.dirname(os.path.abspath(__file__))

# 上游把 Buff / BuffTemplate / GlobalBuff 三类都挂在数据表 "buff" 下，
# 这里按对象类型再拆开，让前端能分别筛选。
TYPES = ["buff", "buff_template", "global_buff", "rogue_item", "autochess", "recal_rune"]
TYPE_ID = {name: i for i, name in enumerate(TYPES)}

CLASS_TO_TYPE = {
    "Buff": "buff",
    "BuffTemplate": "buff_template",
    "GlobalBuff": "global_buff",
    "RogueItem": "rogue_item",
    "AutochessCharChess": "autochess",
    "AutochessEffect": "autochess",
    "AutochessBand": "autochess",
    "Crisis": "recal_rune",
}

TYPE_PREFIX = {
    "buff": "[Buff]",
    "buff_template": "[模板]",
    "global_buff": "[GBuff]",
    # 全息作战矩阵的 catagory 是关卡名（H11-1 尘霾行动-1 之类），拿它当标签太长，
    # 关卡改用二级筛选，标题统一叫「全息」
    "recal_rune": "[全息]",
}

# 肉鸽季度短名，与 meta.subs 里给出的标签一致
SEASON_LABEL = {
    1: "傀影", 2: "水月", 3: "萨米", 4: "萨卡兹", 5: "界园", 6: "黑流树海",
}

# 与上游 document_model.REFERENCE_PATTERN 保持一致：<类别|原始key>
REFERENCE_PATTERN = re.compile(r"<([A-Za-z0-9_]*)\|([^<>|\r\n]+)>")
# 这几类的引用即使查不到条目，也能退回「中文名（原始key）」
BUFF_LIKE = ("Buff", "BuffTemplate", "GlobalBuff", "CardBuff")


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
    untranslated = failed = 0
    for key in ("main", "description", "true", "false"):
        text = field_text(node.get(key))
        if "未翻译" in text:
            untranslated += 1
        if "翻译失败" in text:
            failed += 1
    for child in (node.get("children") or []):
        a, b = count_markers(child)
        untranslated += a
        failed += b
    return untranslated, failed


def field_text(value):
    """把文本字段统一成纯字符串（供统计与搜索使用）"""
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return "".join(part if isinstance(part, str) else str(part[0]) for part in value)
    return "" if value is None else str(value)


def make_refs(text, catalog, pos):
    """把 <Category|key> 就地换成「条目显示名」，并记下它在 index 里的位置。

    查不到条目时不允许留下死链：能查到中文名就退回「中文名（原始key）」，
    否则只留原始 key。这与上游桌面端的处理一致。
    位置直接写成整数，前端拿去做内部跳转；纯文本段就是普通字符串。
    """
    import bena

    if not isinstance(text, str) or "<" not in text or "|" not in text:
        return text

    parts = []
    offset = 0
    for match in REFERENCE_PATTERN.finditer(text):
        if match.start() > offset:
            parts.append(text[offset:match.start()])
        category, key = match.groups()
        entry = catalog.entries.get("%s.%s" % (category, key))
        if entry is not None:
            idx = pos.get(entry.target, -1)
            # 条目存在但没被导出（比如隐藏项）：只给名字，不给跳转
            parts.append([entry.name, idx] if idx >= 0 else entry.name)
        elif category in BUFF_LIKE:
            label = bena.translate_buff_name(key)
            parts.append(label + "（" + key + "）" if label != key else key)
        else:
            parts.append(key)
        offset = match.end()
    if not parts:
        return text
    if offset < len(text):
        parts.append(text[offset:])

    # 一整段纯文本就别用数组了，省体积
    if len(parts) == 1 and isinstance(parts[0], str):
        return parts[0]
    return parts


def normalize(node, catalog, pos):
    """译文树 → 精简结构：只留渲染要用的字段，链接就地解析"""
    if isinstance(node, list):
        return [normalize(child, catalog, pos) for child in node]
    if not isinstance(node, dict):
        # 上游允许 children 里直接放字符串
        return {"main": make_refs(field_text(node), catalog, pos)}

    out = {}
    for key in ("main", "description", "true", "false"):
        if key in node and node[key] is not None:
            out[key] = make_refs(node[key], catalog, pos)
    # true/false 不是文本而是别的类型时，退回字符串，别让渲染端拿到怪东西
    for key in ("true", "false"):
        if key in out and not isinstance(out[key], (str, list)):
            out[key] = field_text(node[key])
    kids = node.get("children")
    if isinstance(kids, list) and kids:
        out["children"] = [normalize(child, catalog, pos) for child in kids]
    if node.get("style_closed"):
        out["style_closed"] = 1
    # last_one：这一段是「动作序列的最后一步」，条件分支到它就没意义了，
    # 上游 document_model.document_rows 靠它决定要不要印「若…」。
    if node.get("last_one"):
        out["last_one"] = 1
    return out


def collect(catalog):
    """按类型分组，保持上游的加载顺序"""
    buckets = {name: [] for name in TYPES}
    for entry in catalog.entries.values():
        type_name = CLASS_TO_TYPE.get(entry.type_name)
        if type_name in buckets:
            buckets[type_name].append(entry)
    return buckets


def sub_plan(buckets):
    """规划二级分类：肉鸽按季度，卫戍协议与全息按上游给的类别"""
    subs = {}
    ids = {}

    seasons = []
    for entry in buckets["rogue_item"]:
        season = int(entry.table.split("_")[1])
        if season not in seasons:
            seasons.append(season)
    if seasons:
        subs["rogue_item"] = [[s, SEASON_LABEL.get(s, "第%d期" % s)] for s in sorted(seasons)]
        for s in seasons:
            ids[("rogue_item", s)] = s

    for type_name in ("autochess", "recal_rune"):
        labels = []
        for entry in buckets[type_name]:
            if entry.catagory not in labels:
                labels.append(entry.catagory)
        if len(labels) > 1:
            subs[type_name] = [[i + 1, label] for i, label in enumerate(labels)]
            for i, label in enumerate(labels):
                ids[(type_name, label)] = i + 1

    return subs, ids


def sub_of(type_name, entry, subs, ids):
    table = subs.get(type_name)
    if not table:
        return 0
    if type_name == "rogue_item":
        return ids[("rogue_item", int(entry.table.split("_")[1]))]
    return ids[(type_name, entry.catagory)]


def raw_of(entry):
    """原文：上游 get_raw_data 可能给 dict，也可能给 list（含 None）"""
    try:
        data = entry.obj.get_raw_data()
    except Exception:
        return []
    items = data if isinstance(data, list) else [data]
    return [compact(item) for item in items if item is not None]


def select(buckets, limit=0):
    """先定下「哪些条目会被导出」，好让交叉引用能算出行号。

    隐藏项（上游 obj.hidden）不导出——与桌面端默认视图一致。
    """
    chosen = []
    for type_name in TYPES:
        picked = []
        for entry in buckets[type_name]:
            if limit and len(picked) >= limit:
                break
            if getattr(entry.obj, "hidden", False):
                continue
            picked.append(entry)
        chosen.append((type_name, picked))
    return chosen


def build(catalog, limit=0):
    buckets = collect(catalog)
    subs, sub_ids = sub_plan(buckets)
    chosen = select(buckets, limit)

    # entry.target → 在 index/data 里的下标，供正文交叉引用直接写成行号
    pos = {}
    n = 0
    for type_name, entries in chosen:
        for entry in entries:
            pos[entry.target] = n
            n += 1

    index = []
    data = []
    stats = {t: {"total": 0, "shown": 0, "error": 0, "untranslated": 0, "failed": 0} for t in TYPES}

    for type_name, entries in chosen:
        stats[type_name]["total"] = len(buckets[type_name])
        prefix = TYPE_PREFIX.get(type_name)
        for entry in entries:
            obj = entry.obj
            try:
                trans = normalize(obj.translate(), catalog, pos)
            except Exception as e:
                trans = {"main": "%s（翻译异常：%s）" % (entry.key, type(e).__name__)}
                stats[type_name]["error"] += 1

            untranslated, failed = count_markers(trans)
            stats[type_name]["untranslated"] += untranslated
            stats[type_name]["failed"] += failed

            name = obj.get_display_name()
            label = prefix + name if prefix else "[" + entry.catagory + "]" + name
            index.append([TYPE_ID[type_name], entry.key, label,
                          # 搜索文本必须与前端 toLowerCase() 的结果可比，
                          # 所以用 lower() 而不是 casefold()（后者会把 ß 变成 ss）
                          (label + " " + entry.key + " " + entry.catagory).lower(),
                          sub_of(type_name, entry, subs, sub_ids)])
            data.append([trans, raw_of(entry)])
            stats[type_name]["shown"] += 1

    return index, data, stats, subs


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", default=os.path.join(HERE, ".src"), help="上游源码目录")
    ap.add_argument("--seasons", default="1,2,3,4,5,6", help="要包含的肉鸽季度，逗号分隔")
    ap.add_argument("-o", "--output", default=os.path.join(HERE, "data.json"))
    ap.add_argument("--gz", default="", help="同时输出 gzip 版本到该路径")
    ap.add_argument("--meta", default="{}", help="附加到 meta 的 JSON 字符串")
    ap.add_argument("--meta-out", default="", help="把最终 meta 单独写到该文件（给 build.py 用）")
    ap.add_argument("--limit", type=int, default=0, help="每类只导出前 N 条（调试用）")
    args = ap.parse_args()

    seasons = [int(s) for s in args.seasons.split(",") if s.strip()]

    src = os.path.abspath(args.src)
    if not os.path.isdir(src):
        sys.exit("找不到上游源码目录：%s" % src)

    # 下面会 os.chdir(src) 进上游源码目录（引擎按相对路径读数据），
    # 输出路径必须在这之前转成绝对路径，否则会落到 .src/ 里。
    output = os.path.abspath(args.output)
    gz_path = os.path.abspath(args.gz) if args.gz else ""
    meta_out = os.path.abspath(args.meta_out) if args.meta_out else ""

    def table_exists(name):
        return os.path.exists(os.path.join(src, "tables", name))

    tables = ["buff"] + ["rogue_%d" % s for s in seasons]
    if table_exists("activity_table.json"):
        tables.append("autochess_3")
    if table_exists("crisis_v2_table.json"):
        tables.append("recal_rune")

    catalog = None
    sys.stdout = _Sink()
    try:
        sys.path.insert(0, HERE)
        sys.path.insert(0, src)
        os.chdir(src)

        from bena.catalog import Catalog

        t0 = time.perf_counter()
        catalog = Catalog(tables).load().install()
        load_seconds = time.perf_counter() - t0

        t1 = time.perf_counter()
        index, data, stats, subs = build(catalog, args.limit)
        build_seconds = time.perf_counter() - t1
    finally:
        sys.stdout = _real

    meta = {
        "builtAt": time.strftime("%Y-%m-%d %H:%M:%S"),
        "seasons": seasons,
        "types": TYPES,
        "subs": subs,
        "count": len(index),
    }
    try:
        meta.update(json.loads(args.meta))
    except Exception:
        pass

    blob = json.dumps({"meta": meta, "index": index, "data": data},
                      ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    with open(output, "wb") as f:
        f.write(blob)

    if meta_out:
        with open(meta_out, "w", encoding="utf-8") as f:
            json.dump(meta, f, ensure_ascii=False)

    gz = gzip.compress(blob, 9)
    if gz_path:
        with open(gz_path, "wb") as f:
            f.write(gz)

    print("载入 %.2fs | 翻译 %.2fs | 导出 %d 条" % (load_seconds, build_seconds, len(index)))
    for t in TYPES:
        s = stats[t]
        print("  %-14s 总 %5d  收录 %5d  整条异常 %2d  未翻译节点 %5d  失败节点 %3d"
              % (t, s["total"], s["shown"], s["error"], s["untranslated"], s["failed"]))
    for warning in getattr(catalog, "warnings", []):
        print("  警告：" + warning)
    print("data.json %.2f MB | gzip %.2f MB | 压缩率 %.1f%%"
          % (len(blob) / 1048576, len(gz) / 1048576, len(gz) * 100.0 / max(len(blob), 1)))


if __name__ == "__main__":
    main()