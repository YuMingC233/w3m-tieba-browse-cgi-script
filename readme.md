# tieba-cli

通过 w3m 阅读经过清理的百度贴吧帖子页面。

过滤器会自动完成两件事：

- 将新版 `/p/帖子ID` 地址转换为可由 w3m 阅读的移动版页面；
- 删除 App 推广、弹窗、头像占位文字、操作按钮和“打开 App”提示；
- 将列表中的帖子链接直接改写到本地过滤器，并补充“上一页 / 下一页”。

正文、作者、日期、贴吧已经嵌入页面的楼中楼以及普通链接会保留。

## 环境要求

- Python 3.10 或更高版本；
- 带 Cookie 支持的 w3m。

项目只使用 Python 标准库，不需要安装 pip 依赖。

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
```

也可以直接打开任意帖子：

```bash
w3m 'https://tieba.baidu.com/p/10955297834'
```

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
w3m 渲染清理后的 HTML
```

过滤器复用 `~/.w3m/cookie`，但 Python 不会读取或打印 Cookie 内容。抓取子进程会禁用 `siteconf`，避免请求再次重定向到 CGI 形成循环。

## 命令行调试

不经过 CGI 也可以输出过滤后的 HTML：

```bash
python tieba_filter.py 'https://tieba.baidu.com/p/10955297834' |
  w3m -T text/html
```

如果百度返回安全验证，先用同一台机器的 w3m 打开移动版页面，完成验证或等待风控解除，再重新进入帖子。

## 测试

```bash
python -m unittest discover -s tests -v
```
