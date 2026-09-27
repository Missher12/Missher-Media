"""Real plan persistence consumed through the public controller/history boundary."""
import json
import os
from pathlib import Path
from subprocess import CompletedProcess

import pytest

from runtime.media_missher_runtime.cli import main
from runtime.media_missher_runtime.platforms.weibo_topic import parse_topic_input, standard_topic_url
from media_missher_history import load_run, export_selected_run
from run_collection import _plan_summary


class Dispatcher:
    async def __aenter__(self): return self
    async def __aexit__(self, *args): pass
    async def preflight(self, requests): pass
    async def collect(self, request):
        return [{"platform": "weibo", "type": "post", "mblog_id": "123", "link": "https://weibo.com/10/123", "title": "fixture"}]


def test_public_xhs_plan_reaches_real_executor_with_complete_request(tmp_path,capsys):
    calls=[]
    class XhsDispatcher(Dispatcher):
        async def collect(self,request):
            calls.append(request)
            assert request.platform=='xhs' and request.complete is True
            assert request.backend=='cdp' and request.page_cap<=3
            return [{'platform':'xhs','type':'note','note_id':'abcdef0123456789abcdef02','link':'https://www.xiaohongshu.com/explore/abcdef0123456789abcdef02','complete':True}]
    path=tmp_path/'plan.json'
    path.write_text(json.dumps({'schema_version':2,'backend':'cdp','count':1,'targets':[{'platform':'xhs','mode':'creator','uid':'abcdef0123456789abcdef01'}]}));os.chmod(path,0o600)
    code=main(['creator','--targets-json',str(path),'--output-dir',str(tmp_path/'runs')],dispatcher=XhsDispatcher())
    assert len(calls)==1
    assert code==0
    summary=json.loads(capsys.readouterr().out)
    assert summary['status']=='success'


@pytest.mark.parametrize('platform,flags,complete,comments',[
    ('xhs',['--xhs-comments','3'],True,3),
    ('bilibili',['--bilibili-complete'],True,0),
    ('bilibili',[],False,0),
])
def test_public_plan_preserves_collection_options_and_resume_identity(tmp_path,capsys,platform,flags,complete,comments):
    requests=[]
    uid='abcdef0123456789abcdef01' if platform=='xhs' else '123'
    key='note_id' if platform=='xhs' else 'dynamic_id'
    class Capture(Dispatcher):
        async def collect(self,request):
            requests.append(request)
            return [{'platform':platform,'type':'post',key:'123','complete':True}]
    path=tmp_path/'plan.json';path.write_text(json.dumps({'schema_version':2,'count':1,'targets':[{'platform':platform,'mode':'creator','uid':uid}]}));os.chmod(path,0o600)
    args=['creator','--targets-json',str(path),'--output-dir',str(tmp_path/'runs')]
    assert main([*args,*flags],dispatcher=Capture())==0
    run=Path(json.loads(capsys.readouterr().out)['run_dir'])
    assert requests[0].complete==complete and requests[0].comment_limit==comments
    saved=json.loads((run/'plan.json').read_text())
    assert saved['xhs_comments']==comments and saved['bilibili_complete']==(platform=='bilibili' and complete)
    before={str(p.relative_to(run)):p.read_bytes() for p in run.rglob('*') if p.is_file()}
    requests.clear()
    changed=['--xhs-comments','4'] if platform=='xhs' else [] if complete else ['--bilibili-complete']
    assert main([*args,*changed,'--resume-run',run.name],dispatcher=Capture())==78
    assert requests==[]
    assert before=={str(p.relative_to(run)):p.read_bytes() for p in run.rglob('*') if p.is_file()}


def test_direct_envelope_uses_plan_executor_and_freezes_comments(tmp_path,capsys):
    calls=[]
    class Capture(Dispatcher):
        async def collect(self,request):
            calls.append(request)
            return [{'platform':'xhs','type':'post','note_id':'123','complete':True}]
    assert main(['creator','--platforms','xhs','--xhs-uid','abcdef0123456789abcdef01','--xhs-comments','3','--count-mode','fixed','--count','1','--output-dir',str(tmp_path/'runs')],dispatcher=Capture())==0
    run=Path(json.loads(capsys.readouterr().out)['run_dir'])
    assert json.loads((run/'plan.json').read_text())['xhs_comments']==3
    assert calls[0].comment_limit==3


