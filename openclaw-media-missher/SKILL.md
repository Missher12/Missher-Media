---
name: media-missher
description: Use when collecting authorized creator posts, keyword search results, Weibo topic participants, or X posts from Bilibili, Xiaohongshu, Douyin, Weibo, or X through an existing signed-in Chrome session.
---

# Media@Missher V17.0.2

Use the shared local runtime. Run preflight before collection, keep targets sequential, use Chrome CDP, and stop immediately when the runtime reports a risk status.

## Commands

```bash
python scripts/preflight.py --json
python scripts/preflight.py --live --cdp-url http://127.0.0.1:9222 --json
python scripts/run_collection.py creator --platforms bilibili,xhs,douyin,weibo --count 1 --bilibili-uid UID --xhs-uid UID --douyin-uid UID --weibo-uid UID --output-dir OUTPUT --allow-navigation --no-feishu
python scripts/run_collection.py search --platform weibo --keyword TOPIC --count 5 --output-dir OUTPUT
```

The runtime home defaults to `~/.local/share/media-missher`. Set `MEDIA_MISSHER_HOME` only when the shared runtime was installed elsewhere.

## Rules

- Chrome CDP is the only active backend. Use the already authenticated Chrome session (`--backend cdp`) independently of the Agent host. Computer Use is removed; old requests return `backend-retired-computer-use`.
- Omitted backend settings default to `cdp`; old non-CDP preferences or plans are refused, never silently rewritten. The backend remains fixed in the plan and manifest.
- Preserve the evidence level of each CDP record. Rendered-page observations never imply response bodies, hidden metrics or complete evidence.
- BrowserSkill is retired. New `--backend browserskill` requests return `backend-retired-browserskill`; historical records remain readable/exportable but cannot resume that backend. Never invoke or install `bsk` as a fallback.
- `--browser-assist browserskill` is retired: it prints one line, `media-missher-diagnostic platform=<p> kind=precondition code=browser-assist-replaced`, and exits 78 before any browser action. Keep `--browser-assist off`, and note that the old `xhs-browser-assist-unsupported` code no longer exists.
- Never export credentials, change accounts, bypass challenges, or rotate network identities.
- `count=0` remains bounded by the runtime page cap. `--count-mode fixed` is the default; `--count-mode best_effort` with `--run-deadline` keeps paginating inside a finite per-platform batch budget, and a budget pause is reported as `budget-exhausted` instead of finished collection.
- Xiaohongshu creator collection is complete by default. Use `--bilibili-complete` when Bilibili details are required; `--xhs-complete` remains compatible, and `--xhs-comments` requests a bounded comment slice.
- Preserve the automatic randomized 5–15 second settle after each Xiaohongshu complete-mode note opens; allow enough platform timeout for the requested count.
- Runtime staging is private JSON. Any CSV, JSONL, or SQLite conversion belongs to the installed Codex adapter, and selection-driven export is a separate offline step that only reads already-saved verified results.
- Screenshots default to `off`. `--screenshot-mode opened|all --allow-navigation` requires `--browser-assist off` and the `cdp` backend.
- Keep at most one Xiaohongshu detail open and one CDP click per record. A requested comment slice may use at most three comment-container scrolls with a 1,500 ms wait after each; it never refreshes or reopens the detail, and a non-risk shortfall remains partial.
- Do not retry a `risk-stopped` result.
- Never overlap collections; the launcher holds the shared private collection lock through runtime exit.

## Troubleshooting

If preflight fails, correct the named missing runtime component or open the required signed-in platform page. Do not clear locks, state, or browser profiles as a recovery shortcut, and do not switch backends to work around a failure.

## 15.3.0 小红书与历史结果规则

小红书每批最多 10 条、3 页，批次启动至少间隔 600 秒；翻页前等待并重新检查风险，保持原来的单次精确详情打开和 5–15 秒停留。风险暂停持久保存，不自动重试、到期清除或切换账号/浏览器。预算仅是本地保守限制，不保证平台安全。

`media_missher_runs` 可离线列出、导出或比较历史运行，以及查询 `xhs-status`；它不能发起采集或清除风险暂停。仅在用户明确要求继续时，才给采集工具传 `resume_run`，并保持原平台、总目标数、后端和私有配置。拒绝风险祖先和无绑定的旧运行；历史已验收数与本次新采数分别报告，原记录不改写。

解除风险暂停不属于自动修复步骤，只能由用户检查账号后明确执行本地 `xhs_safety.py --acknowledge-risk`。这不会清除批次间隔，不会启动采集，也不会允许继续风险旧运行。详情见仓库 `docs/XHS_RELIABILITY_15.3.0.md`。

## 17.0.2 新设备名单

新设备先在 Harness 使用 media_missher_setup 生成 Excel/CSV 模板，导入平台、博主名称和完整官方主页，查看预览后选择行号。同平台每次可选多位；名称不是身份。名单导入和选择完全离线，不启动浏览器或采集。Git 维护入口为 harness-plugin/scripts/setup-device.mjs，构建后使用同一工具实现。profile 的 active_platforms 限定默认范围；旧 profile 无此字段时使用已配置平台。空目标在 runtime 安装和采集前停止。采集只使用 Chrome CDP，连接已有登录会话；旧 Computer Use 请求返回 backend-retired-computer-use，不自动改写。不添加开机启动项，不调用已退休的 BrowserSkill。

## 17.0.2 共享保护

同一用户 HOME 下的新版入口共用 `~/.local/share/media-missher-shared` 的锁与小红书状态。当前、默认及已登记 runtime home 的旧状态保守合并、同步写回；旧客户端不会自动获得全部保护。换端口、后端、浏览器或 runtime home 不会重置新版冷却。不要删除状态或切换 HOME/用户规避暂停。预检与采集共用 17.0.2 版本门槛，版本错误在 CDP 请求前停止；使用配套安装器修正。安装激活后根据本技能或已注册工具说明工作，不依赖维护对话。
