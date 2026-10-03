"""
《贝娜的量角器》手机版构建脚本。

从上游 GitHub 项目拉最新规则 → 准备游戏数据 → 离线跑一遍翻译引擎
→ 打包成一个自包含的 HTML 文件，手机浏览器直接打开即可。

用法：
    python build.py                      # 拉上游规则（默认锁定到已确认的 commit）；数据缺失时自动下载
    python build.py --upstream-ref main  # 不锁定，跟随上游 main 的最新代码
    python build.py --tables ../tables   # 复用已有的游戏数据目录，不重复下载
    python build.py --no-update          # 不联网更新上游源码
    python build.py --update-data        # 强制重新下载游戏数据
    python build.py -o dist/index.html   # 指定输出位置
    python build.py --seasons 5,6        # 只打包指定肉鸽季度

所有中间产物（.src、下载的数据、临时 JSON）都放在本脚本所在目录下。
产物：单个 .html，数据以 gzip+base64 内联，浏览器端用内联的 fflate 解压。
"""
import argparse
import base64
import io
import json
import os
import shutil
import subprocess
import sys
import tarfile
import tempfile
import time
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))

UPSTREAM_REPO = "TeamTorappu/BenaProtractor"
UPSTREAM_API = "https://api.github.com/repos/%s/commits/main" % UPSTREAM_REPO

# 这个构建是无人值守、定时自动跑的，而且会直接 import 上游代码在构建机上执行，
# 产物每天自动发布到 GitHub Pages —— 用户正是在那个页面里填写 AI 接口的 API Key。
# 所以上游不能跟着 main 走：一旦上游仓库被入侵，恶意代码会顺着这条链一路到用户眼前。
# 默认锁定到人工确认过的 commit。升级规则时：看过上游 diff → 改这里 → 提交。
# 想临时跟随最新，用 --upstream-ref main。
UPSTREAM_PIN = "cad69c6471f3ffaa41905424accf3870113e6d2a"


def upstream_tarball(ref):
    return "https://codeload.github.com/%s/tar.gz/%s" % (UPSTREAM_REPO, ref)

REQUIRED_TABLES = [
    "buff_table.json",
    "buff_template_data.json",
    "character_table.json",
    "enemy_database.json",
    "roguelike_topic_table.json",
]

UA = {"User-Agent": "BenaProtractor-Mobile-Build/1.0"}

WORKDIR = HERE
SRC = os.path.join(WORKDIR, ".src")


def log(msg):
    print("[构建] " + msg, flush=True)


def http_get(url, timeout=120):
    """先走 urllib；失败时退到系统 curl（很多环境下代理是配在 curl 里的）。"""
    errors = []
    for attempt in range(2):
        try:
            req = urllib.request.Request(url, headers=UA)
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return resp.read()
        except Exception as e:
            errors.append("urllib(第%d次): %s" % (attempt + 1, e))

    try:
        r = subprocess.run(
            ["curl", "-sSL", "--max-time", str(timeout), "-A", UA["User-Agent"], url],
            capture_output=True)
        if r.returncode == 0 and r.stdout:
            return r.stdout
        errors.append("curl: 退出码 %s %s"
                      % (r.returncode, (r.stderr or b"").decode("utf-8", "replace")[:200]))
    except FileNotFoundError:
        errors.append("curl: 未安装")
    except Exception as e:
        errors.append("curl: %s" % e)

    raise RuntimeError(" | ".join(errors))


def latest_sha():
    data = json.loads(http_get(UPSTREAM_API, timeout=60).decode("utf-8"))
    return data.get("sha"), (data.get("commit", {}).get("committer", {}) or {}).get("date", "")