@pytest.mark.parametrize('platform,flags,expected_complete,expected_comments',[
    ('xhs',['--xhs-comments','3'],True,3),
    ('bilibili',['--bilibili-complete'],True,0),
])
def test_wrapper_to_actual_plan_executor_preserves_advanced_options(tmp_path,monkeypatch,capsys,platform,flags,expected_complete,expected_comments):
    import io
    from contextlib import redirect_stdout
    from types import SimpleNamespace
    import run_collection,media_missher_adapter
    profile=tmp_path/'profile.json';profile.write_text('{}');os.chmod(profile,0o600)
    layout=SimpleNamespace(python=Path('/python'),current=tmp_path/'current',home=tmp_path/'runtime')
    monkeypatch.setattr(run_collection,'resolve_runtime_layout',lambda **_:layout)
    monkeypatch.setattr(run_collection,'_profile_identity',lambda *_:'a'*64)
    calls=[]
    class Capture(Dispatcher):
        async def collect(self,request):
            calls.append(request)
            return [{'platform':platform,'type':'post','note_id':'123','complete':True}] if platform=='xhs' else [{'platform':platform,'type':'post','dynamic_id':'123','complete':True}]
    def execute(command,**kwargs):
        output=io.StringIO()
        with redirect_stdout(output):code=main(list(command.argv[2:]),dispatcher=Capture())
        out=kwargs['run_dir']/'stdout.log';out.write_text(output.getvalue())
        return SimpleNamespace(returncode=code,stdout_path=out)
    monkeypatch.setattr(media_missher_adapter,'execute_engine',execute)
    uid='abcdef0123456789abcdef01' if platform=='xhs' else '123'
    assert run_collection.main(['--profile',str(profile),'--platform',platform,f'--{platform}-uid',uid,'--count','1','--run-deadline','60',*flags,'--data-root',str(tmp_path/'runs'),'--json-summary'])==0
    assert len(calls)==1 and calls[0].complete==expected_complete and calls[0].comment_limit==expected_comments


def test_search_wrapper_envelope_reaches_runtime_search_plan(tmp_path,monkeypatch,capsys):
    import io
    from contextlib import redirect_stdout
    from types import SimpleNamespace
    import run_collection,media_missher_adapter
    profile=tmp_path/'profile.json';profile.write_text('{}');os.chmod(profile,0o600)
    layout=SimpleNamespace(python=Path('/python'),current=tmp_path/'current',home=tmp_path/'runtime')
    monkeypatch.setattr(run_collection,'resolve_runtime_layout',lambda **_:layout)
    monkeypatch.setattr(run_collection,'_profile_identity',lambda *_:'a'*64)
    calls=[]
    class Capture(Dispatcher):
        async def collect(self,request):
            calls.append(request)
            return [{'platform':'weibo','type':'post','mblog_id':'123'}]
    def execute(command,**kwargs):
        output=io.StringIO()
        with redirect_stdout(output):code=main(list(command.argv[2:]),dispatcher=Capture())
        out=kwargs['run_dir']/'stdout.log';out.write_text(output.getvalue())
        return SimpleNamespace(returncode=code,stdout_path=out)
    monkeypatch.setattr(media_missher_adapter,'execute_engine',execute)
    assert run_collection.main(['--profile',str(profile),'--platform','weibo','--search','fixture','--count','1','--run-deadline','60','--data-root',str(tmp_path/'runs'),'--json-summary'])==0
    assert len(calls)==1 and calls[0].keyword=='fixture' and calls[0].uid is None


