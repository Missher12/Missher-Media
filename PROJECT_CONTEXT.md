# Media@Missher Codex Skill Project Context

## Objective

Build an independently authored Codex skill that preserves the supported four-platform Media@Missher collection contract without copying or modifying the installed engine.

## Architecture

Use a standard-library-only thin subprocess adapter. Resolve the existing engine as an external runtime, validate requests before launch, force private JSON staging, validate current-run output, and perform adapter-owned format conversion. Keep repository tests outside the installable `media-missher/` directory.

## External Runtime Boundary

Treat `/Users/missher/.openclaw/workspace/skills/media-missher` as the external engine path for local testing only. Do not import its modules, copy its source or generated artifacts, or modify its files during development. Production resolution will use explicit configuration rather than a bundled personal path.

The external runtime includes work governed by the Non-Commercial Learning License 1.1 and remains subject to its own license. This repository does not relicense or distribute that runtime.

## Current State

- Branch: `codex/media-missher-implementation`
- Design: completed in `docs/superpowers/specs/2026-08-03-media-missher-codex-skill-design.md`
- Implementation plan: recorded in `docs/superpowers/plans/2026-08-03-media-missher-codex-skill.md`
- Current phase: Task 5, final skill instructions and security gates
- Verification command: `PYTHONDONTWRITEBYTECODE=1 uv run --no-project --with pytest python -m pytest -q -p no:cacheprovider`. Official skill validation, real-engine read-only preflight, four-platform schema compatibility, and independent Task 1–4 reviews pass. Live count-1 collection and installation remain pending.

## Known Constraint

The legacy external `scrape_all.py` path requires `--no-feishu`, but non-JSON format handling may still create Feishu-shaped local artifacts. The adapter must therefore force JSON staging and perform any CSV, JSONL, or SQLite conversion itself. A remote Feishu write remains outside this skill and requires separate explicit authorization.

## Rollback Rule

Develop and later install the candidate side by side with the OpenClaw runtime. Roll back only by removing or disabling the new Codex skill; never replace, rewrite, or delete the installed OpenClaw engine or its pre-existing output.
