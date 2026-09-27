# Media@Missher Agent installation design

## Confirmed goal

Match the concrete Tencent/BrowserSkill installation experience: give a shell-capable Agent one installation guide and it can install, discover commands, import a creator roster, guide manual browser login, and carry out an authorized collection. Keep the repository private and retain Missher's proprietary license. The owner selected public download as a distribution design, not permission to expose this development repository or publish its dirty checkout.

Reference inspected on 2026-09-08: https://github.com/Tencent/BrowserSkill and its AGENT_INSTALL.md. Its general Agent entry is a CLI plus Skill; its Harness plugin is a separate adapter. We use that architecture, not its browser implementation or license.

## Function and interface

Add a standalone `media-missher` command with `--version`, `--help`, `doctor`, `install-skill --list`, `install-skill --agent NAME`, `setup`, `collect`, and `runs`. All operational commands call the existing factories and share the Python runtime and safeguards. Installation must not require a Harness installation, DSH_HOME, Cordis context, or access to this conversation. JSON is the machine result; fixed progress remains on stderr. Every command rejects unknown arguments and preserves exit/cancellation results.

`doctor` is read-only and offline by default. It separately reports CLI, runtime, selected creators and unchecked browser/login state. Missing creators/runtime on a fresh device is a next step, not an automatic browser launch or collection. `setup` uses existing status/template/import/activate/browser-check/browser-open behavior. `collect` still resolves the exact selected targets before runtime creation. Paths may be configured explicitly and default to user-private locations independent of Harness.

One shared Skill contains the complete operating contract and references the installed absolute CLI when PATH is unavailable. Support explicit known Agent skill destinations and an explicit generic skill root. Never overwrite an unrelated or edited skill; recognize owned copies and preserve exact previous bytes on upgrade. Installing a Skill is not proof of activation in an existing Agent conversation.

## Data and packaging

Add `agent-plugin/`: a versioned local npm package with executable CLI, shared Skill, compiled existing tool implementation, allowlisted Python payload, and canonical copyright notices. Development source, personal profiles, login state, creator data and test artifacts are excluded. Node >=22.19 and Python 3.11/3.12 are dependencies; Python is provisioned only when the selected collection needs it. The download installer requires an expected SHA-256, validates the exact package identity, installs into a user-owned version directory and switches an owned command only after smoke checks. Keep previous installs recoverable.

macOS and Linux have a POSIX installer. Windows has a PowerShell entry using an existing WSL2 Linux distribution with WSLg for a visible Linux Chrome. All runtime, private data and browser operations stay inside that same Linux environment and HOME. Do not substitute incomplete native Windows chmod/lock semantics or expose CDP across the Windows boundary. Missing WSL/GUI/dependencies is reported with a concrete prerequisite. This is a Windows WSL entry, not a claim of native Windows collection support.

The native Harness/Cordis Bundle remains separately installable and reuses the same implementation. Product 15.6.0 / Bundle 0.6.0 / Agent package 0.1.0 are local candidates; all earlier versioned archives remain immutable. No hosting URL is invented. Until an owner-controlled public download location is actually deployed, the one-sentence entry refers to the delivered local guide/package.

## Acceptance

An isolated user home with no Harness can install the packed Agent artifact, run help/version/doctor, install a Skill, reject an unknown existing Skill, generate templates, import and activate a synthetic roster, refuse blank-device collection before runtime/output, and retrieve local progress. Installer rejects wrong checksums and preserves previous installation on failure. Offline operation does not contact platforms, launch Chrome or alter real user state.

Run focused new tests, all Python and Bundle regressions, package validation and a local installed-artifact smoke. Verify payload/source identity and prior archive/formal state hashes. Report actual macOS execution separately from Linux/Windows scripted or CI evidence. Do not describe unexecuted platform checks as passed. Notify existing task 01a07766-9fe2-7da1-9809-7437205e41c5 when the local candidate is ready.
