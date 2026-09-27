import asyncio
from dataclasses import replace
from runtime.media_missher_runtime.models import CollectionRequest


def test_two_real_page_batches_advance_without_restarting_target():
    from runtime.media_missher_runtime.page_collection import collect_page
    class Page:
        url = "https://s.weibo.com/weibo?q=fixture"
        position = 0
        async def evaluate(self, expression):
            if 'window.scrollTo' in expression:
                self.position += 1
                return None
            if 'return { items }' in expression:
                return {"items": [{"raw": str(100 + self.position), "links": [f"https://weibo.com/10/{100 + self.position}"], "title": "fixture"}]}
            return {"risk": False, "logged_out": False}
        async def wait_for_timeout(self, milliseconds): pass
    class Browser:
        allow_navigation = True
        page = Page()
        navigations = 0
        def require_page(self, platform): return self.page
        async def navigate(self, page, url, **kwargs):
            self.navigations += 1
            page.url = url
        def publish_progress(self, platform, rows): pass
    async def run():
        browser = Browser()
        request = CollectionRequest(platform="weibo", keyword="fixture", count=1, batch_limit=1, page_cap=2, backend="cdp")
        first = await collect_page(request, browser)
        second = await collect_page(replace(request, continue_page=True, exclude_ids=("100",)), browser)
        assert [r["mblog_id"] for r in first + second] == ["100", "101"]
        assert browser.navigations == 1
        assert browser.last_pages == 2
    asyncio.run(run())


def test_x_honors_explicit_response_body_capability():
    from runtime.media_missher_runtime.platforms.x import XCollector
    class AccessibilityObservation:
        supports_response_bodies = False
        def expect_response(self, *_args): raise AssertionError("no response body capability")
    assert XCollector._can_observe_responses(AccessibilityObservation()) is False


def test_x_unreadable_risk_probe_fails_closed():
    import pytest
    from runtime.media_missher_runtime.platforms.x import _raise_for_page_risk
    class Page:
        async def evaluate(self, expression): raise RuntimeError("unavailable")
    with pytest.raises(Exception):
        asyncio.run(_raise_for_page_risk(Page()))


def test_two_topics_visit_one_profile_and_keep_each_post_relation(monkeypatch):
    from runtime.media_missher_runtime.platforms import weibo_topic
    from runtime.media_missher_runtime.plan_runner import PlanRunner
    from runtime.media_missher_runtime.cli import PlanExecutor
    from runtime.media_missher_runtime.contracts import CollectionPlan, Target
    from argparse import Namespace
    calls = []
    class Collector(weibo_topic.TopicCollector):
        async def collect_posts(self):
            mid = "101" if self.topic.name == "one" else "102"
            self.registry.register(uid="10", handle=None, display_name="fixture", topic=self.topic, post_id=mid, observed_at="2026-09-20T00:00:00Z", via_repost=False)
            return [{"platform": "weibo", "type": "post", "mblog_id": mid, "link": f"https://weibo.com/10/{mid}"}]
        async def read_profile(self, uid, url):
            calls.append(uid)
            return {"uid": uid, "name": "fixture"}
    monkeypatch.setattr(weibo_topic.TopicCollector, 'build', classmethod(lambda cls, request, browser: Collector(request=request, browser=browser, topic=weibo_topic.parse_topic_input(request.topic))))
    class Dispatcher:
        async def collect(self, request): return await weibo_topic.collect_topic(request, object())
    plan = CollectionPlan(targets=tuple(Target(platform="weibo", mode="topic", topic=topic, topic_kind="topic") for topic in ["one", "two"]), count=1)
    executor = PlanExecutor(dispatcher=Dispatcher(), plan=plan, args=Namespace(screenshot_mode="off"))
    result = asyncio.run(PlanRunner(plan, execute_task=executor).run())
    assert calls == ["10"]
    relations = [row for row in result.all_records() if row.get("type") == "topic_participant_relation"]
    assert {(row["topic"], row["post_id"], row["uid"]) for row in relations} == {("one", "101", "10"), ("two", "102", "10")}
