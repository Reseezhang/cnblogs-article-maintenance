#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把本地图片通过 MetaWeblog 的 newMediaObject 上传到博客园图床。

用法：
    python upload_image.py 配图/示意图.png
    python upload_image.py 配图/a.png 配图/b.png

上传成功会打印图片 URL，把它填进 Markdown 的 ![](url) 即可。

坑：bits 必须传 xmlrpc.client.Binary(原始 bytes)，不要自己再 base64 一遍 ——
客户端会自动编码；手动编码后 Binary 会抛 TypeError: expected bytes。
"""

import argparse
import os
import sys
import xmlrpc.client
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

HERE = Path(__file__).resolve().parent

MIME = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
        ".gif": "image/gif", ".svg": "image/svg+xml", ".webp": "image/webp"}


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
        print("[错误] 缺少 CNBLOGS_TOKEN（令牌，不是密码）", file=sys.stderr)
        sys.exit(1)
    return cfg


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("files", nargs="+", help="要上传的图片路径")
    ap.add_argument("--name", help="上传后的文件名（只有一张图时生效）")
    args = ap.parse_args()

    cfg = load_env()
    s = xmlrpc.client.ServerProxy(cfg["CNBLOGS_API_URL"], allow_none=True)
    blog = cfg.get("CNBLOGS_BLOG_ID", "")

    for f in args.files:
        p = Path(f)
        if not p.exists():
            print("[跳过] 找不到 %s" % p)
            continue
        name = args.name if (args.name and len(args.files) == 1) else p.name
        mime = MIME.get(p.suffix.lower(), "application/octet-stream")
        payload = {
            "name": name,
            "type": mime,
            "bits": xmlrpc.client.Binary(p.read_bytes()),
        }
        try:
            res = s.metaWeblog.newMediaObject(blog, cfg["CNBLOGS_USERNAME"],
                                              cfg["CNBLOGS_TOKEN"], payload)
        except xmlrpc.client.Fault as e:
            print("[失败] %s -> %s" % (p.name, e.faultString))
            continue
        print("[OK] %s\n     %s" % (p.name, (res or {}).get("url", "")))


if __name__ == "__main__":
    main()
