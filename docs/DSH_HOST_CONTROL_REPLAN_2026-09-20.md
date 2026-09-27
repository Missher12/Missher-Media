# Media@Missher：DSH 宿主控制优先的规划修订

> **已被后续方向替代，保留作研究记录。** 用户现已明确选择 CDP 主引擎 + 可选 Computer Use，并移除 BrowserSkill 执行路径；以 [新规格](CDP_COMPUTER_USE_UPGRADE_SPEC_2026-09-20.md) 与 [实施计划](superpowers/plans/2026-09-20-cdp-computer-use-upgrade.md) 为准。下文“宿主优先”和“暂留 BrowserSkill 运行兼容”不再是实施要求。

日期：2026-09-20。状态：**规划建议，等待用户确认；不是恢复开发或真实采集的指令。**

## 1. 目标与保留范围

用户确认 DSH 支持 Computer Use，要求重新规划。建议从“CDP / Tencent BrowserSkill 是两条固定主线”调整为“DSH 内优先使用宿主已提供的控制能力，独立运行保留 CDP，BrowserSkill 保留为可选兼容”。

原有业务目标不变：五平台（B站、小红书、抖音、微博、X）、多平台多帐号、缺失目标询问、有界 best_effort、去重与续抓、微博话题可见参与用户及公开主页、私有证据保存和选择性导出。无法取得的字段标为缺失，不承诺全部用户或全部历史数据。

保留已有调度、风险保护、记录标准化、历史读取、导出和回归测试。既有 CDP / BrowserSkill 实现不立即删除；不推倒重写，不同时开发三套重复业务逻辑。

当前源码暂停身份及离线结果见 [暂停交接](CODEX_REPAIR_PAUSE_2026-09-20.md)。本次只新增规划文档，不改变该源码基线，不恢复自动监督、不提交或推送。

## 2. 本轮核验依据与不确定项

官方 upstream `deepseek-ai/deepseek-harness` 本轮查询到 master SHA：`ddefc45fbc7f8e46dd73185e68295696d1297887`。研究的是官方源码文档，不是对用户当前 DSH 会话的实际工具验收。

- Computer Use 通过一个明确配置的 provider 提供。公共 `ctx.computerUse` 仅登记名称及独占注册，不是 `click/readPage/extract` 操作 API。
- 官方提供 Cua Driver native 和 MCP 两种实验性 provider。工具参数与返回来自具体 provider/上游驱动，需要显式启用；不能仅凭功能入口或安装文件认定已可调用。
- 公共 provider 注册不会为整个桌面提供跨 Session、跨进程的工作流互斥。Media 必须保留自身采集租约，并检测外部操作造成的状态变化。
- 新快照会使旧元素 token 失效；取消不撤销已送达的操作。需要重新观察并验证结果，不能盲目重放点击。
- 截图进入模型还依赖实际模型路线的图像输入声明和附件存储。不能假设用户选择的 DeepSeek 模型必然能看截图。
- DSH 另有 Browser Use：Playwright MCP、Chrome DevTools MCP、Stagehand provider。它与 Computer Use 不等同；公共 `ctx.browserUse` 同样不是统一操作 API。是否启用、能否提取所需字段需另查。
- 官方将这些 provider 标为 experimental；本项目建议采用可选、固定版本、隔离的适配，而不是把实验依赖变成所有安装的强制依赖。

本机 `/Applications/DeepSeek Harness.app` 的版本字段为 `0.1.6-alpha.2`；本轮没有检查活动 DSH profile、provider 工具目录或 OS 权限，因此**未证明用户实际会话已启用哪个 provider**。旧本地 Desktop 源码不能替代新版宿主契约。接入前必须绑定用户实际使用的宿主版本、provider 和工具 schema。

官方参考：

