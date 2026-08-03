# Media@Missher Codex Skill Design

## Objective

Build a standard Codex skill named `media-missher` in this repository while preserving every supported Media@Missher collection capability. Keep the currently installed OpenClaw skill at `/Users/missher/.openclaw/workspace/skills/media-missher` unchanged until the candidate passes offline, differential, smoke, and explicitly authorized live verification.

The new skill must contain only newly written adapter code. It must not copy the installed engine, its virtual environment, archived platforms, generated data, third-party JavaScript, images, fonts, or inherited source headers.

## Approved Architecture

Use a thin-process adapter around the already installed Media@Missher engine.

- Do not import installed engine modules into the Codex process.
- Invoke the installed engine only through documented subprocess entrypoints.
- Discover the engine from `--engine-root`, `MEDIA_MISSHER_ENGINE_ROOT`, or a private user configuration file, in that order.
- Keep the adapter standard-library-only so the Codex skill does not inherit the engine's 78-package environment.
- Force the external engine to write JSON into a unique private staging directory.
- Validate and convert staged JSON inside the adapter when CSV, JSONL, or SQLite output is requested.
- Never package or modify the external engine as part of this skill.

This design makes the new repository independently authored while retaining current runtime behavior through the existing, already working engine.

## Alternatives Rejected

### Copy and trim the installed engine

Rejected because the active engine contains files derived from code under the Non-Commercial Learning License 1.1. Copying those files would require preserving their source and license terms, would keep the eager-import dependency problem, and would make regression risk materially higher.

### Clean-room rewrite all four platform clients now

Deferred because Bilibili, Xiaohongshu, Douyin, and Weibo have different authenticated APIs, signing behavior, pagination, and risk signals. Rewriting all clients before shipping the adapter would make it impossible to provide credible short-term compatibility evidence. A future clean-room runtime can replace the external engine behind the same adapter contract.

## Repository Layout

```text
/Users/missher/Documents/Media@Missher/
├── PROJECT_CONTEXT.md
├── docs/
│   └── superpowers/
│       ├── specs/
│       └── plans/
├── media-missher/
│   ├── SKILL.md
│   ├── agents/
│   │   └── openai.yaml
│   ├── scripts/
│   │   ├── media_missher_adapter.py
│   │   ├── preflight.py
│   │   ├── run_collection.py
│   │   └── validate_run.py
│   └── references/
│       ├── commands.md
│       ├── configuration.md
│       ├── licensing.md
│       ├── troubleshooting.md
│       └── validation.md
└── tests/
    ├── fixtures/
    ├── fake_engine.py
    ├── test_cli.py
    ├── test_config.py
    ├── test_output.py
    ├── test_packaging.py
    ├── test_preflight.py
    ├── test_runner.py
    ├── test_security.py
    └── test_validation.py
```

`media-missher/` is the installable skill folder. Repository-level tests and design records are not included in the installed skill.

## Skill Metadata and Progressive Disclosure

`SKILL.md` must use exactly these frontmatter keys:

```yaml
---
name: media-missher
description: Operate and validate the locally installed Media@Missher collector for Bilibili, Xiaohongshu, Douyin, and Weibo. Use when a user asks to collect a specific number of posts, search a keyword, request complete Bilibili content or fresh Xiaohongshu engagement, validate a fresh run, or diagnose CDP, login, timeout, lock, or risk-cooldown failures. Keep code review read-only and require separate explicit authorization for any remote Feishu write.
---
```

Keep `SKILL.md` below 250 lines. Put only intent routing, safety rules, the primary workflow, and reference routing in the body. Move commands, configuration, detailed validation rules, troubleshooting, and external-runtime licensing notes to one-level-deep reference files.

Generate `agents/openai.yaml` with the official skill-creator script. Do not add icons, colors, MCP dependencies, or other optional fields that the user did not provide.

## Provenance and License Boundary

- Write every adapter and test file from scratch against the documented command and output contract.
- Do not copy code, comments, tests, JavaScript, fixtures containing real collected data, or documentation prose from the installed engine.
- Do not include legacy upstream source files or inherited copyright headers in the new skill.
- State in `references/licensing.md` that the adapter does not distribute the external runtime and that the external runtime remains governed by its own license.
- Do not label the external engine MIT or imply ownership of it.
- Do not assign a repository-wide license to the new adapter until the user selects one. This avoids accidentally relicensing the external runtime by implication.

