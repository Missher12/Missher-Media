"""Private append-only commit markers; an uncommitted payload is never evidence."""
from contextlib import contextmanager
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import tempfile

MAX_BYTES = 8 * 1024 * 1024
MAX_BATCHES = 4096


def canonical_bytes(value):
    data=json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False).encode()
    if len(data)>MAX_BYTES: raise ValueError('journal-size-limit')
    return data


def _private_directory(path):
    if any(item.is_symlink() for item in (path,*path.parents)): raise ValueError('journal-path-unsafe')
    info=path.stat()
    if not stat.S_ISDIR(info.st_mode) or stat.S_IMODE(info.st_mode)!=0o700 or info.st_uid!=os.getuid(): raise ValueError('journal-directory-unsafe')


def read_private_json(path, limit=MAX_BYTES):
    fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK)
    try:
        info=os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or stat.S_IMODE(info.st_mode)!=0o600 or info.st_uid!=os.getuid() or info.st_nlink!=1 or info.st_size>limit: raise ValueError('journal-file-unsafe')
        data=os.read(fd,limit+1)
        if len(data)>limit: raise ValueError('journal-size-limit')
        def unique(pairs):
            result={}
            for key,value in pairs:
                if key in result: raise ValueError('journal-duplicate-key')
                result[key]=value
            return result
        return json.loads(data,object_pairs_hook=unique)
    finally: os.close(fd)


def atomic_json(path,value):
    data=canonical_bytes(value)
    _private_directory(path.parent)
    fd,name=tempfile.mkstemp(prefix='.commit-',dir=path.parent)
    try:
        with os.fdopen(fd,'wb') as stream:
            stream.write(data);stream.flush();os.fsync(stream.fileno())
        os.replace(name,path)
        directory=os.open(path.parent,os.O_RDONLY|os.O_DIRECTORY)
        try: os.fsync(directory)
        finally: os.close(directory)
    finally:
        if os.path.exists(name):os.unlink(name)


class BatchJournal:
    def __init__(self,run_dir:Path):
        self.run_dir=Path(run_dir).absolute()
        _private_directory(self.run_dir)
        self.directory=self.run_dir/'journal'

    @contextmanager
    def _lock(self):
        self.directory.mkdir(mode=0o700,exist_ok=True)
        _private_directory(self.directory)
        fd=os.open(self.directory/'.lock',os.O_RDWR|os.O_CREAT|os.O_NOFOLLOW,0o600)
        try:
            info=os.fstat(fd)
            if not stat.S_ISREG(info.st_mode) or info.st_nlink!=1 or stat.S_IMODE(info.st_mode)!=0o600 or info.st_uid!=os.getuid():raise ValueError('journal-lock-invalid')
            fcntl.flock(fd,fcntl.LOCK_EX)
            yield
        finally:os.close(fd)

    def recover(self)->list[dict]:
        if not self.directory.exists():return []
        _private_directory(self.directory)
        commits=sorted(self.directory.glob('commit-*.json'))
        if len(commits)>MAX_BATCHES:raise ValueError('journal-batch-limit')
        recovered=[]; previous=None
        for sequence,path in enumerate(commits,1):
            if path.name!=f'commit-{sequence:08d}.json':raise ValueError('journal-sequence-gap')
            marker=read_private_json(path,65536)
            expected={'schema_version','sequence','payload','digest','previous_digest'}
            if not isinstance(marker,dict) or set(marker)!=expected or marker['schema_version']!=1 or type(marker['sequence']) is not int or marker['sequence']!=sequence or marker['previous_digest']!=previous or marker['payload']!=f'batch-{sequence:08d}.json':raise ValueError('journal-commit-invalid')
            payload=read_private_json(self.directory/marker['payload'])
            digest=hashlib.sha256(canonical_bytes(payload)).hexdigest()
            if marker['digest']!=digest or not isinstance(payload,dict) or set(payload)!={'records','checkpoint'} or not isinstance(payload['records'],list) or not isinstance(payload['checkpoint'],dict):raise ValueError('journal-committed-corruption')
            recovered.append({'sequence':sequence,'digest':digest,**payload})
            previous=digest
        return recovered

    def commit(self,sequence:int,records:list[dict],checkpoint:dict)->dict:
        if type(sequence) is not int or not 1<=sequence<=MAX_BATCHES or not isinstance(records,list) or len(records)>10000 or any(not isinstance(item,dict) for item in records) or not isinstance(checkpoint,dict):raise ValueError('journal-input-invalid')
        payload={'records':records,'checkpoint':checkpoint}
        digest=hashlib.sha256(canonical_bytes(payload)).hexdigest()
        with self._lock():
            previous=self.recover()
            if sequence<=len(previous):
                if previous[sequence-1]['digest']!=digest:raise ValueError('journal-sequence-conflict')
                return previous[sequence-1]
            if sequence!=len(previous)+1:raise ValueError('journal-sequence-gap')
            payload_name=f'batch-{sequence:08d}.json'
            atomic_json(self.directory/payload_name,payload)
            # Only this last atomic write makes the payload visible to recovery.
            atomic_json(self.directory/f'commit-{sequence:08d}.json',{'schema_version':1,'sequence':sequence,'payload':payload_name,'digest':digest,'previous_digest':previous[-1]['digest'] if previous else None})
            return {'sequence':sequence,'digest':digest,**payload}


