# Media@Missher CDP + Computer Use + X Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. 用户已指定原开发任务为唯一源码实现者，监督任务审查；不要使用 subagent-driven-development 或创建额外代理。步骤复选框用于记录实际证据，不因文件存在就勾选。用户最新“Agent、DSH 各种都能使用，你看着改”已授权恢复实现；真实平台操作、正式安装升级及 Git 仍暂停。

**Goal:** 将 Media 收敛为 CDP 主引擎及可选 Computer Use 两路径，完成 X、多目标、微博话题、可靠续抓和选择导出，并移除 BrowserSkill 执行链。

**Architecture:** 复用共享业务与数据层，CLI + 共享 Skill 为通用入口，DSH 只是薄包装。CDP 独立可用；Computer Use 采用宿主无关协议，各适配映射已核验的宿主结果/授权管线，不复制采集系统、不伪装 Playwright Page。每个 run 固定 backend，旧 BSK 仅保留历史读取及拒绝迁移信息。

**Tech Stack:** Python 3.11/3.12、既有 Playwright/CDP、TypeScript/Node、Cordis/Harness Bundle、通用 Agent CLI、pytest/vitest/node:test。DSH provider 由宿主提供，不作为核心强依赖。

**Spec:** [CDP_COMPUTER_USE_UPGRADE_SPEC_2026-09-20.md](../../CDP_COMPUTER_USE_UPGRADE_SPEC_2026-09-20.md)。执行者必须一起阅读。

## Global Constraints

- 唯一写入目录 `/Users/missher/Desktop/Media@Missher`；不修改 Documents、正式安装或用户真实配置。
- 最终活动 backend 精确为 `cdp|computer_use`，默认 `cdp`；不提供 `auto`、第三后端、静默切换。
- 用户已授权既有开发任务恢复源码实现、离线测试、本地构建和隔离验证；未恢复真实平台采集、正式安装升级、提交推送或发布。监督自动化仅督促这些已授权事项。
- 通用 CLI/Skill 与 DSH 共用核心和协议；Computer Use 不写死 DSH，每个宿主单独报告能力。不支持本机执行的云端 Agent 不冒称兼容。
- 用户停止限制优先于技能中的频繁提交建议；每任务只交审查记录，最终 Git 更新按独立授权和验收执行。
- 保留已有 dirty 成果；不使用 git reset/checkout 清理，不把 HEAD 当未提交源码版本。
- 平台、帐号、调用来源和租约精确绑定；私有输出；风险状态跨后端、跨进程保留，禁止自动重试挑战。
- 小红书既有 10 条 / 3 页 / 600 秒保护不变；其他平台现有更严格预算继续生效。
- Computer Use 初始默认总时限 600 秒、总动作上限 100 次，连续 2 批无新增停止；权限拒绝、取消或风险立即停止。
- 新计划 schema 2；新 manifest schema 3；计划/manifest/导出/观察独立版本，不机械全局升版。
- 旧 BSK 历史只读可导出；新请求/保存偏好选择它时报 `backend-retired-browserskill`；不卸载用户 BSK 软件。
- 最终证据区分离线、真实宿主本地样例、真实平台、归档安装；旧产物和旧源码测试不得替代新版本验收。

## Review Focus

1. **可选宿主缺失/版本变化**：不阻断 CDP 和离线历史，不误称 Computer Use 已可用。归属任务 1–3、9。
2. **旧 BSK 配置/历史混用**：新执行拒绝而旧证据能读，不偷换后端或修改旧 run。归属任务 2、8。
3. **大整数 ID、重名、推荐/引用卡片**：身份和关系不串，搜索结果不能冒充目标帐号。归属任务 5–7。
4. **进程在提交边界死亡、取消后动作已送达**：只恢复已校验批次，不丢已提交数据、不重复点击、不清风险。归属任务 3–4。
5. **输出/证据污染**：公式注入、路径逃逸、假工具结果、旧截图/旧窗口和多模型转述均不能变成可信采集。归属任务 3、7、9。

## 文件职责与执行顺序