@pytest.mark.parametrize('backend,flags,expected_backend,expected_mode,expected_comments,expected_screenshot',[
    ('computer_use',[],None,None,None,None),
    ('cdp',[],'cdp','best_effort',3,'opened'),
    ('cdp',['--xhs-comments','0','--screenshot-mode','off'],'cdp','best_effort',0,'off'),
    ('cdp',['--count-mode','fixed','--count','1'],'cdp','fixed',3,'opened'),
    ('computer_use',['--backend','cdp'],'cdp','best_effort',3,'opened'),
    ('browserskill',[],None,None,None,None),
])
def test_private_plan_presence_priority_through_public_wrapper(tmp_path,monkeypatch,capsys,backend,flags,expected_backend,expected_mode,expected_comments,expected_screenshot):
    import io
    from contextlib import redirect_stdout
    from types import SimpleNamespace
    import run_collection,media_missher_adapter
    profile=tmp_path/'profile.json';profile.write_text(json.dumps({'backend':'computer_use'}));os.chmod(profile,0o600)
    path=tmp_path/'plan.json';path.write_text(json.dumps({'schema_version':2,'backend':backend,'count':1,'count_mode':'best_effort','xhs_comments':3,'screenshot_mode':'opened','allow_navigation':True,'targets':[{'platform':'xhs','mode':'creator','uid':'abcdef0123456789abcdef01'}]}));os.chmod(path,0o600)
    before=path.read_bytes()
    layout=SimpleNamespace(python=Path('/python'),current=tmp_path/'current',home=tmp_path/'runtime')
    monkeypatch.setattr(run_collection,'resolve_runtime_layout',lambda **_:layout)
    monkeypatch.setattr(run_collection,'_profile_identity',lambda *_:'a'*64)
    calls=[];commands=[]
    class Capture(Dispatcher):
        last_exhausted=True
        async def collect(self,request):
            calls.append(request)
            return [{'platform':'xhs','type':'post','note_id':'123','complete':True}]
    def execute(command,**kwargs):
        commands.append(command.argv)
        output=io.StringIO()
        with redirect_stdout(output):code=main(list(command.argv[2:]),dispatcher=Capture())
        out=kwargs['run_dir']/'stdout.log';out.write_text(output.getvalue())
        return SimpleNamespace(returncode=code,stdout_path=out)
    monkeypatch.setattr(media_missher_adapter,'execute_engine',execute)
    code=run_collection.main(['--profile',str(profile),'--targets-json',str(path),*flags,'--data-root',str(tmp_path/'runs'),'--json-summary'])
    if expected_backend is None:
        assert code==1 and calls==[] and commands==[]
        assert not (tmp_path/'runs').exists()
    else:
        assert len(calls)==1 and calls[0].backend==expected_backend
        assert calls[0].count_mode==expected_mode and calls[0].comment_limit==expected_comments
        assert calls[0].screenshot_mode==expected_screenshot
        if '--backend' not in flags:assert '--backend' not in commands[0]
        if '--count-mode' not in flags:assert '--count-mode' not in commands[0]
        frozen=json.loads((next((tmp_path/'runs').glob('run-*'))/'plan.json').read_text())
        assert frozen['xhs_comments']==expected_comments and frozen['screenshot_mode']==expected_screenshot
    assert path.read_bytes()==before


@pytest.mark.parametrize('kind',['public','symlink','oversize','duplicate'])
def test_wrapper_rejects_untrusted_plan_before_dispatch(tmp_path,monkeypatch,kind):
    import run_collection,media_missher_adapter
    path=tmp_path/'plan.json';path.write_text('{}');os.chmod(path,0o600)
    if kind=='public':os.chmod(path,0o644)
    elif kind=='symlink':
        target=tmp_path/'original.json';path.rename(target);path.symlink_to(target)
    elif kind=='oversize':path.write_bytes(b' '*(2*1024*1024+1))
    else:path.write_text('{"backend":"cdp","backend":"computer_use"}')
    monkeypatch.setattr(media_missher_adapter,'execute_engine',lambda *_a,**_k:pytest.fail('unsafe plan dispatched'))
    assert run_collection.main(['--targets-json',str(path),'--data-root',str(tmp_path/'runs')])==1
    assert not (tmp_path/'runs').exists()