def snapshot_projection(records,plan,states):
    """Project an accepted prefix without making unfinished targets successful."""
    from .exporting import record_kind
    counts={p:sum(r.get('platform')==p for r in records) for p in plan.platforms}
    kinds={}
    for record in records:
        kind=record_kind(record);kinds[kind]=kinds.get(kind,0)+1
    platforms={};diagnostics={}
    for platform in plan.platforms:
        selected=[states.get(t.identity) for t in plan.targets if t.platform==platform]
        risk=next((s for s in selected if s and s.get('stop_reason')=='risk-stopped'),None)
        shortfall=next((s.get('checkpoint',{}).get('evidence_shortfall') for s in selected if s and s.get('checkpoint',{}).get('evidence_shortfall') in {'incomplete-record','screenshot-shortfall'}),None)
        if risk:
            platforms[platform]='risk-stopped';diagnostics[platform]={'kind':'risk-stop','code':risk.get('checkpoint',{}).get('risk_code','risk-signal')}
        elif shortfall:
            platforms[platform]='incomplete';diagnostics[platform]={'kind':'result','code':shortfall}
        elif all(s and s.get('stop_reason') in {'count-reached','natural-end'} for s in selected):
            platforms[platform]='complete';diagnostics[platform]={'kind':'ok','code':'ok'}
        elif not any(s and s.get('phase')!='pending' for s in selected):
            platforms[platform]='not-run';diagnostics[platform]={'kind':'not-run','code':'preflight-aborted'}
        else:
            platforms[platform]='shortfall';diagnostics[platform]={'kind':'result','code':'count-shortfall'}
    status='risk-stopped' if 'risk-stopped' in platforms.values() else 'complete' if all(v=='complete' for v in platforms.values()) else 'partial' if any(counts.values()) else 'failed'
    return {'schema_version':3,'backend':plan.backend,'counts':counts,'record_kinds':kinds,'paths':{p:f'{p}.json' for p in plan.platforms},'platforms':platforms,'diagnostics':diagnostics,'status':status}


def journal_snapshot(run_dir):
    batches=BatchJournal(run_dir).recover()
    if not batches:return None
    latest=batches[-1]
    manifest=latest['checkpoint'].get('manifest')
    if not isinstance(manifest,dict):raise ValueError('journal-manifest-missing')
    records=latest['records']
    return {'schema':1,'manifest':manifest,'artifacts':{p:[r for r in records if r.get('platform')==p] for p in manifest['platforms']}}
