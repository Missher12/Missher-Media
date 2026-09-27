# 入口参数一致性（离线候选）

优先级：CLI 明确给出的值 > 本次私有计划 > 本次选定 profile > 产品默认。解析阶段以 None 表示“未提供”，不得把 fixed/0/off/cdp 默认值制造为计划覆盖。显式 0/off 会参与合并后计划及恢复身份比较。私有计划提前解析保持 0600、owner、单链接普通文件、无符号链接、2 MiB 上限和重复键拒绝。

| Python 计划入口选项 | 未提供 | 显式提供 |
| --- | --- | --- |
| backend | 保留 plan；plan 缺失才读 profile/default | 仅接受 cdp；显式覆盖保留原优先级，旧 CU/BSK 不自动迁移 |
| count / count-mode | 保留 plan | 覆盖 count/count_mode；显式全局 count 清除旧 per_target_counts，避免旧值压过本次选择 |
| xhs-comments / screenshot-mode | 保留 plan | 0/off 同样生效；不适用模式拒绝 |
| run-deadline | 保留 plan | 写入冻结总期限 |
| complete / bilibili-complete / xhs-complete | 保留 plan 的完整性选项；XHS creator 本来要求 complete | 只开启适用 creator 的完整性，不强制全部平台完整；CLI 未声明关闭旗标则不能猜关闭 |
| allow-navigation | 保留 plan 授权 | 仅明确开启；无隐式授权；CLI 未声明关闭旗标则须修改新计划 |
| resume-run | 不恢复 | 按合并后的 plan/backend/profile 匹配；字段不完整或风险祖先拒绝 |
| platform | 从 plan 推导 | 必须与 plan 一致，不静默筛掉目标 |
| UID / per-platform count / search 与 targets-json 混用 | 以 plan 目标为准 | 明确拒绝冲突；修改私有 plan 表达目标级选择 |
| format / collect-as-much-as-safe 与 targets-json 混用 | JSON staging，按 plan 预算 | 非默认格式或旧 count-zero 开关拒绝；使用单独离线导出及 plan 预算 |
| platform-timeout / execution-timeout / cdp-url / profile / data-root | 原有环境/配置解析 | 沿用显式值与安全边界；不伪装为采集目标或字段覆盖 |

Runtime 直接计划入口另支持 batch-pages / batch-interval / per-target-budget：仅显式值覆盖且只能收紧平台限制。未声明的参数由 argparse 拒绝。公共 wrapper 与实际 runtime 的合并结果均由 `test_private_plan_presence_priority_through_public_wrapper` 等生产入口测试覆盖。

| 输入 | Python Skill wrapper | Agent CLI | DSH collect 工厂 |
| --- | --- | --- | --- |
| backend | 仅 Chrome CDP；旧 CU/BSK 请求或偏好在创建输出前拒绝 | 仅 cdp，归一化后传共享工厂 | schema 仅 cdp；旧后端请求拒绝，不调用 runtime provider/CDP |
| count_mode / deadline | 非默认 envelope 转现有 plan 入口，传 --count-mode / --run-deadline | 转 count_mode / run_deadline_seconds | 写入 schema 2 plan |
| 显式 UID / handle / keyword | 私有 plan 不要求额外已保存帐号；普通 envelope 传所选 UID / keyword | targets 数组传共享工厂 | 显式 targets 优先，不合并无关帐号 |
| allow_navigation | 默认 false；仅显式传参 | 默认 false | 原样写入 plan，不因缺页开启 |
| 评论 / complete / 截图 | xhs_comments、bilibili_complete、screenshot_mode 写入冻结计划；传递对应 CLI 参数 | xhs_comments 传共享工厂；不暴露未声明的完整/截图选项 | xhs_comments 同步到 schema 2；未声明的 Bili complete / screenshot 保持 false / off |
| resume | 原 run ID + profile_digest 转发 | resume_run 转共享工厂 | 与原 plan/backend/profile 绑定，风险祖先拒绝 |

生产调用边界由 `tests/test_plan_integration.py`、`tests/test_cli.py`、`agent-plugin/tests/cli.test.mjs` 和 `harness-plugin/tests/plugin.spec.ts` 锁定。合成执行器验证参数与拒绝分支，不证明真实宿主/平台通过。固定 CDP 旧路径保留兼容；不得把 CU 请求丢弃后落入该路径。
