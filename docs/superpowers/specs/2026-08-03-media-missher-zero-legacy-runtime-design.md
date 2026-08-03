# Media@Missher Zero-Legacy Runtime Design

## Goal

Replace the active four-platform collection runtime with independently authored code so that the repository, installed Codex skill, installed OpenClaw skill, and active runtime contain none of the two owner-designated legacy names, while preserving the validated Bilibili, Xiaohongshu, Douyin, and Weibo collection contract.

## User-visible success criteria

1. Creator collection, single-platform keyword search, platform-specific counts and UIDs, Bilibili complete mode, Xiaohongshu complete mode and comment limits continue to work.
2. JSON, CSV, JSONL, and SQLite output continue to preserve native identifiers, links, null-versus-zero values, and nested values.
3. Multi-platform work remains sequential. The runtime stops immediately on risk, locked, blocked, cooldown, `403`, `429`, `461`, `471`, or `999` signals.
4. The repository, installed Codex skill, installed OpenClaw skill, active runtime, generated configuration, and runtime virtual environment contain zero literal occurrences of the two forbidden legacy names supplied by the owner.
5. The separate obsolete crawler project and the replaced OpenClaw engine are absent from their active locations after cutover.
6. Historical Codex memories, conversation logs, migration evidence held outside the active paths, and recoverable Trash contents are not rewritten. They are not runtime dependencies and are excluded from the active-residual gate.

## Rejected approaches

### Rename-only cleanup

Removing source headers, repository URLs, or directory names without replacing reachable implementations would make a text scan pass while retaining the same runtime. This fails the owner's requirement and creates misleading provenance.

### Delete-first cleanup

Removing the old engine before a replacement passes compatibility tests would break all four platforms. This also removes the only immediate rollback path.

### Full product rewrite

Rewriting the already independent Codex adapter, validation, conversion, and safety orchestration would add risk without helping the legacy-removal objective.

## Selected architecture

### Single clean runtime home

Source-controlled runtime code will live under `runtime/` in this repository. Deployment will create one shared runtime home under the user's local application-data directory:

```text
runtime-home/
├── current/                 # deployed source copied from repository runtime/
├── venv/                    # clean dependency environment
└── state/                   # locks, cache, checkpoints, and reports
```

The default location is derived from `Path.home()` at runtime; no personal absolute path is stored in the repository or skill package.

Both Codex and OpenClaw launch the same deployed runtime. The Codex skill stops resolving the old external engine. The OpenClaw skill is replaced with a compact manifest, instructions, and entrypoint shims that launch the shared runtime.

### Runtime modules

```text
runtime/
├── requirements.lock
├── media_missher_runtime/
│   ├── __init__.py
│   ├── cli.py              # compatible creator/search CLI routing
│   ├── browser.py          # existing-CDP connection and page selection
│   ├── safety.py           # pacing, page caps, timeouts, risk stop
│   ├── storage.py          # private JSON staging only
│   ├── models.py           # normalized records and validation helpers
│   └── platforms/
│       ├── bilibili.py
│       ├── xhs.py
│       ├── douyin.py
│       └── weibo.py
└── scripts/
    ├── scrape_all.py
    ├── scrape_bilibili.py
    ├── scrape_xhs.py
    ├── scrape_douyin.py
    └── scrape_weibo.py
```

Each platform module implements only the operations required by the public Media@Missher contract. It does not reproduce unused database, proxy-pool, API server, archived platform, Excel, generic crawler, or web-UI subsystems.

### Independent implementation boundary

New runtime code is written from the approved behavior contract, synthetic response fixtures, current output schemas, and observable browser behavior. Implementers must not read, import, copy, transform, or patch source from either legacy tree. Existing active code is used only as a black-box compatibility oracle during tests.

The top-level API is intentionally small:

```python
async def collect_creator(request: CollectionRequest, browser: BrowserSession) -> list[dict]
async def search(request: SearchRequest, browser: BrowserSession) -> list[dict]
```

Platform code may perform same-origin browser-context requests or parse data already present in the authorized browser page. It must not capture credentials, export cookies, inject fingerprint-evasion logic, solve captchas, rotate accounts, or rotate network exits.

## Behavior preservation

### Browser session

