# Media@Missher V15 Xiaohongshu CDP-Only Browser Ownership Design

**Date:** 2026-08-13

**Status:** Selected for user review

**Selected route:** Remove BrowserSkill from the Xiaohongshu execution path while preserving the existing optional Bilibili integration.

## 1. Goal

Restore reliable Xiaohongshu article collection after live acceptance proved that the BrowserSkill temporary-tab borrowing architecture blocks before the first detail click. Xiaohongshu must use one Playwright/CDP-owned temporary page for creator navigation, exact detail opening, response capture, risk detection, bounded comment enrichment, and private screenshots.

The change must not uninstall or modify Tencent/BrowserSkill on the machine. It removes only Media@Missher's Xiaohongshu dependency on BrowserSkill.

## 2. Confirmed failure

Two authorized 10-article acceptance attempts produced zero records. The first reported the coarse `bsk-transport` code. After safe stage diagnostics were added, the second proved that the failure occurs at `bsk-tab-borrow`.

The failing sequence is:

1. Media opens a temporary Xiaohongshu creator page through CDP.
2. BrowserSkill starts a separate Agent Window.
3. BrowserSkill tries to borrow the CDP-owned temporary tab.
4. The borrow operation fails before snapshot, click, detail response, parsing, or screenshot.

This is an ownership conflict, not a Xiaohongshu HTTP, payload, CAPTCHA, challenge, cooldown, or account-risk result. Repeating the same architecture cannot prove collection reliability.

## 3. Alternatives

### A. Xiaohongshu CDP-only, BrowserSkill retained for Bilibili — selected

Xiaohongshu always uses its existing exact Playwright click. Media retains BrowserSkill only for the currently separate Bilibili creator path. This is the narrowest change and preserves unrelated functionality.

### B. Remove BrowserSkill from all Media@Missher platforms

This has the smallest long-term dependency surface, but it removes an unrelated Bilibili option without evidence that Bilibili needs the same rollback.

### C. BrowserSkill-first single-window Xiaohongshu

BrowserSkill would own the Agent Window from session start, while Media attaches through CDP without creating a page. This avoids borrowing but requires new Agent Window discovery, exact target correlation, listener registration before BrowserSkill navigation, lifecycle ownership, login preflight, and cleanup contracts. It is a larger unproven redesign and is not justified before the known CDP path is accepted live.

## 4. Architecture

For Xiaohongshu, browser ownership becomes single-authority:

```text
Media adapter collection lease
        |
        v
Playwright/CDP temporary XHS creator page
        |
        +-- exact creator and login preflight
        +-- response listener registered before click
        +-- exact note card selected by native note ID
        +-- one Playwright click
        +-- target-bound detail response and risk checks
        +-- existing 5-15 second settle
        +-- bounded visible comment-container enrichment
        +-- private article screenshot when requested
        +-- modal/page cleanup
```

No Xiaohongshu request may start a BrowserSkill session, create an Agent Window, enumerate BrowserSkill tabs, borrow or return a tab, snapshot through BrowserSkill, or issue a BrowserSkill click.

## 5. Public command behavior

- Xiaohongshu collection and screenshots remain available with `--browser-assist off`.
- `--screenshot-mode opened|all` remains independent of BrowserSkill and continues to require `--allow-navigation`.
- An explicit Xiaohongshu request with `--browser-assist browserskill` fails before platform navigation with a fixed safe diagnostic. It must never silently fall back because the caller asked for a behavior that is no longer supported on that platform.
- Bilibili creator collection may continue to use `--browser-assist browserskill` under its existing bounded policy.
- A mixed Bilibili and Xiaohongshu request may not apply one global BrowserSkill mode ambiguously. Until a platform-scoped assist option exists, the adapter rejects that combination and instructs the caller to run Xiaohongshu with assistance off.
- Installed skill examples and Hermes-facing instructions use `--browser-assist off` for Xiaohongshu.

## 6. Xiaohongshu detail behavior

The existing detail contract remains unchanged except for the click owner:

- select the exact visible creator card by expected native note ID;
- register the response listener before the click;
- issue at most one Playwright click;
- accept only the expected target-bound detail response;
- stop immediately on HTTP `403` or `429`, payload `461`, `471`, or `999`, visible challenge, risk, lock, block, or cooldown;
- never refresh or reopen a failed detail;
- preserve the randomized 5-15 second settle for a successful complete detail;
- scroll only one unique visible comment container at most three times when the requested slice is short;
- capture a private screenshot only after the post-detail risk check;
- close only the Media-owned temporary modal or page.

## 7. Diagnostics and compatibility

Add the fixed precondition code `xhs-browser-assist-unsupported` for an unsupported Xiaohongshu BrowserSkill request. The runtime manifest, adapter validator, documentation, and tests must all recognize the same code. No raw BrowserSkill output, URL query, creator UID, account state, or article content may enter diagnostics.

The existing stage-specific `bsk-*` diagnostics remain valid for Bilibili and do not imply that BrowserSkill is still reachable from Xiaohongshu.

The outer adapter must report `failed`, not `partial`, when a run has zero accepted content records even if diagnostic JSON files exist.

## 8. Test strategy

Offline regression must prove:

1. Xiaohongshu with assistance off never constructs or preflights a BrowserSkill bridge.
2. Xiaohongshu exact Playwright click still registers its response listener first.
3. Xiaohongshu screenshots work with assistance off.
4. Xiaohongshu `browserskill` requests fail before navigation and output creation with the fixed diagnostic.
5. Mixed Bilibili/Xiaohongshu BrowserSkill requests fail closed instead of partially applying a global mode.
6. Bilibili BrowserSkill behavior and diagnostics remain unchanged.
7. Zero content records plus diagnostic artifacts produce overall `failed`, not `partial`.
8. The full sockets-disabled suite, compile gate, five entrypoint help checks, residual scan, skill validation, and `git diff --check` pass.

## 9. Live acceptance

After source and installed-state gates pass, run one separately authorized Xiaohongshu acceptance through the standard adapter with:

- one selected private-profile creator target;
- count 10;
- complete Xiaohongshu detail mode;
- a bounded requested comment slice;
- `--browser-assist off`;
- `--screenshot-mode opened`;
- `--allow-navigation`;
- `--no-feishu`.

Accept success only when all 10 current-run records satisfy the Xiaohongshu complete contract and required screenshot evidence validates. Any risk signal stops the run without retry. A non-risk partial or failure receives no automatic second collection unless a new concrete defect is corrected and a new run is explicitly approved.

## 10. Non-goals

This change does not:

- uninstall, update, restart, or reconfigure Tencent/BrowserSkill;
- remove BrowserSkill from Bilibili;
- add stealth, proxy rotation, CAPTCHA handling, fingerprint changes, or platform-control bypass;
- increase concurrency, page caps, retries, click counts, or comment action budgets;
- modify Douyin, Weibo, Feishu, or historical source archives;
- stage, commit, tag, push, publish, or deploy without separate authorization.
