import csv
import json
import sqlite3
from pathlib import Path
import pytest
from runtime.media_missher_runtime.exporting import ExportSelection, export_records


def test_field_groups_cover_every_selected_platform(tmp_path):
    rows=[{'platform':'weibo','type':'post','mblog_id':'1','liked':1}, {'platform':'x','type':'post','tweet_id':'2','bookmarks':7}]
    selection=ExportSelection(run_id='run-mixed',record_kinds=('posts',),platforms=('weibo','x'),field_groups=('metrics',),format='json')
    result=export_records(rows,selection,destination_root=tmp_path)
    data=json.loads(Path(result.paths[0]).read_text())
    assert data['records'][1]['bookmarks']==7


@pytest.mark.parametrize('fmt',['xlsx','csv','json','jsonl','sqlite'])
def test_partial_relation_projection_is_explicit_and_does_not_add_private_fields(tmp_path,fmt):
    row={'platform':'weibo','type':'topic_participant_relation','topic':'萤火虫漫展','uid':'9007199254740993','post_id':'9007199254740994','display_name':'private-label'}
    selection=ExportSelection(run_id='run-relation',record_kinds=('topic_participants',),fields=('uid',),format=fmt)
    result=export_records([row],selection,destination_root=tmp_path)
    assert 'partial-relation-projection' in result.to_json()['warnings']
    assert result.rows==1
    path=Path(result.paths[0])
    if fmt=='json':data=json.loads(path.read_text())['records'][0]
    elif fmt=='jsonl':data=json.loads(path.read_text().splitlines()[0])
    elif fmt=='csv':
        with path.open(newline='',encoding='utf-8-sig') as stream:data=next(csv.DictReader(stream))
    elif fmt=='sqlite':
        with sqlite3.connect(path) as db:
            db.row_factory=sqlite3.Row
            data=dict(db.execute('SELECT * FROM records').fetchone())
    else:
        import openpyxl
        book=openpyxl.load_workbook(path);sheet=book['Topic Participants']
        data=dict(zip([cell.value for cell in sheet[1]],[cell.value for cell in sheet[2]]));book.close()
    assert data['uid']=='9007199254740993'
    assert 'display_name' not in data and 'topic' not in data


def test_shared_post_keeps_both_target_sources_for_export():
    from runtime.media_missher_runtime.plan_runner import _absorb_records
    from runtime.media_missher_runtime.contracts import Target
    from runtime.media_missher_runtime.exporting import select_records
    a=Target(platform='x',mode='search',keyword='one');b=Target(platform='x',mode='search',keyword='two')
    rows=[];seen=set();counts={}
    item={'platform':'x','type':'post','tweet_id':'9007199254740993'}
    assert _absorb_records([item],a,rows,seen,counts)==1
    assert _absorb_records([item],b,rows,seen,counts)==1
    assert len(rows)==1 and counts=={a.identity:1,b.identity:1}
    assert rows[0]['target_identities']==[a.identity,b.identity]
    for target in [a,b]:
        selection=ExportSelection(run_id='run-both',record_kinds=('posts',),targets=(target.identity,),format='json')
        assert len(select_records(rows,selection)['posts'])==1
