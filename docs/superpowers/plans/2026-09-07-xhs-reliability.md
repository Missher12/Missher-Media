# Media@Missher Reliability Implementation Plan

> **For agentic workers:** Use superpowers:subagent-driven-development for bounded independent tasks and execute integration in this task. Steps use checkboxes for progress. The user has already authorized implementation.

**Goal:** Deliver the approved reliability upgrade with priority on conservative Xiaohongshu operation.

**Architecture:** Reuse the shared Python controller and atomic RunStore. Add private safety/history modules at their owning boundaries and keep the Harness Bundle a projection/entry layer. Existing JSON contracts are preserved or explicitly versioned.

**Tech Stack:** Python 3.11+, standard library, Playwright 1.45.0, TypeScript, Vitest, ExcelJS.

## Task 1: Owned process shutdown

Files: `media-missher/scripts/media_missher_adapter.py`, focused new process helper if needed, `tests/test_runner.py` or a focused process test.

- [x] Add a subprocess regression: the real adapter launches a fake looping runtime with `start_new_session=True`; terminate the adapter and assert the runtime stops and the collection lock is unavailable until cleanup.
- [x] Run the regression with the existing code and observe the surviving runtime failure.
- [x] Add bounded signal forwarding/cleanup for only the owned process group, preserving previous signal handlers and normal return contracts.
- [x] Cover parent SIGTERM, SIGINT, timeout, ignored SIGTERM and adjacent-process preservation; run relevant tests.
- [x] Review specification and implementation before integration; retain an uncommitted reviewable diff.

## Task 2: Durable results and parameter/pagination contracts

Files: `runtime/media_missher_runtime/{cli,storage,models}.py`, platform collectors, adapter request builder, focused runtime/CLI tests.

- [x] Add RED cases for a completed first platform followed by cancellation; duplicate advancing pages; search comments 7 and timeout 45 reaching the runtime request.
- [x] Write the manifest as each accepted snapshot is committed; preserve final strict status semantics and existing risk handling.
- [x] Publish accepted platform prefixes, retain them on non-risk failures, and keep risk-stopped as the final authoritative status.
- [x] Forward supported search arguments; reject unsupported comments instead of silently ignoring them.
- [x] Cross duplicate pages only with advancing cursors and a bounded budget; verify count, risk and cursor regressions.

## Task 3: Xiaohongshu conservative safety policy

Files: new private safety helper, `media_missher_adapter.py`, `runtime/media_missher_runtime/platforms/xhs.py`, focused policy tests.

- [x] Add failing tests for blocked starts doing zero browser work, persisted risk latch, strict state validation, bounded batches and wait/risk ordering.
- [x] Keep 5–15 second complete-detail dwell; cap one batch at 10 notes and three creator pages, with bounded spacing before additional pages.
- [x] Enforce at least 10 minutes between Xiaohongshu batch starts, under the existing collection lease. Latch risk until explicit local acknowledgement; do not automatically retry or clear state.
- [x] Expose structured safety status and explicit acknowledgement; a new collection still runs fresh preflight and requires its navigation authorization.
- [x] Verify existing detail binding, comment budgets, screenshots and cancellation tests remain valid.

## Task 4: History and continuation

Files: new standard-library history module/CLI, adapter entrypoints, runtime request/collector exclusion support, focused history tests.

- [x] Test history listing and re-export of exact private runs with no network; reject unsafe paths, malformed schema, wrong permissions and mismatched identities.
- [x] Persist `run-context.json` with schema/version/request digest and requested counts; keep raw profile/credentials out.
- [x] Implement explicit export and two-run comparison preserving observation timestamps, native IDs and prior files.
- [x] Implement continuation from an exact bound non-risk run, with new unique run, skipped accepted IDs and separate historical/new counts. Apply the same Xiaohongshu batch spacing and latch.
- [x] Test context mismatch, chained parents, incomplete older runs, no automatic collection, and immutable source hashes.

## Task 5: Integration and acceptance

Files: manifests/version references, source and Bundle docs, tests and packaging scripts, `PROJECT_CONTEXT.md`, `HANDOVER.md`.

- [x] Update versions and package/Setup/CI references consistently; include new runtime modules in exact payload allowlists.
- [x] Run focused checks after every phase, then the complete suite:

```bash
PYTHONDONTWRITEBYTECODE=1 uv run --offline --no-project --with pytest --with pytest-asyncio --with pytest-socket --with-requirements runtime/requirements.lock python -m pytest -q -p no:cacheprovider --disable-socket --allow-unix-socket
```

- [x] Run Bundle tests, TypeScript, package/Setup verification and suitable isolated smoke. Record failures and resolve them before completion claims.
- [x] Request independent specification and code-quality review of the final diff; resolve actionable findings.
- [x] Update project context/handover with exact files, test evidence, artifact hashes and explicit live limitations. Leave main, installed runtime/profile, Git remotes and releases unchanged.

Final acceptance: runtime 15.3.0 / Bundle 0.2.0; 1059 Python + 65 Bundle tests passed, isolated Harness 0.5.5 smoke passed, source/payload bytes equal. Full evidence and retained limitations are in HANDOVER.md and dist/RELIABILITY-EVIDENCE.json. No live platform requests, operational installation, commit, push or release.