- Connect only to the configured existing CDP endpoint.
- Never start, restart, terminate, or reprofile Chrome.
- Select an already open matching platform page.
- If a required page is missing or logged out, return a structured precondition failure. Navigation is allowed only when separately authorized for a specific validation run.

### Counts and sequencing

- `count=N` means up to and normally exactly `N` validated records per selected platform.
- `count=0` remains explicit collect-as-much-as-safe and is bounded by the page cap.
- The controller launches platforms sequentially and isolates non-risk platform failures.
- Xiaohongshu is never run concurrently with another collection.

### Completeness

- Bilibili complete records require a native ID, non-placeholder title, date, detail completion, and non-null liked/comments/shares/collected values.
- Xiaohongshu complete records require a native ID, detail attempt, non-estimated date, current-run engagement observation, and non-null liked/comments/collected values.
- Unknown values remain null and are never invented as zero.

### Output and privacy

- The runtime writes private mode-`0600` JSON only into a unique mode-`0700` run directory.
- The existing Codex adapter validates current-run JSON and owns CSV, JSONL, and SQLite conversion.
- The runtime never creates Feishu artifacts or performs a remote Feishu write.
- Summaries contain only counts, statuses, paths, and metadata-only samples.

## Error handling

- Risk signals terminate the process group immediately and produce `risk-stopped`.
- Timeouts terminate only the child process group and preserve logs and partial evidence.
- Missing pages, missing login, missing runtime dependencies, or incompatible entrypoints fail preflight before a run directory is created.
- One non-risk retry is allowed only after its concrete prerequisite is corrected.
- No deletion, lock clearing, state clearing, account switching, proxy rotation, or retry amplification is used to recover from platform controls.

## Test strategy

### Offline gates

1. Retain the existing 109 adapter, packaging, security, conversion, and validation tests.
2. Add per-platform response fixtures covering creator and search modes.
3. Add complete-mode fixtures for Bilibili and Xiaohongshu.
4. Add risk, blocked, timeout, missing-page, logged-out, malformed-response, count, deduplication, and null-preservation tests.
5. Disable all real sockets during the default suite.
6. Run all five runtime entrypoints from a path containing spaces and `@`.
7. Scan the repository, installable skill, deployed runtime, OpenClaw skill, and virtual-environment metadata for both forbidden legacy names; the expected count is zero.

### Compatibility gates

1. Feed the same synthetic platform responses to the old black box and the new runtime in separate processes.
2. Normalize timestamps, run IDs, and temporary paths.
3. Compare platform IDs, field names, types, null/zero distinctions, counts, completeness, ordering, and failure statuses.
4. Any behavioral difference must be fixed or explicitly documented as a safety correction before cutover.

### Live acceptance

After every offline gate passes:

1. Run one sequential creator collection for all four platforms with count `1`, Bilibili complete, Xiaohongshu complete, JSON staging, and no Feishu.
2. If a platform page is missing, open one temporary authorized page, validate that platform once, then close it.
3. Validate native IDs, current evidence times, counts, completeness, no risk signal, no timeout, and no Feishu artifacts.
4. Do not retry a risk stop.

## Deployment and destructive cutover

1. Build the clean runtime home and virtual environment without touching the old engine.
2. Install and preflight the new Codex and OpenClaw launchers against the clean runtime.
3. Complete offline, compatibility, and live acceptance gates.
4. Record read-only manifests for the obsolete active trees.
5. Move the obsolete standalone crawler project and replaced engine to recoverable Trash locations. Never use broad recursive deletion.
6. Re-run the active-residual scan and all preflight checks.
7. If any post-cutover gate fails, restore the previous engine from Trash and revert the launcher configuration. If all gates pass, retain Trash only as a short recovery window for the owner to empty later.

## Rollback boundary

Rollback switches both launchers back to the previous engine and restores its directory from Trash. Runtime output directories and historical evidence are never deleted during rollback. The separate obsolete project is not part of the functional rollback because it is not called by Media@Missher.

## Non-goals

- Adding platforms beyond Bilibili, Xiaohongshu, Douyin, and Weibo.
- Restoring archived crawlers, API servers, database layers, proxy pools, or web UI.
- Performing remote Feishu writes.
- Bypassing platform controls or changing authenticated browser identities.
- Rewriting Codex memories, conversation logs, or unrelated user projects merely to remove historical words.
