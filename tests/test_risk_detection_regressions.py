"""Execute the real risk JavaScript against synthetic DOMs; no live browser."""
from __future__ import annotations

import json
import shutil
import subprocess
from types import SimpleNamespace

import pytest

from media_missher_runtime.models import CollectionRequest
from media_missher_runtime.browser import _authentication_observation
from media_missher_runtime.page_risk import risk_probe_expression
from media_missher_runtime.platforms import x, xhs
from media_missher_runtime.platforms import _xhs_detail_enrichment as comments


_NODE_FIXTURE = r"""
const fs = require('node:fs');
const vm = require('node:vm');
const {script, fixture} = JSON.parse(fs.readFileSync(0, 'utf8'));
const node = (item = {}) => ({
  isConnected: true, hidden: !!item.hidden,
  innerText: item.text || '', textContent: item.text || '',
  parentElement: item.parentHidden ? {hidden: true, parentElement: null, getAttribute: () => null} : null,
  getAttribute: (name) => name === 'aria-hidden' && item.ariaHidden ? 'true' : null,
  getBoundingClientRect: () => ({width: item.zeroSize ? 0 : 300, height: 100}),
  querySelector: () => null, querySelectorAll: () => [],
  style: {display: item.display || 'block', visibility: item.visibility || 'visible', opacity: item.opacity ?? '1'},
});
const elements = (fixture.nodes || []).map((item) => ({selector: item.selector, node: node(item)}));
const document = {
  body: node({text: fixture.body || ''}),
  readyState: 'complete',
  location: {pathname: fixture.path || '/explore/ordinary-post'},
  querySelectorAll: (selector) => elements.filter((item) => item.selector === selector).map((item) => item.node),
  querySelector: (selector) => elements.find((item) => item.selector === selector)?.node || null,
};
const window = {getComputedStyle: (element) => element.style || {display:'block',visibility:'visible',opacity:'1'}};
let result = vm.runInNewContext(script, {document, window});
if (typeof result === 'function') result = result(fixture.arg);
process.stdout.write(JSON.stringify(result));
"""


def evaluate_js(script, fixture):
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node is required to execute the real risk probe JavaScript")
    result = subprocess.run(
        [node, "-e", _NODE_FIXTURE],
        input=json.dumps({"script": script, "fixture": fixture}),
        text=True, capture_output=True, check=True, timeout=10,
    )
    return json.loads(result.stdout)


@pytest.mark.parametrize("platform", ["xhs", "x", "bilibili", "douyin", "weibo"])
def test_article_risk_terms_are_content_not_a_challenge(platform):
    value = evaluate_js(risk_probe_expression(platform), {
        "body": "今天讨论企业风控系统和验证码组件，文章引用 Rate limit exceeded。",
    })
    assert value == {"risk": False, "reason": None}


@pytest.mark.parametrize("visibility", [
    {"hidden": True}, {"parentHidden": True}, {"ariaHidden": True},
    {"display": "none"}, {"visibility": "hidden"}, {"opacity": "0"}, {"zeroSize": True},
])
def test_hidden_challenge_widgets_do_not_latch_risk(visibility):
    value = evaluate_js(risk_probe_expression("xhs"), {
        "nodes": [{"selector": ".geetest_panel", **visibility}],
    })
    assert value["risk"] is False


@pytest.mark.parametrize("selector", [
    ".geetest_panel", 'iframe[src*="captcha"]', ".captcha_verify_container",
    '[data-testid="challenge-page"]',
])
def test_visible_challenge_widgets_still_stop(selector):
    value = evaluate_js(risk_probe_expression("xhs"), {"nodes": [{"selector": selector}]})
    assert value == {"risk": True, "reason": "challenge-selector"}


@pytest.mark.parametrize("selector", ["#pl_common_error", ".error-page", ".access-denied"])
def test_visible_blocking_prompt_still_stops(selector):
    value = evaluate_js(risk_probe_expression("weibo"), {
        "nodes": [{"selector": selector, "text": "请求过于频繁，请稍后再试"}],
    })
    assert value == {"risk": True, "reason": "请求过于频繁"}


def test_full_page_verification_requires_validation_route():
    assert evaluate_js(risk_probe_expression("x"), {
        "body": "Verify you are human", "path": "/challenge",
    })["risk"] is True
    assert evaluate_js(risk_probe_expression("x"), {
        "body": "Verify you are human", "path": "/alice/status/1",
    })["risk"] is False


