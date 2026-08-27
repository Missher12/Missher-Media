# Media@Missher DeepSeek Harness Plugin Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a private, native DeepSeek Harness Bundle that exposes the latest Media@Missher runtime as one Agent tool whose zero-argument behavior collects four platforms times ten and produces a private XLSX workbook.

**Architecture:** A TypeScript Cordis tool delegates to the existing Python controller and never duplicates platform collectors. The package embeds the exact 15.2.1 runtime source for atomic first-use provisioning, validates fresh same-run JSON, and uses ExcelJS to create a summary plus per-platform workbook. A canonical tgz is installed through the real Desktop-bundled `dsh` CLI and verified without publishing.

**Tech Stack:** TypeScript ESM, Cordis 4, `@deepseek-ai/dsh-tools`, Node 22+, ExcelJS, tsdown, Vitest, Python 3.11+, existing Playwright/CDP Media@Missher runtime, pnpm 11.

---

## Governing specification

Implement only `docs/superpowers/specs/2026-08-28-deepseek-harness-media-missher-plugin-design.md`. Preserve the Media@Missher 15.2.1 browser and validation behavior. Do not alter platform collectors to satisfy plugin tests.

## File map

- Create `harness-plugin/package.json`: standalone package identity, dependencies, build/test/pack scripts, package whitelist, macOS boundary.
- Create `harness-plugin/cordis.patch.yml`: insert Bundle ID `media-missher` with bounded defaults.
- Create `harness-plugin/tsconfig.json`, `harness-plugin/tsdown.config.ts`, and `harness-plugin/vitest.config.ts`: strict ESM build and source tests.
- Create `harness-plugin/src/config.ts`: platform constants and validated plugin/tool defaults.
- Create `harness-plugin/src/process.ts`: bounded no-shell child process execution coupled to AbortSignal.
- Create `harness-plugin/src/runtime.ts`: exact runtime resolution, optional atomic provisioning, controller invocation, JSON summary parsing, and fresh evidence loading.
- Create `harness-plugin/src/workbook.ts`: private atomic XLSX generation.
- Create `harness-plugin/src/index.ts`: Cordis plugin and `media_missher_collect` registration.
- Create `harness-plugin/scripts/stage-payload.mjs`: copy only the exact source payload required by the private package.
- Create `harness-plugin/scripts/verify-package.mjs`: inspect tgz identity, whitelist, embedded version, secret/residual absence, and built-path leakage.
- Create `harness-plugin/scripts/native-smoke.mjs`: real CLI add, config dump, runtime mount/tool execution with fixtures, remove, and adjacent-data preservation in an isolated DSH home.
- Create `harness-plugin/scripts/install-current-profile.mjs`: install one verified archive through the Desktop-bundled CLI after backing up the current profile manifest.
- Create `harness-plugin/tests/*.spec.ts` and `harness-plugin/tests/fixtures/run/**`: TDD coverage and synthetic evidence.
- Modify `.gitignore`: ignore generated plugin build, payload, work, and dist directories.
- Modify `README.md` and `PROJECT_CONTEXT.md`: private Bundle usage, default 4x10 workbook behavior, dated verification, and public-release boundary.

### Task 1: Scaffold and lock the Bundle identity

**Files:**
- Create: `harness-plugin/package.json`
- Create: `harness-plugin/cordis.patch.yml`
- Create: `harness-plugin/tsconfig.json`
- Create: `harness-plugin/tsdown.config.ts`
- Create: `harness-plugin/vitest.config.ts`
- Test: `harness-plugin/tests/manifest.spec.ts`

- [ ] **Step 1: Write the failing manifest test**

The test reads `package.json` and `cordis.patch.yml`, then asserts package `dsh-media-missher`, version `0.1.0`, `dsh.bundle.patch`, macOS-only installation, `UNLICENSED`, and one patch entry with ID `media-missher` and the four-platform/count-ten defaults.

- [ ] **Step 2: Run RED**

Run `pnpm --dir harness-plugin exec vitest run tests/manifest.spec.ts`. Expected: FAIL because the standalone plugin files do not exist.

- [ ] **Step 3: Add the minimal package and build configuration**

Use Cordis `4.0.1`, DSH tools `0.1.1-rc.2`, ExcelJS `4.4.0`, tsdown `0.22.2`, TypeScript `6.0.3`, and Vitest `4.1.8`. Export `lib/index.js`, `cordis.patch.yml`, and the staged `payload/`. Do not add a client plugin.