## Compatibility Contract

The adapter must preserve these observable capabilities:

| Capability | Required behavior |
|---|---|
| Platforms | Bilibili, Xiaohongshu, Douyin, and Weibo |
| Creator collection | Accept an explicit platform identifier and UID; otherwise use the private profile configuration |
| Keyword search | Support the same single-platform search entrypoints as the installed engine |
| Counts | Support a shared non-negative count and per-platform overrides; `0` means collect as much as permitted by the engine's safety page limit |
| Complete mode | Preserve Bilibili complete content and Xiaohongshu fresh-detail behavior, including per-platform complete flags |
| Xiaohongshu comments | Preserve the bounded per-note comment option |
| Formats | Produce JSON, CSV, JSONL, and SQLite without generating Feishu-format artifacts when Feishu is disabled |
| Multi-platform order | Run selected platforms sequentially and preserve platform-level timeout isolation |
| Error isolation | A non-risk platform failure must not prevent later selected platforms from running |
| Risk behavior | Preserve immediate stop behavior for risk, lock, and cooldown signals; do not amplify retries |
| Output values | Preserve field names and distinguish unknown/null from numeric zero |
| Evidence | Create a unique run directory and validate only files created by that run |

The adapter may reject invalid input earlier than the installed engine. In particular, unknown platforms, negative counts, negative timeouts, incompatible search/complete combinations, missing engine paths, and missing CDP must fail before collection starts.

## Configuration and Privacy

Resolve configuration in this order:

1. Explicit CLI argument.
2. Environment variable.
3. Private user configuration file.
4. Non-sensitive default.

Support these external settings:

- `MEDIA_MISSHER_ENGINE_ROOT`
- `MEDIA_MISSHER_DATA_ROOT`
- `MEDIA_MISSHER_CDP_URL`
- `MEDIA_MISSHER_PROFILE_CONFIG`

The private profile file must be outside the repository, use mode `0600`, and may contain platform UIDs and labels. The repository and installed skill must not contain personal Feishu identity, avatar URLs, Open IDs, platform UIDs, cookies, tokens, browser profiles, proxy credentials, cache files, locks, checkpoints, risk state, or absolute user-specific paths.

The adapter must never read a Feishu credential file or invoke `lark-cli`. Remote Feishu writes are outside this skill's scope and require a separate user-authorized workflow.

## Execution Flow

1. Parse and validate all CLI arguments without importing or invoking the engine.
2. Resolve the external engine root and its Python interpreter.
3. Run preflight checks:
   - engine root exists;
   - expected script exists;
   - engine interpreter is executable;
   - target entrypoint `--help` succeeds;
   - CDP `/json/version` responds for live collection;
   - the requested platform has an authenticated page when a safe local check can establish it.
4. Create a unique private run directory with mode `0700` under the configured data root.
5. Build an argument-vector subprocess command without shell interpolation.
6. For multi-platform creator collection, invoke `scripts/scrape_all.py` sequential mode.
7. For a single-platform keyword search, invoke the matching `scripts/scrape_<platform>.py` entrypoint.
8. Always request JSON from the external engine and always pass `--no-feishu` to the multi-platform entrypoint.
9. Capture stdout and stderr into the run directory without exposing secrets in console summaries.
10. Locate only JSON files created after the recorded run start time.
11. Validate and normalize the selected run.
12. Convert validated data to the requested final format using adapter-owned standard-library code.
13. Return a structured status: `success`, `partial`, `risk_stopped`, `preflight_failed`, or `failed`.

## Output and Feishu Semantics

`--no-feishu` must mean:

- no remote Feishu API or CLI call;
- no Feishu credential access;
- no `feishu_*.json` artifact;
- no implicit maintainer identity added to output.

The adapter always forces JSON staging, which avoids the installed engine's current behavior of generating Feishu-format JSON for non-JSON formats. CSV, JSONL, and SQLite are produced only after validation by the adapter.

Store raw staging files inside the private run directory. Do not print cookies, tokens, personal identifiers, query-string access tokens, or full subprocess environments. Validation summaries may show at most three redacted sample records.

## Safety and Error Handling

