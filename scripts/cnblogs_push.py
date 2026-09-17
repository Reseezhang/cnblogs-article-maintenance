#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""博客园 MetaWeblog 工具：检查 / 列表 / 备份 / 存草稿 / 原地更新。

只依赖标准库，不需要额外安装任何包。

用法：

    python cnblogs_push.py check
    python cnblogs_push.py list
    python cnblogs_push.py backup
    python cnblogs_push.py draft  --file 成稿-01.md
    python cnblogs_push.py update --post-id 12345678 --file 成稿-01.md
    python cnblogs_push.py update --post-id 12345678 --file 成稿-01.md \
        --keywords "Python,自动化测试" --excerpt "列表页摘要"

关键约定（踩过的坑，别改）：
  1. 认证用后台生成的「访问令牌」，不是登录密码 —— 博客园已取消密码登录。
  2. Markdown 正文直接放进 description，绝对不要转成 HTML。
     转完的 HTML 再经 XML-RPC 转义，<pre> 会变成 &lt;pre&gt;，代码块全毁。
  3. 分类里必须包含 [Markdown]，否则博客园按 HTML 解析，Markdown 语法原样显示。
  4. editPost 是全量覆盖且不可回滚，所以 update 之前会自动先备份单篇原文。
  5. mt_keywords（标签）与 mt_excerpt（摘要）不会被 editPost 自动保留，
     必须每次显式带上；不传命令行参数时脚本会沿用原文的旧值。
