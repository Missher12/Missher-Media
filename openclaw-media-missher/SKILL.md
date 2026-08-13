---
name: media-missher
description: Use when collecting authorized creator posts or keyword search results from Bilibili, Xiaohongshu, Douyin, or Weibo through an existing signed-in Chrome session.
---

# Media@Missher V15.2.1

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
- Xiaohongshu creator collection is complete by default. Use `--bilibili-complete` when Bilibili details are required; `--xhs-complete` remains compatible, and `--xhs-comments` requests a bounded comment slice.
- Preserve the automatic randomized 5–15 second settle after each Xiaohongshu complete-mode note opens; allow enough platform timeout for the requested count.
- Runtime staging is private JSON. Any CSV, JSONL, or SQLite conversion belongs to the installed Codex adapter.
- Browser assistance and screenshots default to `off`. BrowserSkill is Bilibili creator-only. Xiaohongshu uses Playwright/CDP only and rejects BrowserSkill before navigation with `xhs-browser-assist-unsupported`; screenshots remain available with `--browser-assist off --screenshot-mode opened|all --allow-navigation`.
- BrowserSkill is optional; Playwright/CDP retains response capture, identifier validation, risk stops, and private screenshots.
- Keep at most one Xiaohongshu detail open and one CDP click per record. A requested comment slice may use at most three comment-container scrolls with a 1,500 ms wait after each; it never refreshes or reopens the detail, and a non-risk shortfall remains partial.
- Do not retry a `risk-stopped` result.
- Never overlap collections; the launcher holds the shared private collection lock through runtime exit.

## Troubleshooting

If preflight fails, correct the named missing runtime component or open the required signed-in platform page. Do not clear locks, state, or browser profiles as a recovery shortcut.
