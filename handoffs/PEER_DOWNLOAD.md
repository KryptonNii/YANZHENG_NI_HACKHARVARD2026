# Peer registry download

状态：**已完成**。

| 项目 | 本次结果 |
| --- | --- |
| API 返回的 totalCount | 553 |
| 翻页数 | 6（100 + 100 + 100 + 100 + 100 + 53） |
| 本次返回的唯一 NCT 数 | 553 |
| 保存份数（完整正文，逐对象核验本次响应） | 553 |
| 既有路径的 sidecar / 索引中的本次 meta | 553 / 553 |
| 本次写入正文数 | 550 |
| 保留并核验相同的受保护正文数 | 3 |
| 失败的 NCT | 无 |
| 其他失败 | 无 |
| 开始时间（America/Toronto） | 2026-10-17T01:58:20-04:00 |
| 结束时间（America/Toronto） | 2026-10-17T01:58:31-04:00 |
| 开始时间（UTC） | 2026-10-17T05:58:20.240Z |
| 结束时间（UTC） | 2026-10-17T05:58:31.833Z |
| dataTimestamp | 2026-10-16T09:00:05 |
| API version | 2.0.5 |

查询：[ClinicalTrials.gov API v2](https://clinicaltrials.gov/api/v2/studies?query.cond=COPD&filter.advanced=AREA[Phase]PHASE3&pageSize=100&countTotal=true)。以本次第一页 `totalCount` 为准，跟随全部 `nextPageToken`，页间调用 `time.sleep(0.3)`。没有字段过滤、条件再筛选或研究内容裁剪。

目录结构（保持扁平目录，兼容现有消费者）：

```text
data/fixtures/peers/registry/
  NCT########.json       # API 返回的完整 study 对象，UTF-8 JSON
  NCT########.meta.json  # 元数据；受保护的既有 sidecar 原样保留
  index.json            # entries[NCT] -> body_path，以及本次完整 meta
handoffs/PEER_DOWNLOAD.md
```

`index.json` 中的路径相对于 `data/fixtures/peers/registry/`。每个 NCT 仅一份正文；文件名等于 `protocolSection.identificationModule.nctId`。索引不内嵌正文，仅提供路径、正文 SHA-256、本次完整研究对象的规范化 SHA-256、分页清单和元数据。

每项 `entries[NCT].meta` 包含 `nct_id`、`source_url`（实际分页请求）、`fetched_at`（UTC）、`dataTimestamp` 和 `attribution: "ClinicalTrials.gov, U.S. National Library of Medicine"`。`dataTimestamp` 取自 `/api/v2/version`，开始与结束均核验。非保护 sidecar 同时保留 `data_timestamp` 兼容字段。

NCT03930732、NCT04456673、NCT04535986 的既有 registry 正文和 sidecar 均逐字节保留；其正文与本次 API study 对象深比较一致后才计入保存份数。本次 meta 在索引内，`legacy_meta_path` 指向未修改的旧 sidecar（使用 `data_timestamp`）。NCT04429503 不在本次 COPD 查询中，未创建其 registry 副本。

未写入 `data/fixtures/ctgov/`；四个受保护 NCT 的既有文件及 ctgov 文件均以抓取前后 SHA-256 核验。未修改应用代码，未运行设计种子或导入流程，未重新生成 cohort，未提交。

独立只读验收通过：553 份正文、553 份 sidecar 和 553 个索引项一致；正文命名、元数据、文件哈希及完整 study 对象哈希均通过。最后一页无下一页令牌；各页请求开始距上页响应结束至少 0.775 秒（包含处理耗时及明确的 0.3 秒暂停）。28 个 ctgov／受保护基线文件哈希不变，ctgov 的 13 个文件集合不变。

范围核验比较了抓取前快照中的 14,584 个范围外或受保护文件。核验窗口内发现 `api/tests/test_benchmark.py`、`api/trialpilot_api/benchmark/cohort.py`、`web/src/features/scenario/peerMirror.test.tsx` 内容发生变化；本下载任务未写入这些路径，未回退其他工作的变更。其余快照文件均保持相同，未发现范围外新增或缺失文件。
