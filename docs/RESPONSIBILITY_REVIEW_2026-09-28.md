# Media@Missher 职责与状态复核

日期：2026-09-28。本轮只审查当前项目职责、交付与安装边界，复用历史证据并做相关局部回归；没有实现协调台账中的 REQ-01 至 REQ-04，没有业务代码修改或 Git 写入。

## 职责与保留边界

Media 的职责是五平台媒体采集、验证、私有证据/历史、选择导出和宿主薄适配。唯一活动执行后端是 Chrome CDP；Computer Use 与 BrowserSkill 仅保留历史来源和明确拒绝路径。

- DSH 入口只注册 `media_missher_collect`、`media_missher_runs`、`media_missher_setup` 和有界的 `media-missher:agent-guidance`；证据为 `harness-plugin/src/index.ts:382` 至 `apply()` 结束处。
- 现有 CSV/XLSX 博主清单导入属于采集目标准备，不承担聊天输入框的通用附件、图片张数/大小限制或 MIME 路由。
- 截图属于采集证据；本插件不注册宿主图片渲染器、全局样式或输入菜单。显式打开隔离采集浏览器及手动登录引导保留，不能因职责分类删掉既有授权功能。
- 模型、推理档位、通用输入、输出渲染、上下文压缩、跨会话统计和消息投递不是本项目职责。
- 静态扫描 `harness-plugin/src` 与 `agent-plugin/src` 未找到 `inputTriggers.registerSource`、`ui-reference`、`ui-input-trigger`、`ui-settings-models`、`ModelRow`、`reasoningEfforts` 接口。此结论限于被检查的源码，不代表所有宿主运行行为已经验收。

## 本轮复核的状态

| 层 | 当前核验结果 |
| --- | --- |
| 唯一源码 | 项目 `开发版/Media@Missher`；分支 `codex/media-v17-cdp-package`，HEAD `ad6e149bae05fa8f86d9718af18c1044f62a03b0`；审查开始工作树干净 |
| 分支与 V17 测试提交 | 相比 `1972602f0b255014b5779a4d0c096008f8930fac`，仅新增 `DEEPSEEK_V4_PROMPT.md` 和 `REVIEW_HANDOFF.md` 两份历史交接文档，业务代码未变 |
| 私有 Git main | GitHub API 本轮确认仓库仍私有；main 为 `0d05c1b4557ca2b1f0b4d3edce3c832ed5268d79`，tree 为 `15b6eaafbe688d3bd46b21d6a9f59d43d9832068`，与上述测试提交的 tree 一致 |
| V17 交付 | 根 `dist/v17.0.0/`，runtime、Agent CLI、DSH Bundle 均为 17.0.0；本轮只验包，不重建 |
| 旧候选 | `harness-plugin/dist` 仍有 Bundle 0.6.0 / runtime 15.6.0；`agent-plugin/dist` 仍有 CLI 0.1.0 / runtime 15.6.0，不能与根 V17 交付混用 |
| 已安装共享运行时 | `~/.local/share/media-missher/current/VERSION` 为 15.6.0；其 `contracts.py:34` 仍声明 CDP 和 Computer Use，本轮未执行这些后端 |
| 已安装 Codex Skill | `~/.codex/skills/media-missher/SKILL.md:6` 为 V15.6.0 |
| 已安装 Hermes Skill | `~/.hermes/skills/openclaw-custom/media-missher/SKILL.md:4` 为 15.2.0；其中“共享运行时 15.2.0”的说明已与本轮文件核验不一致 |
| DSH / 通用 CLI | 检查的 `~/.dsh/profiles/desktop`、`web` 没有直接声明 Media 依赖，其直接 node_modules 下也未发现 Media 包；当前 PATH 未找到 `media-missher`。没有进行有效 Loader 或正在运行的 Agent 会话发现，不能据此概括所有其他 profile/自定义路径 |

