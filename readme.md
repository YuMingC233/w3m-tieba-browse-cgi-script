# w3m-tieba-browse-cgi-script

通过 w3m 阅读经过清理的百度贴吧列表、帖子和楼中楼页面。

过滤器会自动完成以下事情：

- 将新版 `/p/帖子ID` 地址转换为可由 w3m 阅读的移动版页面；
- 删除 App 推广、弹窗、头像占位文字、操作按钮和“打开 App”提示；
- 将列表中的帖子链接直接改写到本地过滤器，并补充“上一页 / 下一页”；
- 为依赖 JavaScript 的帖子正文补充翻页、页码跳转和正倒序查看；
- 将“打开 App 查看评论”替换为本地楼中楼链接，并提供楼中楼翻页。
- 导出 JSON 时优先使用当前 PC JSON 接口，失败时自动回退到旧移动端接口；
- 归档中同时保留可读文本和富内容结构，不丢弃图片 URL、表情、链接或未识别字段。
- 从完整归档生成按时间排序、只包含楼主主楼层与楼中楼的 Markdown。

正文、作者、日期、贴吧已经嵌入页面的楼中楼以及普通链接会保留。完整楼中楼按需加载，不会在进入主帖时一次请求所有楼层的评论。

> [!WARNING]
> 本项目使用的当前 PC JSON 接口与旧移动端 `mo/q---1-3-0--2/m`、`mo/q---1-3-0--2/flr` 都不是有版本兼容保证的公开 API。百度可能随时调整、限制或废弃（deprecated）它们；届时需要更新签名、分页或 HTML 解析逻辑，也可能因安全验证暂时无法使用。

## 环境要求

- Python 3.10 或更高版本；
- 带 Cookie 支持的 w3m。

项目只使用 Python 标准库，不需要安装 pip 依赖。

## 配置新版接口 Cookie

完整导出推荐使用当前 PC JSON 接口。使用前必须先在浏览器登录百度贴吧，并在项目根目录的 `.env` 中填写完整 Cookie：

```dotenv
BAIDU_COOKIE='BAIDUID=...; BDUSS=...; STOKEN=...; ...'
```

可在浏览器开发者工具的 Network 面板中打开一条 `tieba.baidu.com` 请求，复制 Request Headers 里的完整 `Cookie` 值。不要只复制 `BAIDUID`；登录态通常至少依赖 `BDUSS` 和 `STOKEN`。

`.env`、`temp/` 已被 Git 忽略。Cookie、Copy as cURL 和 HAR 都包含可以代表登录身份的敏感信息，不应提交、分享或写入导出 JSON。

Python 客户端优先读取进程环境中的 `BAIDU_COOKIE`，未设置时才读取当前目录或项目根目录的 `.env`。如果使用系统代理，建议让命令行对百度域名直连：

```bash
export NO_PROXY=".baidu.com,.bdstatic.com"
export no_proxy="$NO_PROXY"
```

## 临时运行

在项目目录执行：

```bash
w3m \
  -o cgi_bin="$PWD" \
  -o siteconf_file="$PWD/w3m-siteconf.example" \
  'https://tieba.baidu.com/p/10955297834'
```

也可以先打开贴吧移动版列表。列表本身会经过过滤器，因此可以翻页，点击帖子也不会再依赖 w3m 对相对 `/p/` 地址的二次匹配：

```bash
w3m \
  -o cgi_bin="$PWD" \
  -o siteconf_file="$PWD/w3m-siteconf.example" \
  'https://tieba.baidu.com/mo/q---1-3-0--2/m?kw=%E5%AD%99%E7%AC%91%E5%B7%9D'
```

## 永久配置

在 `~/.w3m/config` 中加入项目的绝对路径：

```text
cgi_bin /home/owner/Coding/OpenSource_Project/tieba-cli
```

再把 `w3m-siteconf.example` 中的规则追加到 `~/.w3m/siteconf`。如果此前已经配置过将 `/p/` 改写到远程移动页的规则，请用本项目的 CGI 规则替换它，或者确保本项目规则排在后面；w3m 使用最后一条匹配规则。

之后正常启动即可：

```bash
w3m 'https://tieba.baidu.com/mo/q---1-3-0--2/m?kw=%E5%AD%99%E7%AC%91%E5%B7%9D'
```

列表底部会显示：

```text
上一页 | 第 2 / 60552 页 | 下一页
跳转到第 [2] 页 [跳转]
```

