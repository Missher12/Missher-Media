"""Deterministic, bounded DOM extractors for CDP visible-page collection.

Every extractor here is a self-contained JavaScript expression that returns a
plain JSON value. CDP runs it through ``page.evaluate`` when page-observed
evidence is appropriate. Computer Use consumes trusted host observations
through its own protocol and does not execute these expressions.

Nothing here follows a link, replays a request or expands a virtual list. The
extractors only read what the current document already renders, and every one
of them caps how many items it returns.
"""

from __future__ import annotations

import json
from typing import Any, Mapping, Sequence

MAX_ITEMS = 200
MAX_TEXT_CHARS = 8000


class ExtractionError(RuntimeError):
    """Raised when a DOM extraction cannot be trusted."""


def _options(payload: Mapping[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


#: Shared helpers injected into every extractor. They are deliberately small so
#: the expression stays reviewable and never reaches outside the document.
_HELPERS = """
const mmVisible = (element) => {
  if (!element || !element.isConnected) return false;
  for (let current = element; current; current = current.parentElement) {
    const style = window.getComputedStyle(current);
    if (current.hidden
      || current.getAttribute('aria-hidden') === 'true'
      || style.display === 'none'
      || style.visibility === 'hidden'
      || style.visibility === 'collapse'
      || Number(style.opacity || '1') === 0) return false;
  }
  const rect = element.getBoundingClientRect();
  return rect.width > 0 && rect.height > 0;
};
const mmText = (element) => {
  if (!element) return null;
  const value = (element.innerText || element.textContent || '').replace(/\\s+/g, ' ').trim();
  return value || null;
};
const mmAttr = (element, name) => {
  if (!element) return null;
  const value = element.getAttribute(name);
  return value === null || value === '' ? null : value;
};
const mmAll = (root, selector) => Array.from(root.querySelectorAll(selector));
const mmHref = (element) => {
  if (!element) return null;
  const value = element.getAttribute('href');
  if (!value) return null;
  try { return new URL(value, document.location.origin).href; } catch (error) { return null; }
};
const mmInt = (value) => {
  if (value === null || value === undefined) return null;
  const matched = String(value).replace(/[,\\s]/g, '').match(/\\d+/);
  return matched ? Number(matched[0]) : null;
};
"""


def _expression(body: str, options: Mapping[str, Any]) -> str:
    return (
        "(() => {"
        + _HELPERS
        + f"const mmOptions = {_options(options)};"
        + body
        + "})()"
    )


# ---------------------------------------------------------------------------
# risk and challenge observation
# ---------------------------------------------------------------------------


RISK_SELECTORS: tuple[str, ...] = (
    ".geetest_panel",
    ".geetest_holder",
    "#geetest-wrap",
    'iframe[src*="geetest"]',
    'iframe[src*="captcha"]',
    ".challenge-page",
    "#challenge-page",
    '[data-testid="challenge-page"]',
    ".challenge-overlay",
    "#challenge-overlay",
    '[data-testid="challenge-overlay"]',
    "#pl_common_error",
    ".m-error",
    ".access-denied",
    '[data-testid="access-denied"]',
)

RISK_PHRASES: tuple[str, ...] = (
    "请完成验证",
    "访问受限",
    "请求过于频繁",
    "账号异常",
    "风控",
    "安全验证",
    "验证码",
    "Something went wrong",
    "Rate limit exceeded",
    "Try again later",
)


def risk_expression() -> str:
    """Return a fixed risk probe that reads only the live document."""

    return _expression(
        """
  for (const selector of mmOptions.selectors) {
    for (const element of mmAll(document, selector)) {
      if (mmVisible(element)) return { risk: true, reason: 'challenge-selector' };
    }
  }
  const body = mmText(document.body) || '';
  for (const phrase of mmOptions.phrases) {
    if (body.includes(phrase)) return { risk: true, reason: phrase };
  }
  return { risk: false, reason: null };
""",
        {"selectors": list(RISK_SELECTORS), "phrases": list(RISK_PHRASES)},
    )


LOGIN_REQUIRED_PHRASES: tuple[str, ...] = (
    "登录后查看",
    "请先登录",
    "立即登录",
    "Sign in to continue",
    "Log in",
)

LOGIN_SELECTORS: tuple[str, ...] = (
    ".login-container",
    ".login-btn",
    "[class*='login-container']",
    "[node-type='loginBtn']",
    ".gn_login",
    "[action-type='login']",
    "[data-e2e='login-button']",
)


def login_expression() -> str:
    """Return a probe that only reports a clearly logged-out document."""

    return _expression(
        """
  for (const selector of mmOptions.selectors) {
    for (const element of mmAll(document, selector)) {
      if (mmVisible(element)) return { logged_out: true, reason: 'login-selector' };
    }
  }
  const body = mmText(document.body) || '';
  for (const phrase of mmOptions.phrases) {
    if (body.includes(phrase)) return { logged_out: true, reason: phrase };
  }
  return { logged_out: false, reason: null };
""",
        {"selectors": list(LOGIN_SELECTORS), "phrases": list(LOGIN_REQUIRED_PHRASES)},
    )


# ---------------------------------------------------------------------------
# X (twitter) page observation
# ---------------------------------------------------------------------------


def x_posts_expression() -> str:
    """Read the visible post cards from the current X page.

    Both ``x.com`` and ``twitter.com`` render ``article[data-testid="tweet"]``
    cards. The extractor reads the outer card only and marks whether the card is
    a repost or a reply so the shared normalizer can classify it. It never
    follows a quoted post into a second record.
    """

    return _expression(
        """
  const cards = mmAll(document, 'article[data-testid="tweet"]').slice(0, mmOptions.maxItems);
  const posts = [];
  for (const card of cards) {
    if (!mmVisible(card)) continue;
    const statusLinks = mmAll(card, 'a[href*="/status/"]').map(mmHref).filter(Boolean);
    let permalink = null;
    for (const link of statusLinks) {
      if (/\\/status\\/\\d+$/.test(new URL(link).pathname)) { permalink = link; break; }
    }
    const social = mmAttr(card, 'data-testid') === 'tweet' ? card : null;
    const handleNode = card.querySelector('[data-testid="User-Name"] a[href^="/"]');
    const handleText = handleNode ? (handleNode.getAttribute('href') || '').replace(/^\\//, '') : null;
    const nameNode = card.querySelector('[data-testid="User-Name"] span');
    const textNode = card.querySelector('[data-testid="tweetText"]');
    const timeNode = card.querySelector('time');
    const metrics = {};
    const metricMap = {
      reply: 'comments', retweet: 'shares', like: 'liked', bookmark: 'bookmarks',
    };
    for (const [testId, field] of Object.entries(metricMap)) {
      const node = card.querySelector('[data-testid="' + testId + '"]');
      metrics[field] = node ? mmInt(mmAttr(node, 'aria-label') || node.textContent) : null;
    }
    const viewsNode = card.querySelector('a[href$="/analytics"]');
    metrics.views = viewsNode ? mmInt(mmAttr(viewsNode, 'aria-label') || viewsNode.textContent) : null;
    const mediaImages = mmAll(card, '[data-testid="tweetPhoto"] img').map((node) => mmAttr(node, 'src')).filter(Boolean);
    const videoNodes = mmAll(card, 'video');
    const quoted = card.querySelector('div[role="link"][tabindex="0"] [data-testid="tweetText"]');
    const socialContext = mmText(card.querySelector('[data-testid="socialContext"]'));
    posts.push({
      permalink,
      handle: handleText,
      author_name: mmText(nameNode),
      text: mmText(textNode),
      datetime: timeNode ? mmAttr(timeNode, 'datetime') : null,
      reply_metric: metrics.comments,
      repost_metric: metrics.shares,
      like_metric: metrics.liked,
      bookmark_metric: metrics.bookmarks,
      view_metric: metrics.views,
      image_urls: mediaImages.slice(0, 8),
      video_count: videoNodes.length,
      has_quoted_text: Boolean(quoted),
      social_context: socialContext,
      promoted: Boolean(card.querySelector('[data-testid="placementTracking"]')),
      has_social_proof: Boolean(card.querySelector('[data-testid="socialContext"]')),
      social,
    });
  }
  const nextLink = mmAll(document, 'a[href*="cursor="]').map(mmHref).filter(Boolean);
  return { posts, next_cursor_url: nextLink.length ? nextLink[0] : null };
""",
        {"maxItems": MAX_ITEMS},
    )


def x_profile_expression() -> str:
    """Read the visible public profile header fields from an X profile page."""

    return _expression(
        """
  const header = document.querySelector('[data-testid="primaryColumn"]') || document;
  const nameNode = header.querySelector('h2[role="heading"] span') || header.querySelector('h1 span');
  const handleNode = header.querySelector('div[data-testid="UserName"] span');
  const bioNode = header.querySelector('[data-testid="UserDescription"]');
  const locationNode = header.querySelector('[data-testid="UserLocation"]');
  const urlNode = header.querySelector('[data-testid="UserUrl"]');
  const joinedNode = header.querySelector('[data-testid="UserProfileHeader_Items"] span');
  const banner = header.querySelector('a[href$="/header_photo"] img') || header.querySelector('img[src*="profile_banners"]');
  const avatar = header.querySelector('img[src*="profile_images"]');
  const statNodes = mmAll(header, 'a[href$="/verified_followers"], a[href$="/followers"], a[href$="/following"]');
  const stats = {};
  for (const node of statNodes) {
    const href = node.getAttribute('href') || '';
    const value = mmInt(node.textContent);
    const label = (node.textContent || '').toLowerCase();
    if (href.endsWith('/following')) stats.following = value;
    else if (href.endsWith('/verified_followers') || label.includes('followers')) stats.followers = value;
  }
  const verifiedNode = header.querySelector('[data-testid="icon-verified"]');
  return {
    display_name: mmText(nameNode),
    handle: handleNode ? (mmText(handleNode) || '').replace(/^@/, '') : null,
    bio: mmText(bioNode),
    location: mmText(locationNode),
    website: mmText(urlNode) || mmHref(urlNode),
    joined: mmText(joinedNode),
    avatar_url: mmAttr(avatar, 'src'),
    banner_url: mmAttr(banner, 'src'),
    followers: stats.followers ?? null,
    following: stats.following ?? null,
    verified: Boolean(verifiedNode),
    private: Boolean(mmText(header).includes('These posts are protected')),
  };
""",
        {},
    )


# ---------------------------------------------------------------------------
# Weibo topic and profile observation
# ---------------------------------------------------------------------------


def weibo_topic_expression() -> str:
    """Read visible standard-topic feed cards and their outer posters.

    The outer poster is the card's own author. A quoted/forwarded inner author is
    returned separately so the shared normalizer can refuse to treat it as a
    topic participant.
    """

    return _expression(
        """
  const cards = mmAll(document, '#pl_feedlist_index .card-wrap[mid], .card-wrap[mid]').slice(0, mmOptions.maxItems);
  const posts = [];
  for (const card of cards) {
    const mid = mmAttr(card, 'mid');
    const from = card.querySelector('.from a');
    const href = mmHref(from);
    const authorDomain = href ? (new URL(href).pathname.split('/')[1] || null) : null;
    const authorLink = card.querySelector('.info .name a, .name a');
    const authorHref = mmHref(authorLink);
    const authorUid = authorHref ? (authorHref.match(/\\/u\\/(\\d+)|\\/(\\d+)(?:\\?|$)/) || []).slice(1).find(Boolean) || null : null;
    const full = card.querySelector('[node-type="feed_list_content_full"]');
    const short = card.querySelector('[node-type="feed_list_content"]');
    const forwarded = card.querySelector('.card-comment, .comment');
    const retweetAuthor = forwarded ? mmText(forwarded.querySelector('.name')) : null;
    const metric = (type) => {
      const node = card.querySelector('[action-type="' + type + '"]');
      return node ? mmInt(node.textContent) : null;
    };
    posts.push({
      mid,
      text: mmText(full || short || card.querySelector('.card-feed .content')),
      truncated: Boolean(short && !full),
      date_text: mmText(from),
      author_name: mmText(card.querySelector('.info .name, .name')),
      author_domain: authorDomain,
      author_uid: authorUid,
      author_href: authorHref,
      retweet_author_name: retweetAuthor,
      liked: metric('feed_list_like'),
      comments: metric('feed_list_comment'),
      shares: metric('feed_list_forward'),
      collected: metric('feed_list_favorite'),
      source: mmText(card.querySelector('.from')),
    });
  }
  const next = document.querySelector('.m-page a.next');
  return { posts, next_page_url: mmHref(next) };
""",
        {"maxItems": MAX_ITEMS},
    )


def weibo_profile_expression() -> str:
    """Read the visible public fields of a Weibo user homepage.

    Fields the page does not render stay ``null``; abbreviated counts keep their
    original display string next to the parsed number so precision is explicit.
    """

    return _expression(
        """
  const scope = document.querySelector('.ProfileHeader, .profile-header, #Pl_Official_Headerv6__1, .WB_frame') || document;
  const nameNode = scope.querySelector('.ProfileHeader_name, .username, h1');
  const avatar = scope.querySelector('.ProfileHeader_avatar img, .photo_wrap img, .avatar img');
  const bioNode = scope.querySelector('.ProfileHeader_info, .description, .profile-info');
  const verifyNode = scope.querySelector('.ProfileHeader_verify, .icon_verify, .vip-icon');
  const statNodes = mmAll(scope, '.ProfileHeader_num, .profile_num, .num');
  const unique = (selector) => mmText(scope.querySelector(selector));
  const count = (selector) => {
    const node = scope.querySelector(selector);
    return node ? mmInt(node.textContent) : null;
  };
  const metaItems = mmAll(scope, '.ProfileHeader_info_item, .profile-info-item').map(mmText).filter(Boolean);
  const labelNodes = mmAll(scope, '.ProfileHeader_tag, .profile-tag, .tag').map(mmText).filter(Boolean);
  return {
    display_name: mmText(nameNode),
    avatar_url: mmAttr(avatar, 'src'),
    bio: mmText(bioNode),
    verified: Boolean(verifyNode),
    verify_text: mmText(verifyNode),
    followers_text: unique('.ProfileHeader_followers, .followers, [href*="fans"]'),
    followers: count('.ProfileHeader_followers .num, .followers .num, [href*="fans"] .num'),
    following_text: unique('.ProfileHeader_following, .following, [href*="follow"]'),
    following: count('.ProfileHeader_following .num, .following .num, [href*="follow"] .num'),
    posts_text: unique('.ProfileHeader_posts, .statuses, [href*="profile"]'),
    posts: count('.ProfileHeader_posts .num, .statuses .num, [href*="profile"] .num'),
    meta_items: metaItems.slice(0, 16),
    tags: labelNodes.slice(0, 16),
    stats_text: statNodes.slice(0, 8).map(mmText).filter(Boolean),
  };
""",
        {},
    )


# ---------------------------------------------------------------------------
# generic list extraction for the legacy four platforms
# ---------------------------------------------------------------------------


#: Legacy list-mode selectors. These cover only the visible card fields; detail,
#: screenshot and comment work stays a CDP-only capability.
LEGACY_LIST_SELECTORS: dict[str, str] = {
    "bilibili": ".bili-dyn-list__item, .feed-card, .bili-video-card",
    "xhs": "section.note-item, .note-item, .feeds-page .note-item",
    "douyin": "[data-e2e='user-post-item'], ul[data-e2e='scroll-list'] li",
    "weibo": "#pl_feedlist_index .card-wrap[mid], .card-wrap[mid]",
}


def legacy_list_expression(platform: str) -> str:
    selector = LEGACY_LIST_SELECTORS.get(platform)
    if selector is None:
        raise ExtractionError("unsupported-platform")
    return _expression(
        """
  const cards = mmAll(document, mmOptions.selector).slice(0, mmOptions.maxItems);
  const items = [];
  for (const card of cards) {
    if (!mmVisible(card)) continue;
    const links = mmAll(card, 'a[href]').map(mmHref).filter(Boolean);
    const text = mmText(card);
    items.push({
      text: text ? text.slice(0, mmOptions.maxTextChars) : null,
      links: links.slice(0, 8),
      title: mmText(card.querySelector('h1, h2, h3, .title, .note-title, .bili-video-card__info--tit')),
      author: mmText(card.querySelector('.name, .author, .bili-video-card__info--author, .user-name')),
      date_text: mmText(card.querySelector('.date, .time, time, .bili-video-card__stats__duration')),
      raw: mmAttr(card, 'data-note-id') || mmAttr(card, 'data-e2e') || mmAttr(card, 'mid'),
      pinned: Boolean(card.querySelector('[class*="pinned"], [class*="top-tag"], .top-tag')),
    });
  }
  return { items };
""",
        {
            "selector": selector,
            "maxItems": MAX_ITEMS,
            "maxTextChars": MAX_TEXT_CHARS,
        },
    )


#: Stable markers inside each probe's options payload. Tests and fakes use these
#: so they never have to guess which probe is asking by matching loose text.
PROBE_MARKERS: dict[str, str] = {
    # The risk and login probes share their option shape, so they are marked by
    # the distinguishing selector each one carries.
    "risk": '"selectors":["' + RISK_SELECTORS[0] + '"',
    "login": '"selectors":["' + LOGIN_SELECTORS[0] + '"',
    # The field extractors are marked by a selector that only they query.
    "weibo_profile": "ProfileHeader_avatar",
    "weibo_topic": "feed_list_content",
    "x_posts": "tweetPhoto",
    "x_profile": "UserDescription",
}


def probe_kind(expression: object) -> str | None:
    """Identify which shared extractor produced one expression, if any."""

    if not isinstance(expression, str):
        return None
    if "mmOptions" not in expression:
        return None
    for name, marker in PROBE_MARKERS.items():
        if marker in expression:
            return name
    return None


def as_mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def as_items(value: Any) -> list[Any]:
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return list(value)
    return []


__all__ = [
    "ExtractionError",
    "PROBE_MARKERS",
    "LEGACY_LIST_SELECTORS",
    "LOGIN_REQUIRED_PHRASES",
    "LOGIN_SELECTORS",
    "MAX_ITEMS",
    "MAX_TEXT_CHARS",
    "RISK_PHRASES",
    "RISK_SELECTORS",
    "as_items",
    "as_mapping",
    "legacy_list_expression",
    "probe_kind",
    "login_expression",
    "risk_expression",
    "weibo_profile_expression",
    "weibo_topic_expression",
    "x_posts_expression",
    "x_profile_expression",
]
