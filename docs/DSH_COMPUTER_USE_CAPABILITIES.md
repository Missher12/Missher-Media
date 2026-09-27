# Computer Use 宿主能力核验 — 2026-09-20

当前结论：**DSH 活动适配未核验，Computer Use 不可启用；不阻断 CLI/CDP/离线导出。** 本轮未读取私有会话数据库、认证配置或桌面图像，没有启动驱动或请求 OS 权限。

阶段审查后的只读补查见 [接入缺口与最小回传请求](DSH_CU_READONLY_GAP_2026-09-20.md)：桌面 asar 中 DSH/Tools 包均为 0.1.6-alpha.2，全局 CLI 为 0.1.1-rc.2。先前构建 SDK 声明不能替代该桌面活动工具 schema；当前会话仍无法核验实际 provider/Session/window/权限。检查未执行 profile boot/config dump 或桌面操作。

离线核心当前仅准入单一 X 目标的结构化 accessibility 观察；多目标、纯 visual 输入及微博话题主页阶段在创建 run 前明确拒绝。微博可见帖子/关系标准化仍是离线辅助代码，不等于完整 CU 话题流程。宿主适配不可用与核心尚未接通的模式是两个独立缺口；不能只恢复宿主就宣布所有模式可用。

证据协议使用显式 `media-canonical-v1` 摘要版本，固定样本位于 `tests/fixtures/protocol/computer-use-digest-v1.json`。Node 验证并序列化完整观察，经 subprocess stdout 传输后由 Python 解析/校验；覆盖指数、负零、最小次正规数、最大安全整数及中文/non-BMP。大整数数值和巨大整数浮点数拒绝，ID 应使用字符串；孤立代理码点拒绝。此协议未改变已有 journal/历史文件的摘要算法。

| 字段 | 本轮证据 |
| --- | --- |
| host_version | `/Applications/DeepSeek Harness.app` CFBundleShortVersionString = 0.1.6-alpha.2；发现该应用可执行进程。此值不等于活动 core/provider 版本，后者 unverified |
| provider_name / provider_version | unverified；当前 Codex 工具目录未暴露 DSH provider 发现接口 |
| tool_schema_digest | unverified；不能把已安装 SDK 当活动 provider schema |
| os | macOS（本机） |
| permission_state | unverified；没有调用真实权限诊断或请求权限 |
| image_route | unverified；不替用户更换模型或配置附件服务 |
| evidence_resolution | SDK 具有 tools/result 最终规范结果观察点；活动 Session 与 provider 结果映射未验证 |
| action_guard | SDK 具有 tools.guard 单调拒绝及 tools/pre-execute；实际 provider 参数/窗口身份映射未验证 |
| status | host-computer-use-unavailable |

源码依据：官方固定 SHA `ddefc45fbc7f8e46dd73185e68295696d1297887` 的 `docs/subsystems/computer-use.md`、`packages/experimental/computer-use-cua-driver-native/src/index.ts` 与 README。ctx.computerUse 仅注册 provider；不含通用 execute/click。provider 使用正常工具执行管线，tools/result 的 value 是执行期规范值，不能从旧持久日志反推它。已安装构建 SDK `@deepseek-ai/dsh-tools 0.1.1-rc.2` 的公开 types/index.d.ts 确认 `tools.guard`、`tools/result`、`ToolExecution.agent` 和 `ToolExecutionResult.value`；当前运行宿主是否采用这些版本仍未知。

三类环境的规则（后续合成测试，不是原生实测）：无 provider → unavailable；provider 存在但权限 denied/unknown → denied/unverified；仅 provider、权限、schema、可信证据接入及动作 guard 全部通过时才可进入 ready。第二宿主的合成 bridge 只证明协议不写死 DSH。

后续启用 DSH 需经其公开管线核验：确切 provider/schema 指纹、可信 HostScope（hostKind/hostInstanceId/sessionId）、目标窗口与动作参数、规范结果或附件解析、权限与模型图像路线。缺任何项则拒绝 prepare；不读取私有状态补洞，不直调 native driver，不从本 Codex 的浏览器能力推断 DSH 能力。