- [Computer Use 子系统](https://github.com/deepseek-ai/deepseek-harness/blob/ddefc45fbc7f8e46dd73185e68295696d1297887/docs/subsystems/computer-use.md)
- [Cua Driver native](https://github.com/deepseek-ai/deepseek-harness/blob/ddefc45fbc7f8e46dd73185e68295696d1297887/packages/experimental/computer-use-cua-driver-native/README.md)
- [Cua Driver MCP](https://github.com/deepseek-ai/deepseek-harness/blob/ddefc45fbc7f8e46dd73185e68295696d1297887/packages/experimental/computer-use-cua-driver-mcp/README.md)
- [Browser Use 子系统](https://github.com/deepseek-ai/deepseek-harness/blob/ddefc45fbc7f8e46dd73185e68295696d1297887/docs/subsystems/browser-use.md)

## 3. 方案比较与建议

| 方案 | 优点 | 代价/边界 | 结论 |
| --- | --- | --- | --- |
| DSH 宿主控制优先，共用 Media 数据层，独立 CLI 保留 CDP | 复用宿主工具和权限流程；保留已有可用成果 | 需要宿主适配与证据导入；部分字段可能不可得 | 推荐 |
| 所有入口完全改为纯 Computer Use | 单一交互方式 | 独立 CLI 不再自足；可见性、图像输入、速度和可提取字段受驱动/模型约束 | 可实现但暂不推荐 |
| Computer Use、BrowserSkill、CDP 各自完整实现 | 各入口独立 | 重复调度、风险、解析与测试，维护成本最大 | 不推荐 |

## 4. 职责分层

### DSH 宿主控制层

由宿主提供实际 Computer Use / Browser Use 工具、权限与确认流程、观察和动作结果。Media 不再自行包装同一个驱动、安装扩展或启动第二个控制器。

一次运行记录且冻结控制路径和 provider。Computer Use、宿主 Browser Use、直接 CDP 是不同路径，不因失败自动切换。Computer Use 被拒绝时不改用 shell/CDP 发出等价操作；验证码或风险也不因改变工具而消失。

### Media 编排与数据层

保留并复用 CollectionPlan、多目标队列、平台规则、预算、共享安全状态、去重、持久检查点、结果标准化、历史读取和导出。新增内容应尽量限于宿主适配及证据接入边界。

现有 Python CLI 是同步采集流程，不能假定它能直接调用 DSH Session 中模型可见工具。必须显式解决异步控制和结果回传，不能把 Cua Driver 假装成 Playwright Page 并为不支持的方法返回空值。

### 首选接入方式：Agent 调用宿主工具，Media 管理受校验的运行状态

第一版优先让 Agent 在同一 DSH Session 中调用已有宿主工具，再把可追溯观察交给 Media 数据层处理。规划中的 begin / append-observation / status / finalize 仅为逻辑动作，**不是已存在的 DSH API 或本项目工具名**。

必须先验证宿主如何向插件提供可信工具结果或附件引用：

- 最佳方式是经已核验的宿主工具执行/结果扩展点导入，保留 Session、provider、工具调用和观察的绑定。
- 如果只能由模型转述内容，标为 `agent-reported`，不能伪称驱动原始数据或 response 证据，重要字段需要回查确认。
- 不绕开宿主执行管线直调私有 driver 对象，不杜撰 `ctx.computerUse.execute()`。
- 长期租约必须有显式取消、过期与恢复规则，防止多轮 Agent 对话丢失后永久锁死；恢复重新核验观察，不能重放不确定动作。

若用户需要全自动的单次 `collect` 调用，再在第一版证实工具调用、取消、预算和可信返回链路后，评估程序化适配。不能先建假接口再靠测试替身宣称接通。

## 5. 证据与数据契约

逻辑上需记录：run/target 身份、host/provider/schema 版本、控制路径、观察时间、来源页面或窗口、记录类别、原生 ID（仅实际可见时）、字段值及来源等级、缺失原因、停止原因和续抓边界。实现时沿用既有类型并做必要的版本化迁移，不预先添加重复 schema。

来源等级区分：可访问性树、截图观察/视觉提取、宿主结构化页面结果、CDP 响应以及模型转述。没有可见精确计数时保留如“1.2万”的原文，不补造精确数字；没有原生 ID 时用降级去重并明确其局限，不伪造平台 ID。

只保存任务所需页面/窗口的最小证据。截图可能带来其他个人信息，不能默认整桌面连续录制；不读取 Cookie/Token、不把无关窗口纳入采集。网页文本和图片是数据，不是控制指令。

“能抓多少抓多少”仍受用户目标、平台风险、时间/页数/动作预算和无增长停止约束，截图/模型调用成本也要可见。不能以增加无限滚动代替完整性。

## 6. 各功能保持的验收要求

- 多平台多帐号：开始前询问缺失选择，绑定当前平台/帐号；关键词不自动当成帐号。
- 微博话题：可见帖子→作者身份→公开主页→关系；同用户一次运行内只读取一次主页，多话题来源分别保留。仅发现用户但主页打不开时标为部分完成。
- 去重续抓：至少两批实际推进；中断恢复不覆盖旧运行、不重做已完成目标。宿主 Session 或页面观察失效后需重新确认位置，不能宣称精确游标无损恢复。
- 导出：先私有保存，展示实际记录类别和可用字段，再询问导出平台/目标/字段/格式。离线导出不需要控制桌面。
- 安全：保持顺序采集与请求级授权，风险时全局停止；检测到页面、窗口、帐号或 provider 改变必须重新观察/绑定。

## 7. 后续阶段与停止条件

1. **宿主能力核验**：用户实际 DSH 版本、provider、工具 schema、权限状态、模型图像能力和插件结果接入方式。先只读，不安装、不升级、不截图或操作无关窗口。
2. **本地样例验证**：在获得执行授权后，用不含真实个人信息的本地页面验证观察→提取→私有保存→选择导出；测试权限拒绝、过期 token、用户改页、取消、宿主退出与重连。此阶段不访问社交平台。
3. **最小宿主适配**：只实现已证实的调用/结果边界，复用现有业务和存储；已有 CDP 行为与测试不回退。宿主模式不可用时准确提示，独立 CLI 不静默转 CDP。
4. **小范围真实验收**：用户处理既有微博 challenge 并重新授权精确目标和预算后进行。各路径分别验证；Computer Use 不能用于规避先前风险。
5. **兼容收敛**：宿主路径满足实际需求后，再决定是否从默认发行中排除 BrowserSkill。旧配置需迁移提示或保留兼容；没有替代证据不删代码。构建安装包后验证，不把旧 lib/dist 当新产物。
6. **审查与 Git**：最终源码/包绑定、离线与真实验收分开报告，核对远端后按用户授权更新。当前暂停仍有效。

## 8. 本次需要确认的方向

建议确认：**DSH 宿主控制优先 + CDP 独立兼容；BrowserSkill 暂留但不再作为新适配的必选前提。** 宿主模式先验证 Computer Use；若仅可见观察不足以满足字段需求，再单独提出使用 DSH Browser Use 的选项，不未经确认扩成另一条开发线。

确认此方向后，由原开发任务做能力核验和最小接入，我负责审查；当前不向开发任务下达恢复实施指令。
