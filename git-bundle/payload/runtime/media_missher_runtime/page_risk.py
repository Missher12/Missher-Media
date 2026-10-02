"""Read visible blocking UI without treating collected content as a challenge.

The probes never navigate or interact. HTTP and structured response risk checks
remain the responsibility of the response collectors.
"""
from __future__ import annotations

import json


_PLATFORMS = frozenset({"xhs", "x", "bilibili", "douyin", "weibo"})
_CHALLENGE_SELECTORS = (
    ".geetest_panel", ".geetest_holder", "#geetest-wrap",
    'iframe[src*="geetest"]', 'iframe[src*="captcha"]',
    ".captcha", "#captcha", '[data-testid="captcha"]',
    ".captcha_verify_container", "#captcha_container", ".captcha-verify-container",
    ".challenge-page", "#challenge-page", '[data-testid="challenge-page"]',
    ".challenge-overlay", "#challenge-overlay", '[data-testid="challenge-overlay"]',
)
_BLOCKING_SELECTORS = (
    "#pl_common_error", ".m-error", ".error-page", '[data-testid="error-page"]',
    ".access-denied", '[data-testid="access-denied"]', ".security-check",
    ".verify-wrap", ".verify-container", ".captcha-container",
)
_DIALOG_SELECTORS = ('[role="alertdialog"]', '[role="dialog"]', '[aria-modal="true"]')
_DIALOG_PROMPTS = (
    "请完成验证", "请进行安全验证", "请先完成安全验证", "请求过于频繁", "访问受限",
    "Rate limit exceeded", "Too many requests", "Verify you are human", "Verify your identity",
)
_BLOCKING_PHRASES = (
    "请完成验证", "访问受限", "请求过于频繁", "账号异常", "风控", "安全验证", "验证码",
    "Rate limit exceeded", "Too many requests", "Verify you are human",
    "Verify your identity", "unusual activity",
)


def risk_probe_function(platform: str) -> str:
    """A self-contained JS function returning ``{risk, reason}``.

    Embed as ``(<function>)()`` inside another extractor. A platform is required
    to keep call sites explicit even while their blocking contracts are shared.
    """
    if platform not in _PLATFORMS:
        raise ValueError("unsupported risk-probe platform")
    options = json.dumps({
        "platform": platform,
        "selectors": _CHALLENGE_SELECTORS,
        "blocking": _BLOCKING_SELECTORS,
        "phrases": _BLOCKING_PHRASES,
        "dialogs": _DIALOG_SELECTORS,
        "prompts": _DIALOG_PROMPTS,
    }, ensure_ascii=False, separators=(",", ":"))
    return """() => {
        /* MEDIA_MISSHER_VISIBLE_RISK */
        const options = """ + options + """;
        const visible = (element) => {
            if (!element || !element.isConnected) return false;
            for (let node = element; node; node = node.parentElement) {
                const style = window.getComputedStyle(node);
                if (node.hidden || node.getAttribute('aria-hidden') === 'true'
                    || style.display === 'none' || style.visibility === 'hidden'
                    || style.visibility === 'collapse' || Number(style.opacity || '1') === 0) return false;
            }
            const rect = element.getBoundingClientRect();
            return rect.width > 0 && rect.height > 0;
        };
        const nodes = (selector) => Array.from(document.querySelectorAll(selector));
        const reasonIn = (element) => {
            const text = (element.innerText || '').replace(/\\s+/g, ' ').trim().toLowerCase();
            return options.phrases.find((phrase) => text.includes(phrase.toLowerCase())) || null;
        };
        for (const selector of options.selectors) {
            if (nodes(selector).some(visible)) return {risk: true, reason: 'challenge-selector'};
        }
        for (const selector of options.blocking) {
            for (const node of nodes(selector)) {
                if (!visible(node)) continue;
                const reason = reasonIn(node);
                if (reason) return {risk: true, reason};
            }
        }
        // A post can itself be displayed as a dialog. Bare words such as
        // captcha/risk are insufficient here; require a leading system prompt.
        for (const selector of options.dialogs) {
            for (const node of nodes(selector)) {
                if (!visible(node)) continue;
                const text = (node.innerText || '').trim().toLowerCase();
                const reason = options.prompts.find((phrase) => text.startsWith(phrase.toLowerCase()));
                if (reason) return {risk: true, reason};
            }
        }
        // Full-page validation can lack a widget; require its dedicated route
        // as well as a visible blocking prompt, never a post's body by itself.
        const path = document.location?.pathname || '';
        if (/(?:^|\\/)(?:captcha|challenge|verify|verification|security-check)(?:\\/|$)/i.test(path)
            && visible(document.body)) {
            const reason = reasonIn(document.body);
            if (reason) return {risk: true, reason};
        }
        return {risk: false, reason: null};
    }"""


def risk_probe_expression(platform: str) -> str:
    """A directly evaluable expression returning ``{risk, reason}``."""
    return "(" + risk_probe_function(platform) + ")()"