def sync_upstream(ref):
    """把上游源码同步进 .src（保留 tables/）。返回 (sha, date, 是否变更)。

    ref 是完整 commit SHA 时按锁定版本同步，不联网查版本；传 "main" 才是跟随最新。
    """
    stamp_path = os.path.join(SRC, ".upstream.json")
    old = {}
    if os.path.exists(stamp_path):
        try:
            old = json.load(open(stamp_path, encoding="utf-8"))
        except Exception:
            old = {}

    pinned = ref != "main"
    if pinned:
        sha, date = ref, old.get("date", "")
        if old.get("sha") == ref and os.path.exists(os.path.join(SRC, "anne.py")):
            log("上游已锁定 %s，本地源码一致" % ref[:7])
            return sha, date, False
    else:
        try:
            sha, date = latest_sha()
        except Exception as e:
            if os.path.exists(os.path.join(SRC, "anne.py")):
                log("拉取上游版本信息失败（%s），沿用现有 .src" % e)
                return old.get("sha", "unknown"), old.get("date", ""), False
            raise SystemExit("拉取上游版本信息失败，且 .src 里没有可用源码：%s" % e)

        if sha and sha == old.get("sha") and os.path.exists(os.path.join(SRC, "anne.py")):
            log("上游未更新（%s）" % sha[:7])
            return sha, date, False

    log("下载上游源码 %s ..." % ref[:7])
    try:
        blob = http_get(upstream_tarball(ref), timeout=300)
    except Exception as e:
        if os.path.exists(os.path.join(SRC, "anne.py")):
            log("下载失败，沿用现有 .src 的源码（规则可能不是最新）")
            log("  原因：%s" % e)
            log("  若需最新规则，请配置代理后重试，或设置环境变量 HTTPS_PROXY")
            return old.get("sha", "unknown"), old.get("date", ""), False
        raise SystemExit("下载上游源码失败，且 .src 里没有可用源码：%s" % e)

    tmp = tempfile.mkdtemp(prefix="bena-")
    try:
        with tarfile.open(fileobj=io.BytesIO(blob), mode="r:gz") as tf:
            try:
                tf.extractall(tmp, filter="data")
            except TypeError:      # Python < 3.11.4 没有 filter 参数
                tf.extractall(tmp)
        roots = [d for d in os.listdir(tmp) if os.path.isdir(os.path.join(tmp, d))]
        if not roots:
            raise SystemExit("压缩包结构异常")
        root = os.path.join(tmp, roots[0])

        os.makedirs(SRC, exist_ok=True)
        for name in os.listdir(SRC):
            if name == "tables":
                continue
            path = os.path.join(SRC, name)
            if os.path.isdir(path):
                shutil.rmtree(path)
            else:
                os.remove(path)

        for name in os.listdir(root):
            s = os.path.join(root, name)
            d = os.path.join(SRC, name)
            if os.path.isdir(s):
                shutil.copytree(s, d)
            else:
                shutil.copy2(s, d)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    json.dump({"sha": sha, "date": date, "ref": ref, "pinned": pinned,
               "syncedAt": time.strftime("%Y-%m-%d %H:%M:%S")},
              open(stamp_path, "w", encoding="utf-8"))
    log("上游源码已同步，共 %d 个文件" % sum(len(f) for _, _, f in os.walk(SRC)))
    return sha, date, True


def _missing(directory):
    return [n for n in REQUIRED_TABLES if not os.path.exists(os.path.join(directory, n))]


def _copy_into(source, target):
    copied = 0
    if not os.path.isdir(source):
        return 0
    for name in os.listdir(source):
        s = os.path.join(source, name)
        d = os.path.join(target, name)
        if os.path.isfile(s) and (not os.path.exists(d) or os.path.getmtime(s) > os.path.getmtime(d)):
            shutil.copy2(s, d)
            copied += 1
    return copied


def ensure_tables(update_data, tables_dir, fallback_dir):
    """准备游戏数据。

    注意：上游代码是按相对路径 './tables/xxx.json' 读的，所以数据必须落在 .src/tables，
    不能另指一处目录。--tables 和兄弟目录 tables/ 只是「复制源」，用来省掉 72 MB 下载。
    """
    cache = os.path.join(SRC, "tables")
    os.makedirs(cache, exist_ok=True)

    if update_data:
        for n in REQUIRED_TABLES:
            p = os.path.join(cache, n)
            if os.path.exists(p):
                os.remove(p)

    if not _missing(cache):
        log("游戏数据齐全，直接复用")
        return

    for source in (tables_dir, fallback_dir):
        if not source or not os.path.isdir(source):
            continue
        if os.path.abspath(source) == os.path.abspath(cache):
            continue
        n = _copy_into(source, cache)
        if n:
            log("从 %s 复制了 %d 个数据文件" % (source, n))
        if not _missing(cache):
            return

    log("需要联网下载游戏数据（国内可能需要代理）…")
    code = (
        "import os,sys;"
        "sys.path.insert(0,%r);"
        "os.chdir(%r);"
        "import downloader;"
        "downloader.prepare_files()" % (SRC, SRC)
    )
    r = subprocess.run([sys.executable, "-c", code])
    if r.returncode != 0:
        raise SystemExit("游戏数据下载失败。可以手动把明日方舟数据表复制到 %s" % cache)

    left = _missing(cache)
    if left:
        raise SystemExit("仍然缺少数据文件：%s" % ", ".join(left))
    log("游戏数据已就绪")