- [ ] **Step 4: Install dependencies and run GREEN**

Run `pnpm --dir harness-plugin install --frozen-lockfile=false` and the focused manifest test. Expected: one passing test.

- [ ] **Step 5: Commit the scaffold**

Run `git add harness-plugin/package.json harness-plugin/pnpm-lock.yaml harness-plugin/cordis.patch.yml harness-plugin/tsconfig.json harness-plugin/tsdown.config.ts harness-plugin/vitest.config.ts harness-plugin/tests/manifest.spec.ts && git commit -m "feat: scaffold Media Harness bundle"`.

### Task 2: Define safe defaults and process execution

**Files:**
- Create: `harness-plugin/src/config.ts`
- Create: `harness-plugin/src/process.ts`
- Test: `harness-plugin/tests/config.spec.ts`
- Test: `harness-plugin/tests/process.spec.ts`

- [ ] **Step 1: Write RED configuration tests**

Assert that an empty tool request resolves to platforms `bilibili,xhs,douyin,weibo`, count `10`, XHS comments `0`, and navigation true. Assert duplicate/unknown platforms, count outside 1..50, comments outside 0..100, non-integers, unsafe profile paths, and non-positive timeouts fail with stable error codes.

- [ ] **Step 2: Run the configuration tests and verify RED**

Run `pnpm --dir harness-plugin exec vitest run tests/config.spec.ts`. Expected: module-not-found failure for `src/config.ts`.

- [ ] **Step 3: Implement normalized config and tool arguments**

Export `PLATFORMS`, `normalizePluginConfig(input, dshHome)`, and `normalizeCollectArgs(input)`. Resolve the default profile to `~/.config/media-missher/profile.json`, runtime to `~/.local/share/media-missher`, and output to `$DSH_HOME/media-missher/runs`; require absolute configured paths and reject symlinks later at I/O time.

- [ ] **Step 4: Run configuration GREEN**

Run the focused test. Expected: all configuration cases pass.

- [ ] **Step 5: Write RED process tests**

Use a fixture Node child to assert exact argv preservation without a shell, bounded stdout/stderr, non-zero exit reporting, timeout termination, and AbortSignal termination. The child must never interpolate shell metacharacters.

- [ ] **Step 6: Implement `runProcess`**

Spawn with `shell: false`, `detached: true` on POSIX, cap each output stream at 1 MiB, and kill the process group on abort/timeout. Return `{ code, signal, stdout, stderr }` only after both streams close.

- [ ] **Step 7: Run process GREEN and commit**

Run `pnpm --dir harness-plugin exec vitest run tests/config.spec.ts tests/process.spec.ts`, then commit the four files with `git commit -m "feat: add bounded Media process adapter"`.

### Task 3: Stage and verify the exact Media runtime payload

**Files:**
- Create: `harness-plugin/scripts/stage-payload.mjs`
- Create: `harness-plugin/scripts/verify-package.mjs`
- Test: `harness-plugin/tests/payload.spec.ts`
- Modify: `.gitignore`

- [ ] **Step 1: Write the RED payload test**

The test runs the stage script into a temporary directory and requires exactly `VERSION`, `runtime/**`, `media-missher/scripts/**`, `tools/install_media_missher.py`, and `tools/scan_active_residuals.py`. It rejects symlinks, private profiles, JSON evidence, PNGs, logs, credentials, caches, and a version other than `15.2.1`.

- [ ] **Step 2: Run RED**

Run `pnpm --dir harness-plugin exec vitest run tests/payload.spec.ts`. Expected: missing stage script.

- [ ] **Step 3: Implement payload staging and ignore generated outputs**

Use `fs.cp` with an explicit allowlist, remove the destination before copying, verify every copied item is a regular file/directory, and write no generated content into Git. Ignore `harness-plugin/lib`, `payload`, `node_modules`, `.work`, and `dist`.

- [ ] **Step 4: Implement archive verification**

Extract the requested tgz into a temporary directory, verify package identity, Bundle patch, package file allowlist, payload version, absence of secret/residual names, executable entry, and no absolute checkout path in built JavaScript. Print only archive path, byte count, and SHA-256.

- [ ] **Step 5: Run payload GREEN and commit**

Run the focused payload test and `node harness-plugin/scripts/stage-payload.mjs`. Commit scripts, test, and `.gitignore` with `git commit -m "build: stage exact Media runtime payload"`.

### Task 4: Bridge the controller and validate private evidence