| 范围 | 修改/新增重点 |
| --- | --- |
| 执行契约与能力 | `runtime/media_missher_runtime/{contracts,models,backends,capabilities}.py`，`harness-plugin/src/{config,plan}.ts` |
| 宿主能力接入（新增） | 无宿主依赖 `shared/{computer-use-contract,host-evidence}.ts`；DSH 薄适配 `harness-plugin/src/{computer-use,host-evidence}.ts`；通用 CLI `agent-plugin/src/computer-use.mjs`；Python `runtime/media_missher_runtime/computer_use.py` |
| 原入口与生命周期 | `runtime/media_missher_runtime/cli.py`，`media-missher/scripts/run_collection.py`，`harness-plugin/src/{index,process}.ts`，`agent-plugin/bin/media-missher.mjs` |
| 持久恢复 | `runtime/media_missher_runtime/{storage,continuation,plan_runner,best_effort,shared_safety}.py`；新增 `batch_journal.py` |
| 平台规则 | `runtime/media_missher_runtime/platforms/{x,weibo_topic}.py` 与原四平台采集器；共享 `page_collection.py` |
| 导出/交互 | `runtime/media_missher_runtime/exporting.py`，`media-missher/scripts/{manage_runs,media_missher_history}.py`，`harness-plugin/src/{runs,agent-guidance,creator-list}.ts`，`agent-plugin/src/targets.mjs` |
| 移除/归档 | BSK 专属源码与分支、对应测试、`harness-plugin/scripts/{stage-payload,verify-package}.mjs`、`agent-plugin/scripts/{archive,build}.mjs` |

顺序：1 能力核验 → 2 契约 → 2A 跨 Agent 入口 → 3 最小 CU 闭环 → 4 持久可靠性 → 5 X → 6 微博话题 → 7 多目标/导出 → 8 BSK 清理 → 9 全套/安装/现场 → 10 审查/Git。任务 3 的真实宿主阻断不妨碍 4–8 的纯离线/CDP工作，但不能据此跳过最终 CU 验收；任务9/10涉及真实平台、正式安装和Git的步骤仍须单独恢复授权。

以下“新增”名称是**本项目拟实现的接口**，不是 DSH 已提供 API。除已有入口外，不得凭名称猜宿主调用方式。

## 通用验证命令

所有命令工作目录明确设为桌面工程；Harness/Agent 子命令分别使用其子目录。先用 `command -v` 核验工具，不改系统 PATH，不联网安装以掩盖缺失环境。

```sh
PYTHONDONTWRITEBYTECODE=1 uv run --offline --no-project --python 3.12 --with pytest --with pytest-asyncio --with pytest-socket --with-requirements runtime/requirements.lock python -m pytest -q -p no:cacheprovider --disable-socket --allow-unix-socket tests/
```

```sh
# workdir: /Users/missher/Desktop/Media@Missher/harness-plugin
pnpm exec vitest run --maxWorkers=1 --no-file-parallelism
pnpm exec tsc --noEmit
```

```sh
# workdir: /Users/missher/Desktop/Media@Missher/agent-plugin
node --test tests/*.test.mjs
```

定向 Python 测试用上面的相同禁网环境，将末尾 `tests/` 替换为各任务指定文件；不得直接取消禁网来修测试。下面 Run 缩写 `pytest` 均指这个完整环境。测试状态保留失败→修复→通过的证据。

---

### Task 1：固定现场基线与真实宿主能力

**Files:** 读取 `AGENTS.md`、`docs/CODEX_REPAIR_PAUSE_2026-09-20.md`；新增 `docs/DSH_COMPUTER_USE_CAPABILITIES.md`。不修改宿主仓库/profile。

**Interfaces:** 输出能力报告，字段固定为 `host_version, provider_name, provider_version, tool_schema_digest, os, permission_state, image_route, evidence_resolution, action_guard, status`。未知或拒绝必须记录为 `unverified|denied|unavailable`，不能记 passed。

- [ ] 记录真实路径、分支、完整 SHA、dirty 文件清单和可恢复快照；比对上一轮源码摘要，不清理差异。
- [ ] 只读核实用户实际运行的 DSH 版本/活动 provider，而不是仅看 `/Applications` 的版本字段；记录工具发现与权限诊断结果，不请求系统权限、不截屏。
- [ ] 核验当前宿主公开工具执行/结果扩展点：能否解析可信调用结果/附件、绑定 Session、检查取消与本任务动作边界。报告精确符号、源码/文档版本及一份脱敏输入输出样例，不能写假 `ctx.computerUse.execute()`。
- [ ] 对三个环境分别记录结果：无 provider、provider 激活但权限不足、provider 与权限具备。前两者都不应启动浏览器或影响 CDP。
- [ ] 若拿不到可信证据解析或动作管线，任务 3 真实接入停在明确阻断；不读取私有会话数据库/认证文件、不绕宿主直接 import driver。报告交监督审查。

