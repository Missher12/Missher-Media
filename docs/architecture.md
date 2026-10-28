# 架构与维护入口

[返回首页](../README.md)

```mermaid
flowchart LR
  A[用户或 Agent 的明确任务] --> B[CLI / 计划校验]
  B --> C[共享锁、节奏与风险检查]
  C --> D[Chrome CDP 会话]
  D --> E[平台解析与目标绑定]
  E --> F[字段校验、去重与来源记录]
  F --> G[本地 JSON 和运行清单]
  G --> H[按选择离线导出]
```

CDP 是唯一活动后端。运行时通过 Playwright 连接浏览器，平台模块处理当前页面和与目标相匹配的响应；保存与导出不依赖模型生成字段。

| 模块 | 职责 |
| --- | --- |
| `runtime/scripts/` | 便携入口，定位同一份运行时 |
| `cli.py`、`contracts.py`、`models.py` | 参数、请求、记录与计划合同 |
| `browser.py`、`detail_open.py` | 连接、页面所有权和详情操作 |
| `platforms/` | 五个平台及微博话题解析 |
| `plan_runner.py`、`best_effort.py`、`batch_journal.py` | 顺序计划、有界批次、检查点与适用的续采 |
| `shared_safety.py`、`collection_pacing.py`、`page_risk.py` | 共享锁、正常间隔、风险状态及可见阻断检查 |
| `storage.py`、`exporting.py` | 原子保存、运行清单、选择导出与表格保护 |
| `tests/` | 核心行为测试、模拟浏览器与合成夹具 |

旧后端名字用于拒绝退役请求或读取历史记录，不表示 BrowserSkill / Computer Use 重新启用，不应仅为消除文字命中而删除兼容边界。

`SOURCE_MANIFEST.json` 记录原样导出的 81 个核心源码、测试与夹具文件；文档和展示样例独立维护。`SHA256SUMS.txt` 覆盖公开目录中除其自身外的文件。

新增能力应贯通请求校验、平台实现、结果质量与测试。不要用放宽身份校验、删除风险检查或将未知值填零来提高表面成功率。宿主界面、模型配置和账号管理由外部集成处理。
