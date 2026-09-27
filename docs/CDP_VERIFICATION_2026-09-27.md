# CDP 精简后的完整验证

日期：2026-09-27。按用户“你测试一下先”的要求，对当前开发版重新构建并执行完整回归，补充真实 Chrome 与 Python 运行时的本地 CDP 验证。

## 结果

| 检查 | 本次结果 |
| --- | --- |
| Python 完整回归 | **1,285 passed，0 failed**；启用禁网，使用项目 CI 的完整测试依赖 |
| DSH Bundle 回归 | **17 个文件，290 passed，0 failed** |
| 通用 Agent CLI 回归 | **55 passed，0 failed** |
| TypeScript 类型检查 | `tsc --noEmit` 通过 |
| 当前源码重新构建 | 通过；Agent 与 DSH 的编译入口字节一致 |
| 编译入口契约 | 仅注册 collect、runs、setup；backend 仅为 `cdp`，无 Computer Use 控制器导出 |
| 当前 payload | Agent、DSH 各 51 个文件与源文件一致，无退役后端执行模块 |
| 真实 Chrome 启动 | Chrome 153.0.8010.53：专用配置启动、本地欢迎页、CDP 连接、会话复用、原配置备份和清理通过 |
| Python 核心实际连接 | 当前源代码的 `BrowserSession` 通过 Playwright CDP 连接独立临时 Chrome，通过本地 DOM 读取 |
| 实际截图与边界 | 本地合成正文截图、PNG 签名、SHA-256、0600 权限通过；可见风险提示阻止截图；缺失平台页和未授权导航被拒绝；断开连接保留浏览器及页面 |

三套完整回归合计 **1,630 项通过，无失败**。Python 的 1 条 warning 来自验证禁网确实生效的测试，属于预期。构建仍有既有 DSH SDK 相对类型声明提示，构建和类型检查均成功。

这次补齐了此前精简记录中未执行最终完整 Python 复跑的验证缺口。测试期间没有修改产品源代码。

## 身份与保护检查

- 实际目录：项目的 `开发版/Media@Missher`。
- 分支：`codex/media-browser-agent-desktop-20260920`。
- HEAD：`f87dd8858a0b888f03a7885a1641823af13457bd`。工作区包含既有未提交改动；验证对象是当前实际文件，不只限于该提交。
- 根 VERSION 仍为 15.6.0；本次没有发布 V17。
- 对测试前记录的 370 个既有项目文件、60 个已安装文件和其中 7 个冻结发行文件核对摘要，均未改变。
- 两次浏览器检查均使用临时专用配置；测试创建的浏览器和目录已清理，未遗留测试 Chrome 进程。

## 验证边界

本次真实浏览器检查只打开本地合成测试页面，没有登录或采集真实平台。完整离线回归覆盖平台解析、恢复、历史导出和风险控制，但不能据此声称当前真实平台采集已通过。

编译入口注册检查使用隔离的工具注册器，没有安装到或调用当前 DSH、Hermes 等真实宿主。已有安装和冻结发行包保持原样。

## 证据

- [完整机器可读结果](../.superpowers/sdd/2026-09-27-cdp-verification-131720/verification.json)
- [Python 全量日志](../.superpowers/sdd/2026-09-27-cdp-verification-131720/python-full.log)
- [DSH 全量日志](../.superpowers/sdd/2026-09-27-cdp-verification-131720/harness-full.log)
- [Agent CLI 全量日志](../.superpowers/sdd/2026-09-27-cdp-verification-131720/agent-full.log)
- [构建日志](../.superpowers/sdd/2026-09-27-cdp-verification-131720/build.log)
- [真实 Chrome 启动结果](../.superpowers/sdd/2026-09-27-cdp-verification-131720/chrome-native.log)
- [Python 核心 CDP 实测结果](../.superpowers/sdd/2026-09-27-cdp-verification-131720/runtime-cdp-native.log)
- [本地 CDP 实测脚本](../.superpowers/sdd/2026-09-27-cdp-verification-131720/runtime-cdp-smoke.py)

原始日志、临时验证脚本和测试前文件摘要保存在本机证据目录，不属于发行包。
