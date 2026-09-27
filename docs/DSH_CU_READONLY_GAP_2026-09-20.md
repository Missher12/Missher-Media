# DSH CU 接入缺口：只读核验与最小回传请求

本次在离线候选 `2b5ded9536c0801170f6fb3e1e054484bce726ae4272e41f339bd8f90d7e75ac` 获阶段接受后，仅查看安装元数据及全局 CLI 帮助。生产源码未改动，没有启用/修改 profile、启动或重启 DSH、安装升级、请求 OS 权限、读取私有会话库/密钥、截图/点击或访问平台。

## 当前能确认什么

| 来源 | 确认值 | 不能推断 |
| --- | --- | --- |
| `/Applications/DeepSeek Harness.app/Contents/Info.plist` | Desktop `0.1.6-alpha.2`，bundle id `com.deepseek.harness` | 当前会话的 provider、授权或窗口 |
| 同应用 `app.asar` 内 package.json 元数据 | `@deepseek-ai/dsh`、`@deepseek-ai/dsh-tools`、`@deepseek-ai/dsh-desktop-host` 均为 `0.1.6-alpha.2` | 包存在不代表 provider 已激活，SDK 版本也不等于活动工具 schema |
| `/Users/missher/.local/bin/dsh` 解析后的包 | `@deepseek-ai/dsh 0.1.1-rc.2` | 此全局 CLI 不等于桌面捆绑版本或活动桌面实例 |
| 全局 `dsh --help` | launcher 的 profile/patch/dump、web、plugin 命令 | 没有已声明的活动 provider/Session/window 查询入口；未尝试 boot/profile help 或 config dump |
| 当前 Codex 工具目录 | 未暴露 DSH/Harness provider、Session、window/schema 发现接口 | Codex 自己的浏览器能力不能替代 DSH 能力 |

只枚举安装包内名字含 computer/cua/browser/desktop 的 manifest，未发现以 computer-use/cua 命名的捆绑包；这**不能证明用户活动 profile 没有另外安装 provider**。没有遍历用户私有会话或读取完整配置来猜测活动状态。

因此 active provider 名称/版本、实际工具 schema、可信 Session/window 映射、权限、图像路线仍为 `unverified`。当前集成继续 `host-computer-use-unavailable`；此结论不是“DSH 不支持 CU”。

## 可复制到 DSH 当前会话的最短检查请求

> 请只读报告当前会话**实际暴露**的 Computer Use 工具名称和输入 JSON schema，并标注来源是当前工具目录还是静态文档。仅回传非敏感字段：宿主/core 版本；provider 名称/版本与启用状态；工具 schema 或其摘要；Session/window 身份、规范工具结果、附件引用分别由哪个公开接口/字段提供（只报接口与字段名，不报真实会话 ID、窗口标题或截图）；现成可见的权限/图像路线状态；是否有公开的动作前 guard 与结果事件接口。没有可靠来源就填 `unverified`。不要调用 observe/click/scroll 等工具，不启动/安装/改配置/申请权限，不读取私有会话库、密钥或完整配置，不输出真实页面内容。请勿从已安装包推断活动能力。

回传形状可为：`host_version, core_version, provider_name, provider_version, active_state, tools[{name,input_schema,source}], scope_api, window_api, result_api, attachment_api, guard_api, permission_state, image_route`。删除 schema 中的私人默认路径/样例值；保留参数名称、类型、required 和 enum。不要凭模型转述生成 `host-verified` 证据；该摘要只用于确认接入设计，真实闭环仍需后续受控验证。

## 剩余实现范围（不是只差实测）

| 范围 | 当前状态 | 可独立的核心工作 | 需要真实宿主格式后完成 |
| --- | --- | --- | --- |
| CU 多目标 | 未实现，prepare 明确拒绝 | 可复用计划/日志/去重，实现目标队列、每目标计数、全局 100 动作/600 秒预算和恢复状态 | 目标转换时的可信窗口/目标绑定、旧 ref 失效、动作与新观察串联 |
| CU 微博话题及公开主页 | 可见帖子/参与者/关系只有离线 normalizer，完整主页阶段未接通 | 可复用按 UID 去重、跨话题来源关系、主页访问登记与失败/风险前缀处理 | 将实际 accessibility/观察格式映射为已绑定用户主页字段；必须证明 UID，不能按昵称补齐 |
| CU 纯 visual | 未实现，结构化入口拒绝原始像素/模型自报字段 | 可复用字段质量、unknown/rounded、记录/导出契约与证据引用边界 | 明确图像附件路线、观察帧/窗口/时间/摘要绑定和视觉解析结果的可信来源；不把截图推断升级为隐藏精确指标 |
| DSH 活动适配 | 未验证，默认 unavailable | 宿主无关协议、单 X accessibility 合成生命周期及安全门已有离线证据 | 当前 provider 的真实 schema、作用域、窗口、结果 resolver、权限和可执行 guard 映射及闭环 |

上述核心独立工作没有被删除或改写为“仅需实测”。本阶段按监督要求保持生产源码稳定，等待 DSH 非敏感只读信息后确定接入边界与下一阶段范围。此前微博 challenge 仍未解除，“萤火虫漫展”仅为后续默认验收话题，不授权重试。