### Task 2：两路径契约与旧数据迁移

**Files:** 修改 `contracts.py`、`models.py`、`backends.py`、`capabilities.py`、`cli.py`、TS `config.ts/plan.ts`、Agent CLI；测试 `tests/test_runtime_contracts.py`、`tests/test_run_history.py`、`harness-plugin/tests/config.spec.ts`、`agent-plugin/tests/cli.test.mjs`。

**Interfaces:** 保持 `normalize_backend(explicit, *, preference=None, legacy_assist=None) -> str`；活动值改为 `cdp|computer_use`。历史 backend 校验与新执行校验拆开。现有 `load_run` 继续读取旧五字段/schema 2，包括已退休 BSK 来源；新产物由 schema 3 写出。

- [ ] 补以下新契约红测，以及 schema 1 CDP 计划迁移、schema 2 BSK 历史只读、未知版本失败的夹具。

```python
import pytest
from runtime.media_missher_runtime.contracts import BACKENDS, ContractError, normalize_backend

def test_active_backends_are_exactly_two():
    assert BACKENDS == ("cdp", "computer_use")
    assert normalize_backend(None) == "cdp"
    assert normalize_backend("computer_use") == "computer_use"

def test_retired_backend_does_not_silently_fallback():
    with pytest.raises(ContractError, match="backend-retired-browserskill"):
        normalize_backend(None, preference="browserskill")
```

- [ ] Run `pytest tests/test_runtime_contracts.py tests/test_run_history.py`，确认仅新契约失败；缺失文件或导入错误不得当作业务失败证据。
- [ ] 最小修改枚举、各层参数与分派；无宿主请求 `computer_use` 时返回 `host-computer-use-unavailable`，不调用 CDP/BSK。删除活动能力矩阵中的 BSK，CU 逐项依能力报告判断，不硬编码全部 full。
- [ ] 计划/manifest/导出独立版本化，增加兼容读取测试；不得将旧 run 的 backend 改写为 CDP。
- [ ] 重跑指定 Python/TS/Agent 测试；加无 DSH/CU/BSK 可执行文件的隔离启动测试，验证 CDP dry preflight、历史读取、导出只依赖自身组件。提交本阶段审查记录，不提交 Git。

### Task 2A：跨 Agent 自描述入口与依赖隔离

**Files:** 修改 `agent-plugin/bin/media-missher.mjs`、`agent-plugin/src/skills.mjs`、`agent-plugin/skill/SKILL.md`、`AGENT_INSTALL.md`、TS `config.ts/plan.ts`；新增 `agent-plugin/tests/portability.test.mjs`。

**Interfaces:** `media-missher capabilities` 返回版本化 JSON；`media-missher computer-use prepare|ingest|status|finalize|cancel` 使用任务 3 共享协议。新增 `coreProtocolVersion` 和每 backend 的状态/原因；不能因打印了 computer_use 名称就报告 ready。

- [ ] 红测：无 DSH_HOME、无 DSH 包/原生驱动、无 BSK 的隔离子进程，执行 help/capabilities/历史读取/导出均不启动浏览器、不安装软件；CDP 参数解析正常，显式 CU 清楚拒绝而非回退。

```js
import assert from 'node:assert/strict'
import test from 'node:test'
import { parseCli } from '../bin/media-missher.mjs'

test('capability discovery is a host-neutral CLI command', () => {
  assert.equal(parseCli(['capabilities']).command, 'capabilities')
})
```

