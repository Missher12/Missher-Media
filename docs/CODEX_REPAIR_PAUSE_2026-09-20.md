# Codex 当前修复暂停交接 — 2026-09-20

状态：**当前修复收尾后按用户要求暂停。不是整个项目验收完成。** 用户将先查看新版 DeepSeek Harness Computer Use，再决定后续方向。不得自动继续开发、采集、适配 Computer Use、升级浏览器或 BrowserSkill，也不得提交或推送。

## 工作区和证据身份

- 唯一修改目标是桌面 Media@Missher；Documents 原项目未修改。
- 分支 `codex/media-browser-agent-desktop-20260920`，HEAD `f87dd8858a0b888f03a7885a1641823af13457bd`，没有本轮提交。
- 保留接手时全部未提交成果。接手前快照保存在系统临时目录 `media-before-codex-8uluf8hv/source.tar.gz`。
- 冻结的源码/测试/配置摘要：`3771861e1291be3f7ee4627cd2ca7db5fca81152f954554fbea77161a637e2f1`，174 个文件。算法：`git ls-files --cached --others --exclude-standard` 中现存非链接的 py/ts/mjs/json/yaml/yml/lock 文件（不含 docs），逐文件 SHA-256，按路径排序的紧凑 JSON 再 SHA-256。文档更新不改变此摘要。
- 桌面 origin 仍指向本机 Documents 仓库；只读核对 Documents 配置显示其上游为 `github.com/Missher12/media-missher.git`，没有修改远程、推送或核验远端最新状态。

## 本轮修复

1. 新计划输出单一 JSON 摘要；统一 v2 `manifest.json`、`committed.json`、运行摘要及历史读取。旧五字段 manifest 保持兼容；v2 的 partial 和风险状态有独立校验。已保存前缀可按选择离线导出，采集不再自动生成 Excel。
2. 修复公共入口在计划任务前要求旧 platform_uids、拒绝 X 的阻断；显式搜索目标无需先保存无关帐号。主页输入按精确域名/路径解析身份并拒绝冲突。
3. 传递批次排除 ID、页数和记录预算；CDP 续批在匹配目标页上推进。显式续抓读取已提交的同计划/后端/配置快照，跳过已完成目标、保留原运行。源采集进度、超时/取消和进程组收尾复用既有机制。
4. 修复风险异常跨层分类、风险前缀丢失、未启动平台状态、超时/取消和部分完成状态。风险运行不可自动续抓；计划 XHS 批次使用共享持久安全门。
5. 修复微博标准话题域名；只为实际接受的帖子发现用户，限定主页访问范围，跨话题复用已访问主页并保留帖子—话题—用户关系。主页风险继续向上传播。
6. BrowserSkill 固定源码基线确认 0.3.0 的 wire protocol 为 1.3；新增四平台页面列表路径，X 通过真实能力标记选择页面读取，不误用 expect_response 占位方法。未知指标保持缺失；不把 network 元数据当响应正文。
7. Agent 归档严格清单补齐本轮 runtime 模块；未重新发布、安装或替换任何宿主。

主要文件组：`runtime/media_missher_runtime/`（cli/storage/contracts/plan_runner/best_effort/models/browser/bsk_session/bsk_page/progress/page_collection 与平台采集器）；`media-missher/scripts/run_collection.py`、`media_missher_history.py`；`harness-plugin/src/index.ts`、`runtime.ts`、`private-config.ts`；`agent-plugin/scripts/archive.mjs`。新增 `tests/test_plan_integration.py`、`tests/test_page_collection.py`，补充既有 Python 与 TS 回归。

## 冻结后离线验证

- Python 全套：**1304 passed**，111.49 秒；1 个既有 pytest-socket 预期禁网警告。
- Harness：**289 passed / 17 files**，29.35 秒。
- Agent CLI：**51 passed**，16.21 秒。
- `tsc --noEmit`：通过；`git diff --check`：通过。
- 命令：Python 使用 `uv run --offline --no-project --python 3.12 --with pytest --with pytest-asyncio --with pytest-socket --with-requirements runtime/requirements.lock python -m pytest -q -p no:cacheprovider --disable-socket --allow-unix-socket tests/`（设置 `PYTHONDONTWRITEBYTECODE=1`）；Harness 使用 `vitest run --maxWorkers=1 --no-file-parallelism`；Agent 使用 `node --test tests/*.test.mjs`。
- 这些是源码离线/合成验证。没有本轮安装包、正式宿主安装或完整原生功能验收；现有 lib/dist 不代表当前源码。

## 真实验收与停止边界

用户给出的关键词是“萤火虫漫展”。实际只执行微博普通话题：CDP、1 条、1 页、总期限 60 秒、单平台超时 45 秒；未猜帐号。北京时间 20:16:09–20:16:11，观察到 `challenge`，帖子/参与用户/主页/关系全部为 0。立即全局停止；没有重试或切换平台、后端、帐号或出口。

私有证据位于用户数据目录 `media-live-20260920-etc_fbqm`，唯一运行 `run-1789906563691335000-87580192`；同目录 `ACCEPTANCE.json` 保存脱敏命令预算、时间、状态、源码文件哈希。该次 runtime 摘要 `1651d0d24855917bf18934ed322c6d094ff1c07d1e86fb469adb7a6f22eb8b7c`，与最终修复快照不同。历史读取通过；内部空结果 JSON 选择导出正确保留 risk-stopped，但不属于业务采集/导出成功。证据不在仓库内，不得提交。

本机只读检查：bsk CLI/daemon 0.1.10、协议 1.0；扩展 0.3.0、协议 1.3，活动 session 数 0。版本不匹配是独立阻断；没有升级、安装、重启或发起 BrowserSkill 会话。

| 范围 | 证据 | 结论 |
| --- | --- | --- |
| 入口→私有保存→历史→选择导出 | 集成回归、包含 partial/risk/timeout/cancel | 离线通过 |
| 多目标续抓 | 实际运行器的两次合成调用、跳过已完成目标、原文件不变 | 合成通过 |
| 两批分页与排除 | 页面及 CDP 微博采集器回归、不同原生 ID | 合成通过，不证明全部平台现场分页 |
| 同用户参与两个话题 | 一次主页调用、两条来源关系 | 合成通过 |
| X/BrowserSkill 能力与失败关闭 | 固定源码核对、适配器回归 | 离线通过，真实 BrowserSkill 阻断 |
| 微博普通话题现场 | challenge、0 条 | 仅入口/风险关闭验证，不是采集通过 |
| 五平台帐号、多帐号、X 和用户主页现场 | 未执行或风险后停止 | 未验收 |

## 暂停后待决定事项

- 等用户看完 Harness Computer Use 再决定后续方向；本轮没有适配或替换它。
- 真实风险需用户处理平台提示并重新明确授权，不能从本交接自动恢复采集。
- BrowserSkill 环境版本协调与真实会话另行决定；不把 CDP 证据代替双后端通过。
- 后续审查仍需关注：强制断电后仅 checkpoint 的恢复、跨进程精确游标延续、全部平台大批次完整性及字段覆盖、实际构建归档/安装后的全链路。当前续抓以已提交快照和排除 ID 为基础，不承诺穷尽结果。
- Git 更新等待后续监督审查和用户恢复任务；此次明确不提交、不推送、不打 tag、不发布。
