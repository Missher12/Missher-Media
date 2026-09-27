import pytest
from runtime.media_missher_runtime import contracts


def test_chrome_cdp_is_the_only_active_backend():
    assert contracts.BACKENDS == ('cdp',)
    assert contracts.normalize_backend(None) == 'cdp'
    with pytest.raises(contracts.ContractError, match='backend-retired-computer-use'):
        contracts.normalize_backend('computer_use')


def test_retired_preference_never_falls_back():
    with pytest.raises(contracts.ContractError, match='backend-retired-browserskill'):
        contracts.normalize_backend(None, preference='browserskill')


def test_old_cdp_plan_is_upgraded_without_global_schema_rewrite():
    plan=contracts.CollectionPlan.from_json({'schema_version':1,'backend':'cdp','targets':[{'platform':'weibo','mode':'creator','uid':'10'}]})
    assert plan.to_json()['schema_version'] == 2
    assert contracts.SCHEMA_VERSION == 1


def test_old_plan_cannot_claim_new_host_protocol():
    with pytest.raises(contracts.ContractError, match='backend-retired-computer-use'):
        contracts.CollectionPlan.from_json({'schema_version':1,'backend':'computer_use','targets':[{'platform':'x','mode':'creator','handle':'fixture'}]})


def test_computer_use_without_host_never_constructs_cdp(tmp_path, monkeypatch, capsys):
    from runtime.media_missher_runtime import cli
    monkeypatch.setattr(cli.RuntimeDispatcher, '__init__', lambda *a, **k: pytest.fail('CDP fallback'))
    code=cli.main(['creator','--platform','weibo','--weibo-uid','10','--backend','computer_use','--output-dir',str(tmp_path/'runs')])
    assert code == 78
    assert 'backend-retired-computer-use' in capsys.readouterr().err
    assert not (tmp_path/'runs').exists()


def _old_run(tmp_path, version, backend="browserskill"):
    import json, os
    root=tmp_path/'runs';root.mkdir(mode=0o700)
    run=root/'run-old';run.mkdir(mode=0o700)
    records=[{'platform':'weibo','type':'post','mblog_id':'123','link':'https://weibo.com/10/123','backend':backend}]
    manifest={'schema_version':version,'backend':backend,'record_kinds':{'posts':1},'counts':{'weibo':1},'paths':{'weibo':'weibo.json'},'platforms':{'weibo':'complete'},'status':'complete','diagnostics':{'weibo':{'kind':'ok','code':'ok'}}}
    for name,value in [('manifest.json',manifest),('weibo.json',records),('plan.json',{'schema_version':2 if backend == 'computer_use' else 1,'backend':backend,'targets':[{'platform':'weibo','mode':'creator','uid':'10'}]})]:
        path=run/name;path.write_text(json.dumps(value));os.chmod(path,0o600)
    return root,run


def test_old_browserskill_history_remains_readable_and_exportable(tmp_path):
    from media_missher_history import load_run,export_selected_run
    root,run=_old_run(tmp_path,2)
    assert load_run(root,run.name)['manifest']['backend']=='browserskill'
    result=export_selected_run(root,run.name,record_kinds=['posts'],format_name='json')
    assert result['rows']==1 and result['source_backend']=='browserskill'


def test_new_manifest_cannot_claim_retired_backend(tmp_path):
    from media_missher_history import load_run,HistoryError
    root,run=_old_run(tmp_path,3)
    with pytest.raises(HistoryError):load_run(root,run.name)


def test_retired_history_cannot_resume_before_browser_entry(tmp_path):
    from runtime.media_missher_runtime.cli import _read_plan_resume
    root,run=_old_run(tmp_path,2)
    plan=contracts.CollectionPlan(targets=(contracts.Target(platform='weibo',mode='creator',uid='10'),))
    with pytest.raises(ValueError):_read_plan_resume(root,run.name,plan,None)


def test_old_computer_use_history_exports_original_provenance_but_cannot_resume(tmp_path):
    from media_missher_history import load_run, export_selected_run
    from runtime.media_missher_runtime.cli import _read_plan_resume
    root, run = _old_run(tmp_path, 3, backend='computer_use')
    assert load_run(root, run.name)['manifest']['backend'] == 'computer_use'
    result = export_selected_run(root, run.name, record_kinds=['posts'], format_name='json')
    assert result['rows'] == 1
    assert result['source_backend'] == 'computer_use'
    plan = contracts.CollectionPlan(targets=(contracts.Target(platform='weibo', mode='creator', uid='10'),))
    with pytest.raises(ValueError):
        _read_plan_resume(root, run.name, plan, None)


@pytest.mark.parametrize('schema', [1, 2])
def test_retired_private_plan_never_reaches_dispatcher(tmp_path, monkeypatch, capsys, schema):
    import json
    from runtime.media_missher_runtime import cli
    plan = tmp_path / 'plan.json'
    plan.write_text(json.dumps({'schema_version': schema, 'backend': 'computer_use', 'targets': [{'platform': 'weibo', 'mode': 'creator', 'uid': '10'}]}))
    plan.chmod(0o600)
    monkeypatch.setattr(cli.RuntimeDispatcher, '__init__', lambda *a, **k: pytest.fail('CDP fallback'))
    assert cli.main(['creator', '--targets-json', str(plan), '--output-dir', str(tmp_path / 'runs')]) == 78
    assert 'backend-retired-computer-use' in capsys.readouterr().err
    assert not (tmp_path / 'runs').exists()
