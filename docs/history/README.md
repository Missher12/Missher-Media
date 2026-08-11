# Historical archive index

This index separates safe Media@Missher source history from local operational or third-party archives. It intentionally records no credentials, private target identifiers, collected content, or browser data.

## Preserved in GitHub

| Milestone | Git reference | Contents |
| --- | --- | --- |
| Initial independent skill work | history beginning at `b8dccda` | Codex skill, adapter, validation, and safety development |
| Standalone runtime | history through `320cc6c` | Independently authored shared runtime and atomic installer |
| Media@Missher V12 | `v12.0.0` / `173d636` | First tagged standalone release |
| Media@Missher V15 | `v15.0.0` / `9910084` | BrowserSkill bridge, exact detail opening, and private screenshots |

All safe local Git branches and release tags are mirrored to the private repository. Git history is the version archive; installed `previous-*` directories are recovery copies rather than separate source releases.

## Local-only quarantined archives

| Historical artifact | SHA-256 | Why it is not copied into Git |
| --- | --- | --- |
| Media@Missher V7.1 package | `0fb4cf160cc0a12bf2231e481f5a6734237acbe8dc7e1a65a2ae6a021b79361d` | Contains a bundled third-party crawler without a packaged license, historical private configuration, proxy and messaging integration, and unrelated platform modules |
| Media@Missher V8.0 optimized package | `8c0c59f550595f14cdd75268bc77eb06bbc56595b1c71611b923bdd8b5c288c5` | Contains historical hard-coded identifiers plus cookie extraction, interaction, stealth, proxy, OpenClaw, and third-party integration paths that are outside the current safety boundary |

The original archives remain recoverable in the owner's local OpenClaw retirement archive. Their hashes provide identity evidence without placing unsafe contents in permanent Git history.

## Never upload

- collection JSON, caches, checkpoints, screenshots, traces, or generated reports
- browser profiles, cookies, account identifiers, private UIDs, tokens, or credentials
- runtime state, virtual environments, deployment locks, or owner metadata
- third-party source without compatible license and provenance review

Future historical imports require a fresh secret scan, provenance review, private-repository verification, and explicit owner approval of the exact sanitized file list.
