# -*- coding: utf-8 -*-
"""博客园随笔删除（含强制备份）。

安全设计：备份 + 校验通过才允许删除，任一步失败整体中止，不会删一半。

用法：
    python delete_posts.py --ids 12345678,12345679             # 只备份，不删
    python delete_posts.py --ids 12345678,12345679 --apply      # 备份校验通过后删除

站点前缀（删后探活用）按「CNBLOGS_HOME → 接口返回的 permaLink 推断」自动确定。
"""
import argparse
import json
import os
import pathlib
import re
import sys
import urllib.error
import urllib.request
import xmlrpc.client

HERE = pathlib.Path(__file__).resolve().parent
BACKUP_DIR = pathlib.Path.cwd() / "删除备份"


def find_env():
    """查找顺序：环境变量 CNBLOGS_ENV → 脚本同目录 → 工作目录 → 用户主目录。"""
    if os.environ.get("CNBLOGS_ENV"):
        return pathlib.Path(os.environ["CNBLOGS_ENV"])
    for c in (HERE / ".cnblogs.env", pathlib.Path.cwd() / ".cnblogs.env",
              pathlib.Path.home() / ".cnblogs.env"):
        if c.exists():
            return c
    return None


def die(msg):
    print("\n[中止] " + msg)
    sys.exit(1)


def load_env():
    env = find_env()
    if env is None:
        die("找不到 .cnblogs.env（找过脚本同目录、工作目录、用户主目录）")
    cfg = {k: v for k, v in os.environ.items() if k.startswith("CNBLOGS_")}
    for raw in env.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        cfg.setdefault(k.strip(), v.strip())
    for k in ("CNBLOGS_API_URL", "CNBLOGS_USERNAME", "CNBLOGS_TOKEN"):
        if not cfg.get(k):
            die("配置缺 %s" % k)
    return cfg


def slugify(title):
    s = re.sub(r'[\\/:*?"<>|\r\n\t]', "-", title)
    s = re.sub(r"\s+", "-", s.strip())
    return s[:70]


