# Media@Missher Codex Skill Project Context

## Objective

Build an independently authored Codex skill that preserves the supported four-platform Media@Missher collection contract without copying or modifying the installed engine.

## Architecture

Use a standard-library-only thin subprocess adapter. Resolve the existing engine as an external runtime, validate requests before launch, force private JSON staging, validate current-run output, and perform adapter-owned format conversion. Keep repository tests outside the installable `media-missher/` directory.

## External Runtime Boundary

Treat `/Users/missher/.openclaw/workspace/skills/media-missher` as the external engine path for local testing only. Do not import its modules, copy its source or generated artifacts, or modify its files during development. Production resolution will use explicit configuration rather than a bundled personal path.

The external runtime includes work governed by the Non-Commercial Learning License 1.1 and remains subject to its own license. This repository does not relicense or distribute that runtime.

## Current State

- Delivery branch: `codex/media-missher-skill` (implementation prepared in `codex/media-missher-implementation` for fast-forward merge)
- Design: completed in `docs/superpowers/specs/2026-08-03-media-missher-codex-skill-design.md`
- Implementation plan: recorded in `docs/superpowers/plans/2026-08-03-media-missher-codex-skill.md`
- Current phase: final verification and installation complete; independent whole-change review and delivery-branch merge remain.
- Installed skill: `/Users/missher/.codex/skills/media-missher`
- Verification command: `PYTHONDONTWRITEBYTECODE=1 uv run --no-project --with pytest --with pytest-socket python -m pytest -q -p no:cacheprovider --disable-socket`. The final candidate passes 106 offline tests, official skill validation, special-character-path portability, real-engine live preflight, and staged reviews.
- Live compatibility: Xiaohongshu, Douyin, and Weibo each produced and validated one current record in the sequential four-platform run. Bilibili produced and validated one complete current record after its required platform page was temporarily opened. Both runs had no Feishu artifacts, risk signal, or timeout; the temporary page was closed.
- External runtime integrity: the source aggregate used for the installation gate was `31cf449f1db6f12dc1483672205d9ffc757612220f2f70b9aba41df8c865e75b` before and after installation, and no source file had a current-day modification time.

## Known Constraint

The legacy external `scrape_all.py` path requires `--no-feishu`, but non-JSON format handling may still create Feishu-shaped local artifacts. The adapter must therefore force JSON staging and perform any CSV, JSONL, or SQLite conversion itself. A remote Feishu write remains outside this skill and requires separate explicit authorization.

The external runtime can require a matching platform page to be open in the existing debugging-enabled Chrome session. The adapter does not start Chrome or navigate pages automatically. A missing page is a concrete partial-run prerequisite, not proof that the collector implementation failed.

## Rollback Rule

Develop and later install the candidate side by side with the OpenClaw runtime. Roll back only by removing or disabling the new Codex skill; never replace, rewrite, or delete the installed OpenClaw engine or its pre-existing output.
