# 快速开始

[返回首页](../README.md)

## 环境

准备 Python 3.12、Chrome、可用的本机 CDP 端点，以及已经明确授权的采集目标。运行依赖固定为 Playwright 1.45.0 和 openpyxl 3.1.5。此版本组合与当前 Chrome 的实际兼容性需要在使用环境中确认，不声明全系统已验收。

取得源码并进入项目目录。Linux / macOS：

```bash
python3.12 -m venv .venv
. .venv/bin/activate
python -m pip install -r runtime/requirements.lock
```

Windows PowerShell 可直接调用虚拟环境解释器，无需改变脚本执行策略：

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r runtime/requirements.lock
.\.venv\Scripts\python.exe runtime/scripts/scrape_all.py --help
```

Windows 示例只是环境准备方法；源码的文件权限及浏览器行为仍需实机验证。下文的 `python` 指当前虚拟环境解释器。安装依赖会联网下载软件包，但不会自动安装 Chrome。

## 准备 Chrome

使用独立浏览器数据目录。Chrome 从 136 起限制默认用户数据目录的远程调试开关，调试端口应配合非默认 `--user-data-dir` 使用，参见 [Chrome 官方说明](https://developer.chrome.com/blog/remote-debugging-port)。

例如在项目目录的另一个终端启动专用 Chrome：

Linux：

```bash
google-chrome --remote-debugging-port=9222 --user-data-dir="$PWD/browser-profile"
```

macOS：

```bash
"/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" \
  --remote-debugging-port=9222 --user-data-dir="$PWD/browser-profile"
```

Windows PowerShell（按实际安装位置调整）：

```powershell
& "$env:ProgramFiles\Google\Chrome\Application\chrome.exe" --remote-debugging-port=9222 --user-data-dir="$PWD\browser-profile"
```

在这个浏览器中手动登录目标平台。将端点保持在本机，不添加面向公网的监听、端口转发或任意来源放行参数。不要把日常 Chrome 的个人目录复制进仓库。`browser-profile/` 和 `outputs/` 已被忽略，但忽略规则不能代替提交前检查。

只读访问 `http://127.0.0.1:9222/json/version` 可以确认调试服务是否响应；这只证明端点可达，不证明登录、解析或实际采集成功。不要公开完整调试响应和 WebSocket 地址。

## 查看命令

```bash
python runtime/scripts/scrape_all.py --help
python runtime/scripts/scrape_all.py creator --help
python runtime/scripts/scrape_all.py search --help
```

入口读取本仓 runtime。查看帮助不会打开或连接 Chrome，也不会采集内容。

## 指定作者

以下命令会实际采集；先将占位符替换为已确认的 UID：

```bash
python runtime/scripts/scrape_all.py creator \
  --platforms bilibili --bilibili-uid YOUR_CONFIRMED_CREATOR_ID \
  --count 1 --cdp-url http://127.0.0.1:9222 \
  --allow-navigation --output-dir ./outputs
```

平台标识为 `bilibili`、`xhs`、`douyin`、`weibo`、`x`。对应作者参数为 `--bilibili-uid`、`--xhs-uid`、`--douyin-uid`、`--weibo-uid`、`--x-uid`；各平台对标识格式的要求不同，使用实际稳定标识，不以昵称猜测账号。

## 关键词搜索与普通话题

```bash
python runtime/scripts/scrape_all.py search \
  --platform bilibili --keyword "城市漫步" --count 3 \
  --cdp-url http://127.0.0.1:9222 --allow-navigation --output-dir ./outputs
```

微博普通话题通过 `--topic` 请求：

```bash
python runtime/scripts/scrape_all.py search \
  --platform weibo --topic "城市漫步" --count 3 \
  --cdp-url http://127.0.0.1:9222 --allow-navigation --output-dir ./outputs
```

微博超话不支持。条数表示请求目标，实际条数可能因内容不足、时间预算、字段缺失或页面阻断而减少。

## 参数与结果

| 参数 | 用途 |
| --- | --- |
| `--count` | 明确条数；初次使用从小范围开始 |
| `--allow-navigation` | 允许本次任务按目标导航 |
| `--output-dir` | 必填，本地记录与运行清单的输出根目录 |
| `--cdp-url` | 使用者提供的 Chrome CDP 地址 |
| `--count-mode fixed` | 固定目标的一批采集，仍受平台上限约束 |
| `--count-mode best_effort`、`--run-deadline` | 在明确时间预算内执行有界批次，不保证取完全部历史 |
| `--targets-json` | 显式多目标计划文件；POSIX 环境要求私有权限，结构见运行时合同 |
| `--screenshot-mode` | 平台和任务支持时请求截图，不代表所有平台均支持 |

记录位于 `outputs/run-…/`。不同执行路径可能使用不同清单结构；读取本次命令配套的 JSON、状态和诊断，不假设所有运行只有一个固定文件名。标准错误中可能有进度和诊断信息。

CLI 的 `--format` 仅接受 `json`。Excel 等格式使用[导出接口](data-capabilities.md#导出接口)。

## 常见问题

| 现象 | 处理方法 |
| --- | --- |
| 无法连接 CDP | 检查专用 Chrome、端口与非默认数据目录 |
| 登录墙、验证码或权限提示 | 在浏览器中手动处理并确认状态；不要让 Agent 循环重试 |
| `collection-busy` | 等待已有采集任务正常退出；不要删除锁文件强行并发 |
| `platform-cooldown` | 等待已有间隔结束，不通过重启 Agent 绕过 |
| `platform-risk-latched` | 停止采集，由使用者检查诊断和页面；不要自动清除状态文件 |
| 返回部分结果 | 查看条数、缺失字段和停止原因，不能将 partial 当作完整成功 |
| 没有 Excel 文件 | 采集默认保存 JSON，导出是后续的独立操作 |
| DSH 提示不是组合包 | 本仓是 Python 核心源码，需通过本地进程适配接入 |

结束使用时正常关闭专用 Chrome。运行数据和浏览器资料由你自行备份和管理。