**Files:**
- Create: `harness-plugin/src/runtime.ts`
- Test: `harness-plugin/tests/runtime.spec.ts`
- Test fixture: `harness-plugin/tests/fixtures/run/**`

- [ ] **Step 1: Write RED runtime-decision tests**

Assert that exact `current/VERSION` plus executable `venv/bin/python` skips installation; missing/stale/bad version selects the embedded installer; provisioning invokes `--source <payload> --home <runtime> --runtime-only`; unsupported platforms fail before mutation.

- [ ] **Step 2: Run decision RED**

Run `pnpm --dir harness-plugin exec vitest run tests/runtime.spec.ts -t "runtime"`. Expected: missing runtime module.

- [ ] **Step 3: Implement exact-version resolution and provisioning**

Resolve all paths, reject symlinked runtime/profile/payload components, require profile mode 0600 on POSIX, use the existing installer for mutation, and recheck the exact version/executable after install. Never run provisioning at plugin load.

- [ ] **Step 4: Write RED controller-command tests**

Assert the empty request invokes the controller with `--platform bilibili,xhs,douyin,weibo --count 10 --xhs-comments 0 --allow-navigation --no-feishu --json-summary`, the private profile and output root, BrowserSkill off, screenshots off, and no UID values in argv or environment.

- [ ] **Step 5: Implement controller invocation and summary parsing**

Run the controller with the runtime venv Python and `MEDIA_MISSHER_HOME`. Parse one JSON object from stdout, accept documented status values, and retain only bounded safe fields. A non-zero wrapper exit still parses the truthful summary before deciding whether records can be exported.

- [ ] **Step 6: Write RED evidence-path tests**

Cover a fresh fixture manifest and four JSON files, absent platform output, symlink evidence, `..` escape, absolute manifest entry, duplicate paths, malformed JSON, mismatched counts, and an unrelated old run.

- [ ] **Step 7: Implement same-run evidence loading**

Resolve the controller `run_dir`, require it below the configured output root, read only `manifest.json` and platform basenames declared there, reject symlinks and escapes, and return platform records/status/diagnostics without private profile data.

- [ ] **Step 8: Run runtime GREEN and commit**

Run `pnpm --dir harness-plugin exec vitest run tests/runtime.spec.ts`. Commit runtime source, tests, and fixtures with `git commit -m "feat: bridge Media runtime into Harness"`.

### Task 5: Generate the default inspection workbook

**Files:**
- Create: `harness-plugin/src/workbook.ts`
- Test: `harness-plugin/tests/workbook.spec.ts`

- [ ] **Step 1: Write workbook RED tests**

Generate from the four-platform fixture and reopen the file with ExcelJS. Require six sheet names, four summary rows, forty fixture detail rows when the fixture requests ten each, a forty-row combined sheet, frozen/filter headers, identifier text cells, JSON rendering for nested values, formula-prefix escaping, output directory mode 0700, file mode 0600, and no surviving temporary file.

- [ ] **Step 2: Run RED**

Run `pnpm --dir harness-plugin exec vitest run tests/workbook.spec.ts`. Expected: missing workbook module.

- [ ] **Step 3: Implement the minimal private XLSX projector**

Use ExcelJS; derive first-seen columns, flatten nested values to compact JSON, stringify identifier-like keys, escape `=`, `+`, `-`, and `@`, style only headers/status rows, write to a unique private temporary path, rename atomically, and chmod the final path.

- [ ] **Step 4: Run workbook GREEN and commit**

Run the focused test and commit with `git commit -m "feat: export Media collection workbook"`.

### Task 6: Register the Agent tool

**Files:**
- Create: `harness-plugin/src/index.ts`
- Test: `harness-plugin/tests/plugin.spec.ts`

- [ ] **Step 1: Write plugin RED tests**

Mount the plugin in a Cordis context with a real `ToolRuntime`, assert registration/disposal of `media_missher_collect`, execute it through the tool registry against fixture controller/runtime adapters, and assert default 4x10 arguments, canonical return fields, generic call/result locations, and AbortSignal forwarding.

- [ ] **Step 2: Run RED**

Run `pnpm --dir harness-plugin exec vitest run tests/plugin.spec.ts`. Expected: missing entry module/tool.

- [ ] **Step 3: Implement the Cordis entry**

Export `name = "media-missher"`, `inject = ["tools", "dshHomePath"]`, `apply(ctx, config)`, and the default plugin object. Register a `defineTool` with optional `platforms`, `count`, `xhs_comments`, and `allow_navigation`; return only status, paths, total, and bounded summary. Set a foreground timeout slightly above the configured controller timeout and honor `exec.signal`.