将光标移动到页码输入框，按回车后输入目标页码，再移动到“跳转”并按回车，即可直接打开指定的帖子列表页。过滤器会根据百度返回的每页数量，将页码自动换算成 `pn` 偏移量；超出总页数时会显示明确的错误提示。

也可以直接打开任意帖子：

```bash
w3m 'https://tieba.baidu.com/p/10955297834'
```

帖子正文超过一页时，页面底部会显示普通链接：

```text
上一页 | 第 2 / 19 页 | 下一页
倒序查看
跳转到第 [2] 页 [跳转]
```

将光标移动到页码输入框，按回车后输入 `7`；再移动到“跳转”并按回车，即可打开第 7 页。“倒序查看”会从全帖最后一页开始向前阅读，再次切换“正序查看”会回到相同的逻辑页码。

`pn` 是楼层偏移量而不是页码，过滤器会根据百度页面返回的每页数量、总页数和阅读顺序自动计算；不需要手动修改 URL。百度原始的 `r=1` 只反转当前分页块，过滤器会额外镜像页码，使倒序阅读覆盖整个帖子。

帖子中存在未完整展开的楼中楼时，原来的 App 提示会变成普通链接：

```text
贴吧用户_G2ZRZEb: 3
杨连强帅: 3
查看全部 111 条楼中楼
```

将光标移到“查看全部”并按回车，会打开本地 CGI 页面。楼中楼每页显示 10 条，保留作者和正文，底部提供独立分页：

```text
上一页 | 共 111 条 · 第 2 / 12 页 | 下一页
```

按 `B` 即可返回帖子。评论数会随新回复变化，因此链接文字和总页数可能在两次打开之间增加。

## 工作方式

```text
w3m 打开贴吧列表页
        ↓
siteconf 先将列表页交给本地过滤器
        ↓
Python 生成上下页链接，并把 /p/帖子ID 改成 CGI 链接
        ↓
w3m 点击 CGI 帖子链接
        ↓
过滤器调用子 w3m 获取移动版 HTML
        ↓
Python 按 DOM class 删除无用节点
        ↓
Python 为帖子正文生成上下页、跳页和正倒序链接
        ↓
w3m 渲染清理后的 HTML
        ↓
点击“查看全部楼中楼”
        ↓
CGI 按页取得移动端 flr JSON，清理其中的 HTML 后交给 w3m 渲染
```

过滤器复用 `~/.w3m/cookie`，但 Python 不会读取或打印 Cookie 内容。抓取子进程会禁用 `siteconf`，避免请求再次重定向到 CGI 形成循环。

楼中楼使用按需分页而不是自动抓取全部内容，原因是一个帖子可能包含许多带评论的楼层；自动展开会显著增加等待时间和请求数量，也更容易触发百度安全验证。

## 命令行调试

不经过 CGI 也可以输出过滤后的 HTML：

```bash
python tieba_filter.py 'https://tieba.baidu.com/p/10955297834' |
  w3m -T text/html
```

如果百度返回安全验证，先用同一台机器的 w3m 打开移动版页面，完成验证或等待风控解除，再重新进入帖子。

直接调试楼中楼 CGI 时，需要同时提供帖子 ID、父楼层 `pid` 和页码：

```bash
w3m 'file:/cgi-bin/tieba_filter.py?lzl=1&tid=10955297834&pid=153847299771&pn=1'
```

直接调试帖子正文第 2 页时，可以传入楼层偏移量 `pn=30`：

```bash
w3m 'file:/cgi-bin/tieba_filter.py?10955297834&pn=30'
```

## 导出完整帖子

需要把帖子交给 Agent 或其他程序继续分析时，先确认 `.env` 已填写 `BAIDU_COOKIE`，再显式测试推荐的新版接口：

```bash
python -m tieba_cli export 10955297834 --source current
```

`current` 模式在首次导出时遇到 Cookie 失效或接口变更会直接报错；已有完整快照时则保留旧 JSON，并把更新状态标记为 `check_failed`。确认配置可用后，日常可使用默认的 `auto`：

```bash
python -m tieba_cli export 10955297834
```

`auto` 会优先请求当前 PC JSON 接口；如果登录态、网络、签名或返回格式异常，则自动回退到旧移动端 HTML 接口。也可强制使用旧接口：

```bash
python -m tieba_cli export 10955297834 --source legacy
```

