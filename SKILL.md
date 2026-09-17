---
name: cnblogs-article-maintenance
description: 维护博客园（cnblogs.com）文章：批量改写与原地更新、修复「Markdown 没渲染、读者看到 ## 和 ** 源码」、上传配图、补标签与摘要、批量删除随笔、备份与回滚。触发场景：帮改博客园文章、博客园批量推送 Markdown、文章排版乱了、博客园文章显示的是源码、给博客园文章配图、删掉博客园某些文章、清理博客、查博客园文章阅读量/标签、MetaWeblog 接口问题、博客文章结构优化。
---

# 博客园文章维护（MetaWeblog）

用官方 MetaWeblog 接口维护博客园文章。比浏览器自动化稳得多：协议层不会因为前端改版失效，
而且能原地更新（**保留原 URL、阅读量、评论**）。

## 一、先判断是哪类任务

| 用户说 | 要做什么 |
|---|---|
| 「帮我改文章结构/描述」 | 走第二节的标准五步流程 |
| 「文章排版乱了，显示一堆 `##` 和 `**`」 | 这是**未渲染**，见第三节，一次 editPost 就能修 |
| 「配张图」 | `upload_image.py` 上传 → 把 URL 填进 `![]()` → 重新 update |
| 「备份一下」/「改坏了怎么还原」 | `cnblogs_push.py backup`；回滚见第五节 |
| 「把某些文章删掉」/「清理博客」 | **先出清单分档让用户划范围**，再走第九节，`delete_posts.py` 强制先备份后删除 |

**动手前先跑一次 `check_render.py`。** 实测过：看起来"内容不错"的文章，
线上可能是源码墙——不知道这一点就改，会把结构问题和渲染问题混在一起判断。

---

## 二、标准工作流（五步，顺序不要换）

```
① backup            → 全站原文落本地，这是唯一的后悔药
② html2md.py        → 把 description 还原成干净 Markdown 底稿，看清骨架
③ 写成稿            → 保留全部技术内容，只重排结构 + 加小标题 + 改表格
④ update            → 推送（自动备份单篇 + 保分类 + 补 [Markdown]）
⑤ check_render.py   → 立刻验证渲染，字面量必须归零
```

命令示例（在放 `.cnblogs.env` 的工作目录下执行）：

```bash
S=<skill>/scripts
python $S/cnblogs_push.py check                                    # 验令牌
python $S/cnblogs_push.py backup                                   # ① 全站备份
python $S/html2md.py 原始备份/12345678-xxx.md -o 还原/12345678.md   # ② 出底稿
# ③ 写成稿 → 成稿-01.md
python $S/cnblogs_push.py update --post-id 12345678 --file 成稿-01.md  # ④
python $S/check_render.py 12345678                                 # ⑤ 验证
```

**改稿的六条固定手法**（实测有效，读者扫读率明显提升）：
1. 头部加「系列导航 + 本篇/上一篇/下一篇链接 + 脱敏声明」
2. 新增 **TL;DR**，把最硬的坑提到第一屏（原文往往要读到第 8 节才看到）
3. 平铺章节改成「分层实现 → 排坑索引 → 原则收束」
4. 踩坑清单从文末死列表改成带「详见 §x」跳转的**索引**，并前移
5. 散落的「现象 + 解法」段落改成**表格**
6. **技术内容一字不删**——只重新分组、加小标题、改表格；数值和命令参数原样保留

---

## 三、文章「未渲染」——最常见的坑

### 症状
读者看到的是带 `##`、`**`、``` 的源码，不是排版。

### 根因
正文是把 Markdown 源码粘进了博客园的 **HTML 编辑器**，且**文章分类为空** ——
缺少博客园用来识别 Markdown 的 `[Markdown]` 标记，于是内容按 HTML 解析。

典型特征：`description` 里每行被包成 `<div>## 1. 标题</div>`，
**正文中 0 个 `<h2>` / `<pre>` / `<table>`，但含大量字面量 `##`、`**`**。

### 修复
`editPost` 推送**干净的 Markdown 原文** + 分类里加 `[Markdown]`。
实测：修复后 `h2=10, table=3, code=53`，字面量全部归零。

> 副作用：分类里会多出一个可见的「Markdown」标签，**去不掉**——去掉它渲染就失效。

---

## 四、MetaWeblog 七个坑（全部踩过）

