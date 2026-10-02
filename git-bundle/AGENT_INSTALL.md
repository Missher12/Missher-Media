# Media@Missher — Agent installation guide

Give an Agent this sentence with the supplied Setup folder:

> Install Media@Missher following AGENT_INSTALL.md in this folder, add its Skill to your Agent, and guide me through creator import and platform login before the first collection.

This guide belongs to **Agent CLI 17.0.2 / runtime 17.0.2**. It works without DeepSeek Harness. Repository access is unnecessary when using the packaged Setup. The repository remains private and the original software is proprietary, Copyright (c) 2026 Missher. The guide does not authorize a collection, browser launch or account login by itself.

Use the host-selected model and reasoning settings, including GPT-6 Astra when the user selected it. This package has no model API client. Continue steps already authorized by the current request; ask only for missing choices that affect the result. Model selection, CLI installation, Skill discovery and a successful task are separate checks.

## 1. Install the CLI

Use the supplied archive and its exact entry in `SHA256SUMS.txt`. Run from the extracted Setup directory. Require **Node.js >=22.19 with npm** from https://nodejs.org/. Runtime Python **3.11 or 3.12** is needed before collection; setup/Skill/doctor do not provision it or start a browser. No administrator privileges are needed for the Media installer.

macOS or Linux:

```sh
sh ./install.sh --archive "$PWD/missher-media-missher-17.0.2.tgz" --sha256 "<exact SHA-256 from SHA256SUMS.txt>"
```

Windows PowerShell, using an existing WSL2 distribution (check its actual name with `wsl --list --verbose`):

```powershell
.\install.ps1 -Archive .\missher-media-missher-17.0.2.tgz -Sha256 '<exact SHA-256 from SHA256SUMS.txt>' -Distribution Ubuntu
```

Windows uses the **same Linux runtime in WSL2**, not a native Windows collector. Follow https://learn.microsoft.com/windows/wsl/install for WSL prerequisites and https://learn.microsoft.com/windows/wsl/tutorials/gui-apps for WSLg. Continue the commands below in that same distribution and Linux user. Its runtime, profile, results and dedicated browser stay in Linux HOME, never `/mnt/c`. A Windows Agent can execute commands with `wsl.exe --distribution <name> --exec <absolute Linux CLI> ...`; an Agent running inside WSL uses the normal Skill installer. Do not assume a Skill installed in Linux HOME is discoverable by a Windows-native Agent; pass this guide and the installed Skill to that Agent explicitly.

The installer returns `executable`, an absolute CLI path, and preserves the previous installation. Use that path if `media-missher` is not on PATH. It does not edit shell startup files or the Agent's host settings. A checksum failure, unknown existing command, or edited Skill must be resolved by inspecting ownership; do not force-overwrite it.

## 2. Install and discover the Skill

```sh
media-missher --version
media-missher install-skill --list
media-missher install-skill --agent codex
media-missher doctor
```

Choose the actual current Agent from `--list`, or supply its documented skill root with `--skill-root /absolute/skills`. Do not install into every detected Agent. If PATH is missing, substitute the installer's absolute `executable` for `media-missher`. Skill installation is separate from activation: reload the host's skills or open a new task if required, and verify that the Agent can read the installed Skill and invoke `--help` in its actual shell. Unknown hosts can read the same Skill directly and use the CLI; no MCP or Cordis runtime is required for this path.

An existing `media-missher` Skill may belong to the separate atomic runtime installer. Do not put a second copy under the same name or force the CLI installer to claim it. Inspect its ownership and version, retain a rollback copy, and use the authorized installer for that entry. A Skill requiring runtime 17.0.2 must not be paired with an installed 15.2.1 runtime; complete the verified upgrade before collection. Never bypass the version check.

`doctor` is offline. Report each unmet prerequisite and follow its next step. A blank device should report missing selected creators; it must not create a runtime, collect, probe CDP or launch a browser. If Python is needed, use `python3.12` or `python3.11`; `MEDIA_MISSHER_INSTALL_PYTHON` can identify the bootstrap interpreter. Installing the CLI is not a successful data collection.

## 3. Import and select creators

```sh
media-missher setup template
media-missher setup import --file /absolute/creators.xlsx
media-missher setup activate --import-id <returned-ID> --rows 1,3
media-missher setup status
```

Show the template and import preview to the user. Require platform, creator name and full official homepage. Names are labels; never infer an account ID from a possibly duplicated name. Activate the user's intended rows; several accounts on one platform are supported. Explicit targets already supplied by the user need no roster re-import. Empty examples are not targets. CSV and XLSX parsing are offline; keep the saved roster and result files private.

## 4. Guide login in the dedicated browser

When the user asks to open the AI collection browser:

```sh
media-missher setup browser-open --confirm-open
media-missher setup browser-check
```

Use installed official Chrome. Linux/WSL must have a visible graphical desktop and a supported Chrome/Chromium installation. The browser uses its own profile and a static local page with official platform login links. Let the user sign in manually, then check the local connection and selected platform pages. **Connected is not authenticated.** Do not request passwords, cookies or verification codes, disable browser sandboxing, publish a CDP port, import the everyday browser profile or automate a CAPTCHA. Keep browser and runtime in the same OS environment.

## 5. First authorized collection and result

Once the user has selected the target platforms, count and navigation scope, call one bounded collection. For example, if the user authorized one Xiaohongshu record and page navigation:

```sh
media-missher collect --platforms xhs --count 1 --allow-navigation
```

The collector checks login and exact target binding before saving output. Run platforms sequentially. Xiaohongshu stays at most 10 notes/3 pages, with 600 seconds between batch starts and a persistent risk stop. Never auto-retry, reset a pause or change HOME/account/browser to evade it. BrowserSkill is retired. Report actual status/counts and private evidence paths first. Export is a separate offline choice of targets, record kinds, fields and format; do not automatically create Excel. Reuse export choices already supplied. If the user needs to act, describe only that missing step.

Chrome CDP is the only active backend. `media-missher capabilities` reports declarations without opening a browser; installation and declared support do not prove readiness. Computer Use is removed, including its lifecycle command. Old requests are refused with `backend-retired-computer-use`; historical runs remain readable/exportable. DSH and other host native acceptance must still be checked separately.

History and progress stay local: `media-missher runs list`, `runs progress`, `runs xhs-status`. Historical data is not proof of a fresh run. Existing Harness users can keep using the separate Cordis Bundle; both paths share the same underlying collector and same-user protection.

## Distribution status

This local candidate includes installable packages and a complete Agent entry. A public one-sentence download URL is not live yet. Publishing will require an owner-controlled distribution location; never make the private source repository public or invent a successful download URL. Public availability does not change Missher's proprietary license.