导出时会在终端显示“正文页”和“楼中楼”两个阶段的进度条。进度写入 stderr，stdout 仍然只输出最终 `thread.json` 路径，因此不会影响脚本通过命令替换或管道取得结果路径。输出被重定向或由 Agent 调用时，每个阶段只输出一行完成信息，避免产生大量刷新字符。

默认结果位于：

```text
~/.cache/tieba-cli/threads/10955297834/thread.json
```

也可以指定独立目录：

```bash
python -m tieba_cli export 10955297834 \
  --output ./exports/10955297834
```

输出目录包含：

- `thread.json`：完成后生成的全帖快照，适合提交给 Agent；
- `posts.jsonl`：每行一个主楼层，适合流式处理和文本检索；
- `manifest.json`：导出状态、实际数据源和已完成进度；
- `current/`：新版接口的逐页正文、楼中楼和断点清单；
- `pages/` 与 `lzl/`：回退到旧移动端时使用的逐页缓存。

### JSON 富内容结构

导出格式为 `schema_version: 2`。每个主楼层和楼中楼都同时提供：

- `content_text`：便于 Agent、全文检索和终端阅读的纯文本；
- `content`：富内容数组。新版接口返回的每个对象会原样保留，包括图片 `media[].origin_src`、尺寸、表情、@用户、链接及尚未识别的字段；
- `content_html`：使用旧移动端回退时保留的正文 HTML，便于未来前端重建图片、链接和格式。
- `is_thread_owner`：该内容作者是否为帖子楼主，主楼层与楼中楼都会生成。

图片文件本身不会被下载；归档保留的是百度响应中的 URL 和相关元数据。Cookie、`tbs` 和请求签名不会写入归档。

### 楼主识别与手动纠正

程序默认使用 `floor == 1` 的作者识别楼主，优先按 `author_id` 匹配该作者的其他主楼层和楼中楼；旧接口没有作者 ID 时退回精确用户名匹配。识别结果记录在 `thread.owner`：

```json
{
  "status": "detected",
  "source": "first_floor",
  "author_id": "123456",
  "author": "示例用户",
  "match_by": "author_id"
}
```

如果接口没有返回首楼，`status` 会是 `unknown`，程序不会猜测楼主。如果自动结果有误，打开已经导出的 `thread.json`，在正确作者的任意一个主楼层对象中手动加入：

```json
"thread_owner_override": true
```

再次执行原导出命令后，程序会读取该字段，将同一作者的所有主楼层和楼中楼标记为 `is_thread_owner: true`，并把 `thread.owner.source` 改为 `manual_override`。手动字段必须是 JSON 布尔值 `true`，不能写成字符串 `"true"`。如果不同作者同时带有手动标记，程序会报错而不会任选其中一个；删除错误标记、只保留正确作者的一个标记后再执行即可。

正文页中的已展示楼中楼会直接保留。如果讨论必须包含全部楼中楼，可显式启用：

```bash
python -m tieba_cli export 10955297834 \
  --include-lzl \
  --delay 1.5
```

同时也支持 `rd` 为值:

```bash
python -m tieba_cli export 10955297834 \
  --include-lzl \
  --delay rd
```

`--include-lzl` 可能产生很多请求，也更容易遇到百度安全验证，所以默认关闭。`--delay` 控制连续请求的最小间隔，默认 1 秒。首次导出遇到验证、网络错误或手动中断后，重新执行同一命令会复用已经成功写入的逐页缓存。

### 按时间导出楼主全部发言

使用默认缓存目录完成包含楼中楼的导出后，可以生成只包含楼主发言的 Markdown：

```bash
python -m tieba_cli export 10955297834 --include-lzl --delay 1.5
python -m tieba_cli owner-md 10955297834
```

第二条命令只读取本地 `thread.json`，不会再次请求百度。它根据 `is_thread_owner` 排除其他用户，将楼主的主楼层和楼中楼按 `posted_at` 合并排序，同时保留楼层、PID、正文以及能够从富内容中提取的图片 URL。时间缺失的旧接口内容不会丢弃，而是标记为“时间未知”并放在文档末尾。

生成文件以楼主用户 ID 命名，位于该帖缓存目录，例如：

```text
~/.cache/tieba-cli/threads/10955297834/123456.md
```

如果缓存未完整导出、没有使用 `--include-lzl`、楼主身份无法确认或接口没有提供楼主用户 ID，命令会直接报错，不会生成可能缺漏或命名错误的文档。目前该工具只读取默认缓存目录；使用 `export --output` 产生的自定义目录不会被自动查找。

