# Media@Missher DeepSeek Harness Plugin Design

**Date:** 2026-08-28

**Status:** Authorized by the user's explicit delegation to choose and complete the recommended design

**Source baseline:** Media@Missher `15.2.1` at commit `5e381dec905f0f4df23d09e48fe8f2c1e9313775`

## 1. Goal

Package the latest private Media@Missher runtime as a native DeepSeek Harness Cordis Bundle. After the Bundle is installed, a Harness agent can call one model-visible tool to collect creator records and receive a private Excel workbook. A call with no arguments collects ten records from each of Bilibili, Xiaohongshu, Douyin, and Weibo in one sequential run.

The plugin must preserve the existing browser, identity, risk, privacy, and no-Feishu controls. It must not copy the Codex plugin format, modify the Harness application repository, publish a public release, or invent a second collection implementation.

## 2. Product translation

### Target

Give DeepSeek Harness an independently installable Media@Missher Bundle that an agent can run directly.

### Functions

- Register a `media_missher_collect` Agent tool.
- Default to `bilibili,xhs,douyin,weibo`, ten records per platform, creator mode, sequential execution, BrowserSkill off, screenshots off, no Feishu, and exact-host navigation authorized by the explicit tool call.
- Permit a bounded platform subset, count from 1 through 50, optional XHS comment count, and an explicit navigation switch.
- Reuse the installed Media@Missher `15.2.1` runtime when it is exact and healthy.
- Carry an embedded source payload and atomically provision the same runtime on first use when the exact runtime is absent.
- Read creator identifiers only through the existing private mode-0600 Media@Missher profile; do not expose identifiers as model arguments or tool results.
- Return a structured status, total count, run directory, manifest path, workbook path, and a short per-platform summary.

### Data

The Python runtime remains authoritative for collection JSON and `manifest.json`. The Node plugin reads only the fresh run referenced by the controller summary, validates that every path stays inside that run directory, and projects the records into an XLSX workbook. Raw JSON remains private evidence and is never embedded in the Harness session result.

### Agent interface

```text
media_missher_collect({})
  -> four platforms x ten
  -> JSON evidence under the Harness Media state directory
  -> one XLSX workbook
  -> compact status and paths returned to the agent
```

### Acceptance

- `dsh plugin --profile web add <absolute-tgz>` installs a real Bundle and `--dump-config` contains both package and Bundle identifiers.
- The installed Bundle registers the Agent tool on the real Harness runtime.
- With no tool arguments, the process command selects all four platforms and count ten.
- A fixture run produces a workbook with `Summary`, `All Platforms`, `Bilibili`, `Xiaohongshu`, `Douyin`, and `Weibo` sheets.
- Package verification proves that the embedded runtime version is exactly `15.2.1`, no secrets or collected data are packaged, and generated JavaScript contains no local build path.
- A final authorized live invocation completes one sequential default run or stops truthfully at the first preflight/risk boundary without retry or bypass.

## 3. Alternatives

### A. Selected: native Bundle with a thin runtime adapter and embedded source payload

The Bundle registers one tool, delegates collection to the existing Python controller, and generates the workbook after validating the controller's private evidence. It reuses an exact installed runtime or performs the existing atomic runtime-only install on demand.

This is selected because it produces a real Harness plugin without forking collection logic, retains the current live-accepted runtime, and gives a new installation a bounded provisioning path.

### B. Bundle that only shells out to the current Codex installation

This is smaller, but it fails the one-click requirement on a machine where Media@Missher is not already installed. It also makes the Bundle version unrelated to the runtime version. It is rejected.

### C. Copy the Python collectors into TypeScript

This would create two platform implementations and double the identity, response-binding, risk, and maintenance burden. It is rejected.

### D. Modify DeepSeek Harness core or the Desktop app

Harness already exposes a native tool registry and Bundle patch format. A core modification would increase blast radius and make independent install/uninstall impossible. It is rejected.

## 4. Architecture

```text
Harness agent
    |
    | media_missher_collect
    v
Cordis tool plugin
    |-- normalize bounded arguments
    |-- ensure exact 15.2.1 runtime
    |-- spawn the existing controller with AbortSignal
    v
Media@Missher controller
    |-- private profile -> platform UIDs
    |-- live preflight and collection lease
    |-- sequential Bilibili/XHS/Douyin/Weibo
    |-- risk stop / no blind retry / no Feishu
    v
private run JSON + manifest
    |
    | validated same-run paths only
    v
XLSX projector
    |-- summary sheet
    |-- combined sheet
    |-- four platform sheets
    v
private workbook path returned to Harness
```

The Cordis package name is `dsh-media-missher`; the Bundle ID and plugin name are `media-missher`. State is rooted at `$DSH_HOME/media-missher`. The shared runtime defaults to `~/.local/share/media-missher` so Codex and Harness retain one runtime installation and its existing cross-process collection lease. The dedicated Chrome profile and CDP endpoint remain owned by Media@Missher.