@pytest.mark.parametrize('platform,flags,extra',[
    ('xhs',[],{'complete':False}),
    ('bilibili',['--bilibili-complete'],{'complete':False}),
    ('bilibili',['--screenshot-mode','all','--allow-navigation'],{'screenshot_status':'failed'}),
])
def test_full_count_with_incomplete_requested_evidence_remains_partial(tmp_path,capsys,platform,flags,extra):
    class Partial(Dispatcher):
        async def collect(self,request):
            return [{'platform':platform,'type':'post',('note_id' if platform=='xhs' else 'dynamic_id'):'123','link':'https://example.invalid/fixture/123',**extra}]
    uid='abcdef0123456789abcdef01' if platform=='xhs' else '123'
    path=tmp_path/'plan.json';path.write_text(json.dumps({'schema_version':2,'count':1,'targets':[{'platform':platform,'mode':'creator','uid':uid}]}));os.chmod(path,0o600)
    assert main(['creator','--targets-json',str(path),*flags,'--output-dir',str(tmp_path/'runs')],dispatcher=Partial())==1
    summary=json.loads(capsys.readouterr().out)
    assert summary['status']=='partial'
    run=Path(summary['run_dir'])
    assert load_run(run.parent,run.name)['counts'][platform]==1
    assert json.loads((run/'manifest.json').read_text())['status']=='partial'
    expected='screenshot-shortfall' if 'screenshot_status' in extra else 'incomplete-record'
    assert json.loads((run/'manifest.json').read_text())['diagnostics'][platform]['code']==expected
    for filename in ['run_manifest.json','summary.json','run-result.json']:
        assert json.loads((run/filename).read_text())['status']=='partial'
    assert export_selected_run(run.parent,run.name,record_kinds=['posts'],format_name='json')['rows']==1
    before={str(p.relative_to(run)):p.read_bytes() for p in run.rglob('*') if p.is_file()}
    class Forbidden(Dispatcher):
        async def __aenter__(self):pytest.fail('incomplete prefix skipped as completed')
    assert main(['creator','--targets-json',str(path),*flags,'--resume-run',run.name,'--output-dir',str(tmp_path/'runs')],dispatcher=Forbidden())==78
    assert before=={str(p.relative_to(run)):p.read_bytes() for p in run.rglob('*') if p.is_file()}


@pytest.mark.parametrize('platform,extra',[('xhs',{'complete':True,'liked':0,'comments':0}),('bilibili',{'liked':0})])
def test_plan_keeps_known_zero_and_does_not_require_unrequested_complete(tmp_path,capsys,platform,extra):
    class Complete(Dispatcher):
        async def collect(self,request):
            return [{'platform':platform,'type':'post',('note_id' if platform=='xhs' else 'dynamic_id'):'123','link':'https://example.invalid/fixture/123',**extra}]
    uid='abcdef0123456789abcdef01' if platform=='xhs' else '123'
    path=tmp_path/'plan.json';path.write_text(json.dumps({'schema_version':2,'count':1,'targets':[{'platform':platform,'mode':'creator','uid':uid}]}));os.chmod(path,0o600)
    assert main(['creator','--targets-json',str(path),'--output-dir',str(tmp_path/'runs')],dispatcher=Complete())==0
    summary=json.loads(capsys.readouterr().out);run=Path(summary['run_dir'])
    assert summary['status']=='success'
    loaded=load_run(run.parent,run.name)
    assert loaded['records'][0]['liked']==0
    assert loaded['manifest']['status']=='complete'


def test_risk_prefix_wins_over_incomplete_evidence_and_exports(tmp_path,capsys):
    from runtime.media_missher_runtime.cli import RiskStop
    class Risk(Dispatcher):
        async def collect(self,request):raise RiskStop('challenge')
        def partial_records(self,platform):return [{'platform':'xhs','type':'post','note_id':'123','link':'https://www.xiaohongshu.com/explore/123','complete':False}]
    path=tmp_path/'plan.json';path.write_text(json.dumps({'schema_version':2,'count':1,'targets':[{'platform':'xhs','mode':'creator','uid':'abcdef0123456789abcdef01'}]}));os.chmod(path,0o600)
    assert main(['creator','--targets-json',str(path),'--output-dir',str(tmp_path/'runs')],dispatcher=Risk())==75
    summary=json.loads(capsys.readouterr().out);run=Path(summary['run_dir'])
    assert summary['status']=='risk-stopped'
    for filename in ['manifest.json','run_manifest.json','summary.json','run-result.json']:
        assert json.loads((run/filename).read_text())['status']=='risk-stopped'
    exported=export_selected_run(run.parent,run.name,record_kinds=['posts'],format_name='json')
    assert exported['rows']==1 and exported['source_status']=='risk-stopped'