### 更新检查与归档状态

对已经完整导出的帖子再次执行相同命令时，程序会默认检查更新：

- 重新扫描全部正文页，更新总楼层数、新增或删除的楼层，以及同一 `pid` 下已修改的正文；
- 比较每个主楼层的 `nested_reply_count`。数量发生变化时，只重新抓取该父楼层的完整楼中楼，并按楼中楼 `pid` 去重；
- 楼中楼数量未变化时复用原有完整楼中楼，避免无条件产生大量请求。

楼中楼接口没有全帖级版本号，因此“删掉一条又新增一条”或直接编辑内容、但总数恰好不变时，无法只靠计数可靠发现。需要确认这类变化时使用：

```bash
python -m tieba_cli export 10955297834 \
  --full-refresh-lzl \
  --delay 1.5
```

`--full-refresh-lzl` 会自动启用完整楼中楼导出，并忽略计数是否变化，重新请求所有父楼层的楼中楼。

`manifest.json` 的 `update` 与 `thread.json` 的 `export.update` 会同步记录三种状态：

- `active`：最近一次检查成功，归档内容是当前成功取得的快照；
- `check_failed`：检查因 Cookie 过期、网络、安全验证、接口变更等原因失败，原有 JSON 继续保留，不能据此判断帖子已删除；
- `archived`：任一接口明确返回帖子不存在或已删除，立即归档，之后默认不再访问百度。

状态中还会保留 `last_checked_at`、`last_success_at`、`last_error`、`consecutive_not_found`、`archived_at` 和 `archive_reason`。普通请求失败、拿不到楼层数量、Cookie 失效、“加载数据失败”或没有楼层的通用空页面都不会永久归档，避免把短暂风控或接口故障误判为删帖。只有接口给出明确的不存在、删除或封禁信号时才会立即进入 `archived`，不要求另一个接口再次确认。

新版或旧版首屏没有任何主楼层时，程序会把它视为无效候选快照：不会写入 `thread.json`、不会清空 `posts.jsonl`，也不会把空页面缓存成有效首屏。已有成功归档时，只更新 `export.update` 为 `check_failed` 并继续保留最后一次非空正文。首次导出只能取得空页面时则直接报错，不生成 `complete` 快照。

对于封禁或删除场景，只要新版或旧移动端任一接口明确返回“帖子可能已被删除”、不存在或同等含义的信号，就立即标记为 `archived`。已有成功快照时会完整保留正文、楼中楼与图片 URL；首次获取就确认删除时只生成归档状态的 `manifest.json`，不会用空内容生成或覆盖 `thread.json` 和 `posts.jsonl`。后续普通运行会直接报告已归档且不再发起请求。

若需要重新检查已归档帖子，可使用：

```bash
python -m tieba_cli export 10955297834 --force-refresh
```

强制刷新成功后，状态会恢复为 `active`；失败时仍保留已有正文和图片 URL。

w3m/CGI 阅读仍使用旧移动端页面和 w3m Cookie jar；结构化导出则优先使用 `.env` 中的登录 Cookie 请求当前 JSON 接口。两条路径都不会尝试绕过 CAPTCHA 或安全验证。

## 让 Codex 直接讨论帖子

仓库包含 [`tieba-discuss`](skills/tieba-discuss/SKILL.md) Skill。它会调用上述导出命令，并要求 Agent 按楼层和 `pid` 区分贴吧原文与自己的推断。Skill 本身不重复实现抓取逻辑，也不会直接读取 Cookie。

在项目根目录把 Skill 链接到 Codex 的个人 Skill 目录：

```bash
mkdir -p ~/.codex/skills
ln -s "$PWD/skills/tieba-discuss" ~/.codex/skills/tieba-discuss
```

如果目标已经存在，`ln` 会拒绝覆盖；请先确认它是旧副本还是正确链接，不要直接删除。重启 Codex 或开启新会话使其发现 Skill，之后可以这样使用：

```text
使用 $tieba-discuss 读取帖子 10955297834，梳理争议双方的主要依据。
```

要求“完整讨论”或问题依赖楼中楼时，Skill 会使用 `--include-lzl`；否则默认只导出全部主楼层和页面已经嵌入的楼中楼，以减少请求和触发安全验证的概率。若导出中断，Agent 应报告 `manifest.json` 的未完成状态，而不是把局部内容当成全帖。

## 测试

```bash
python -m unittest discover -s tests -v
```
