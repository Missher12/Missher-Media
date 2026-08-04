---
name: media-missher
description: Use when collecting authorized creator posts or keyword search results from Bilibili, Xiaohongshu, Douyin, or Weibo through an existing signed-in Chrome session.
---

# Media@Missher V12

Use the shared local runtime. Run preflight before collection, keep platforms sequential, and stop immediately when the runtime reports a risk status.

## Commands

```bash
python scripts/preflight.py --json
python scripts/preflight.py --live --cdp-url http://127.0.0.1:9222 --json
python scripts/run_collection.py creator --platforms bilibili,xhs,douyin,weibo --count 1 --bilibili-uid UID --xhs-uid UID --douyin-uid UID --weibo-uid UID --output-dir OUTPUT --allow-navigation --no-feishu
python scripts/run_collection.py search --platform weibo --keyword TOPIC --count 5 --output-dir OUTPUT
```

The runtime home defaults to `~/.local/share/media-missher`. Set `MEDIA_MISSHER_HOME` only when the shared runtime was installed elsewhere.

## Rules

- Use only the already authenticated Chrome CDP session.
- Never export credentials, change accounts, bypass challenges, or rotate network identities.
- `count=0` remains bounded by the runtime page cap.
- Use `--bilibili-complete`, `--xhs-complete`, and `--xhs-comments` only when those details are required.
- Preserve the automatic randomized 5–15 second settle after each Xiaohongshu complete-mode note opens; allow enough platform timeout for the requested count.
- Runtime staging is private JSON. Any CSV, JSONL, or SQLite conversion belongs to the installed Codex adapter.
- Do not retry a `risk-stopped` result.

## Troubleshooting

If preflight fails, correct the named missing runtime component or open the required signed-in platform page. Do not clear locks, state, or browser profiles as a recovery shortcut.