def test_post_dialog_risk_words_are_not_a_verification_prompt():
    assert evaluate_js(risk_probe_expression("xhs"), {
        "nodes": [{"selector": '[role="dialog"]', "text": "风控技术分享和验证码教程"}],
    })["risk"] is False
    assert evaluate_js(risk_probe_expression("xhs"), {
        "nodes": [{"selector": '[role="dialog"]', "text": "请完成验证后继续访问"}],
    })["risk"] is True


@pytest.mark.asyncio
async def test_browser_authentication_uses_same_visible_challenge_contract():
    class Page:
        fixture = {"body": "验证码设计文章", "nodes": [{"selector": ".geetest_panel", "parentHidden": True}]}

        async def evaluate(self, script, options):
            return evaluate_js("(" + script + ")", {**self.fixture, "arg": options})

    page = Page()
    assert await _authentication_observation(page, "xhs") == {
        "logged_out": False, "challenge": False, "ready": True,
    }
    page.fixture = {"nodes": [{"selector": ".geetest_panel"}]}
    assert (await _authentication_observation(page, "xhs"))["challenge"] is True


@pytest.mark.asyncio
@pytest.mark.parametrize("reader", [xhs._read_search_cards, xhs._read_detail_html, xhs._read_search_settlement])
async def test_xhs_embedded_extractors_share_the_visible_risk_contract(reader):
    class Page:
        fixture = {"body": "风控知识分享"}

        async def evaluate(self, script):
            return evaluate_js("(" + script + ")", self.fixture)

    page = Page()
    assert (await reader(page))["risk_text"] == ""
    page.fixture = {"nodes": [{"selector": ".geetest_panel"}]}
    assert (await reader(page))["risk_text"] == "challenge-selector"


def test_comment_scripts_ignore_article_terms_but_preserve_real_challenges():
    for script in (comments._READ_COMMENTS_SCRIPT, comments._SCROLL_COMMENTS_SCRIPT):
        assert evaluate_js("(" + script + ")", {"body": "风控知识分享", "arg": 3})["risk_text"] == ""
        assert evaluate_js("(" + script + ")", {
            "nodes": [{"selector": ".geetest_panel"}], "arg": 3,
        })["risk_text"] == "challenge-selector"


@pytest.mark.asyncio
async def test_xhs_uses_scoped_risk_probe_for_live_document_observation():
    class Page:
        fixture = {"body": "风控技术分享及验证码教程"}

        async def evaluate(self, script):
            return evaluate_js("(" + script + ")", self.fixture)

    page = Page()
    await xhs._raise_for_challenge(page)
    page.fixture = {"nodes": [{"selector": ".geetest_panel", "hidden": True}]}
    await xhs._raise_for_challenge(page)
    page.fixture = {"nodes": [{"selector": ".geetest_panel"}]}
    with pytest.raises(xhs.CollectionStopped, match="challenge-selector"):
        await xhs._raise_for_challenge(page)


@pytest.mark.asyncio
@pytest.mark.parametrize("timeout_location", ["exit", "value"])
async def test_x_challenge_after_response_timeout_is_a_risk_stop(timeout_location):
    class Page:
        risk = False
        actions = 0

        async def evaluate(self, _script):
            return {"risk": self.risk, "reason": "challenge-selector" if self.risk else None}

        def expect_response(self, *_args, **_kwargs):
            page = self

            class Expectation:
                async def __aenter__(self):
                    return self

                async def __aexit__(self, *_args):
                    if timeout_location == "exit":
                        page.risk = True
                        raise TimeoutError("synthetic challenge replaced the response")

                @property
                async def value(self):
                    page.risk = True
                    raise TimeoutError("synthetic response wait expired")

            return Expectation()

    page = Page()
    collector = x.XCollector(CollectionRequest(platform="x", uid="alice", count=1), SimpleNamespace())

    async def action():
        page.actions += 1

    with pytest.raises(x.CollectionStopped, match="challenge"):
        await collector._capture_while(page, lambda _: True, action)
    assert page.actions == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("when", ["before", "after", "settle"])
async def test_x_rechecks_risk_around_each_scroll(when):
    class Page:
        risk = when == "before"
        scrolls = 0

        async def evaluate(self, script):
            if "window.scrollTo" in script:
                self.scrolls += 1
                self.risk = when == "after"
                return True
            return {"risk": self.risk}

        async def wait_for_timeout(self, _ms):
            self.risk = when == "settle"

    page = Page()
    with pytest.raises(x.CollectionStopped, match="challenge"):
        await x.XCollector._scroll(page)
        await x.XCollector._settle(page)
    assert page.scrolls == (0 if when == "before" else 1)