def run_export(seasons, src, out_json, out_gz):
    log("离线运行翻译引擎…")
    cmd = [sys.executable, os.path.join(HERE, "export_data.py"),
           "--src", src, "--seasons", seasons, "-o", out_json, "--gz", out_gz]
    r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if r.returncode != 0:
        sys.stdout.write(r.stdout or "")
        sys.stderr.write(r.stderr or "")
        raise SystemExit("数据导出失败")
    lines = (r.stdout or "").strip().splitlines()
    for line in lines:
        log("  " + line)
    return lines


def render(out_html, gz_path, meta):
    tpl = open(os.path.join(HERE, "template.html"), encoding="utf-8").read()
    fflate = open(os.path.join(HERE, "fflate.min.js"), encoding="utf-8").read()
    payload = base64.b64encode(open(gz_path, "rb").read()).decode("ascii")

    meta = dict(meta)
    meta["gzMB"] = round(os.path.getsize(gz_path) / 1048576.0, 2)

    for token in ("__PAYLOAD__", "__FFLATE__", "__META__"):
        if token not in tpl:
            raise SystemExit("模板缺少占位符 %s" % token)

    html = (tpl
            .replace("__PAYLOAD__", payload)
            .replace("__FFLATE__", fflate)
            .replace("__META__", json.dumps(meta, ensure_ascii=False)))

    parent = os.path.dirname(os.path.abspath(out_html))
    if parent:
        os.makedirs(parent, exist_ok=True)
    with open(out_html, "w", encoding="utf-8", newline="\n") as f:
        f.write(html)

    if "</html>" not in html[-200:]:
        raise SystemExit("生成的 HTML 结尾异常")
    return len(html.encode("utf-8"))


def main():
    global WORKDIR, SRC
    ap = argparse.ArgumentParser()
    ap.add_argument("-o", "--output", default="")
    ap.add_argument("--workdir", default=HERE, help="中间产物存放目录（默认脚本所在目录）")
    ap.add_argument("--tables", default="", help="已有的游戏数据目录，指定后不重复下载")
    ap.add_argument("--seasons", default="1,2,3,4,5,6")
    ap.add_argument("--upstream-ref", default=UPSTREAM_PIN,
                    help="上游 ref：完整 commit SHA（锁定）或 main（跟随最新）。默认 %s" % UPSTREAM_PIN[:7])
    ap.add_argument("--no-update", action="store_true", help="不联网更新上游源码")
    ap.add_argument("--update-data", action="store_true", help="强制重新下载游戏数据")
    ap.add_argument("--keep-temp", action="store_true", help="保留中间的 data.json / data.json.gz")
    args = ap.parse_args()

    WORKDIR = os.path.abspath(args.workdir)
    SRC = os.path.join(WORKDIR, ".src")
    os.makedirs(WORKDIR, exist_ok=True)
    output = args.output or os.path.join(WORKDIR, "index.html")

    t0 = time.perf_counter()

    if args.no_update:
        if not os.path.exists(os.path.join(SRC, "anne.py")):
            raise SystemExit(".src 里没有源码，去掉 --no-update 先同步一次上游")
        sha, date = "local", ""
        log("跳过联网更新，使用现有 .src")
    else:
        sha, date, changed = sync_upstream(args.upstream_ref)

    # 游戏数据的候选来源：显式指定 > 工作目录上一级的 tables/ > 联网下载
    fallback = os.path.join(os.path.dirname(WORKDIR), "tables")
    ensure_tables(args.update_data, args.tables, fallback)

    data_json = os.path.join(HERE, "data.json")
    data_gz = os.path.join(HERE, "data.json.gz")
    lines = run_export(args.seasons, SRC, data_json, data_gz)

    count = 0
    for line in lines:
        if line.startswith("载入 "):
            try:
                count = int(line.split("导出 ")[1].split(" ")[0])
            except Exception:
                pass

    meta = {
        "builtAt": time.strftime("%Y-%m-%d %H:%M:%S"),
        "upstream": {"repo": UPSTREAM_REPO, "sha": (sha or "")[:7], "date": date},
        "seasons": [int(s) for s in args.seasons.split(",") if s.strip()],
        "types": ["buff", "buff_template", "global_buff", "rogue_item"],
        "count": count,
    }

    size = render(output, data_gz, meta)

    if not args.keep_temp:
        for p in (data_json, data_gz):
            if os.path.exists(p):
                os.remove(p)

    log("完成 %.1fs" % (time.perf_counter() - t0))
    log("产物：%s" % output)
    log("体积：%.2f MB" % (size / 1048576.0))


if __name__ == "__main__":
    main()