## 5. Tool contract

The tool accepts only these model-facing fields:

- `platforms`: optional comma-separated subset in canonical order; default all four.
- `count`: optional integer 1 to 50; default 10 per selected platform.
- `xhs_comments`: optional integer 0 to 100; default 0.
- `allow_navigation`: optional boolean; default true because calling the collection tool is an explicit collection/navigation request. Setting false preserves fail-closed exact-page behavior.

The tool does not accept profile paths, runtime paths, UIDs, cookies, tokens, arbitrary URLs, browser-assist modes, screenshot modes, proxy settings, concurrency, retry counts, or output paths.

The canonical result contains only:

- `status`;
- selected platform string;
- requested count per platform;
- total accepted record count;
- private run directory;
- manifest path when present;
- workbook path when records are present;
- one bounded summary line.

Raw records and private identifiers stay in files. The UI uses a generic card with the output locations attached.

## 6. Runtime lifecycle

On each call, the plugin checks the shared runtime `current/VERSION`, executable venv Python, and controller payload version. If all are exact, it does not reinstall. If the runtime is missing or stale, the call runs the embedded `tools/install_media_missher.py --runtime-only` against the shared runtime home. The existing installer owns locking, private permissions, staging validation, atomic rotation, and rollback.

Provisioning occurs only inside an explicit tool call. Plugin load and Harness startup do not modify the runtime. A failed install leaves the prior current runtime in place and returns a tool error without collection.

The controller is spawned without a shell. The plugin passes a minimal environment override, captures bounded stdout/stderr, couples the foreground process to the Harness execution signal, and terminates the controller process group on cancellation. The controller retains the inner engine process-group risk monitor and timeout.

This first Bundle targets macOS, matching the current Media@Missher runtime and the user's Harness installation. Unsupported operating systems fail at the package/platform gate instead of making an unverified portability claim.

## 7. Workbook contract

Every workbook contains:

1. `Summary`: platform, requested count, collected count, platform status, diagnostic kind, diagnostic code, run status, and generation time.
2. `All Platforms`: all accepted records with a leading platform column.
3. `Bilibili`, `Xiaohongshu`, `Douyin`, and `Weibo`: one platform per sheet, including an empty header-only sheet when that platform was selected but returned no records.

Columns follow first-seen JSON key order. Nested objects and arrays are compact JSON strings. Identifier-like fields are written as text. Strings beginning with Excel formula prefixes are escaped. The workbook directory is mode 0700 and the file is mode 0600. Writing uses a temporary file followed by atomic rename.

## 8. Safety and privacy

- Keep one Media collection lease and sequential platform execution.
- Keep BrowserSkill off and screenshots off for the default path.
- Use only the existing CDP endpoint and signed-in browser profile.
- Stop on platform risk, verification, preflight, timeout, or exact-identity failure; do not retry automatically.
- Never generate Feishu artifacts.
- Never package the private profile, browser state, cookies, credentials, collected JSON, screenshots, logs, existing runtime state, or prior workbooks.
- Do not include UID values in the tool schema or returned value.
- Validate real paths and reject evidence that escapes the controller run directory or uses symlinks.
- Preserve existing adjacent Harness profile bundles and Media runtime state during install/uninstall.

## 9. Installation and release boundary

The deliverable is one local canonical `.tgz` plus its SHA-256 file and an installation helper that calls the real Desktop-bundled `dsh` CLI for the `web` profile. The CLI remains authoritative for transactional dependency and Bundle composition.

The repository README states that no public-distribution license has been selected. Therefore this task may build, install, test, and locally commit the private Bundle, but it must not push, tag, create a public GitHub Release, publish to npm, or add the plugin to a public marketplace.

## 10. Verification layers

### Offline

- Unit tests for default arguments, platform/count bounds, runtime exact-version decisions, cancellation, controller-summary parsing, same-run path validation, workbook structure, formula escaping, manifest identity, and package whitelist.
- TypeScript build, package verification, Python source suite, payload privacy scan, and `git diff --check`.

### Live preflight

- Exact runtime version and package payload match.
- Current private profile exists, is mode 0600, and has all four configured platform keys without printing values.
- CDP is reachable and current Media preflight is `ok`.

### Real operation

- Install into the real `web` profile through the bundled `dsh` CLI.
- Verify `--dump-config` contains `dsh-media-missher` and `media-missher` while preserving existing bundles.
- Invoke the installed tool contract against the real runtime with no arguments.
- Require four platform counts of ten, manifest diagnostics `ok/ok`, workbook archive validity, private permissions, and no Feishu/symlink artifacts for a success claim.
- If risk or preflight stops, preserve its evidence and report that exact boundary without retrying.

