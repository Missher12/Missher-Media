# Media@Missher reliability and Xiaohongshu safety

Approved direction: the user accepted the source audit recommendations and asked to prioritize Xiaohongshu because of platform risk. This document makes that accepted scope concrete; routine implementation continues without another approval round.

## Baseline and ownership

Git main is `9d70e1a3030b1534c464155df618e661b56a1f70`, runtime 15.2.1. This isolated worktree starts at `f87dd8858a0b888f03a7885a1641823af13457bd`, incorporating the already-tested 0.1.1 Bundle hardening. Its 30 packaged core files are byte-equal to main. No other worktree or operational profile is modified. Target versions: runtime 15.3.0 and Bundle 0.2.0. Publishing and real collection are outside this implementation run.

## Goal and behavior

Preserve useful, validated work through interruption; make Stop cover every owned worker; reduce unnecessary Xiaohongshu requests; provide explicit historical export and continuation without treating old records as fresh.

1. Stop/timeout propagates through the Node wrapper, Python adapter, runtime and owned descendants. The collection lease remains held until owned execution stops. Chrome is never a termination target.
2. Persist a valid manifest after every committed platform snapshot, with completed prefixes on partial failures. Unexpected interruption must not erase the discoverability of earlier committed results. Risk status wins over partial/success.
3. Duplicate-only pages may be crossed only when the server cursor advances and page/time budgets permit. Search comments and timeouts must reach runtime, or unsupported combinations fail explicitly.
4. Xiaohongshu retains exact note binding, one click/open per note, existing 5–15 second detail dwell, bounded comment scrolling, sequential browser ownership, and no automatic BrowserSkill use. Introduce a conservative batch ceiling, spacing between batches/pages, and a persistent risk latch. These are local conservative defaults, not a promise of platform approval or a guaranteed safe rate. Any detected challenge/403/429/risk stops the entire run. A risk latch has no automatic expiry or retry; explicit operator acknowledgement does not waive fresh preflight.
5. Historical queries and re-export work offline. A history catalog derives from private immutable run artifacts; it is not an alternate freshness validator. Export identifies source runs and observation timestamps.
6. Explicit continuation binds the prior run to the same local profile/request identity, accepts only non-risk prior evidence, creates a new run and skips previously accepted native IDs. Each batch is separately bounded and authorized. Existing content can be re-observed in an ordinary fresh collection; comparisons report metric changes with both observation times.

## Data and interfaces

Keep existing platform JSON and strict diagnostic manifest readable. Add a separate private `run-context.json` schema 1 for run ID, request/profile digest, product version, requested counts, parent run and timestamps; no credentials or raw profile values. One atomic `committed.json` schema 1 contains the strict manifest and declared JSON artifacts and is the commit point for platform snapshots; legacy files remain compatibility projections. The stopped controller restores only its current run's committed files before applying current-run freshness checks. `run-result.json` retains controller-detected risk as an additional authoritative stop. Historical APIs validate ownership, 0700/0600 permissions, file limits, no symlinks/path escapes, manifest paths/counts and native-ID uniqueness. Bound individual and cumulative accepted counts cannot exceed original positive targets. Old unbound runs remain exportable but cannot be resumed.

Add CLI history/export/compare and safety status/acknowledgement operations as standard-library commands. Add explicit continuation options to the shared adapter; new tool entrypoints use the same implementation when applicable. Model-facing results contain only fixed diagnostics, counts and private paths. No raw records, creator IDs or credentials enter tool responses.

## Acceptance

- Reproduce the previously observed process-tree cancellation, missing-manifest interruption, duplicate-page shortfall and dropped search arguments, then turn each into a regression that passes.
- Test risk before action and after waits, risk latch persistence across processes, no automatic reset, private-state corruption, batch spacing and no requests on blocked starts.
- Test interrupted prefixes for all platforms, prior-run immutability, profile mismatch, duplicate IDs, stale/unsafe files and separation of historical/current counts.
- Run the full sockets-disabled Python suite, Bundle tests/typecheck, exact payload/package checks and isolated native process/lifecycle smoke where available. Actual platform collection requires a separately specified target/count/navigation authorization and is not represented by fixtures.

## Implementation boundaries

Use existing controller, RunStore, adapters and platform parsers. Keep changes scoped to process lifecycle, run metadata/history, safety/budget policy and pagination/request wiring. Do not redesign all platform parsers or weaken target identity to improve counts. Do not install dependencies into the operational Python venv, manipulate browser profile/cookies, publish, or modify other projects.
