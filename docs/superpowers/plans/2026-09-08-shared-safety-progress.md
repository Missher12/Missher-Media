# Shared Safety and Progress Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans to implement this plan task-by-task. Stay in the owned existing worktree and preserve its earlier uncommitted changes. No publication or formal installation.

**Goal:** Deliver private runtime 15.5.0 / Bundle 0.5.0 with shared protection, consistent preflight and bounded progress evidence.

**Architecture:** User-scoped coordination is independent of runtime/CDP identity and retains legacy locks. A validated inherited descriptor holds the same lock across adapter and child; the XHS guard migrates state conservatively. Fixed progress events travel separately from the final controller JSON.

**Tech Stack:** Python 3.11/3.12, fcntl, existing Playwright runtime, TypeScript, existing Harness ToolDefinition/ExcelJS.

---

### 1. Shared protection (root)

- [x] Add failing `tests/test_shared_safety.py`: two homes contend; a subprocess accepts only a verified held descriptor; non-inherited entry contends; risk/max time migrate and acknowledge stays idempotent; links/corruption fail closed.
- [x] Run `python -m pytest tests/test_shared_safety.py -q` and observe missing module/behavior failures.
- [x] Create `runtime/media_missher_runtime/shared_safety.py`; modify `xhs_policy.py`, runtime `cli.main`, adapter `_collection_lease` and `execute_engine` descriptor transport. Lock ordering is installation lease → shared collection lease → local collection lease → shared XHS state → legacy state; no automatic waiting/retry.
- [x] Re-run targeted shared/XHS/runner/lifecycle tests, fixing behavioral regressions only.

### 2. One runtime-version gate (root)

- [x] Add version mismatch regression proving both preflight and collection reject before subprocess/CDP.
- [x] Extract `runtime_version_check(layout)` with bounded regular-file/owner/link/mode validation and a sanitized version result. Call it before probes and before creating output. Preserve lease validation.
- [x] Run preflight/runner/security checks; update active source, fixtures, installer and package constants to 15.5.0 / 0.5.0, leaving historical evidence and archives immutable.

### 3. Structured progress (bounded implementation agent)

- [x] Read actual SDK types; do not invent a live tool callback. Add failing tests for fragmented/oversize/unknown payloads and final JSON compatibility.
- [x] Add a small fixed-schema progress module, instrument browser/login/collection/validation/export boundaries with monotonic timings, carry only safe events through stderr and preserve final stdout JSON.
- [x] Make Bundle process progress optional and bounded; expose local progress inspection or existing supported host mechanism plus durable per-run timings. No platform pacing or collector-budget changes.
- [x] Run affected Python/Bundle tests and report ownership and evidence. Root reviews spec then quality before integration acceptance.

### 4. Validation and delivery (root)

- [x] Run `python -m pytest -q`, `pnpm exec tsc --noEmit`, `pnpm test`; record actual outputs and distinguish any synthetic fixtures.
- [x] Build and verify new tgz/Setup; normal isolated installation + Harness native smoke, without a second platform batch. Match package payload bytes to implementation and independently hash artifacts.
- [x] Add 15.5.0 usage/evidence documentation and prepend current PROJECT_CONTEXT/HANDOVER; preserve historical hashes. Send a completion report to `01a07766-9fe2-7da1-9809-7437205e41c5` and provide the user the reviewed local installer.

Validation checkpoints replace unnecessary approval pauses. No git commit of mixed prior work is assumed; the reviewed candidate remains in the existing owned branch unless separately authorized.
