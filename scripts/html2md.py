#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把博客园 description 里的 HTML 形态还原成干净 Markdown。

背景：几篇文章的正文实际是 Markdown 源码被博客园当成 HTML 处理后的产物
（换行变 <div>、符号被转义），另几篇是从网页整段复制进来的 HTML（带一堆
冗余 DOM 和 class）。直接改稿看不清骨架，先用本脚本还原成 Markdown 底稿。

用法：
    python html2md.py 原始备份/12345678-xxx.md
    python html2md.py 原始备份/12345678-xxx.md -o 还原/12345678.md
    python html2md.py 原始备份/ -o 还原/ --shift 1
    python html2md.py 原始备份/ -o 还原/ --only 12345678,12345679

--shift N：把所有标题整体下调 N 级（h1 -> ## 即 shift=1），用来修正
          「用 h1 当节标题」这类层级问题。默认 0（忠实还原）。

只依赖标准库。
"""

import argparse
import re
import sys
from html.parser import HTMLParser
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# 会自然产生换行的标签
BLOCK_TAGS = {
    "div", "p", "section", "article", "aside", "header", "footer", "main",
    "nav", "figure", "figcaption", "blockquote", "form", "fieldset", "dl",
}
SKIP_TAGS = {"script", "style", "noscript", "svg", "head", "title", "meta", "link"}


class HtmlToMarkdown(HTMLParser):
    def __init__(self, shift=0):
        super().__init__(convert_charrefs=True)
        self.shift = shift
        self.lines = []          # 已完成的行（含空行占位）
        self.buf = []            # 当前行缓冲
        self.pre_buf = []        # <pre> 内容缓冲
        self.in_pre = False
        self.in_fence = False    # 是否处在 ``` 围栏内（原文围栏散落在 <div> 里）
        self.pre_lang = ""
        self.skip_depth = 0
        self.list_stack = []     # [(kind, counter)]
        self.link_stack = []     # [href]
        self.table = None        # 表格收集状态
        self.row = None

    # ------------------------------------------------------------ 工具
    def out_line(self, text):
        """写入一整行（不经过缓冲）。"""
        self.flush()
        self.lines.append(text)

    def flush(self):
        """把缓冲写为一行。

        代码围栏内保留行首空格（ASCII 架构图/目录树靠它对齐）；
        围栏外去掉首尾空白，并按内容过滤残行。
        """
        text = "".join(self.buf).replace("\xa0", " ")
        text = text.rstrip()
        # 列表内保留缩进（嵌套层级靠它表达）
        if not self.in_fence and not self.list_stack:
            text = text.lstrip(" ")
        if text:
            if self.in_fence:
                self.lines.append(text)
            elif not re.fullmatch(r"[-–—>]+", text):
                # 过滤「只剩一个 - 或 >」的残留行；注意不能误杀表格分隔行 |---|---|
                self.lines.append(text)
                # 块级内容之间补空行，否则相邻两行会被 Markdown 合并成一段。
                # 列表项（连续）和表格行（连续）除外，补空行会把它们打断。
                if (not self.list_stack and not self.in_fence
                        and not text.startswith("|") and not text.startswith("- ")
                        and not text.startswith("> ")):
                    self.lines.append("")
            if text.strip().startswith("```"):
                self.in_fence = not self.in_fence
        self.buf = []

    def indent(self):
        return "  " * max(0, len(self.list_stack) - 1)

    # ------------------------------------------------------------ 文本
    def handle_data(self, data):
        if self.skip_depth:
            return
        if self.in_pre:
            self.pre_buf.append(data)
            return
        text = data.replace("\xa0", " ")
        if not text.strip():
            # 纯空白：仅在两段内容之间保留一个分隔空格
            if self.buf:
                self.buf.append(" ")
            return
        self.buf.append(text)

    # ------------------------------------------------------------ 标签
    def handle_starttag(self, tag, attrs):
        a = dict(attrs)

        if tag in SKIP_TAGS:
            self.skip_depth += 1
            return
        if self.skip_depth:
            return

        if tag == "pre":
            self.flush()
            self.in_pre = True
            self.pre_buf = []
            cls = (a.get("class") or "")
            m = re.search(r"(?:language|lang|brush)[-:]([A-Za-z0-9+#]+)", cls)
            self.pre_lang = m.group(1) if m else ""
            return

        if self.in_pre:
            return  # pre 内部标签一律剥掉

        if tag in BLOCK_TAGS:
            # <div> 是我们的换行单位：进块标签前先收尾当前行
            self.flush()
            return

        if tag == "br":
            self.flush()
            return

        if tag == "hr":
            self.out_line("")
            self.out_line("---")
            self.out_line("")
            return

        if tag in ("h1", "h2", "h3", "h4", "h5", "h6"):
            self.flush()
            level = int(tag[1]) + self.shift
            level = max(1, min(6, level))
            self.buf.append("\n\x00H%d\x00" % level)  # 占位，收尾时换 # 前缀
            return

        if tag in ("ul", "ol"):
            self.flush()
            self.list_stack.append([tag, 0])
            return

        if tag == "li":
            self.flush()
            if self.list_stack:
                kind, n = self.list_stack[-1]
                self.list_stack[-1][1] = n + 1
                marker = "- " if kind == "ul" else "%d. " % (n + 1)
                self.buf.append(self.indent() + marker)
            else:
                self.buf.append("- ")
            return

        if tag in ("strong", "b"):
            self.buf.append("**")
            return

        if tag in ("em", "i"):
            self.buf.append("*")
            return

        if tag == "code":
            if not self.in_pre:
                self.buf.append("`")
            return

        if tag == "a":
            self.link_stack.append(a.get("href") or "")
            self.buf.append("[")
            return

        if tag == "img":
            src = a.get("src") or ""
            alt = a.get("alt") or ""
            if src and not src.startswith("data:"):
                self.flush()
                self.out_line("![%s](%s)" % (alt, src))
            return

        if tag == "blockquote":
            self.buf.append("> ")
            return

        # ---- 表格 ----
        if tag == "table":
            self.flush()
            self.table = []
            return
        if tag == "tr" and self.table is not None:
            self.row = []
            return
        if tag in ("td", "th") and self.row is not None:
            self.flush()
            return

    def handle_endtag(self, tag):
        if tag in SKIP_TAGS:
            self.skip_depth = max(0, self.skip_depth - 1)
            return
        if self.skip_depth:
            return

        if tag == "pre":
            self._emit_pre()
            self.in_pre = False
            self.pre_buf = []
            return

        if self.in_pre:
            return

        if tag in BLOCK_TAGS:
            self.flush()
            return

        if tag in ("h1", "h2", "h3", "h4", "h5", "h6"):
            text = "".join(self.buf)
            self.buf = []
            text = re.sub(r"[ \t]+", " ", text.replace("\xa0", " ")).strip()
            m = re.match(r"^\x00H(\d)\x00(.*)$", text, re.S)
            if m:
                level, title = int(m.group(1)), m.group(2).strip()
            else:
                level, title = int(tag[1]) + self.shift, text
            if title:
                self.lines.append("")
                self.lines.append("#" * level + " " + title)
                self.lines.append("")
            return

        if tag in ("ul", "ol"):
            self.flush()
            if self.list_stack:
                self.list_stack.pop()
            # 最外层列表结束后补空行，避免和下一段粘连
            if not self.list_stack:
                self.lines.append("")
            return

        if tag == "li":
            self.flush()
            return

        if tag in ("strong", "b"):
            self.buf.append("**")
            return

        if tag in ("em", "i"):
            self.buf.append("*")
            return

        if tag == "code":
            if not self.in_pre:
                self.buf.append("`")
            return

        if tag == "a":
            href = self.link_stack.pop() if self.link_stack else ""
            self.buf.append("](%s)" % href)
            return

        if tag in ("td", "th") and self.row is not None:
            self.row.append("".join(self.buf).replace("\xa0", " ").strip())
            self.buf = []
            return

        if tag == "tr" and self.row is not None:
            if self.table is not None:
                self.table.append(self.row)
            self.row = None
            return

        if tag == "table":
            self.flush()
            self._emit_table()
            self.table = None
            return

    # ------------------------------------------------------------ 输出
    def _emit_pre(self):
        text = "".join(self.pre_buf)
        text = text.replace("\xa0", " ").replace("\r\n", "\n").replace("\r", "\n")
        lines = text.split("\n")
        while lines and not lines[0].strip():
            lines.pop(0)
        while lines and not lines[-1].strip():
            lines.pop()
        if not lines:
            return
        self.lines.append("")
        if lines[0].lstrip().startswith("```"):
            # 原文自带 Markdown 围栏（内容被博客园包进了 <pre>），直接沿用
            self.lines.extend(lines)
        else:
            self.lines.append("```" + self.pre_lang)
            self.lines.extend(lines)
            self.lines.append("```")
        self.lines.append("")

    def _emit_table(self):
        rows = [r for r in (self.table or []) if any(c for c in r)]
        if not rows:
            return
        width = max(len(r) for r in rows)
        rows = [r + [""] * (width - len(r)) for r in rows]
        self.lines.append("")
        self.lines.append("| " + " | ".join(rows[0]) + " |")
        self.lines.append("|" + "---|" * width)
        for r in rows[1:]:
            self.lines.append("| " + " | ".join(r) + " |")
        self.lines.append("")

    def result(self):
        self.flush()
        if self.in_pre:
            self._emit_pre()
        # 压缩空行 + 去尾空白
        out = []
        blank = 0
        for ln in self.lines:
            ln = ln.rstrip()
            if not ln:
                blank += 1
                if blank > 1:
                    continue
            else:
                blank = 0
            out.append(ln)
        while out and not out[0]:
            out.pop(0)
        while out and not out[-1]:
            out.pop()
        return "\n".join(out) + "\n"


def convert(path, shift=0):
    raw = Path(path).read_text(encoding="utf-8", errors="replace")
    p = HtmlToMarkdown(shift=shift)
    p.feed(raw)
    p.close()
    return p.result()


def main():
    ap = argparse.ArgumentParser(description="HTML -> Markdown 还原")
    ap.add_argument("src", help="单个 .md/.html 文件，或一个目录")
    ap.add_argument("-o", "--out", help="输出文件或输出目录（目录模式必填）")
    ap.add_argument("--shift", type=int, default=0, help="标题层级整体下调 N 级")
    ap.add_argument("--only", help="目录模式下只处理这些 postId，逗号分隔")
    ap.add_argument("--suffix", default="", help="输出文件名后缀，如 -还原")
    args = ap.parse_args()

    src = Path(args.src)
    only = set((args.only or "").split(",")) if args.only else None

    if src.is_dir():
        if not args.out:
            print("目录模式必须指定 -o 输出目录", file=sys.stderr)
            sys.exit(1)
        outdir = Path(args.out)
        outdir.mkdir(parents=True, exist_ok=True)
        files = sorted(src.glob("*.md"))
        n = 0
        for f in files:
            pid = f.name.split("-")[0]
            if only and pid not in only:
                continue
            md = convert(f, args.shift)
            target = outdir / (f.stem + args.suffix + ".md")
            target.write_text(md, encoding="utf-8")
            print("  %-12s %6d -> %6d 字符  %s" % (pid, f.stat().st_size, len(md), target.name))
            n += 1
        print("\n[OK] 共还原 %d 篇到 %s" % (n, outdir))
    else:
        md = convert(src, args.shift)
        if args.out:
            Path(args.out).write_text(md, encoding="utf-8")
            print("[OK] %d 字符 -> %s" % (len(md), args.out))
        else:
            print(md)


if __name__ == "__main__":
    main()