@pytest.mark.parametrize('target,flags',[
    ({'platform':'weibo','mode':'creator','uid':'123'},['--xhs-comments','3']),
    ({'platform':'bilibili','mode':'search','keyword':'fixture'},['--bilibili-complete']),
    ({'platform':'xhs','mode':'search','keyword':'fixture'},['--xhs-comments','3']),
    ({'platform':'xhs','mode':'search','keyword':'fixture'},['--xhs-complete']),
    ({'platform':'xhs','mode':'search','keyword':'fixture'},['--complete']),
])
def test_inapplicable_plan_options_refuse_before_dispatch(tmp_path,target,flags):
    class Forbidden(Dispatcher):
        async def __aenter__(self):pytest.fail('invalid option reached browser')
    path=tmp_path/'plan.json';path.write_text(json.dumps({'schema_version':2,'targets':[target]}));os.chmod(path,0o600)
    assert main(['creator','--targets-json',str(path),*flags,'--output-dir',str(tmp_path/'runs')],dispatcher=Forbidden())==78
    assert not (tmp_path/'runs').exists()


def test_plan_controller_history_and_selected_export(tmp_path, capsys):
    plan = tmp_path / "plan.json"
    plan.write_text(json.dumps({"schema_version": 1, "targets": [{"platform": "weibo", "mode": "creator", "uid": "10"}], "count": 1}))
    os.chmod(plan, 0o600)
    root = tmp_path / "runs"
    code = main(["creator", "--targets-json", str(plan), "--output-dir", str(root)], dispatcher=Dispatcher())
    captured = capsys.readouterr()
    summary = _plan_summary(CompletedProcess([], code, captured.out.encode(), captured.err.encode()))
    assert summary["status"] == "success"
    from pathlib import Path
    run = Path(summary["run_dir"])
    assert str(run / "manifest.json") in summary["evidence"]
    loaded = load_run(root, run.name)
    assert loaded["manifest"]["backend"] == "cdp"
    assert len(loaded["records"]) == 1
    exported = export_selected_run(root, run.name, record_kinds=["posts"], fields=["mblog_id"], format_name="json")
    assert exported["rows"] == 1
    assert exported["source_backend"] == "cdp"
    assert not list(run.glob("*.xlsx"))


def test_standard_topic_url_roundtrip():
    assert parse_topic_input(standard_topic_url("旅行")).name == "旅行"


@pytest.mark.parametrize("host", ["s.weibo.com.evil.test", "evil.test", "weibo.com.evil.test"])
def test_topic_rejects_impostor_hosts(host):
    with pytest.raises(RuntimeError, match="topic-host-unsupported"):
        parse_topic_input(f"https://{host}/weibo?q=%23topic%23")


def test_plan_topic_keeps_all_record_categories(tmp_path, capsys):
    class TopicDispatcher(Dispatcher):
        async def collect(self, request):
            return [
                {"platform": "weibo", "type": "post", "mblog_id": "123", "link": "https://weibo.com/10/123"},
                {"platform": "weibo", "type": "topic_participant", "uid": "10", "topic": "旅行", "link": "https://weibo.com/u/10"},
                {"platform": "weibo", "type": "user_profile", "uid": "10", "link": "https://weibo.com/u/10", "profile_status": "complete"},
            ]
    root = tmp_path / "runs"
    code = main(["creator", "--topic", "旅行", "--count", "1", "--output-dir", str(root)], dispatcher=TopicDispatcher())
    output = capsys.readouterr()
    summary = _plan_summary(CompletedProcess([], code, output.out.encode(), b""))
    assert summary["run_dir"]
    from pathlib import Path
    loaded = load_run(root, Path(summary["run_dir"]).name)
    assert {row["type"] for row in loaded["records"]} == {"post", "topic_participant", "user_profile"}
    assert len(loaded["records"]) == 3