- [ ] **Step 4: Run plugin GREEN and the complete plugin suite**

Run `pnpm --dir harness-plugin test`. Expected: all plugin tests pass with no warning/error output.

- [ ] **Step 5: Commit the Agent surface**

Commit entry and tests with `git commit -m "feat: expose Media collection Agent tool"`.

### Task 7: Package, install, and run native acceptance

**Files:**
- Create: `harness-plugin/scripts/native-smoke.mjs`
- Create: `harness-plugin/scripts/install-current-profile.mjs`
- Create: `harness-plugin/README.md`
- Modify: `README.md`
- Modify: `PROJECT_CONTEXT.md`
- Test: `harness-plugin/tests/native-smoke.spec.ts`

- [ ] **Step 1: Write native smoke RED**

Against a temporary `DSH_HOME`, require real CLI `plugin add`, config dump identity, installed entry import, fixture tool execution/workbook creation, `plugin remove`, preserved adjacent profile data, and preserved Media state. Expected failure: smoke/install scripts are absent.

- [ ] **Step 2: Implement native smoke and current-profile installer**

Resolve the Desktop CLI at `/Applications/DeepSeek Harness.app/Contents/Resources/app.asar.unpacked/node_modules/@deepseek-ai/dsh/lib/bin.js`, use `process.execPath`, never invoke a shell, back up only `~/.dsh/profiles/web/package.json`, verify the archive before add, and restore the backup only if add fails. The isolated smoke removes its temporary home; the current-profile installer never removes unrelated bundles.

- [ ] **Step 3: Add operator documentation**

Document the zero-argument 4x10 default, first-use runtime provisioning, login/profile prerequisite, install/remove commands, state/output locations, risk-stop behavior, macOS scope, and private/no-public-release boundary.

- [ ] **Step 4: Run complete offline verification**

Run:

```bash
pnpm --dir harness-plugin test
pnpm --dir harness-plugin run build
pnpm --dir harness-plugin run pack
node harness-plugin/scripts/verify-package.mjs harness-plugin/dist/dsh-media-missher-0.1.0.tgz
PYTHONDONTWRITEBYTECODE=1 python -m pytest -q -p no:cacheprovider --disable-socket --allow-unix-socket
git diff --check
```

Require zero failures and record exact counts, archive bytes, and SHA-256.

- [ ] **Step 5: Run isolated native CLI lifecycle smoke**

Run `node harness-plugin/scripts/native-smoke.mjs --cli /Applications/DeepSeek\ Harness.app/Contents/Resources/app.asar.unpacked/node_modules/@deepseek-ai/dsh/lib/bin.js --archive <absolute-tgz>`. Require install, Bundle composition, fixture tool output, workbook reopen, uninstall, adjacent-data preservation, and state preservation.

- [ ] **Step 6: Install the verified archive into the real web profile**

Run `node harness-plugin/scripts/install-current-profile.mjs --archive <absolute-tgz> --profile web`, then run the real CLI `--profile web --dump-config`. Require existing bundles plus `dsh-media-missher`/`media-missher` and no credential output.

- [ ] **Step 7: Run live preflight and one zero-argument acceptance**

Check profile mode and platform-key count without values, execute the current Media live preflight, then invoke the installed tool contract once with `{}`. Do not retry a risk/preflight stop. On success, independently validate four counts of ten, `ok/ok` diagnostics, XLSX archive readability, mode 0600/0700, and no Feishu/symlink artifacts.

- [ ] **Step 8: Update context and commit the delivery**

Record dated evidence and limitations in `PROJECT_CONTEXT.md`, update README, add the verified checksum file, and commit with `git commit -m "docs: deliver private Media Harness plugin"`. Do not push, tag, release, publish, or modify Harness source.

## Self-review

- The plan covers the native Bundle identity, Agent tool, exact latest runtime, zero-argument 4x10 default, table output, private state, real CLI installation, offline verification, preflight, and real-operation acceptance.
- It contains no deferred feature or placeholder.
- `platforms`, `count`, `xhs_comments`, `allow_navigation`, `status`, `runDirectory`, `manifestPath`, and `workbookPath` retain the same names across config, runtime, workbook, and tool tasks.
- The plugin remains a thin adapter; platform code, browser ownership, risk logic, and output truth stay in the existing runtime.