def home_from_link(cfg, posts):
    """站点前缀：优先 CNBLOGS_HOME，其次从 permaLink 推断。

    以前这里写死成具体博客地址，开源后必然失效；改成自动推断，
    换博客不用改脚本。
    """
    home = (cfg.get("CNBLOGS_HOME") or "").rstrip("/")
    if home:
        return home
    for p in posts:
        link = p.get("permaLink") or p.get("link") or ""
        if "/p/" in link:
            return link.split("/p/")[0].rstrip("/")
    return ""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ids", required=True, help="逗号分隔的 postId")
    ap.add_argument("--apply", action="store_true", help="备份校验通过后真删除")
    args = ap.parse_args()

    ids = [x.strip() for x in args.ids.split(",") if x.strip()]
    if not ids:
        die("没给 postId")

    cfg = load_env()
    s = xmlrpc.client.ServerProxy(cfg["CNBLOGS_API_URL"], allow_none=True)
    user, token = cfg["CNBLOGS_USERNAME"], cfg["CNBLOGS_TOKEN"]

    BACKUP_DIR.mkdir(exist_ok=True)
    manifest = []
    fetched = []
    print("=" * 78)
    print("第 1 步：备份 %d 篇" % len(ids))
    print("=" * 78)

    for pid in ids:
        try:
            p = s.metaWeblog.getPost(pid, user, token)
        except Exception as e:
            # 已删过的 postId 会走这里（Fault 404 博文不存在），整体中止
            die("拉取 %s 失败：%s" % (pid, e))
        if not p:
            die("postId %s 不存在或已被删（getPost 返回空）" % pid)
        fetched.append(p)

        title = p.get("title") or "(无标题)"
        body = p.get("description") or ""
        base = "%s-%s" % (pid, slugify(title))
        (BACKUP_DIR / (base + ".md")).write_text(body, encoding="utf-8")
        meta = {k: (("<%d chars>" % len(v)) if k == "description" else v)
                for k, v in p.items()}
        (BACKUP_DIR / (base + ".meta.json")).write_text(
            json.dumps(meta, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
        manifest.append({
            "postid": pid, "title": title, "chars": len(body),
            "dateCreated": str(p.get("dateCreated")),
            "categories": p.get("categories") or [],
            "keywords": p.get("mt_keywords") or "",
            "file": base + ".md",
            "link": p.get("permaLink") or p.get("link") or "",
        })
        print("  ✓ %-9s %-7d 字符  %s" % (pid, len(body), title[:52]))

    # 校验：正文必须非空，且落盘大小与接口返回一致
    bad = []
    for m in manifest:
        f = BACKUP_DIR / m["file"]
        if not f.exists():
            bad.append("%s 文件没落盘" % m["postid"])
            continue
        on_disk = len(f.read_text(encoding="utf-8"))
        if on_disk == 0:
            bad.append("%s 备份是空的" % m["postid"])
        elif on_disk != m["chars"]:
            bad.append("%s 落盘 %d 字符，接口返回 %d 字符，不一致" % (m["postid"], on_disk, m["chars"]))
    if bad:
        print("\n[中止] 备份校验不通过，不会删除任何东西：")
        for b in bad:
            print("  ✗ " + b)
        sys.exit(1)

    mf = BACKUP_DIR / "manifest.json"
    old = json.loads(mf.read_text(encoding="utf-8")) if mf.exists() else []
    known = {x["postid"] for x in old}
    mf.write_text(json.dumps(old + [x for x in manifest if x["postid"] not in known],
                            ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    print("\n  ✓ 备份校验通过：%d 篇正文完整落盘" % len(manifest))
    print("  ✓ 清单：%s" % mf)
    print("  ✓ 合计 %d 字符" % sum(m["chars"] for m in manifest))

    if not args.apply:
        print("\n（未加 --apply，只备份不删除）")
        return

    print()
    print("=" * 78)
    print("第 2 步：删除")
    print("=" * 78)
    ok, fail = 0, []
    for m in manifest:
        pid = m["postid"]
        try:
            r = s.blogger.deletePost("", pid, user, token, True)
            if r:
                ok += 1
                print("  ✓ 已删除 %-9s %s" % (pid, m["title"][:48]))
            else:
                fail.append("%s 返回 False" % pid)
                print("  ✗ 返回 False %-9s %s" % (pid, m["title"][:44]))
        except Exception as e:
            fail.append("%s %s" % (pid, e))
            print("  ✗ 异常 %-9s %s" % (pid, str(e)[:60]))

    print()
    print("=" * 78)
    print("第 3 步：验证（应全部 404 / 410）")
    print("=" * 78)
    home = home_from_link(cfg, fetched)
    if not home:
        print("  [跳过] 无法确定站点前缀，请设置 CNBLOGS_HOME 后手动探活")
    still = []
    for m in manifest:
        if home:
            url = "%s/p/%s.html" % (home, m["postid"])
            try:
                req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 Chrome/126"})
                resp = urllib.request.urlopen(req, timeout=25)
                code = resp.getcode()
            except urllib.error.HTTPError as e:
                code = e.code
            except Exception as e:
                code = "ERR %s" % str(e)[:30]
            gone = code in (404, 410)
            if not gone:
                still.append("%s (%s)" % (m["postid"], code))
            print("  %s %-9s HTTP %-8s %s" % ("✓" if gone else "✗", m["postid"], code,
                                              m["title"][:44]))
        else:
            print("  ? %-9s （未探活） %s" % (m["postid"], m["title"][:44]))

    print()
    print("删除成功 %d / %d" % (ok, len(manifest)))
    if fail:
        print("删除失败：%s" % "; ".join(fail))
    if still:
        print("仍可访问（未删掉）：%s" % ", ".join(still))
        sys.exit(2)


if __name__ == "__main__":
    main()
