# Codex Desktop 项目入口

- 唯一开发与审改目录为 `/Users/missher/Desktop/Media@Missher`。2026-09-23 用户授权当前任务落实 GPT-6 Astra 接入修复，并明确确认将本机 Codex Skill 与共享运行时正式升级到 15.6.0；该同步升级已完成。原开发任务已结束，本轮保持单一写入者并保护既有修改。Harness/OpenClaw 正式安装、真实平台采集和 Git 操作仍按原约定暂停；本地构建与隔离验证可以继续。
- Astra 接入的当前证据见 `docs/ASTRA_MIGRATION_2026-09-23.md`。模型由宿主选择，沿用用户的模型与推理级别；分别核验源码、安装版本、Skill 发现和真实任务，不为改模型引入第二套采集核心。
- 最新规划先读 `docs/CDP_COMPUTER_USE_UPGRADE_SPEC_2026-09-20.md` 与 `docs/superpowers/plans/2026-09-20-cdp-computer-use-upgrade.md`。最终只保留 CDP 主引擎和可选 Computer Use，纳入 X、多帐号、best_effort、可靠续抓、选择导出和微博话题用户/主页采集；不得将规划当成已实现。
- `DEEPSEEK_V4_PROMPT.md`、`REVIEW_HANDOFF.md`、`docs/DSH_HOST_CONTROL_REPLAN_2026-09-20.md` 保留作历史，不再是恢复开发指令。BrowserSkill 退出活动运行链，旧数据只读与明确迁移诊断保留；不卸载用户全局工具。
- CDP 是默认长期后端，不作为多余代码删除；每次采集固定一个后端，无静默故障切换。Computer Use 不可用不能阻断 CDP；平台、帐号、字段证据和共享风险保护不得因切换后端而丢失。
- 通用 CLI + 共享 Skill 是跨 Agent 基础，DSH 只做薄适配；Computer Use 协议不写死 DSH 工具名、目录或 Session 来源。按宿主真实能力启用，不宣称所有 Agent 的 CU 已兼容，不为泛兼容新建远程网关或第三 backend。
- 本项目维护共享采集运行时、Codex skill 与 Harness Bundle；先核验当前任务指定工作树、完整 SHA、版本来源及已有修改。
- 按需读取目标工作树 PROJECT_CONTEXT.md 的当前摘要、架构和本次平台边界；历史采集、安装及发布记录仅按需定位，不能替代本轮证据。
- 从目标工作树 README、测试目录和 harness-plugin/package.json 发现对应检查，分别报告静态、合成、原生和真实平台结果。
- 保持单一浏览器所有者、顺序采集、精确目标绑定、私有输出及风险立即停止；BrowserSkill、导航和截图继续遵循现有请求级授权。
- Skill 安装、Host 配置和当前会话工具可见性分别核验；安装、真实采集与发布按当前任务已有授权和项目分发边界执行。
- 已有 dirty 内容必须保留；共享文件单一写入者。Git 更新前重新核对远程：桌面复制时 origin 指向 Documents 本机仓库。用户授权的是验证后更新 Git，不等于公开仓库、改 tag 或发布 Release。
