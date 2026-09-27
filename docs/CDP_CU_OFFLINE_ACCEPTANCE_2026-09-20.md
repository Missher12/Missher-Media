# CDP / Computer Use 离线候选证据 — 2026-09-20

本轮继续开发已完成一次源码收敛、离线回归、重建和 Agent 隔离安装。**不是完整 CU 功能交付，不是实际平台验收，也未正式安装或发布。** 开发目录仅 `/Users/missher/Desktop/Media@Missher`，原有 dirty 内容保留；HEAD 仍为 `f87dd8858a0b888f03a7885a1641823af13457bd`，版本仍为 runtime 15.6.0 / Agent 0.1.0 / Bundle 0.6.0，没有提交、推送或 tag。

监督最终阶段审查已接受 `2b5ded…` 为明确受限的离线候选；独立核对源码/包指纹，并复跑相关 97 项检查通过。此接受不是完整项目/CU 或 Git 放行。随后只读补查未改变生产源码，剩余接入范围及最小信息请求见 [DSH CU 接入缺口](DSH_CU_READONLY_GAP_2026-09-20.md)。当前停在等待 DSH 非敏感只读信息的阶段。

## 已实现的变化

主要文件归属：

| 文件 | 变化 |
| --- | --- |
| `runtime/media_missher_runtime/{contracts,models,capabilities,backends}.py` | 后端/版本/计划选项冻结与能力边界 |
| `runtime/media_missher_runtime/{cli,plan_runner,batch_journal,shared_safety}.py` | 参数合并、顺序计划、前缀恢复、独立入口安全门与完整性判定 |
| `runtime/media_missher_runtime/computer_use.py`、`shared/*.ts` | 宿主无关证据和生命周期协议 |
| `runtime/media_missher_runtime/{platforms/x,exporting}.py` | X 精确绑定、排序、来源关系及导出选择 |
| `media-missher/scripts/{run_collection,media_missher_history}.py` | 公共 Skill 入口参数 presence、私有计划读取、离线历史/导出 |
| `harness-plugin/src/{index,plan,config,private-config,creator-list,agent-guidance,computer-use,host-evidence}.ts` | 共享计划、needs-input、宿主适配边界与模型可见说明 |
| `agent-plugin/{bin/media-missher,src/targets,src/computer-use}.mjs` | 独立 CLI、平台原生身份、capabilities 和缺宿主拒绝 |
| `tests/test_*upgrade.py`、`tests/test_plan_integration.py`、`tests/test_computer_use_contract.py`、`tests/test_batch_recovery.py` 及插件测试 | 生产入口链、恢复、风险、字段和安装回归；不依赖真实平台 |

- 活动 backend 精确为 CDP / Computer Use；CDP 独立默认，缺少可信宿主时 CU 明确拒绝，无隐式回退。计划 schema 2、manifest schema 3；记录/导出版本独立。BSK 专属执行模块移除，旧数据仍可读/导出，旧后端新请求明确退休。
- 宿主无关证据协议：作用域、窗口、provider/schema、真实派发 callId、观察时间和版本化摘要绑定。固定 Node→JSON→Python 样本覆盖数值/Unicode 边界。新动作计费，最后一个已预留观察仍可结算；取消后迟到风险持久化且不覆盖新租约。
- 批次 journal 先写数据、后写原子提交标记；恢复校验完整摘要链。真实子进程分别在数据写完、提交标记写完及末批损坏后退出，验证忽略未提交尾部、恢复已提交前缀、拒绝损坏；原证据不改写。
- X handle 统一 15 位并归一化，排序从计划传到请求；响应变量按 JSON 精确解析，拒绝重复键、嵌套伪匹配、错误关键词或未证实排序。大整数 ID 维持字符串。
- 多目标共享帖子去重后保留各目标来源，单目标过滤仍可找到该帖子。混合平台/类别的字段组取相应并集；只导出关系一侧时明确 `partial-relation-projection`，不擅自补入未选字段。
- Python Skill、Agent CLI、DSH 工厂的参数边界有针对性回归。修复 Python wrapper 丢弃 backend/count_mode 及 CLI 把小红书 24hex / 抖音 secUid 当 X handle 的实际问题。缺少目标返回 `needs-input`，显式目标不要求导入无关名单。详细映射见 `ENTRY_PARAMETER_PARITY.md`。
- 活动 Skill、help 和工具描述同步新边界，旧 BSK 诊断仅作历史解释；CDP 详情 guard、结果不明不重放、信号清理、XHS 保护与风险前缀断言保留。

审查补充修复：XHS 公共计划入口补齐 BACKEND_CDP 导入；bilibili_complete、xhs_comments、screenshot_mode 纳入 schema 2 冻结计划及恢复身份。公共 wrapper→runtime main→PlanExecutor 验证评论、Bili complete 和搜索预算传递，不适用模式建档前拒绝。显式预算现在进入实际多批 PlanRunner，停滞保留 partial，不把批次结束当全部完成。CU finalize 拒绝未结算调用及期限后的 complete，期限结算后其他在途风险仍可有界持久化。