"""

import argparse
import json
import os
import re
import sys
import xmlrpc.client
from datetime import datetime
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

HERE = Path(__file__).resolve().parent
BACKUP_DIR = Path.cwd() / "原始备份"
PRE_UPDATE_DIR = BACKUP_DIR / "更新前"
MD_FLAG = "[Markdown]"


def find_env():
    """按「脚本同目录 -> 当前工作目录 -> 用户主目录」的顺序找配置文件。"""
    for c in (HERE / ".cnblogs.env",
              Path.cwd() / ".cnblogs.env",
              Path.home() / ".cnblogs.env"):
        if c.exists():
            return c
    return None


def die(msg):
    print("\n[错误] " + msg, file=sys.stderr)
    sys.exit(1)


def load_env():
    """读取配置。环境变量优先，.cnblogs.env 补充（不覆盖已有的环境变量）。

    配置文件的位置：脚本同目录 -> 当前工作目录 -> 用户主目录。
    """
    cfg = {k: v for k, v in os.environ.items() if k.startswith("CNBLOGS_")}
    env_file = find_env()
    if env_file:
        for raw in env_file.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            cfg.setdefault(k.strip(), v.strip())
    else:
        print("  [注意] 未找到 .cnblogs.env，仅使用 CNBLOGS_* 环境变量。")
    missing = [k for k in ("CNBLOGS_API_URL", "CNBLOGS_USERNAME", "CNBLOGS_TOKEN") if not cfg.get(k)]
    if missing:
        die("配置缺少这几项：%s\n请把 .cnblogs.env 放在「脚本同目录 / 当前目录 / 用户主目录」任一位置。"
            % ", ".join(missing))
    if not cfg.get("CNBLOGS_TOKEN"):
        die("CNBLOGS_TOKEN 是空的。注意这里要填访问令牌，不是登录密码。")
    return cfg


def connect(cfg):
    return xmlrpc.client.ServerProxy(cfg["CNBLOGS_API_URL"], allow_none=True)


def blog_id(cfg, override=None):
    return override or cfg.get("CNBLOGS_BLOG_ID") or ""


def dt_str(v):
    if v is None:
        return ""
    if hasattr(v, "value"):
        return str(v.value)
    return str(v)


def call(fn, *args):
    try:
        return fn(*args)
    except xmlrpc.client.Fault as e:
        die("博客园返回错误：%s" % e.faultString)
    except Exception as e:
        die("%s: %s" % (type(e).__name__, e))


def get_all_posts(cfg, limit=200):
    s = connect(cfg)
    return call(s.metaWeblog.getRecentPosts, blog_id(cfg), cfg["CNBLOGS_USERNAME"],
                cfg["CNBLOGS_TOKEN"], limit)


def slugify(text, maxlen=40):
    text = re.sub(r"[\\/:*?\"<>|]", "", text or "untitled")
    text = re.sub(r"\s+", "-", text.strip())
    return text[:maxlen] or "untitled"


def extract_title(md, fallback="未命名"):
    for line in md.splitlines():
        if line.startswith("# "):
            return line[2:].strip()
    return fallback


def norm_categories(cats):
    """规范化分类：去空、去重、保证含 [Markdown]。"""
    out = []
    for c in cats or []:
        c = (c or "").strip()
        if c and c not in out:
            out.append(c)
    if MD_FLAG not in out:
        out.insert(0, MD_FLAG)
    return out


# ---------------------------------------------------------------- commands

def cmd_check(cfg, args):
    s = connect(cfg)
    cats = call(s.metaWeblog.getCategories, blog_id(cfg), cfg["CNBLOGS_USERNAME"], cfg["CNBLOGS_TOKEN"])
    print("[OK] 认证通过，令牌有效。")
    print("     端点：%s" % cfg["CNBLOGS_API_URL"])
    print("     已有分类 %d 个：%s" % (len(cats), ", ".join(c.get("title", "") for c in cats[:20])))


def cmd_list(cfg, args):
    posts = get_all_posts(cfg, args.limit)
    print("共取回 %d 篇，按时间倒序：\n" % len(posts))
    print("%-12s %-24s %-18s %s" % ("postId", "发布时间", "分类", "标题"))
    print("-" * 100)
    for p in posts:
        cats = ",".join(p.get("categories") or []) or "-"
        print("%-12s %-24s %-18s %s" % (
            p.get("postid", "?"),
            dt_str(p.get("dateCreated"))[:19],
            cats[:18],
            p.get("title", ""),
        ))


def cmd_backup(cfg, args):
    posts = get_all_posts(cfg, args.limit)
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    index = []
    for p in posts:
        pid = str(p.get("postid", ""))
        title = p.get("title", "未命名")
        body = p.get("description") or ""
        meta = {
            "postid": pid,
            "title": title,
            "dateCreated": dt_str(p.get("dateCreated")),
            "categories": p.get("categories") or [],
            "mt_keywords": p.get("mt_keywords") or "",
            "permaLink": p.get("permaLink") or p.get("link") or "",
            "backupTime": stamp,
            "bodyChars": len(body),
        }
        (BACKUP_DIR / ("%s-%s.md" % (pid, slugify(title)))).write_text(body, encoding="utf-8")
        (BACKUP_DIR / ("%s-%s.meta.json" % (pid, slugify(title)))).write_text(
            json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
        index.append(meta)
        print("  已备份 %-12s %s" % (pid, title))
    (BACKUP_DIR / ("_index-%s.json" % stamp)).write_text(
        json.dumps(index, ensure_ascii=False, indent=2), encoding="utf-8")
    print("\n[OK] 共备份 %d 篇到 %s" % (len(index), BACKUP_DIR))


def load_original_meta(postid):
    """从最近一次备份里找某篇的元信息，用来保留原有分类。"""
    if not BACKUP_DIR.exists():
        return None
    metas = sorted(BACKUP_DIR.glob("*-*.meta.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    for m in metas:
        try:
            data = json.loads(m.read_text(encoding="utf-8"))
        except Exception:
            continue
        if str(data.get("postid")) == str(postid):
            return data
    return None


def fetch_post(cfg, postid):
    s = connect(cfg)
    try:
        return s.metaWeblog.getPost(str(postid), cfg["CNBLOGS_USERNAME"], cfg["CNBLOGS_TOKEN"])
    except xmlrpc.client.Fault:
        return None


def save_pre_update(postid, post):
    if not post:
        return
    PRE_UPDATE_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    body = post.get("description") or ""
    base = "%s-%s" % (postid, stamp)
    (PRE_UPDATE_DIR / (base + ".md")).write_text(body, encoding="utf-8")
    (PRE_UPDATE_DIR / (base + ".meta.json")).write_text(json.dumps({
        "postid": str(postid),
        "title": post.get("title", ""),
        "categories": post.get("categories") or [],
        "mt_keywords": post.get("mt_keywords") or "",
        "dateCreated": dt_str(post.get("dateCreated")),
        "savedAt": stamp,
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    print("  覆盖前已存一份原文：原始备份/更新前/%s.md" % base)


def cmd_draft(cfg, args):
    body = Path(args.file).read_text(encoding="utf-8")
    title = args.title or extract_title(body)
    cats = norm_categories(args.categories or [cfg.get("CNBLOGS_DEFAULT_CATEGORY", "随笔分类"), MD_FLAG])
    struct = {"title": title, "description": body, "categories": cats}
    s = connect(cfg)
    pid = call(s.metaWeblog.newPost, blog_id(cfg), cfg["CNBLOGS_USERNAME"], cfg["CNBLOGS_TOKEN"],
               struct, False)
    print("[OK] 草稿已创建，postId = %s" % pid)
    print("     标题：%s" % title)
    print("     分类：%s" % ", ".join(cats))
    print("     草稿不会公开；到后台确认渲染效果后再决定是否发布。")


def cmd_update(cfg, args):
    src = Path(args.file)
    if not src.exists():
        die("找不到成稿文件：%s" % src)
    body = src.read_text(encoding="utf-8")
    title = args.title or extract_title(body)
    postid = str(args.post_id)

    prev = fetch_post(cfg, postid)
    save_pre_update(postid, prev)

    base_cats = None
    if prev and prev.get("categories"):
        base_cats = list(prev["categories"])
    else:
        meta = load_original_meta(postid)
        if meta:
            base_cats = list(meta.get("categories") or [])
    if base_cats is None:
        print("  [注意] 没能取回原文分类，将使用默认分类。")
        base_cats = [cfg.get("CNBLOGS_DEFAULT_CATEGORY", "随笔分类")]
    cats = norm_categories(base_cats)

    struct = {"title": title, "description": body, "categories": cats}

    # 标签与摘要：没在命令行指定就沿用原文（这两个字段是编辑时容易被清空的，
    # 所以无论有没有新值都显式带上）。
    keywords = args.keywords if args.keywords is not None else ((prev or {}).get("mt_keywords") or "")
    excerpt = args.excerpt if args.excerpt is not None else ((prev or {}).get("mt_excerpt") or "")
    struct["mt_keywords"] = keywords
    struct["mt_excerpt"] = excerpt

    s = connect(cfg)
    ok = call(s.metaWeblog.editPost, postid, cfg["CNBLOGS_USERNAME"], cfg["CNBLOGS_TOKEN"],
              struct, args.publish)

    print("\n[%s] 更新完成 postId=%s" % ("OK" if ok else "失败", postid))
    print("     标题：%s" % title)
    print("     分类：%s" % ", ".join(cats))
    print("     标签：%s" % (keywords or "(未设置)"))
    print("     摘要：%s" % ((excerpt[:40] + "…") if len(excerpt) > 40 else (excerpt or "(未设置)")))
    print("     正文：%d 字符，Markdown 原文直传" % len(body))
    print("     状态：%s" % ("已发布" if args.publish else "存为草稿"))
    if prev and (prev.get("permaLink") or prev.get("link")):
        print("     链接：%s" % (prev.get("permaLink") or prev.get("link")))


def main():
    ap = argparse.ArgumentParser(description="博客园 MetaWeblog 工具")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("check", help="验证令牌是否可用")
    p.set_defaults(func=cmd_check)

    p = sub.add_parser("list", help="列出最近文章")
    p.add_argument("--limit", type=int, default=100)
    p.set_defaults(func=cmd_list)

    p = sub.add_parser("backup", help="备份全部文章到本地")
    p.add_argument("--limit", type=int, default=200)
    p.set_defaults(func=cmd_backup)

    p = sub.add_parser("draft", help="新建一篇草稿")
    p.add_argument("--file", required=True)
    p.add_argument("--title")
    p.add_argument("--categories", nargs="*")
    p.set_defaults(func=cmd_draft)

    p = sub.add_parser("update", help="原地更新已有文章（保留原 URL）")
    p.add_argument("--post-id", required=True)
    p.add_argument("--file", required=True)
    p.add_argument("--title")
    p.add_argument("--keywords", help="标签，逗号分隔。不传则沿用原文")
    p.add_argument("--excerpt", help="列表页摘要。不传则沿用原文")
    p.add_argument("--no-publish", dest="publish", action="store_false",
                   help="更新后存为草稿而不公开发布")
    p.set_defaults(func=cmd_update, publish=True)

    args = ap.parse_args()
    cfg = load_env()
    args.func(cfg, args)


if __name__ == "__main__":
    main()