- Keep collection sequential; never run platform collectors concurrently.
- Never overlap Xiaohongshu jobs.
- Do not restart Chrome, replace cookies, clear risk state, clear locks, rotate accounts, rotate network exits, bypass captchas, or inject anti-detection scripts.
- Treat `403`, `429`, `461`, `471`, `999`, explicit risk signals, locks, and active cooldowns as terminal for the current run.
- Permit at most one retry after a clearly non-risk transient failure and only when the underlying engine already permits it.
- Preserve platform page limits, pacing, jitter, low-resource behavior, checkpoints, and failure isolation.
- On timeout or cancellation, terminate only the child process started by the adapter, retain evidence, and do not kill unrelated engine or Chrome processes.

## Test Strategy

Follow test-driven development for each behavior change.

### Default offline suite

The default suite must:

- disable all network sockets;
- prohibit Redis, MongoDB, CDP, Feishu, and external command access except controlled fake-engine subprocesses;
- redirect `HOME`, data, state, cache, lock, checkpoint, report, and output paths to temporary directories;
- fail any write outside the test temporary directory;
- use no real sleeps;
- have no unexpected skips or xfails.

### Fake engine

Create a repository-owned fake executable that implements only the documented subprocess contract and emits synthetic, non-user fixture data. Use it to test:

- argument forwarding;
- platform allow-list validation;
- shared and per-platform counts;
- search versus creator routing;
- complete flags and Xiaohongshu comments;
- timeout and platform failure isolation;
- risk-stopped classification;
- output discovery by run start time;
- secret redaction;
- JSON, CSV, JSONL, and SQLite conversion;
- absence of Feishu artifacts.

### Differential contract tests

Use synthetic fixtures that represent the installed engine's four platform schemas. Compare normalized adapter outputs field by field after removing timestamps, random run IDs, and temporary paths. Cover both creator and search records for every platform, with additional Bilibili title/date/complete cases and Xiaohongshu freshness/null/risk/checkpoint cases.

Do not copy old test source or real collected records. Re-express required behavior in new tests.

### Packaging tests

Assert that the installable skill contains only the allow-listed skill files and does not contain:

- `.venv`;
- cache or Playwright artifacts;
- `data/`, logs, locks, checkpoints, or run output;
- old absolute paths;
- personal identifiers or platform UIDs;
- engine source, inherited headers, third-party JavaScript, images, or fonts;
- `openclaw.skill.json`, changelogs, deployment guides, or historical design documents.

## Verification and Cutover

Verification proceeds in this order:

1. Run the skill-creator validator.
2. Run the complete offline suite.
3. Run packaging allow-list and secret scans.
4. Run `--help` for `preflight.py`, `run_collection.py`, and `validate_run.py` from a path containing spaces and special characters.
5. Run preflight against the installed engine without collection.
6. With explicit user authorization, run one sequential live collection for each platform with count `1`, no Feishu, and a unique run directory.
7. Read and validate every current-run JSON file and the Xiaohongshu report; do not accept exit code or console success alone.
8. Compare candidate adapter results with the installed engine's accepted field and count contract.
9. Install the Codex skill side by side at `~/.codex/skills/media-missher` only after every applicable gate passes.

The installed OpenClaw skill is never replaced by this cutover. Rollback consists of removing or disabling only the new Codex skill. Development and installation must not modify the installed engine source or pre-existing output. An explicitly authorized live verification may create a new isolated run directory and may update only the engine's normal cache, lock, checkpoint, report, and risk-state files required by that run.

## Acceptance Criteria

- The new skill contains no copied engine or upstream source code.
- The existing OpenClaw skill source remains byte-for-byte untouched by development and installation, and pre-existing output is never overwritten.
- All four platforms retain creator collection and keyword search behavior available through the installed entrypoints.
- Count, complete-mode, Xiaohongshu comments, timeout isolation, risk stop, and all four output formats behave according to the compatibility table.
- `--no-feishu` produces neither remote writes nor local Feishu artifacts.
- Invalid input fails before Chrome or the engine is contacted.
- Default tests use no real network, database, browser, external service, or out-of-scope filesystem write.
- Skill validation, offline tests, packaging tests, smoke tests, and preflight all pass with fresh evidence.
- Live verification, when authorized and technically available, returns and validates one current record per platform without modifying Feishu.
- The candidate remains side by side with the old runtime so rollback is immediate.