| # | 坑 | 做法 |
|---|---|---|
| 1 | 密码登录已取消 | 用后台「设置 → 其他设置 → 允许 MetaWeblog 博客客户端访问」生成的**访问令牌** |
| 2 | `description` 转了 HTML | **直接放 Markdown 原文**。转成 HTML 后经 XML-RPC 转义，`<pre>` 会变成 `&lt;pre&gt;`，代码块全毁 |
| 3 | 分类缺 `[Markdown]` | 必须带上，否则按 HTML 解析，Markdown 原样显示（官方文档没写） |
| 4 | `editPost` 全量覆盖、不可回滚 | update 前先 `getPost` 备份，并**原样带回原分类**，否则分类被清空 |
| 5 | `mt_keywords` / `mt_excerpt` 不自动保留 | 标签和摘要必须**每次显式带上**，否则被清空。`cnblogs_push.py update` 不传参数时会自动沿用原文旧值 |
| 6 | `newMediaObject` 的 `bits` 报 `TypeError` | 传 `xmlrpc.client.Binary(原始 bytes)`，**不要自己再 base64 一遍** |
| 7 | 抓页面拿到旧内容 | 线上有 CDN 缓存。抓取要加 `Cache-Control: no-cache` 且 URL 带时间戳（`check_render.py` 已内置） |

**端点**：`https://rpc.cnblogs.com/metaweblog/<博客名>`
**可用方法**：`newPost` / `editPost` / `getPost` / `getRecentPosts` / `getCategories` / `newMediaObject` / `blogger.deletePost`（删除，见第九节）

---

## 五、回滚

两层备份，缺一不可：

```
原始备份/                  # backup 命令产出的全站快照
原始备份/更新前/            # 每次 update 前自动存的单篇快照（带时间戳）
```

还原某一篇：

```bash
python <skill>/scripts/cnblogs_push.py update --post-id 12345678 \
       --file "原始备份/更新前/12345678-20260101-120000.md"
```

> 注意：这样会把正文恢复成当初的 HTML 形态，**渲染问题会跟着回来**。

---

## 六、脚本清单（`scripts/`）

| 脚本 | 用途 | 需要令牌 |
|---|---|---|
| `cnblogs_push.py` | 主工具：`check` / `list` / `backup` / `draft` / `update`（支持 `--keywords` `--excerpt` `--no-publish`） | 是 |
| `html2md.py` | description 的 HTML 形态 → 干净 Markdown 底稿。支持 `--shift N` 整体调标题层级、`--only <ids>` 批量 | 否 |
| `check_render.py` | 抓线上页面判断渲染状态（字面量必须为 0）。改完必跑 | 否 |
| `verify_all.py` | 渲染 + 元信息（正文长度/摘要/标签/分类）一次核对 | 是 |
| `upload_image.py` | 上传本地图片到博客园图床，返回 URL | 是 |
| `delete_posts.py` | 批量删除随笔：**强制先备份 + 校验落盘一致才删**，删后自动探活。支持 `--apply` 开关 | 是 |

全部只依赖 Python 标准库，不需要 `pip install` 任何东西。

### html2md.py 的四个实现要点（改它之前先看这里）

1. **必须有 `handle_data`**，否则所有文本被静默丢弃（第一版只输出 1 个字符，排查了很久）。
2. **代码围栏内保留行首空格，围栏外才 lstrip** —— 否则 ASCII 架构图、目录树的缩进全丢。
3. **表格分隔行 `|---|---|` 不能当"残留符号行"过滤掉**。
4. **块级元素之间补空行**，否则相邻两行被 Markdown 合并成一段；但**列表内、表格行内不能补**，否则把列表和表格打断。

---

## 七、配置

复制 `.cnblogs.env.example` 为 `.cnblogs.env`（**不要把它提交到任何仓库**）：

```
CNBLOGS_API_URL=https://rpc.cnblogs.com/metaweblog/<博客名>
CNBLOGS_USERNAME=<后台显示的 MetaWeblog 登录名>
CNBLOGS_TOKEN=<访问令牌>
CNBLOGS_BLOG_ID=
CNBLOGS_HOME=                 # 可选，形如 https://www.cnblogs.com/<博客名>，删文探活用
```

查找顺序：**脚本同目录 → 当前工作目录 → 用户主目录**；也可用 `CNBLOGS_*` 环境变量覆盖
（环境变量优先，`.cnblogs.env` 只补空缺）。

**安全约定**：令牌等价于账号密码。**不要让用户把令牌贴在对话里** ——
让用户直接写进 `.cnblogs.env`，脚本只读文件、不打印内容。

---