- [ ] 实现 CLI JSON/stdout、进度/stderr 与稳定退出码；增加 --help 对两路径、缺失信息、选择导出的描述，非交互输入不得等待 stdin 或猜平台帐号。
- [ ] 用相同目标/选择输入跑 CLI 与 DSH 工具工厂，比较标准化计划和导出选择语义一致；DSH 特有上下文不得改变默认帐号或替用户开启导航。
- [ ] 核验 Codex/Claude/Cursor/OpenClaw/Hermes 与自定义 Skill 路径发现；测试只安装所选目标、路径有空格、已有用户编辑保护与更新回滚，不改真实宿主目录。
- [ ] 在 `agent-plugin` Run `node --test tests/portability.test.mjs tests/cli.test.mjs tests/targets.test.mjs`；共享构建模块可来自本仓库，但通用包运行时不能 import DSH/provider 或访问其私有状态。

### Task 3：Computer Use 最小宿主闭环

**Files:** 新增无宿主依赖 `shared/computer-use-contract.ts`、`shared/host-evidence.ts`；新增 DSH 薄适配 `harness-plugin/src/computer-use.ts/host-evidence.ts`、通用入口 `agent-plugin/src/computer-use.mjs`、Python `runtime/media_missher_runtime/computer_use.py`；修改共享构建入口、`index.ts/agent-guidance.ts`；新增 `harness-plugin/tests/computer-use.spec.ts`、`tests/test_computer_use_contract.py`。

**Interfaces:** 本地类型及方法如下，归共享模块；DSH `host-evidence.ts` 的实际映射只能使用任务 1 核验的扩展点。通用协议不含 `ctx`、品牌工具名、DSH_HOME 或私有会话目录。

```ts
export interface HostComputerCapability {
  available: boolean
  provider: string | null
  schemaDigest: string | null
  permission: 'granted' | 'denied' | 'unknown'
  observation: 'accessibility' | 'visual' | 'both' | 'none'
  trustedEvidence: boolean
  actionGuard: boolean
}
export interface HostScope {
  hostKind: string
  hostInstanceId: string
  sessionId: string
}
export interface HostRunBinding extends HostScope {
  runId: string
  targetIdentity: string
  provider: string
  schemaDigest: string
  windowIdentity: string
}
export interface HostObservation {
  binding: HostRunBinding
  observationId: string
  observedAt: string
  source: 'accessibility' | 'visual'
  provenance: 'host-verified'
  evidenceRef: string
  contentDigest: string
  payload: unknown
}
export interface HostEvidenceBridge {
  capability(scope: HostScope): Promise<HostComputerCapability>
  resolve(binding: HostRunBinding, evidenceRef: string, signal: AbortSignal): Promise<HostObservation>
}
// Python computer_use.py 提供：
// validate_host_observation(value: dict, binding: dict) -> dict
// 结构/大小/绑定校验；来源真实性由宿主 bridge 核验，不信任模型提交的 provenance 字段。
```

- [ ] 给 bridge 写红测：跨 Session、旧窗口、新 schema、过期观察、伪造 evidenceRef、模型自称 host-verified、被篡改 payload 全部拒绝；fixture 测试不算宿主通过。

```ts
import { describe, expect, it } from 'vitest'
import { canStartComputerUse } from '../../shared/computer-use-contract.js'

describe('computer use admission', () => {
  it('requires trusted evidence and a guarded host path', () => {
    const capability = { available: true, provider: 'fixture', schemaDigest: 'a'.repeat(64),
      permission: 'granted' as const, observation: 'accessibility' as const,
      trustedEvidence: false, actionGuard: true }
    expect(canStartComputerUse(capability)).toBe(false)
  })
})
```

