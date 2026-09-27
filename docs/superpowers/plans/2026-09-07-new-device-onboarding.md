# Media New Device Onboarding Implementation Plan

> **For agentic workers:** Use superpowers:subagent-driven-development for the bounded parser task and separate specification/quality review. The root owns orchestration and integration. Never run multiple implementation subagents at once.

**Goal:** Let a blank device import and select creators before any runtime installation, browser action or collection.

**Architecture:** Reuse ExcelJS in the macOS Bundle for offline CSV/XLSX handling. A private setup service writes versioned immutable imports and activates selected rows into the existing profile contract. Collection checks target readiness before ensureRuntime. Preserve the 15.3.0 candidate artifacts and ship a new 15.4.0 / 0.3.0 candidate.

**Tech Stack:** TypeScript, Node, ExcelJS, Vitest; existing standard-library Python controller.

## Task 1: Offline creator list parser and templates

Files: create harness-plugin/src/creator-list.ts and harness-plugin/tests/creator-list.spec.ts. Independent implementer owns only these files.

```ts
export interface Creator { platform: Platform; name: string; homepage: string; nativeId: string }
export async function parseCreatorList(bytes: Buffer, format: 'csv' | 'xlsx'): Promise<Creator[]>
export async function buildCreatorTemplates(): Promise<{ csv: Buffer; xlsx: Buffer }>
```

- [x] RED: valid Chinese CSV and Excel input yields the same typed rows; name-only, duplicate native IDs, wrong hosts, short links, formulas and oversized documents throw fixed codes.
- [x] Implement strict offline URL normalization and bounded CSV/ZIP/XLSX parsing; queries and fragments are discarded, never fetched.
- [x] Generate genuinely empty editable templates plus instructions; template-only import rejects zero creators.
- [x] Run `pnpm exec vitest run tests/creator-list.spec.ts`: 154 passed. Spec review passed; quality findings fixed. Final independent follow-up was automatically blocked and returned no verdict; root source review is recorded separately.

## Task 2: Private setup workflow and collection gate

Files: create harness-plugin/src/setup.ts, harness-plugin/src/private-config.ts and harness-plugin/tests/setup.spec.ts; modify harness-plugin/src/{index,config,runtime}.ts and their tests.

```ts
const missing = await inspectTargets(config.profilePath, requestedPlatforms)
if (missing.length > 0) return needsSetupValue(missing)
// Only after target validation: ensureRuntime -> controller -> evidence.
```

- [x] RED: blank/missing profile collection produces needs-setup without ensureRuntime/processRunner/output work; subset profile defaults to configured subset.
- [x] Use bounded no-follow private JSON helpers, immutable import IDs and atomic activation with exact prior-profile backup. Select at most one row per platform.
- [x] Register `media_missher_setup` status/template/import/activate actions; fixed model summaries and local artifact paths; no direct credential or native UID tool arguments.
- [x] Preserve existing CDP connection only in this candidate. A separately requested manual-browser entry can be a future increment; import/activate/collect never start Chrome implicitly.
- [x] Verify empty-device workflow without Python or network and preserve old profile/adjacent files.

## Task 3: Version, package, delivery

Files: VERSION, Bundle manifest/scripts/tests, skill docs, README, PROJECT_CONTEXT.md, HANDOVER.md and new onboarding evidence file.

- [x] Bump only active product/Bundle version references to 15.4.0/0.3.0; retain old 0.2.0 assets and evidence.
- [x] Test new-device flow through the installed Bundle in isolated DSH_HOME, with synthetic files and no actual Chrome/platform requests.
- [x] Run TypeScript, complete Bundle/Python suites, exact payload/Setup validation; fix reported review findings. Final results: 244 Bundle, 1066 Python, 35 payload and two library files matched, installed smoke passed.
- [ ] Obtain the final independent source-review verdict before formal installation/release. The follow-up was blocked by automated tool content review; no approval is inferred.
- [x] Prepare template/installer links, historical data links, real CDP behavior and clear real-platform limits for local candidate delivery. Keep main, installed runtime, formal profiles, LaunchAgents and Git remotes unchanged.