def test_executor_passes_batch_exclusions_and_page_budget():
    import asyncio
    from argparse import Namespace
    from runtime.media_missher_runtime.cli import PlanExecutor
    from runtime.media_missher_runtime.contracts import CollectionPlan, Target
    from runtime.media_missher_runtime.plan_runner import TaskContext
    from runtime.media_missher_runtime.batch_policy import policy_for
    target = Target(platform="weibo", mode="creator", uid="10")
    plan = CollectionPlan(targets=(target,), count_mode="best_effort")
    context = TaskContext(target=target, task_index=0, task_total=1, count_mode="best_effort", count=10, budget=10, deadline_seconds=30, policy=policy_for("weibo"), backend="cdp", evidence_level="response", excluded_ids=("weibo:post:mblog_id:123",))
    class CheckingDispatcher(Dispatcher):
        async def collect(self, request):
            assert request.exclude_ids == ("123",)
            assert request.page_cap == context.policy.batch_pages
            return []
    executor = PlanExecutor(dispatcher=CheckingDispatcher(), plan=plan, args=Namespace(screenshot_mode="off"))
    asyncio.run(executor(target, context))


def test_plan_risk_keeps_prefix_and_does_not_start_next_target(tmp_path, capsys):
    from runtime.media_missher_runtime.cli import RiskStop
    class RiskDispatcher(Dispatcher):
        calls = 0
        async def collect(self, request):
            self.calls += 1
            raise RiskStop("http-429")
        def partial_records(self, platform):
            return [{"platform": "weibo", "type": "post", "mblog_id": "123", "link": "https://weibo.com/10/123"}]
    plan = tmp_path / "plan.json"
    plan.write_text(json.dumps({"schema_version": 1, "targets": [{"platform": "weibo", "mode": "creator", "uid": uid} for uid in ("10", "20")], "count": 1}))
    os.chmod(plan, 0o600)
    dispatcher = RiskDispatcher()
    code = main(["creator", "--targets-json", str(plan), "--output-dir", str(tmp_path / "runs")], dispatcher=dispatcher)
    output = capsys.readouterr()
    summary = _plan_summary(CompletedProcess([], code, output.out.encode(), output.err.encode()))
    assert summary["status"] == "risk-stopped"
    assert dispatcher.calls == 1
    from pathlib import Path
    run = Path(summary["run_dir"])
    loaded = load_run(run.parent, run.name)
    assert len(loaded["records"]) == 1




@pytest.mark.parametrize("target", [{"platform": "x", "mode": "creator", "handle": "fixture"}, {"platform": "weibo", "mode": "topic", "topic": "旅行"}])
def test_controller_plan_targets_do_not_require_legacy_profile_uids(tmp_path, monkeypatch, capsys, target):
    import run_collection
    plan = tmp_path / "plan.json"
    plan.write_text(json.dumps({"schema_version": 1, "targets": [target], "count": 1}))
    os.chmod(plan, 0o600)
    calls = []
    def forward(args, **kwargs):
        calls.append(args.targets_json)
        return 0
    monkeypatch.setattr(run_collection, "_forward_plan", forward)
    assert run_collection.main(["--targets-json", str(plan), "--platform", target["platform"], "--data-root", str(tmp_path / "runs")]) == 0
    assert calls == [plan]


@pytest.mark.parametrize("failure", [TimeoutError, __import__('asyncio').CancelledError])
def test_interrupted_plan_keeps_exportable_prefix(tmp_path, capsys, failure):
    class InterruptedDispatcher(Dispatcher):
        async def collect(self, request): raise failure()
        def partial_records(self, platform):
            return [{"platform": "weibo", "type": "post", "mblog_id": "123", "link": "https://weibo.com/10/123"}]
    code = main(["creator", "--topic", "旅行", "--count", "2", "--output-dir", str(tmp_path / "runs")], dispatcher=InterruptedDispatcher())
    output = capsys.readouterr()
    summary = _plan_summary(CompletedProcess([], code, output.out.encode(), output.err.encode()))
    assert summary["status"] == "partial"
    from pathlib import Path
    run = Path(summary["run_dir"])
    loaded = load_run(run.parent, run.name)
    assert loaded["manifest"]["status"] == "partial"
    assert len(loaded["records"]) == 1
    assert export_selected_run(run.parent, run.name, record_kinds=["posts"], format_name="json")["source_status"] == "partial"


