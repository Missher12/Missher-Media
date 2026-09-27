import json
from pathlib import Path
import pytest
from runtime.media_missher_runtime.batch_journal import BatchJournal


def test_committed_batch_survives_reopen(tmp_path):
    journal=BatchJournal(tmp_path)
    journal.commit(1,[{'platform':'x','tweet_id':'9007199254740993'}],{'target_identity':'x:creator:fixture','backend':'cdp'})
    batches=BatchJournal(tmp_path).recover()
    assert len(batches)==1
    assert batches[0]['records'][0]['tweet_id']=='9007199254740993'


def test_uncommitted_tail_is_not_recovered(tmp_path):
    journal=BatchJournal(tmp_path);journal.commit(1,[{'id':'1'}],{})
    folder=tmp_path/'journal'
    folder.mkdir(exist_ok=True)
    (folder/'batch-00000002.json').write_text('{"records":[{"id":"2"}]}')
    assert len(journal.recover())==1


def test_committed_corruption_fails_instead_of_dropping_prefix(tmp_path):
    journal=BatchJournal(tmp_path);journal.commit(1,[{'id':'1'}],{})
    path=tmp_path/'journal'/'batch-00000001.json'
    if path.exists(): path.write_text('{}')
    with pytest.raises(ValueError):journal.recover()


def test_duplicate_sequence_is_idempotent_but_conflicting_content_fails(tmp_path):
    journal=BatchJournal(tmp_path)
    first=journal.commit(1,[{'id':'1'}],{})
    assert journal.commit(1,[{'id':'1'}],{})==first
    with pytest.raises(ValueError):journal.commit(1,[{'id':'2'}],{})


@pytest.mark.parametrize('boundary,expected',[('payload',1),('commit',2),('corrupt',None)])
def test_real_process_exit_at_commit_boundary(tmp_path,boundary,expected):
    import os,subprocess,sys
    root=Path(__file__).resolve().parents[1]
    journal=BatchJournal(tmp_path);journal.commit(1,[{'platform':'x','tweet_id':'1'}],{})
    script="""import os,sys
from pathlib import Path
from runtime.media_missher_runtime import batch_journal as module
folder=Path(sys.argv[1]);boundary=sys.argv[2]
write=module.atomic_json
def interrupted(path,value):
    write(path,value)
    if path.name==('batch-00000002.json' if boundary=='payload' else 'commit-00000002.json'):
        if boundary=='corrupt':(folder/'journal/batch-00000002.json').write_text('{}')
        os._exit(91)
module.atomic_json=interrupted
module.BatchJournal(folder).commit(2,[{'platform':'x','tweet_id':'1'},{'platform':'x','tweet_id':'2'}],{})
"""
    result=subprocess.run([sys.executable,'-c',script,str(tmp_path),boundary],cwd=root,env={**os.environ,'PYTHONDONTWRITEBYTECODE':'1'},timeout=10)
    assert result.returncode==91
    before={p.name:p.read_bytes() for p in (tmp_path/'journal').iterdir() if p.is_file()}
    if expected is None:
        with pytest.raises(ValueError,match='corruption'):BatchJournal(tmp_path).recover()
    else:
        recovered=BatchJournal(tmp_path).recover()
        assert len(recovered)==expected
        assert len(recovered[-1]['records'])==expected
    assert before=={p.name:p.read_bytes() for p in (tmp_path/'journal').iterdir() if p.is_file()}


def test_actual_cli_commits_before_next_target_crash_and_history_reads_prefix(tmp_path,capsys):
    import os
    from runtime.media_missher_runtime.cli import main
    from media_missher_history import load_run,export_selected_run
    class Dispatcher:
        async def __aenter__(self):return self
        async def __aexit__(self,*args):pass
        async def preflight(self,requests):pass
        async def collect(self,request):
            if request.uid=='20':raise SystemExit('synthetic-process-exit')
            return [{'platform':'weibo','type':'post','mblog_id':'101','link':'https://weibo.com/10/101'}]
    plan=tmp_path/'plan.json';plan.write_text(json.dumps({'schema_version':2,'targets':[{'platform':'weibo','mode':'creator','uid':uid} for uid in ['10','20']],'count':1}));os.chmod(plan,0o600)
    with pytest.raises(SystemExit):main(['creator','--targets-json',str(plan),'--output-dir',str(tmp_path/'runs')],dispatcher=Dispatcher())
    run=next((tmp_path/'runs').glob('run-*'))
    loaded=load_run(run.parent,run.name)
    assert loaded['manifest']['status']=='partial'
    assert loaded['counts']['weibo']==1
    assert export_selected_run(run.parent,run.name,record_kinds=['posts'],format_name='json')['rows']==1
