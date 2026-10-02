# Configure the shared runtime

This reference defines the shared runtime layout, configuration precedence, private profile, browser backend selection, collection envelope, and creator target requirements.

## Resolve the runtime home

The repository `VERSION` file is the authoritative product version. Media@Missher V17.0.2 uses `17.0.2`; its controller rejects an older installed core before live preflight. The installer reports this product version separately from its unique UTC timestamp-and-random-suffix deployment release. Do not replace the unique deployment release with a fixed product version because upgrades and recovery paths depend on release uniqueness.

`MEDIA_MISSHER_HOME` selects the shared runtime home. When it is unset, the runtime and installed skills use `~/.local/share/media-missher`. OpenClaw is retired on the current machine; its source package and dual-skill installer mode remain only for backward compatibility with historical environments.

The home contains these paths:

- `current/`: deployed source, product `VERSION`, and five entrypoints
- `venv/`: Python 3.11 or 3.12 dependency environment (required by the pinned dependencies)
- `state/`: mode-`0700` locks, checkpoints, cache, reports, and default `runs/`

The runtime installer writes mode-`0600` `.media-missher-owner.json` and `.media-missher-release` markers. With the recommended `--codex-only` mode, the release value must match across `current/`, `venv/`, and the Codex skill; the backward-compatible default additionally requires the OpenClaw skill to match. Installation holds `.media-missher-install.lock`; launchers take a shared lock before using a release. Adapter collections additionally hold the mode-`0600` `.media-missher-collection.lock` exclusively through collection and evidence validation, so the dedicated browser profile cannot be collected concurrently.

Preflight rejects missing or inconsistent markers, symlinked path components, a non-private state directory, an unwritable state directory, missing dependencies, broken entrypoints, and a timed-out install lock.

## Apply configuration precedence

For runtime paths and connection settings, command-line values override environment values, which override the private profile. For plan-bound collection options, an explicit CLI option overrides the current private plan, then profile/default values apply only when the plan omits the option. Explicit `0` and `off` are values, not omissions.

Supported environment variables are:

- `MEDIA_MISSHER_HOME`: shared runtime home
- `MEDIA_MISSHER_DATA_ROOT`: parent for unique private run directories
- `MEDIA_MISSHER_CDP_URL`: existing CDP endpoint, default `http://127.0.0.1:9222`, used by the `cdp` backend
- `MEDIA_MISSHER_PROFILE_CONFIG`: private profile path

Do not place credentials, browser storage, cookies, or personal absolute paths in the installable skill.

## Create a private profile

Store the profile outside the repository and installed skills. Apply exact mode `0600` before using it:

```bash
chmod 600 "$PROFILE_PATH"
```

Use this structure with your own creator identifiers:

```json
{
  "data_root": "~/.local/share/media-missher/state/runs",
  "cdp_url": "http://127.0.0.1:9222",
  "backend": "cdp",
  "platform_uids": {
    "bilibili": "configured_bilibili_id",
    "xhs": "configured_xhs_id",
    "douyin": "configured_douyin_id",
    "weibo": "configured_weibo_id"
  }
}
```

`platform_uids` remains the four-platform shorthand used by the adapter. An X target is not a numeric UID: supply its handle as a plan target `handle`, or pass `--x-uid HANDLE` on the runtime controller.

The optional `backend` field accepts only `cdp`. Omit it for the same default. Retired preferences are refused; an explicitly selected `--backend cdp` can override them for a new request without rewriting the saved profile.

Creator mode requires a non-empty `platform_uids` value for every selected platform. A command-line `--<platform>-uid` value overrides its profile value. Search mode needs a keyword and does not require a creator UID.

The adapter rejects a profile inside the repository or installed skill. It also rejects permissions other than `0600`, unknown platforms, empty targets, negative or fractional counts, and negative or non-finite timeouts.

The profile must not contain Feishu credentials. Media@Missher never performs a remote Feishu write.

## Chrome CDP only

Chrome CDP is the only active backend. Omit `--backend` or use `--backend cdp`; it attaches through Playwright/CDP to the existing signed-in Chrome endpoint and works independently of the Agent host or DSH.

The backend stays `cdp` in the plan, manifest and export provenance. Explicit CLI values override the private plan, then the profile; omitted values preserve the plan, including explicit `0` and `off`. An old non-CDP preference or plan is refused before collection, never silently rewritten. There is no `auto` or alternate backend.

Computer Use and its lifecycle command are removed. Old requests return `backend-retired-computer-use`; BrowserSkill requests return `backend-retired-browserskill`. Historical runs remain readable and exportable with their original provenance, but cannot resume a retired backend. Never install or invoke an alternative browser controller to work around a failure.

## Configure screenshots

`--browser-assist` defaults to `off` and must remain off. The retired `browserskill` bridge returns `browser-assist-replaced`; other unknown values are invalid. `--screenshot-mode` defaults to `off` and accepts `off|opened|all`. Private screenshots are a `cdp` capability. Any non-default screenshot mode requires explicit `--allow-navigation`.

`--screenshot-mode all` requires a positive effective count. Count `0` remains available with `off` or `opened`, because `opened` creates no additional opens. Bilibili search rejects a non-`off` screenshot mode.

## Configure the collection envelope

`--count-mode` accepts `fixed` (default) or `best_effort`.

- `fixed` keeps the existing per-platform count behaviour and stops at the requested count.
- `best_effort` means collect as much as you can. It has no fixed ten-record total cap and promises no total: it keeps paginating inside `--run-deadline` (default 900 seconds), bounded by a finite per-platform batch budget, a stall limit, and cancellation. A budget pause is reported as `budget-exhausted`, not as finished collection.

`--run-deadline SECONDS`, `--batch-pages N`, `--batch-interval SECONDS`, and `--per-target-budget N` describe that envelope. `--targets-json PATH` supplies a private mode-`0600` multi-target plan, so one run can carry several accounts, several platforms, or a Weibo topic; targets still execute sequentially under one browser owner.

A plan may only tighten a platform's own limits: batch pages, batch records, and the stall limit are clamped down, and the batch interval is never shortened below the platform's value. The Xiaohongshu 10-notes / 3-pages / 600-seconds-between-starts policy and its persistent risk pause are unchanged and cannot be relaxed by a plan, a backend switch, a target change, or a different runtime home.

Mixing backends inside one run is not supported, because one run has exactly one browser owner. Use a separate authorized run for the other backend.

## Creator list onboarding (17.0.2)

Use the offline Harness `media_missher_setup` tool: template, import, preview, then activate explicit preview row numbers. The CSV/XLSX columns are platform, creator_name and homepage_url. Import strips URL query/fragment values and requires an official creator homepage; it never resolves names or short links online. Several accounts on one platform may be selected in one import; a display name stays a label and is never an identity. The private profile retains platform_uids for compatibility, creator_targets for display, and active_platforms for the current default selection. Unselected stored targets remain available only when explicitly selected. The Git controller respects active_platforms unless --platform is supplied; a legacy profile without that field defaults to configured targets. No setup action launches Chrome or installs the collection runtime.

## Shared protection (17.0.2)

Runtime installation paths still follow MEDIA_MISSHER_HOME. Collection protection is separately shared under `~/.local/share/media-missher-shared`, using the same user HOME across entrypoints. Do not override HOME, delete shared state, switch browser/account/backend, or use an older client to evade a pause. Default/current/registered legacy homes are retained and their XHS states conservatively merged and synchronized under locks. Unknown legacy clients and another OS user/HOME are outside this coordination boundary.
