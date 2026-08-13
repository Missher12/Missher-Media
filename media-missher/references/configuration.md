# Configure the shared runtime

This reference defines the shared runtime layout, configuration precedence, private profile, and creator target requirements.

## Resolve the runtime home

The repository `VERSION` file is the authoritative product version. Media@Missher V15.2 uses `15.2.0`. The installer reports this product version separately from its unique UTC timestamp-and-random-suffix deployment release. Do not replace the unique deployment release with a fixed product version because upgrades and recovery paths depend on release uniqueness.

`MEDIA_MISSHER_HOME` selects the shared runtime home. When it is unset, the runtime and installed skills use `~/.local/share/media-missher`. OpenClaw is retired on the current machine; its source package and dual-skill installer mode remain only for backward compatibility with historical environments.

The home contains these paths:

- `current/`: deployed source, product `VERSION`, and five entrypoints
- `venv/`: Python 3.11 or newer dependency environment
- `state/`: mode-`0700` locks, checkpoints, cache, reports, and default `runs/`

The runtime installer writes mode-`0600` `.media-missher-owner.json` and `.media-missher-release` markers. With the recommended `--codex-only` mode, the release value must match across `current/`, `venv/`, and the Codex skill; the backward-compatible default additionally requires the OpenClaw skill to match. Installation holds `.media-missher-install.lock`; launchers take a shared lock before using a release. Adapter collections additionally hold the mode-`0600` `.media-missher-collection.lock` exclusively through collection and evidence validation, so the dedicated browser profile cannot be collected concurrently.

Preflight rejects missing or inconsistent markers, symlinked path components, a non-private state directory, an unwritable state directory, missing dependencies, broken entrypoints, and a timed-out install lock.

## Apply configuration precedence

Command-line values override environment values. Environment values override the private profile.

Supported environment variables are:

- `MEDIA_MISSHER_HOME`: shared runtime home
- `MEDIA_MISSHER_DATA_ROOT`: parent for unique private run directories
- `MEDIA_MISSHER_CDP_URL`: existing CDP endpoint, default `http://127.0.0.1:9222`
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
  "platform_uids": {
    "bilibili": "configured_bilibili_id",
    "xhs": "configured_xhs_id",
    "douyin": "configured_douyin_id",
    "weibo": "configured_weibo_id"
  }
}
```

Creator mode requires a non-empty `platform_uids` value for every selected platform. A command-line `--<platform>-uid` value overrides its profile value. Search mode needs a keyword and does not require a creator UID.

The adapter rejects a profile inside the repository or installed skill. It also rejects permissions other than `0600`, unknown platforms, empty targets, negative or fractional counts, and negative or non-finite timeouts.

The profile must not contain Feishu credentials. Media@Missher never performs a remote Feishu write.

## Configure optional V15 browser modes

`--browser-assist` defaults to `off`; `--screenshot-mode` defaults to `off`. The accepted values are `--browser-assist off|browserskill` and `--screenshot-mode off|opened|all`. BrowserSkill is accepted only for Bilibili creator collection. Xiaohongshu requires `--browser-assist off`; an explicit assisted request fails before navigation with `xhs-browser-assist-unsupported`. Screenshots support Bilibili and Xiaohongshu. Any non-default value requires `--allow-navigation`.

BrowserSkill is an external optional dependency. The compatibility baseline is BrowserSkill 0.1.10 and extension 0.1.6. Media@Missher does not download, install, upgrade, or launch that dependency during preflight. Playwright/CDP remains the authority for response listening, native-ID validation, risk checks, and screenshot capture.

BrowserSkill 0.1.10 performs its own upstream bundled skill sync whenever an explicitly requested assisted run actually executes `bsk session start`; JSON mode hides the upstream hint but does not suppress that sync. Media@Missher does not bypass this upstream behavior. Its preflight remains read-only and does not start a session or download or upgrade the BrowserSkill binary or extension.

`--screenshot-mode all` requires a positive effective count. Count `0` remains available with `off` or `opened`. Bilibili search rejects non-`off` browser assistance and screenshot modes; creator dynamics are the supported Bilibili BrowserSkill path. Xiaohongshu creator detail and screenshots remain Playwright/CDP-only.
