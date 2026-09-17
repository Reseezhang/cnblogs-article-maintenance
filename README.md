# cnblogs-article-maintenance

用博客园**官方 MetaWeblog 接口**维护文章，而不是浏览器自动化。

协议层不会因为前端改版失效，而且能**原地更新**——保留原 URL、阅读量、评论。

> 这是一个 [Agent Skill](https://docs.claude.com/en/docs/claude-code/skills)：`SKILL.md` 描述工作流，
> `scripts/` 是可直接执行的工具。技能目录和脚本本身都可以独立使用。

## 它解决什么

| 你说 | 它做什么 |
|---|---|
| 「帮我改文章结构」 | 五步流程：备份 → 还原底稿 → 写成稿 → 推送 → 验证渲染 |
| 「文章排版乱了，显示一堆 `##` 和 `**`」 | 这是未渲染，一次 `editPost` 修好 |
| 「配张图」「不能带真实截图」 | 自绘示意图 → Edge headless 渲染 → 上传图床 |
| 「把某些文章删掉」 | 先列清单分档让你划范围，再强制备份校验后删除 |
| 「备份一下」 | 全站原文落本地，这是唯一的后悔药 |

## 四个别人很少提的坑

**1. Markdown 没渲染的根因是分类为空。**

博客园靠分类里的 `[Markdown]` 标记判断用哪种解析器。少了它，正文里的 `##`、`**`、
代码围栏会**原样显示给读者**。

诊断特征很明确：正文里 `<h2>` / `<pre>` / `<table>` 全是 0 个，但含大量字面量 `##`。

（真实踩过：4 篇文章对读者是一堵源码墙，而这几篇恰好是我内容最好的几篇。
阅读量一直上不去的直接原因在这里，不在 SEO。）

**2. `description` 里直传 Markdown，千万别转 HTML。**

转完的 HTML 再经 XML-RPC 转义，`<pre>` 会变成 `&lt;pre&gt;`，代码块全毁。

**3. `mt_keywords` / `mt_excerpt` 不会被 `editPost` 自动保留。**

标签和摘要必须**每次显式带上**，否则被清空。`cnblogs_push.py update` 不传参数时会自动沿用原文旧值。

**4. `editPost` 是全量覆盖且不可回滚。**

所以更新前自动存一份原文快照，并原样带回原分类——否则分类也被清空。

## 快速开始

```bash
cp .cnblogs.env.example .cnblogs.env     # 填入后台生成的访问令牌
S=./scripts

python $S/cnblogs_push.py check                        # 验令牌
python $S/cnblogs_push.py backup                       # 全站备份（唯一的后悔药）
python $S/check_render.py --all                        # 诊断哪些文章没渲染
python $S/html2md.py 原始备份/12345678-xxx.md -o 还原/12345678.md
python $S/cnblogs_push.py update --post-id 12345678 --file 成稿-01.md
python $S/verify_all.py 12345678                       # 渲染 + 元信息一次核对
```

> **令牌等价于账号密码。** 它只存在于 `.cnblogs.env`（已被 `.gitignore` 排除），
> 脚本只读文件、不打印内容。请用后台生成的**访问令牌**，不是登录密码——博客园已取消密码登录。

## 脚本

| 脚本 | 用途 | 需要令牌 |
|---|---|---|
| `cnblogs_push.py` | 主工具：`check` / `list` / `backup` / `draft` / `update`（支持 `--keywords` `--excerpt` `--no-publish`） | 是 |
| `html2md.py` | 把 `description` 的 HTML 形态还原成干净 Markdown 底稿，支持 `--shift N` 调标题层级 | 否 |
| `check_render.py` | 抓线上页面判断渲染状态（字面量必须为 0）。改完必跑 | 否 |
| `verify_all.py` | 渲染 + 元信息（正文长度 / 摘要 / 标签 / 分类）一次核对 | 是 |
| `upload_image.py` | 上传本地图片到博客园图床，返回 URL | 是 |
| `delete_posts.py` | 批量删除：**强制先备份 + 校验落盘一致才删**，删后自动探活 | 是 |

全部只依赖 Python 标准库，不需要 `pip install` 任何东西。

## 配图：不能带真实截图怎么办

如果文章内容来自真实工作、不能外发截图，**不要打码**——重造 > 重绘 > 打码，
一块黑条本身就在告诉读者"这里有东西"。正确做法是自绘示意图：

```bash
# ① 用 HTML/CSS 写图（源文件留着，以后改文字重渲即可）
# ② Edge headless 截图
msedge --headless=new --disable-gpu --hide-scrollbars \
       --default-background-color=00000000 \
       --user-data-dir=<临时目录> --window-size=1210,646 \
       --screenshot="配图/xxx.png" "file:///.../配图/xxx.html"
# ③ 上传
python $S/upload_image.py 配图/xxx.png
```

两个坑：`--hide-scrollbars` 必须加，否则截图里会出现滚动条；窗口高度要算准，
矮了会把卡片底部裁掉。

## 删除是不可逆的

博客园的 MetaWeblog **没有回收站访问能力**（回收站在后台，需要登录 cookie）。
所以本地备份是唯一的后悔药。

`delete_posts.py` 把「备份 → 校验落盘字符数与接口一致 → 才删」串成一次执行，
**任何一步失败整体中止**，不会删一半。删后还会自动探活确认没误伤保留的文章。

删之前先想清楚代价：老博客的流量往往高度集中在少数几篇老文上。
（实测：18 篇 2019 年文章占了全站 17390 阅读里的 17089 篇次。）

## 关于 html2md.py

博客园把正文存成什么样的 HTML，取决于当初是怎么贴进去的——可能是干净的 Markdown
被包进 `<div>`，也可能是从网页整段复制的、带着上百层空 `div` 和前端框架 class 的碎片。

`html2md.py` 用标准库把这两种形态都还原成干净 Markdown。改它之前先看 `SKILL.md`
第六节的四个实现要点，那里记着为什么必须那样写。

## 许可

MIT，见 [LICENSE](LICENSE)。
