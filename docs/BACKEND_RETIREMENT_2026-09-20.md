# BrowserSkill 活动链退休清单

按 CDP/Computer Use 规格移除。恢复依据：本轮基线私有快照 `media-cdp-cu-baseline-os8pxo_i/source.tar.gz`；没有卸载用户 bsk、扩展、驱动或其他项目。

- 删除 `browser_skill.py`、`bsk_session.py`、`bsk_page.py`：旧桥接/子进程协议/页面模拟器不属于新后端。
- 删除 `test_runtime_browser_skill.py`、`test_runtime_bsk_page.py`：只测试已退出的驱动和协议；旧历史来源/退休输入由 `test_backend_upgrade.py`、`test_backend_retirement.py`覆盖。
- 保留 CDP `DetailOpenCoordinator`、截图、原四平台及 `page_collection.py` 的可见字段解析；删除辅助 bridge 点击分支，guard 拒绝和结果不明不重放迁移为 CDP 与 HostScope/Computer Use 测试。
- Bilibili 原身份绑定、精确 detail、零值/缺失、popup 归属及风险断言改走 CDP complete 路径，不删除业务安全断言。
- Bilibili 已知零值用例现在显式请求 CDP complete，因此其 complete 预期由 false 改为 true；零值/缺失、身份和详情证据断言仍保留。此变化来自请求语义，非放宽验收。
- 活动 Skill、CLI help、Harness 工具 description 与注入提示已改为 CDP / 可选 Computer Use，保留退休诊断和历史来源。文档测试相应验证缺宿主拒绝、CDP 独立及禁止旧 bsk 启动命令。
- 旧 manifest/导出仍保留 browserskill 标签和历史诊断词汇；这些文字命中不是可执行后端。
- 新归档清单移除 BSK 模块，新增共享 Computer Use 核心/批次日志；最终包需重新构建和验证，旧 lib/dist 不作为新源码证据。