def test_partial_plan_has_consistent_saved_status(tmp_path, capsys):
    class PartialDispatcher(Dispatcher):
        async def collect(self, request):
            return [{"platform": request.platform, {"weibo": "mblog_id", "bilibili": "dynamic_id"}[request.platform]: str(i), "type": "post", "link": "https://example.invalid/item"} for i in range(2 if request.platform == "weibo" else 1)]
    plan = tmp_path / "plan.json"
    plan.write_text(json.dumps({"schema_version": 1, "targets": [{"platform": p, "mode": "creator", "uid": "10"} for p in ["weibo", "bilibili"]], "count": 2}))
    os.chmod(plan, 0o600)
    code = main(["creator", "--targets-json", str(plan), "--output-dir", str(tmp_path / "runs")], dispatcher=PartialDispatcher())
    output = capsys.readouterr()
    summary = _plan_summary(CompletedProcess([], code, output.out.encode(), output.err.encode()))
    from pathlib import Path
    run = Path(summary["run_dir"])
    assert summary["status"] == "partial"
    for name in ["manifest.json", "run_manifest.json", "summary.json", "run-result.json"]:
        assert json.loads((run / name).read_text())["status"] == "partial"


def test_resume_skips_completed_target_and_preserves_parent(tmp_path, capsys):
    class First(Dispatcher):
        async def collect(self, request):
            count = 2 if request.uid == "10" else 1
            return [{"platform": "weibo", "type": "post", "mblog_id": request.uid + str(i), "link": f"https://weibo.com/{request.uid}/{i}"} for i in range(count)]
    class Second(Dispatcher):
        async def collect(self, request):
            assert request.uid == "20"
            assert request.exclude_ids == ("200",)
            return [{"platform": "weibo", "type": "post", "mblog_id": "201", "link": "https://weibo.com/20/1"}]
    plan = tmp_path / "plan.json"
    plan.write_text(json.dumps({"schema_version": 1, "targets": [{"platform": "weibo", "mode": "creator", "uid": uid} for uid in ("10", "20")], "count": 2}))
    os.chmod(plan, 0o600)
    args = ["creator", "--targets-json", str(plan), "--output-dir", str(tmp_path / "runs")]
    main(args, dispatcher=First())
    from pathlib import Path
    first = Path(json.loads(capsys.readouterr().out)["run_dir"])
    before = {str(p.relative_to(first)): p.read_bytes() for p in first.rglob("*") if p.is_file()}
    assert main([*args, "--resume-run", first.name], dispatcher=Second()) == 0
    second = Path(json.loads(capsys.readouterr().out)["run_dir"])
    assert second != first
    assert len(load_run(second.parent, second.name)["records"]) == 4
    assert before == {str(p.relative_to(first)): p.read_bytes() for p in first.rglob("*") if p.is_file()}


def test_topic_profile_risk_propagates_before_next_homepage():
    import asyncio
    from runtime.media_missher_runtime.platforms.weibo_topic import TopicCollector, parse_topic_input, CollectionStopped
    class Collector(TopicCollector):
        async def read_profile(self, uid, url): raise CollectionStopped("http-429")
    collector = Collector(request=None, browser=None, topic=parse_topic_input("旅行"))
    with pytest.raises(CollectionStopped):
        asyncio.run(collector.collect_profile("10"))


def test_browser_session_recognizes_x_hosts():
    from runtime.media_missher_runtime.browser import _HOSTS, _ENTRY_URLS
    assert {"x.com", "www.x.com", "twitter.com", "www.twitter.com"} <= _HOSTS["x"]
    assert _ENTRY_URLS["x"] == "https://x.com/home"