计划入口优先级已统一为显式 CLI > 本次私有计划 > profile > 默认值。未提供选项保留计划，显式 0/off/count 生效；CU 计划不可被默认 CDP 覆盖。计划读取保留私有文件/大小/链接/重复键检查，未支持的混用明确拒绝。详情见 `ENTRY_PARAMETER_PARITY.md`。

完整性判定复用 `_evidence_shortfall`：足量且所请求字段/截图不完整时，保留前缀并报告 partial 与具体 shortfall；已知零值与未要求 complete 不误判，风险优先。不完整前缀可导出，但不能在 resume 中仅凭数量跳成成功；summary 的 resumable 与入口拒绝保持一致。

## 验证与精确产物

日志目录：`.superpowers/sdd/2026-09-20-cdp-computer-use-upgrade/`。

| 验证 | 本轮结果与范围 |
| --- | --- |
| Python 全套 | `python-final-candidate.log`：1295 passed，1 个预期禁网断言警告；无真实平台请求 |
| Harness 全套 | `harness-final-candidate.log`：18 files / 293 passed；tsc --noEmit 通过 |
| Agent 全套 | `agent-final-candidate.log`：54 passed；先前失败日志保留为修复过程，不用于最终通过结论 |
| 关键生命周期 | `lifecycle-final-3.log`：24 项通过，包括实际子进程提交边界、未结算 finalize、期限及迟到风险/租约；亦纳入最终 Python 全套 |
| 构建 | `build-final-candidate.log` 通过；共享编译入口无运行时 DSH import。类型打包有第三方相对 module declaration 提示，未影响 tsc/build，但未据此声称原生宿主兼容 |
| 源码归档对应 | 两个最终包的 47 个 runtime/adapter payload 与冻结源码逐文件 SHA 匹配；无 BSK 专属模块 |
| Agent 隔离安装 | `isolated-install-final-candidate.log` passed，Intel macOS / Node 25.6.0，临时 HOME，真实 npm 依赖安装及实际 launcher；新包版本、capabilities、CU 五动作拒绝、空设备无 runtime/output、Skill 幂等/编辑保护、Excel 模板、合成 CSV 导入/激活通过 |
| 未执行 | 真实浏览器/平台请求 0；DSH 启动/正式安装 0；没有请求 OS 权限；Linux/Windows 原生和真实 Agent 会话激活未验证 |

生产源码清单（86 文件，不含测试、文档或生成产物）位于 `source-final-candidate.json`。算法：按相对路径排序，各项拼接 UTF-8 路径字节 + 单字节 NUL + 内容 SHA-256 的 32 个原始字节，不附尾换行，再对整个串取 SHA-256：

`2b5ded9536c0801170f6fb3e1e054484bce726ae4272e41f339bd8f90d7e75ac`

审查修复后重新运行 Python/Harness/Agent 全套、构建和隔离安装，绑定同一最终源码与下表产物。旧 `source-final.json` / `fe9e…` 冻结仍保留作审查依据，不代替新版证据。

| 本地候选 | 字节数 | SHA-256 |
| --- | ---: | --- |
| `agent-plugin/dist/missher-media-missher-0.1.0.tgz` | 276080 | `025def52489664dc79d6a67685ae4c8fc6a31349a220e7584e5b948f0133729e` |
| `agent-plugin/dist/Media-Missher-Agent-Setup-v0.1.0.zip` | 293624 | `7f3a0de0ccbc033c363d052c34fe2e0865aa62e5bf3e880cc87e278389c98c31` |
| `harness-plugin/dist/dsh-media-missher-0.6.0.tgz` | 342532 | `49e0ad1606d7821eb0cbdc2ac11e67745ffc84f7965e225e33b4a664c7da6deb` |

旧 `2c0d…`、`13dbc…`、`5399…`、`9337…` Agent 包安装记录属于已替换快照，不作为上述新版验收。旧生成物恢复备份：系统临时目录 `media-before-cu-build-ru7rzt5o/generated.tar.gz`；基线源码备份 `media-cdp-cu-baseline-os8pxo_i/source.tar.gz`。没有清理用户输出。

## 未完成与下一步

1. DSH 实际 provider/schema、Session、窗口、权限、证据 resolver 和动作 guard 映射仍未核验，因此默认 CU unavailable。能力报告见 `DSH_COMPUTER_USE_CAPABILITIES.md`。
2. 离线 CU 核心只准入单一 X accessibility 目标；多目标切换、微博话题主页阶段、纯 visual 解析未完成，已在建档前拒绝。拒绝只是保护边界，不等于这些承诺功能已实现。后续按已核验宿主能力接通并验收，不能以合成 bridge 代替原生通过。
3. CDP 微博话题帖子/参与者/主页及风险前缀沿用本轮回归；未做新的平台访问。用户给出的后续默认话题为“萤火虫漫展”，此前微博 challenge 风险停止仍有效，禁止重试或切 CU 绕过。
4. X 的适用平台许可、真实 DSH 本地样例、真实平台、正式宿主升级、Git 与发布均没有恢复授权。当前可审查和保留本地候选，不宣称完整项目交付。