- [ ] Run `pnpm exec vitest run tests/computer-use.spec.ts`。新增本地 `canStartComputerUse(capability: HostComputerCapability): boolean`，仅在任务 1 对应能力具备时返回 true；无 provider 不允许创建采集 run。
- [ ] 通用 CLI 与 DSH 的 `media_missher_computer_use` 工具共用 `prepare|ingest|status|finalize|cancel`。prepare 消费共享计划；ingest 只接受 `run_id/evidence_ref`，可信身份由配置且获准的适配器取得，不接受模型自填 host 身份或任意 shell 命令；其余动作均检查 host instance/Session/租约。沿用私有存储，不另造数据库。
- [ ] 用两个不同 hostKind 的合成 bridge 跑同一协议测试，验证没有隐藏 DSH 假设、跨宿主重放被拒绝、切换 Agent 不静默接管已有 run。合成第二宿主只能算协议可移植性，不得声称该品牌实机通过。实际宿主是否支持CU由真工具目录、权限、guard与证据解析共同决定。
- [ ] Agent 调用 DSH 已有原生工具；Media 不重复注册 click/scroll 工具。宿主动作前检查授权目标、预算和租约；动作后新观察验证；不能通过另一个工具绕开已拒绝动作。缺少可执行 guard 则声明集成不完整，不以提示词代替程序保护。
- [ ] 绑定宿主已解析证据传给 Python 标准化；`validate_host_observation` 设字节/深度/记录数上限并验证 binding，不接受任意文件路径/URL 下载。`agent-reported` 只能留为未验证材料，不升级为成功记录。
- [ ] 测取消后已送达动作不重放、观察版本变更、租约超时、另一个本项目 run 同时启动、普通页面提示注入。其他应用不可控，检测漂移后停止重绑。
- [ ] 经用户恢复并授权本地样例后，使用无隐私的本地页面做真实宿主 observe→有界滚动→ingest→finalize→离线导出；无 OS 权限/图像路线时记录阻断，不自行启用。保存工具调用元数据及摘要，不截无关窗口。

### Task 4：批次提交、断电恢复、增量与停止

**Files:** 新增 `runtime/media_missher_runtime/batch_journal.py`、`tests/test_batch_recovery.py`；修改 `storage.py/continuation.py/plan_runner.py/best_effort.py/cli.py/shared_safety.py`；扩展 `test_plan_integration.py/test_process_lifecycle.py`。

**Interfaces:** 新增 `BatchJournal(run_dir: Path)`，`commit(sequence: int, records: list[dict], checkpoint: dict) -> dict`，`recover() -> list[dict]`。返回仅为已完整提交批次；checkpoint 包含计划/配置摘要、target、backend、source cursor（若有效）、records 摘要、completed targets、risk marker。

- [ ] 写三段故障注入红测：记录写完而提交标记未完成；提交标记原子落盘后进程退出；末批记录损坏。前两者分别“不承认未提交批次”“恢复已提交批次”，已提交损坏则拒绝继续而不是静默忽略。

```python
from runtime.media_missher_runtime.batch_journal import BatchJournal

def test_committed_batch_survives_reopen(tmp_path):
    journal = BatchJournal(tmp_path)
    journal.commit(1, [{"platform": "x", "tweet_id": "9007199254740993"}],
                   {"target_identity": "x:creator:fixture", "backend": "cdp"})
    batches = BatchJournal(tmp_path).recover()
    assert len(batches) == 1
    assert batches[0]["records"][0]["tweet_id"] == "9007199254740993"
```

- [ ] Run `pytest tests/test_batch_recovery.py tests/test_plan_integration.py`。实现每批独立记录文件与最后写入的原子提交元数据，复用 RunStore 的权限/fsync 路径保护；重复 sequence 相同摘要幂等、不同摘要冲突报错。
- [ ] 将真实采集器进度绑定该 journal，不只给模拟 Runner 增加方法。两批记录必须实际不同；已完成目标跳过，当前目标排除历史 ID，主页访问登记也能恢复。
- [ ] 恢复读取批次校验链，创建新 run/parent 关系；原 run 字节不变。游标未知/过期走重新定位+排除，并明确恢复级别。CU 丢失 Session 时不复用旧 token。
- [ ] 新进程风险恢复测试必须在任何浏览器调用前拒绝；timeout/cancel 仍保存已提交前缀；回收本任务进程组与租约，不杀用户浏览器、不关用户原页面。
- [ ] 复跑 `test_batch_recovery.py/test_plan_integration.py/test_process_lifecycle.py/test_shared_safety.py/test_xhs_policy.py`，核对未启动/部分成功状态跨 summary/manifest/run-result/controller 一致。小红书保护值不变。

### Task 5：X 第五平台补齐与两路径字段一致性

**Files:** 修改 `platforms/x.py`、`contracts.py`、`page_collection.py`、`extraction.py`；新增 `tests/test_x_upgrade.py` 与 `tests/runtime_fixtures/x_upgrade.json`；扩展 `test_runtime_x_topic_collectors.py`、TS/Agent 目标测试。