def test_forward_plan_uses_owned_engine_lifecycle(tmp_path, monkeypatch, capsys):
    import run_collection
    from argparse import Namespace
    from types import SimpleNamespace
    import media_missher_adapter
    profile = tmp_path / 'profile.json'
    profile.write_text('{}'); os.chmod(profile, 0o600)
    args = run_collection.build_parser().parse_args(['--topic', '旅行', '--count', '1', '--json-summary'])
    def execute(command, *, timeout, run_dir, **kwargs):
        assert '--profile-digest' in command.argv
        assert timeout > 0
        out = run_dir / 'stdout.log'; out.write_text(json.dumps({'status':'partial','run_dir':None,'evidence':[],'errors':[]}))
        err = run_dir / 'stderr.log'; err.write_text('')
        return SimpleNamespace(returncode=1,stdout_path=out,stderr_path=err)
    monkeypatch.setattr(media_missher_adapter, 'execute_engine', execute)
    monkeypatch.setattr(run_collection.subprocess, 'run', lambda *a, **k: pytest.fail('unowned subprocess.run'))
    layout=SimpleNamespace(python=Path('/python'),current=tmp_path/'current',home=tmp_path/'runtime')
    assert run_collection._forward_plan(args, layout=layout, data_root=tmp_path/'runs', cdp_url='http://127.0.0.1:9222', backend='cdp', profile_digest='a'*64) == 1
    assert json.loads(capsys.readouterr().out)['status'] == 'partial'


def test_skill_production_entry_preserves_envelope_at_engine_boundary(tmp_path, monkeypatch, capsys):
    import run_collection
    import media_missher_adapter
    from types import SimpleNamespace
    profile=tmp_path/'profile.json';profile.write_text('{}');os.chmod(profile,0o600)
    layout=SimpleNamespace(python=Path('/python'),current=tmp_path/'current',home=tmp_path/'runtime')
    monkeypatch.setattr(run_collection,'resolve_runtime_layout',lambda **_:layout)
    monkeypatch.setattr(run_collection,'_profile_identity',lambda *_:'a'*64)
    calls=[]
    def execute(command,**kwargs):
        calls.append(command.argv)
        out=kwargs['run_dir']/'stdout.log';out.write_text(json.dumps({'status':'partial','run_dir':None,'evidence':[],'errors':[]}))
        return SimpleNamespace(returncode=1,stdout_path=out)
    monkeypatch.setattr(media_missher_adapter,'execute_engine',execute)
    assert run_collection.main(['--profile',str(profile),'--platform','weibo','--weibo-uid','123','--backend','cdp','--count-mode','best_effort','--run-deadline','1800','--allow-navigation','--resume-run','run-parent','--data-root',str(tmp_path/'runs'),'--json-summary'])==1
    argv=calls[0]
    for flag,value in [('--backend','cdp'),('--count-mode','best_effort'),('--run-deadline','1800'),('--weibo-uid','123'),('--resume-run','run-parent'),('--profile-digest','a'*64)]:
        assert argv[argv.index(flag)+1]==value
    assert '--allow-navigation' in argv
    calls.clear()
    assert run_collection.main(['--profile',str(profile),'--platform','weibo','--weibo-uid','123','--backend','computer_use','--data-root',str(tmp_path/'forbidden')])==1
    assert calls==[] and not (tmp_path/'forbidden').exists()


@pytest.mark.parametrize('platform,url,expected', [
    ('weibo','https://weibo.com/u/123','123'),
    ('bilibili','https://space.bilibili.com/123','123'),
    ('xhs','https://www.xiaohongshu.com/user/profile/abcdef0123456789abcdef01','abcdef0123456789abcdef01'),
    ('douyin','https://www.douyin.com/user/MS4wLjAB_fixture','MS4wLjAB_fixture'),
    ('x','https://x.com/Example','example'),
])
def test_creator_homepage_binds_canonical_native_identity(platform,url,expected):
    from runtime.media_missher_runtime.contracts import Target
    target=Target(platform=platform,mode='creator',homepage=url)
    assert (target.handle if platform=='x' else target.uid)==expected


def test_creator_homepage_rejects_conflicting_identity():
    from runtime.media_missher_runtime.contracts import Target, ContractError
    with pytest.raises(ContractError):
        Target(platform='weibo',mode='creator',uid='999',homepage='https://weibo.com/u/123')
