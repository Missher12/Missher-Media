# Media@Missher 15.3.0 / Bundle 0.2.0 候选说明

本次按用户确认的升级方向实施，优先减少小红书重复请求和异常后继续运行。Git CLI 与 Harness Bundle 共用 Python 采集核心。候选在独立工作树内开发；正式安装、真实平台采集和发布不属于本次离线验证。

## 小红书的默认行为

| 控制点 | 行为 |
| --- | --- |
| 单批数量 | 最多 10 条笔记；原始目标数保留，超出上限时返回部分结果 |
| 列表页 | 每批最多 3 页；后续翻页前等待 3 秒，并在等待前后检查风险 |
| 正文页 | 创作者采集保持完整详情优先；每条只做一次精确打开，保留 5–15 秒停留 |
| 评论 | 默认 0；用户明确请求才读取，原有最多 3 次、间隔 1.5 秒的评论滚动预算保留 |
| 批次间隔 | 同一 runtime home 的小红书批次实际启动时间至少相隔 600 秒；前置平台耗时不会抵消间隔，重启程序不会清除 |
| 风险暂停 | 403、429、461、471、999、验证页和风险信号立即停止；控制器从输出检测到风险时也会补存暂停，不自动过期或重试 |
| 继续工作 | 用户显式指定原运行 ID，使用原请求和私有配置；重新检查环境，并受同样的批次限制 |

这些数值是本地保守预算，并非平台认可的安全阈值，不能保证账号不触发风控。程序不切换账号、代理或浏览器规避限制，也不处理验证码。历史导出和对比只读本地记录，不产生平台请求。

## 修复的问题与处理方式

问题：Harness 停止后，独立进程组中的 Python runtime 可能继续采集。原因：外层只结束适配器进程组，适配器没有完整转发停止信号。影响：界面显示停止时，浏览器仍可能被操作，锁也可能过早释放。推荐方案已实现：适配器先清理自己创建的 runtime 进程组及其子进程，保持 collection lease 到清理结束；外层 8 秒宽限大于内层有界清理预算。用户 Chrome 不在终止范围内。

问题：原 manifest 只在所有平台结束后写出。原因：已完成数据和最终清单之间存在长时间空窗。影响：中断可能使已有结果无法被现有验证器发现。推荐方案已实现：每个接受的进度前缀都保存到私有原子 `committed.json`；兼容原有逐平台 JSON 与 manifest。历史读取以完整快照为准，当前进程结束后可恢复其兼容文件，风险状态优先。

问题：搜索的超时和评论参数没有完整传到实际请求。推荐方案已实现：传递平台超时和评论数量；不支持的组合明确拒绝。小红书搜索评论需要显式导航和 `screenshot-mode all`，普通搜索不会默默忽略评论参数。

问题：某页全部重复内容时，后面有新内容也可能提前停止。推荐方案已实现：API 列表只在游标有进展且仍有预算时跨过重复页；不无限重试。小红书续采在打开详情之前跳过验收合格的历史原生 ID。

## 数据与验收边界

- `run-context.json`：schema 1、运行 ID、原请求摘要、私有配置摘要、原始目标数、版本、父运行 ID及时间；不保存原始配置或凭据。
- `committed.json`：一个原子文件包含严格 manifest 和声明的数据。写入被中断时，上一份完整快照仍可读取。
- `run-result.json`：记录控制器的最终状态；控制器发现的风险也会阻止续采。
- `continuation.json`：本次私有排除计划，只包含平台和已验收的原生 ID，不改变导航权限。
- `xhs-safety.json`：运行时 state 目录中的持久批次时间与风险暂停，使用独立锁和私有权限。
- 旧版无 context 的结果可以历史导出，但不能续采。父链最多 32 层；任一祖先发生风险、请求/配置不匹配或证据无效，均拒绝续采。
- 小红书历史记录必须通过原有完整性、原运行时间边界和所需截图验证才能跳过；单独写 `complete: true` 不算验收通过。
- 续采生成新目录。新工作簿只包含本次新记录，汇总列单独标明历史已验收数、当前目标和父运行 ID。原记录和观测时间不改写。
- 普通新采集仍可以重新观测相同内容，用于比较两个时间点的指标；不会把历史缓存当作新观测。

## 使用入口

Harness 新增 `media_missher_runs`，支持 `list`、`export`、`compare`、`xhs-status`。该工具不能发起采集或解除风险暂停。`media_missher_collect` 增加可选 `resume_run`；必须由用户明确要求继续，其他参数使用原来的平台、总目标数和私有配置。

Git 中可直接使用标准库的离线入口：

```bash
python3 media-missher/scripts/manage_runs.py list --data-root /private/output/root
python3 media-missher/scripts/manage_runs.py export --data-root /private/output/root --run-id run-EXACT-ID --format csv
python3 media-missher/scripts/manage_runs.py compare --data-root /private/output/root --before run-EARLIER-ID --after run-LATER-ID
python3 runtime/scripts/xhs_safety.py
```

续采使用 `run_collection.py --resume-run run-EXACT-ID`，并重复原来的 profile、平台、总目标数和导航选项。只支持创作者模式、正数总目标；不自动排队，也不在冷却结束后自动启动。`count 0` 仍表示“在安全预算内尽量采集”，小红书每批仍不超过 10 条，但不提供无限目标续采。

风险暂停只能在用户自行检查正常浏览器中的账号状态后，由本地操作者明确运行 `python3 runtime/scripts/xhs_safety.py --acknowledge-risk` 解除。该动作仅确认已检查，不证明平台已解除限制，不会清除 600 秒批次间隔，也不会发起采集。发生过风险的旧运行仍不能续采。

自定义 runtime home 时，检查和确认命令必须使用相同的 `MEDIA_MISSHER_HOME`；不要删除安全状态文件来解除阻断。新 Git 控制器会在 live preflight 前核对 runtime 15.3.0，旧安装必须先安装匹配候选，避免保护只存在于源码而未进入实际核心。

## 交付与测试

候选安装包为 `harness-plugin/dist/Media-Missher-Harness-Setup-bundle-v0.2.0.zip`，内层 Bundle 为 `dsh-media-missher-0.2.0.tgz`。安装前核对同目录的 SHA-256 清单。历史 GitHub bootstrap 仍指向已发布 v15.2.1，不用于安装本地候选。

最终离线测试：Python **1059 passed**（一个有意验证网络阻断的警告），Bundle **65 passed**，TypeScript 通过。包中 **35 个 payload 源文件逐字节一致**，Bundle 和 Setup 精确白名单及校验通过。

真实 Harness 0.5.5 CLI 在临时 DSH_HOME 完成安装、激活、同版本重装及备份、卸载和邻接状态保留；已安装模块实际调用 list/export/compare/xhs-status 均通过。采集投影使用四平台各 10 条合成数据，六页工作簿重读通过；实际平台请求 **0**。这不等于小红书真实登录或账号风控验收。

规格审查和独立质量审查均通过；新增回归覆盖控制器输出风险、混合平台实际计时、坏历史类型、BV 截图恢复等集成边界。完整文件哈希和验收范围见 `harness-plugin/dist/RELIABILITY-EVIDENCE.json`；项目交接见 PROJECT_CONTEXT.md / HANDOVER.md。