V17 完整包 SHA-256：`435a722998c7e0edf21d31b1432e7d09d3ff5119a2b7f0ce79607519c8532c0c`。源码包逐文件清单为 282 项，摘要为 `6081df86f62076ff90425e5b0dc61f0f36256f558740602a0d43548cb7580876`。

## 发现与最小建议

1. **交付与安装层不一致。**原因：V17 交付明确没有替换生产安装。影响：不能把 Git main 的 V17/CDP-only 说明当作本机已激活能力。推荐：维持现状；将来获得安装授权后，按宿主逐项核验安装归属、版本、发现和调用，不能由 `@插件` 选择动作触发升级。
2. **Hermes 安装说明存在陈旧版本断言。**原因：旧 Skill 标记 15.2.0，而共享 current 已为 15.6.0。影响：Agent 可能按旧版本说明选入口或判定能力。推荐：后续在明确授权的 Hermes 安装维护中统一说明与匹配的运行时；本轮不修改已安装 Skill。
3. **旧 Git 授权容易被误用。**原因：项目 AGENTS.md 保留上一轮打包/推送叙述。影响：可能越过本轮“只分类、审查和局部回归”的边界。已在项目 AGENTS.md 添加当前阶段，并将旧授权标为历史。

未发现需要迁移或删除的跨项目业务实现。新需求保持由协调台账的输入、模型设置、context-manager 等负责人处理；没有复制其他插件实现或修改宿主源码。

## 未来 `@插件` 的最小信息边界（仅分类，未实现）

建议复用已有身份：Bundle 挂载 ID `media-missher`、包名 `dsh-media-missher`、显示名 `Media@Missher`；可调用工具 ID 以宿主当前实际注册的三个 `media_missher_*` 名称为准。通用 CLI 包名是 `@missher/media-missher`，不能仅按显示名或版本号推断 DSH 工具已可用。

简要说明可使用“通过 Chrome CDP 采集授权媒体内容、验证并私有保存，再按选择离线导出”。发现层只携带身份、简短说明及宿主已核实的可用状态，不包含 profile 内容/路径、博主清单、运行 ID、记录正文、图片或截图、CDP 地址、登录状态或凭据。不能调用 setup status、doctor、runs list 来填充通用菜单。

`agent-plugin/src/capabilities.mjs` 的现有声明不读取私有 profile：`configuration.inspected=false`，CDP 为 `unverified`、`ready=false`。这是静态能力声明，不是实际浏览器/平台准备就绪证明。是否展示为可执行能力应由宿主当前启用/注册状态决定，选择引用不立即运行采集、安装、导航或导出，也不整包注入所有说明。

## 验证分层

本轮在临时隔离副本执行，未复制或重建源目录 lib：

- 复用现有 CLI 测试中的 5 项：无运行时的帮助/版本/发现、严格参数拒绝、目标/后端/导出参数边界、离线导出路由、五平台/CDP/导出帮助，全部通过。导出路由使用已有 fakeCore，未读取真实记录。
- 现有 `tools/verify_distribution.mjs` 对隔离复制的 V17 归档执行成功，外层摘要、源码逐文件摘要、嵌套包、文档入口和禁止文件检查通过。
- 额外执行静态 capabilities 探针：只返回 CDP、未读取私有配置、没有声称 ready，隔离 HOME 内容未变。
- 未重新运行全量 1,635 项测试。该数字来自 2026-09-27 `VALIDATION.json`，属于历史证据；main 的同日 CI run `36300746072` 本轮只读查询仍为 success。

本轮未验收：生产 Loader/当前 Agent 会话激活、原生 UI、任何新 `@插件` 行为、真实模型、真实平台、登录、Windows/WSL 图形浏览器。没有修改生产 profile、已安装运行时/Skill、用户数据或模型设置，也没有重启应用。

文档改动仅为本报告与项目 AGENTS.md；协调独占回执另写入 `coordination/2026-09-28/media-missher.md`。这些审查文档是本地新增改动，未纳入旧 V17 归档，也未提交或推送。