## 八、配图（自绘示意图 → 上传）

用户常有的约束：文章内容来自真实工作、**不能带真实截图**。
解法是用示意图，流程：

```bash
# ① 用 HTML/CSS 写图（源文件留在 配图/，以后改文字重渲即可）
# ② Edge headless 截图
msedge --headless=new --disable-gpu --hide-scrollbars \
       --default-background-color=00000000 \
       --user-data-dir=<临时目录> --window-size=1210,646 \
       --screenshot="配图/xxx.png" "file:///.../配图/xxx.html"
# ③ 上传
python <skill>/scripts/upload_image.py 配图/xxx.png
# ④ 把返回的 URL 填进 Markdown
```

**三个坑**：① 必须加 `--hide-scrollbars`，否则出滚动条（还会连带挤出横向滚动条）；
② **窗口高度要算准**，矮了会把卡片底部裁掉（内容高度 = padding + 标题区 + 行数 × 行高 + 页脚）；
③ 图片**不要打码**——重造 > 重绘 > 打码，一块黑条本身就在告诉读者"这里有东西"。

---

## 九、删除随笔（不可逆，先划范围再动手）

### 接口
`blogger.deletePost(appKey, postid, username, password, publish)` → 恒返回 `true`。
appKey 传空字符串即可。**博客园的 MetaWeblog 文档页把可用方法写在这里**：
`https://www.cnblogs.com/<博客名>/services/metaweblog.aspx`

> 注意：`system.listMethods` **不可用**（返回 `Fault 1: 'Failed to handle XmlRpcService call'`）。
> 想确认某个方法是否被支持，只能查上面那个文档页，别浪费轮次去探。

### 删除前的强制流程（缺一步都不许删）

1. **列全清单**：从 `原始备份/*.meta.json` 取全部 postId + 日期 + 标题，
   再抓一遍每篇的**阅读数 / 评论数**——正则用 `post_view_count">(\d+)<`、
   `post_comment_count">(\d+)<`（不是 `阅读\((\d+)\)`，会全抓成 -1）。
2. **分档让用户划范围**。按用户自己的说法分档，不要替用户扩大范围。
   经验：标题含「学习」是一档；「用 X 技术写的工具」是另一档——
   后者往往是用户的职业技能相关资产（如 aapt 取包名/targetSdkVersion 对 Android 测试），
   **主动提示保留**，但决定权交给用户。
3. **报阅读量代价**。老博客的流量往往高度集中在少数几篇老文上
   （实测：18 篇 2019 年文章占全站 17390 阅读中的 17089，其中最高的单篇占全站约 27%）。
   删之前必须把这个数字告诉用户，并指出其中单篇最高的那篇。
4. **备份 → 校验 → 才删**。`delete_posts.py` 已把这三步串成一次执行，
   并且**备份任何一篇失败、或落盘字符数与接口返回不一致时整体中止**，不会删一半。
5. **删后探活**：目标 URL 应全部 404/410；再对**保留的文章**逐个探活确认没误伤。

### 命令

```bash
S=<skill>/scripts
# 只备份不删（安全预览）
python $S/delete_posts.py --ids 12345678,12345679,...
# 备份校验通过后真删
python $S/delete_posts.py --ids 12345678,12345679,... --apply
```

备份落在 **当前工作目录** 的 `删除备份/`（含 `.md` 正文 + `.meta.json` + `manifest.json` 清单）。
已删除的 postId 再传给它，会在 `getPost` 阶段报 `Fault 404: '博文不存在'` 并整体中止——
**这个中止路径要保留，它是防止"备份不完整却继续删"的闸门**。

探活的站点前缀按「`CNBLOGS_HOME` → 从接口返回的 `permaLink` 推断」自动确定，
**不需要改脚本**。

### 三个已知事实

- **回不去**：接口无回收站访问能力，`回收站` 在后台（需登录 cookie），脚本读不到。
  所以本地备份是唯一的后悔药。
- **评论会随文章一起消失**。删之前把有评论的文章单独点出来给用户看。
- 删掉的只是该篇；**分类、标签、图床里的图片不会自动清理**。

### 实现坑

- `getPost` 返回的 `dateCreated` 是 `xmlrpc.client.DateTime`，**`json.dumps` 会抛
  `TypeError: Object of type DateTime is not JSON serializable`** —— 要加 `default=str`。
- 同一个文件**不要并行发多个 Edit**：写入会互相覆盖，表现为"工具报成功但改动没生效"
  （踩过一次，排查了一轮）。
