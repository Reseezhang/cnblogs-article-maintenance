#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""诊断博客园文章正文的渲染状态 —— 判断 Markdown 到底有没有被渲染。

判断标准：
  正常渲染  -> 正文容器里出现 <h2> / <pre> / <table> / <code>
  未渲染    -> 出现字面量 '##'、'**'、``` （读者看到的是源码）

为什么需要它：正文 `description` 里看起来"有 Markdown"，不代表线上渲染成了排版。
实测过 4 篇文章分类为空、缺 `[Markdown]` 标记，于是被按 HTML 解析，
读者看到的是带 `##` 和 `**` 的源码墙。**改完文章必须跑一次这个脚本。**

⚠️ 统计字面量前会先把 <pre>/<code> 区域挖空。不这么做会大量误报：
   在代码块里出现 ``` 或 ** 是正常内容（示例代码、讲 Markdown 语法的文章本身），
   它们被正确渲染进了代码块，不是"未渲染"。

用法：
    python check_render.py 12345678 12345679
    python check_render.py --all                 # 取当前目录「原始备份/」里全部 postId
    python check_render.py --home https://www.cnblogs.com/yourname 12345678
"""

import argparse
import json
import re
import sys
import time
import urllib.request
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/126 Safari/537.36"


def backup_dir():
    for d in (Path.cwd() / "原始备份", Path(__file__).resolve().parent / "原始备份"):
        if d.is_dir():
            return d
    return None


def site_home():
    """从备份的 permaLink 推断站点前缀。"""
    d = backup_dir()
    if not d:
        return ""
    for m in d.glob("*.meta.json"):
        try:
            pl = json.loads(m.read_text(encoding="utf-8")).get("permaLink") or ""
        except Exception:
            continue
        if "/p/" in pl:
            return pl.split("/p/")[0]
    return ""


def titles_and_ids():
    d = backup_dir()
    out = {}
    if not d:
        return out
    for m in d.glob("*.meta.json"):
        try:
            x = json.loads(m.read_text(encoding="utf-8"))
            out[str(x["postid"])] = x.get("title", "")
        except Exception:
            continue
    return out


def fetch(url):
    req = urllib.request.Request(url, headers={
        "User-Agent": UA, "Cache-Control": "no-cache", "Pragma": "no-cache"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read().decode("utf-8", errors="replace")


def strip_code(seg):
    """把 <pre> 与 <code> 区域整体挖空。

    代码块里的 ``` / ** / ## 是渲染正常的证据，不是"未渲染"的信号。
    先挖 <pre>（它内部通常还包着 <code>），再挖剩下的行内 <code>。
    """
    seg = re.sub(r"<pre\b[^>]*>.*?</pre>", " ", seg, flags=re.S | re.I)
    seg = re.sub(r"<code\b[^>]*>.*?</code>", " ", seg, flags=re.S | re.I)
    return seg


def analyze(pid, home):
    # 加时间戳绕过 CDN 缓存，否则刚推完可能抓到旧内容
    url = "%s/p/%s?t=%d" % (home, pid, int(time.time()))
    html = fetch(url)
    i = html.find("cnblogs_post_body")
    if i < 0:
        return None
    seg = html[i:i + 45000]
    plain = strip_code(seg)
    return {
        "url": url.split("?")[0],
        "h2": len(re.findall(r"<h2", seg)),
        "h3": len(re.findall(r"<h3", seg)),
        "pre": len(re.findall(r"<pre", seg)),
        "table": len(re.findall(r"<table", seg)),
        "code": len(re.findall(r"<code", seg)),
        # 只在「非代码区域」统计字面量
        "lit_div": len(re.findall(r"^\s*<div>#{1,6} ", plain, re.M)),
        "lit_hash": plain.count("##"),
        "lit_bold": plain.count("**"),
        "lit_fence": plain.count("```"),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("posts", nargs="*", help="postId，可多个")
    ap.add_argument("--all", action="store_true", help="取备份里的全部 postId")
    ap.add_argument("--home", help="站点前缀，如 https://www.cnblogs.com/xxx")
    args = ap.parse_args()

    home = args.home or site_home()
    t = titles_and_ids()

    ids = list(args.posts)
    if args.all or not ids:
        ids = list(t.keys())
    if not ids:
        print("没有可检查的 postId：请传入 postId，或先跑一次 backup", file=sys.stderr)
        sys.exit(1)
    if not home:
        print("无法确定站点前缀，请用 --home 指定（如 https://www.cnblogs.com/yourname）", file=sys.stderr)
        sys.exit(1)

    print("站点：%s" % home)
    print("（字面量统计已排除 <pre>/<code> 区域，代码块里的 ``` 与 ** 不算问题）\n")
    print("%-10s %4s %4s %4s %5s %5s %7s %6s %7s  %s" % (
        "postId", "h2", "h3", "pre", "table", "code",
        "字面##", "字面**", "字面```", "标题"))
    print("-" * 128)

    bad, ok = [], []
    for pid in ids:
        try:
            r = analyze(pid, home)
        except Exception as e:
            print("%-10s 抓取失败：%s" % (pid, e))
            continue
        if not r:
            print("%-10s 未找到正文容器" % pid)
            continue
        # 判定：任一信号非 0 就是可疑，并把触发原因打出来
        reasons = []
        if r["lit_div"]:
            reasons.append("<div>## x%d" % r["lit_div"])
        if r["lit_fence"]:
            reasons.append("``` x%d" % r["lit_fence"])
        if r["lit_bold"]:
            reasons.append("** x%d" % r["lit_bold"])
        if r["lit_hash"] and not r["lit_div"]:
            reasons.append("## x%d" % r["lit_hash"])
        broken = bool(reasons)

        (bad if broken else ok).append(pid)
        print("%-10s %4d %4d %4d %5d %5d %7d %6d %7d  %s%s" % (
            pid, r["h2"], r["h3"], r["pre"], r["table"], r["code"],
            r["lit_hash"], r["lit_bold"], r["lit_fence"],
            t.get(pid, "")[:24],
            "  <== 未渲染（" + "、".join(reasons) + "）" if broken else ""))

    print("\n结论：%d 篇未渲染，%d 篇正常。" % (len(bad), len(ok)))
    if bad:
        print("未渲染：" + ", ".join(bad))
        print("修复：把 Markdown 原文直接放进 description，并在分类里加上 [Markdown]，"
              "然后用 cnblogs_push.py update 覆盖推送。")


if __name__ == "__main__":
    main()