**Interfaces:** 复用 `Target`、`target_url`、`target_binding`、`normalize_post`、`normalize_response_payload`、`dedup_key`，不新增 X 专用任务引擎。CU 转换可见观察到共同 normalizer 的输入；不存在的字段传 None。

- [ ] 写帐号/搜索/hashtag、旧 twitter 链接、恶意主机、handle 长度冲突、超大 ID、quoted/repost、推荐卡片、空指标和缩写指标红测。fixture 使用合成内容，不拷贝真实用户正文/身份。

```python
from runtime.media_missher_runtime.platforms.x import parse_display_metric

def test_x_metrics_never_invent_exact_values():
    assert parse_display_metric(None) == (None, "unknown")
    assert parse_display_metric("1.2K") == (1200.0, "rounded")
    assert parse_display_metric("0") == (0, "exact")
```

- [ ] Run `pytest tests/test_x_upgrade.py tests/test_runtime_x_topic_collectors.py`；沿用现有解析，统一入口与解析器的 handle 规则，`tweet_id/author_id/conversation_id` 全程字符串。
- [ ] 按规格第 6 节逐字段补标准化及字段组；作者资料只关联已绑定作者，不把 feed 推荐用户写到目标主页；多帐号共享帖子内容仍保留各目标来源关系。
- [ ] CDP 响应先校验来源/任务/状态再解析，列表请求与详情响应分开；没有可用响应准确标部分/失败，不合成请求重放。CU 只处理可见卡片/主页，不把截图数字变成精确隐藏指标。
- [ ] 加网络错误体、登录页、challenge、429、页面无增长、排序未生效、正文截断、引用作者与外层作者不同测试；风险停止后另一目标/后端调用计数必须为 0。
- [ ] 增加 X→持久化→历史→按字段导出的集成回归，核对回复数/浏览量/书签的语义。平台规则限制列入能力报告：无适用许可不启动真实 X 自动化，不另建 API 后端；不会因离线测试通过取消该限制。

### Task 6：微博话题与公开主页关系

**Files:** 修改 `platforms/weibo_topic.py`、`plan_runner.py`、`computer_use.py`、`exporting.py`；新增 `tests/test_weibo_topic_upgrade.py`；扩展 `test_plan_integration.py`。

**Interfaces:** 复用 `parse_topic_input`、`ParticipantRegistry.register`、`normalize_profile` 和三类记录；关联去重键包含 topic、post ID、UID，用户主页访问键为 platform+UID。

- [ ] 补普通话题 URL/名称、超话独立拒绝、引用内层作者排除、同用户两话题、主页失败/风险、1帖子多伴随记录红测。

```python
from runtime.media_missher_runtime.platforms.weibo_topic import ParticipantRegistry, parse_topic_input

def test_same_user_retains_two_topic_relations():
    registry = ParticipantRegistry()
    for topic, post in (("展会A", "100"), ("展会B", "101")):
        registry.register(uid="10", handle=None, display_name="fixture",
                          topic=parse_topic_input(topic), post_id=post,
                          observed_at="2026-09-20T00:00:00Z", via_repost=False)
    assert len(registry.users) == 1
    assert len(registry.relations) == 2
```

- [ ] Run `pytest tests/test_weibo_topic_upgrade.py tests/test_plan_integration.py`。复用已修逻辑并接 CU 观察，按 UID 确认主页；无法确认身份时保留发现短缺，不按昵称猜用户。
- [ ] 主页调用计数跨话题/恢复为 1；两条来源关系可分别导出；同一关系重复观察去重。帖子 count 不截断主页/关系记录。
- [ ] 测主页不可见保留 profile_status/reason；主页 risk 全局停止且前缀仍可读；无数据时明确0，不把“无异常”算采集成功。
- [ ] 超话未实现/未测不标支持。真实微博挑战仍未解除，禁止以 CU 模式重试；本阶段只用合成页面，现场门槛留任务 9。

### Task 7：多目标询问、字段选择及离线导出

**Files:** 修改 TS `config.ts/plan.ts/creator-list.ts/agent-guidance.ts/runs.ts`、Agent `targets.mjs`、Python `contracts.py/exporting.py`、`manage_runs.py/media_missher_history.py`；新增 `tests/test_export_upgrade.py`，扩展 `test_cli.py/test_run_history.py` 与 TS `creator-list.spec.ts/plugin.spec.ts/workbook.spec.ts`。

