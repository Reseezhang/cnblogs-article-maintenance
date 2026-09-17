#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""改稿后的最终验收：渲染 + 元信息一次性核对。

比 check_render.py 多一层：除了抓页面看渲染，还会通过 API 核对
正文长度、摘要、标签、分类 —— 确认 editPost 没把字段清空。

用法：
    python verify_all.py 12345678 12345679
    python verify_all.py --all
"""

import argparse
import os
import sys
import xmlrpc.client
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from check_render import analyze, site_home, titles_and_ids   # noqa: E402

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

HERE = Path(__file__).resolve().parent


def find_env():
    for c in (HERE / ".cnblogs.env",
              Path.cwd() / ".cnblogs.env",
              Path.home() / ".cnblogs.env"):
        if c.exists():
            return c
    return None


def load_env():
    cfg = {k: v for k, v in os.environ.items() if k.startswith("CNBLOGS_")}
    env_file = find_env()
    if env_file:
        for raw in env_file.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            cfg.setdefault(k.strip(), v.strip())
    if not cfg.get("CNBLOGS_TOKEN"):
        print("[错误] 缺少 CNBLOGS_TOKEN", file=sys.stderr)
        sys.exit(1)
    return cfg


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("posts", nargs="*")
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--home")
    args = ap.parse_args()

    home = args.home or site_home()
    t = titles_and_ids()
    ids = list(args.posts) or list(t.keys())
    if not home or not ids:
        print("需要 postId 和站点前缀（可用 --home 指定）", file=sys.stderr)
        sys.exit(1)

    cfg = load_env()
    s = xmlrpc.client.ServerProxy(cfg["CNBLOGS_API_URL"], allow_none=True)

    print("站点：%s\n" % home)
    print("【渲染层】")
    print("%-10s %4s %4s %4s %5s %5s %7s %6s  %s" % (
        "postId", "h2", "h3", "pre", "table", "code", "字面##", "字面**", "标题"))
    print("-" * 116)
    bad = []
    for pid in ids:
        try:
            r = analyze(pid, home)
        except Exception as e:
            print("%-10s 抓取失败：%s" % (pid, e))
            continue
        if not r:
            print("%-10s 未找到正文容器" % pid)
            continue
        broken = (r["lit_hash"] > 0) or (r["lit_fence"] > 0)
        if broken:
            bad.append(pid)
        print("%-10s %4d %4d %4d %5d %5d %7d %6d  %s%s" % (
            pid, r["h2"], r["h3"], r["pre"], r["table"], r["code"],
            r["lit_hash"], r["lit_bold"], t.get(pid, "")[:24],
            "  <== 未渲染" if broken else ""))

    print("\n【元信息层】")
    print("%-10s %-9s %-5s %-30s %s" % ("postId", "正文字符", "摘要", "标签", "分类"))
    print("-" * 116)
    for pid in ids:
        try:
            p = s.metaWeblog.getPost(str(pid), cfg["CNBLOGS_USERNAME"], cfg["CNBLOGS_TOKEN"])
        except Exception as e:
            print("%-10s 读取失败：%s" % (pid, e))
            continue
        kw = p.get("mt_keywords") or ""
        print("%-10s %-11d %-7s %-30s %s" % (
            pid, len(p.get("description") or ""),
            "有" if (p.get("mt_excerpt") or "") else "无",
            kw if kw else "(空)", ",".join(p.get("categories") or [])))

    print()
    if bad:
        print("[注意] 这些篇目渲染异常（字面量残留）：" + ", ".join(bad))
    else:
        print("[OK] 全部渲染正常，无字面量残留。")


if __name__ == "__main__":
    main()
