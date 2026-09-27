# Agent entry implementation plan

> **For agentic workers:** Use superpowers:subagent-driven-development for the bounded CLI task and sequential specification/quality review. Continue integration locally. Existing user authorization covers implementation; preserve the owned dirty tree and do not stage, commit, install into formal profiles or publish.

**Goal:** Deliver the BrowserSkill-style CLI + Skill installation path while preserving the shared collector and native Harness plugin.

**Architecture:** Standalone Node executable calls the existing built factory exports; the existing Python payload remains the only collector. POSIX installation serves macOS/Linux and the Windows PowerShell entry delegates to one WSL2 environment. All Agent installations share one operating Skill.

**Tech Stack:** Node 22.19+, ESM, existing TypeScript/Vitest build, Python 3.11/3.12, npm package archives, POSIX shell, PowerShell/WSL2.

## 1. Foundation

- [x] Inspect exact worktree, baseline, prior dirty ownership, source architecture and BrowserSkill's actual guide; snapshot prior artifact and formal-state hashes.
- [x] Add `agent-plugin/bin/media-missher.mjs`, `agent-plugin/src/skills.mjs`, `agent-plugin/skill/SKILL.md` and `agent-plugin/tests/cli.test.mjs`. Keep parsing and skill installation separate. Export `createRunsTool` alongside the existing factory exports from `harness-plugin/src/index.ts`.
- [x] CLI routes `setup status|template|import --file PATH|activate --import-id ID --rows 1,3|browser-check|browser-open --confirm-open`, `collect --platforms LIST --count N --allow-navigation`, `runs list|export --run-id ID --format FORMAT|compare --before ID --after ID|xhs-status|progress`. Use per-command strict option sets and AbortController propagation. Tests use an isolated HOME and synthetic public creator identifiers, never actual targets.
- [x] `doctor` returns explicit next steps for absent runtime or targets without installing/probing; `install-skill --list` is read-only, explicit installation has a manifest digest and refuses edited/unowned paths. Run `node --test agent-plugin/tests/*.test.mjs` after building/staging shared code.

## 2. Installation and platform integration

- [x] Add `agent-plugin/package.json`, `agent-plugin/scripts/build.mjs`, `agent-plugin/scripts/install.mjs`, root `install.sh`, root `install.ps1`, and `AGENT_INSTALL.md`. Build copies compiled factory implementation and allowlisted payload, not developer checkout files or user data. Installer verifies archive SHA-256 and exact package identity before npm install in a new owned release directory, then verifies help/version before switching an owned launcher. Failure leaves earlier current command intact.
- [x] Add Linux fixed Chrome discovery and graphical-session checks in `harness-plugin/src/browser-setup.ts`; enable Linux in the shared runtime gate. Preserve all macOS behavior, ownership constraints, sequential locks and login controls. Windows delegates through WSL2 without altering POSIX protections.
- [x] Update live version contracts to runtime 15.6.0 and Bundle 0.6.0 without modifying historical archives/evidence. Update README and copyright packaging references without changing license grants.
- [x] Add installer integration tests for wrong digest, unknown existing paths, cancellation/failed staged install, repeat install and exact payload identity. Build with existing pnpm tooling; install the actual tgz into an isolated macOS HOME.

## 3. Verification and handoff

- [x] Run independent spec review; fix concrete gaps. Then run independent quality review; fix concrete correctness/security issues.
- [x] Run full socket-disabled Python suite, full Bundle Vitest suite, TypeScript, active residual scan and package checks. Run the new CLI/installer tests. Label any OS that cannot actually execute here as unverified and prepare bounded CI acceptance jobs.
- [x] Pack new versioned Agent/Bundle/Setup archives; compare embedded payload to source and retained artifacts/formal settings to the baseline snapshot. Record exact hashes and executed commands in an evidence JSON and `docs/AGENT_ENTRY_15.6.0.md`.
- [x] Update PROJECT_CONTEXT.md and HANDOVER.md with current state, install command, ownership and native/platform limitations. Notify the requested existing task with concrete paths and evidence. Final answer distinguishes local usable entry from pending public hosting.

Completion evidence: docs/AGENT_ENTRY_15.6.0.md and agent-plugin/dist/AGENT-ENTRY-EVIDENCE.json. Local candidate completed on 2026-09-08; Linux/WSL native execution, actual host-session activation, formal installation and public hosting are explicitly unverified/pending. Requested existing task was notified successfully.