**Interfaces:** 原 `media_missher_collect` 保留 CDP 调用；明确 CU 时交由宿主模式，不能创建 CDP 子进程。`media_missher_runs action=export` 沿用 ExportSelection；缺失目标返回 `needs-input` 及字段，不猜帐号。

- [ ] 写缺失平台/帐号、已给多个精确链接、不支持模式、帐号重名、混合关键词与帐号、只选部分字段的红测；断言已给信息不重复请求。

```python
import pytest
from runtime.media_missher_runtime.exporting import ExportSelection, ExportError

def test_export_requires_an_explicit_record_category():
    with pytest.raises(ExportError):
        ExportSelection(run_id="run-fixture", record_kinds=())
```

- [ ] Run `pytest tests/test_export_upgrade.py tests/test_cli.py tests/test_run_history.py`；保持 Agent 交互负责问人、CLI 返回结构化缺失项，不用阻塞 stdin 或自行选帐号。
- [ ] 展示采集汇总与可用字段后消费用户导出选择；不自动写 Excel。显式选择“全部实际字段”可一次导出，不增加无谓确认。
- [ ] XLSX/CSV/JSON/JSONL/SQLite 参数化测试：长整数保持字符串、emoji/换行不损坏、formula前缀安全、路径逃逸/软链接/覆盖拒绝、原 run 不变、全程无网络/浏览器调用。
- [ ] 验证各目标/话题过滤、用户与关系类别、缺失/缩写数字、风险前缀导出；只选关系一侧时提示部分投影，不暗添用户没选的敏感字段。
- [ ] 更新安装后可发现的 Skill/Agent guidance，而不是仅在开发对话说明；检查独立 CLI 与 DSH 返回的计划/导出选择一致。

### Task 8：彻底退出 BrowserSkill 执行链

**Files:** 盘点并移除 `runtime/media_missher_runtime/browser_skill.py/bsk_session.py/bsk_page.py` 及专属测试；修改 `detail_open.py/platforms/bilibili.py/cli.py` 相关分支；修改 `harness-plugin/scripts/stage-payload.mjs/verify-package.mjs`、`agent-plugin/scripts/archive.mjs/build.mjs`，活动 README/Skill/参数帮助；新增 `tests/test_backend_retirement.py`。

**Interfaces:** 不新增替代入口；保留 `backend-retired-browserskill` 诊断、历史来源字符串、只读兼容夹具。

- [ ] 用以下只读搜索制作每项“删除/保留理由”清单，保留 `page_collection`、CDP详情协调器、截图和共享风险代码。

```sh
rg -n 'BrowserSkill|browserskill|bsk_|browser_skill|browser-assist' runtime media-missher harness-plugin agent-plugin tests tools openclaw-media-missher
```

- [ ] 写退休后端输入拒绝、旧历史可导出、归档不存在 BSK 文件、没有 bsk 子进程调用、能力矩阵只有两种执行路径的失败测试。历史提案和兼容诊断里的文字命中不算运行残留。
- [ ] 使用 apply_patch 精确移除专属源文件/分支；先把必要安全测试迁移到共享/CU测试再删除旧专属用例，禁止为变绿而删仍适用的安全断言。
- [ ] 不操作用户全局 bsk/扩展，不修改 Documents/正式runtime。旧产物生成清单后在本项目内可恢复归档；用户采集输出和凭据不搬入仓库。
- [ ] Run `pytest tests/test_backend_retirement.py tests/test_packaging.py tests/test_runtime_detail_open.py tests/test_run_history.py`，再跑对应 TS/Agent 归档测试，验证共享CDP没有回退。

### Task 9：冻结、构建、隔离安装和分层验收

**Files:** `harness-plugin/package.json/agent-plugin/package.json/VERSION`（只有准备发布时统一版本）、对应构建脚本与校验器；新增 `docs/CDP_COMPUTER_USE_ACCEPTANCE.md`，更新 README/PROJECT_CONTEXT/HANDOVER。

**Interfaces:** 最终证据表逐项记录源码摘要、包SHA256、平台/模式/backend、测试类型、时间、结果、阻断。用户输出只给统计和私有证据路径，不展示个人资料样本。

- [ ] 全套 Python/Harness/Agent/tsc/diff 检查在同一冻结源码上通过；不得以旧测试数量作为目标去凑数。源码再改则重测相关范围，最终重新冻结。
- [ ] 执行 `pnpm run build`、`pnpm run stage:payload`（Harness目录）和 `node scripts/build.mjs`（Agent目录），先归档确认旧生成物可恢复；查看构建脚本具体清理目标，不能用宽泛 rm 清理工作区。
- [ ] 对新包运行 `verify-package.mjs` 与 `archive.mjs` 对应校验：来源模块齐全、无 BSK payload、无私有数据、无意外 DSH/native import 进入独立 Agent 入口。匹配唯一源码摘要并计算包校验和。
- [ ] 用专用临时 `DSH_HOME` / 运行目录做安装/工具发现/卸载/状态隔离，保留原用户配置；若安装需新增系统依赖或 OS 授权则交用户处理。原包 smoke 命令必须先读帮助，不能误跑真实平台。
- [ ] 在无DSH/CU/BSK环境验证CDP入口和离线导出；在真实DSH本地合成页面验证CU的权限拒绝、旧观察、取消、私有证据和导出。这是原生样例，不是平台实测。
- [ ] 只有用户重新授权精确目标/预算且既有平台风险已妥善处理才开始真实平台验收。每次只一个控制者，遇风险全局停止；X 还需满足规格6.3。未能进行的格子标未验收，不擅自扩大采集。
- [ ] 形成五平台×模式×两路径的真实能力表：CDP抓到的精确字段不能冒充CU字段；话题0条不算主页通过；只跑本地样例不算全平台通过。

### Task 10：最终审查与 Git 更新门槛

**Files:** 更新 `HANDOVER.md/PROJECT_CONTEXT.md`、本计划复选框和验收文档；禁止提交运行证据/凭据/用户资料。

- [ ] 开发任务回报：精确修改文件、删除清单与恢复依据、测试命令与结果、原生/现场范围、产物摘要、未解决事项、Git状态。监督任务只读审查和下达修正，不双写代码。
- [ ] 监督检查十项任务及规格逐条覆盖；明确剩余不支持范围由用户接受，不能将受限候选说成全部完成。
- [ ] 只有用户明确恢复Git步骤且验收条件满足后，重新核验远端URL/分支权限/差异归属。桌面 origin 指向本机Documents不是发布目标；不盲推、不force push、不自动改为公共仓库。
- [ ] 逐文件暂存经审查改动，记录最终完整提交SHA；不顺手提交其他人的未归属修改。新提交与产物构建身份核对后再执行已授权推送；tag/Release需要对应授权。
- [ ] 最终交付清楚区分“代码完成”“安装通过”“实际平台通过”和“平台受限”。用户当前已恢复开发；若后续再次要求暂停，只保留交接并暂停监督。真实平台、正式安装升级和 Git 的独立暂停边界仍有效。

## 可复制的后续开发任务书

> 用户已恢复开发，交给既有开发任务 `01a0bea1-6642-7102-985b-6788b8760294`：
>
> 在 `/Users/missher/Desktop/Media@Missher` 继续实现。先读 `docs/CDP_COMPUTER_USE_UPGRADE_SPEC_2026-09-20.md` 与 `docs/superpowers/plans/2026-09-20-cdp-computer-use-upgrade.md`。最终只保留 `cdp` 和 `computer_use`；CLI+共享Skill服务各种可执行本地命令的Agent，DSH只是薄包装。CDP默认独立可用，Computer Use是宿主无关协议，各宿主经真实能力核验接入，不能将所有Agent都需要DSH。移除BrowserSkill运行链但保留旧数据只读与配置拒绝迁移。完整纳入X、五平台多帐号、有界多抓与可靠续抓、微博话题参与用户公开主页和选择导出。按任务逐步红测、最小修改、验证和回报，不推倒重写、不启动代理、不修改Documents原项目。宿主接口先核验，不编造API；缺一个宿主CU不得卡住独立CLI/CDP工作。真实平台风险和X规则分别处理，不以换控制器绕过。由监督任务审查，不恢复真实采集、正式安装升级、提交推送或发布。
