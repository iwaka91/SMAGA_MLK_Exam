from __future__ import annotations

from pathlib import Path
from datetime import datetime, timedelta, timezone
from urllib import request, parse, error
import json, os, threading, secrets

TZ_WIB = timezone(timedelta(hours=7))

def now_wib():
    return datetime.now(TZ_WIB)

def iso(dt):
    return dt.isoformat(timespec='seconds')

class BackendError(RuntimeError):
    pass

class LocalBackend:
    mode = 'local'
    def __init__(self, db_file: Path):
        self.db_file = Path(db_file)
        self.lock = threading.RLock()
        self.db_file.parent.mkdir(parents=True, exist_ok=True)

    def _load(self):
        with self.lock:
            if not self.db_file.exists():
                return {'exams': [], 'sessions': [], 'submissions': [], 'assets': []}
            data = json.loads(self.db_file.read_text(encoding='utf-8'))
            data.setdefault('exams', [])
            data.setdefault('sessions', [])
            data.setdefault('submissions', [])
            data.setdefault('assets', [])
            return data

    def _save(self, data):
        with self.lock:
            tmp = self.db_file.with_suffix('.tmp')
            tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
            tmp.replace(self.db_file)

    def is_empty(self):
        return not self._load()['exams']

    def list_exams(self):
        return [dict(x) for x in self._load()['exams']]

    def get_exam_by_id(self, exam_id, include_keys=True):
        e = next((x for x in self._load()['exams'] if x.get('id') == exam_id), None)
        if not e: return None
        out = json.loads(json.dumps(e))
        if not include_keys: out.pop('keys', None)
        return out

    def get_exam_by_code(self, code, include_keys=True):
        code = str(code or '').strip().upper()
        e = next((x for x in self._load()['exams'] if str(x.get('code','')).upper() == code), None)
        if not e: return None
        out = json.loads(json.dumps(e))
        if not include_keys: out.pop('keys', None)
        return out

    def save_exam(self, exam):
        db = self._load()
        old = next((x for x in db['exams'] if x.get('id') == exam['id']), None)
        if old: db['exams'][db['exams'].index(old)] = exam
        else: db['exams'].append(exam)
        self._save(db)
        self.touch_assets_for_exam(exam['id'], [q.get('image_url','') for q in exam.get('questions',[])])
        return exam

    def delete_exam(self, exam_id):
        db = self._load()
        db['exams'] = [x for x in db['exams'] if x.get('id') != exam_id]
        db['sessions'] = [x for x in db['sessions'] if x.get('exam_id') != exam_id]
        db['submissions'] = [x for x in db['submissions'] if x.get('exam_id') != exam_id]
        self._save(db)

    def list_sessions(self, exam_id=None):
        rows = self._load()['sessions']
        return [dict(x) for x in rows if not exam_id or x.get('exam_id') == exam_id]

    def get_session(self, session_id):
        return next((dict(x) for x in self._load()['sessions'] if x.get('session_id') == session_id), None)

    def find_active_session(self, exam_id, participant_number):
        return next((dict(x) for x in self._load()['sessions'] if x.get('exam_id')==exam_id and x.get('participant_number')==participant_number and not x.get('submitted')), None)

    def find_any_session(self, exam_id, participant_number):
        return next((dict(x) for x in self._load()['sessions'] if x.get('exam_id')==exam_id and x.get('participant_number')==participant_number), None)

    def find_session_submission(self,session_id):
        return next((dict(x) for x in self._load()['submissions'] if x.get('session_id')==session_id), None)

    def create_session(self, sess):
        db = self._load(); db['sessions'].append(sess); self._save(db); return sess

    def mark_session_submitted(self, session_id, submitted=True):
        db = self._load()
        for s in db['sessions']:
            if s.get('session_id') == session_id: s['submitted'] = bool(submitted)
        self._save(db)

    def list_submissions(self, exam_id=None):
        rows = self._load()['submissions']
        return [dict(x) for x in rows if not exam_id or x.get('exam_id') == exam_id]

    def find_submission(self, session_id, idem):
        return next((dict(x) for x in self._load()['submissions'] if x.get('session_id')==session_id and x.get('idempotency_key')==idem), None)

    def create_submission(self, row):
        db = self._load(); db['submissions'].append(row)
        for s in db['sessions']:
            if s.get('session_id') == row.get('session_id'): s['submitted'] = True
        self._save(db); return row

    def reset_session(self, session_id):
        db = self._load(); found = False
        for s in db['sessions']:
            if s.get('session_id') == session_id: s['submitted'] = False; found = True
        db['submissions'] = [x for x in db['submissions'] if x.get('session_id') != session_id]
        self._save(db); return found

    def overview(self):
        db=self._load()
        return {'exam_count':len(db['exams']),'published_count':sum(x.get('status')=='published' for x in db['exams']),'session_count':len(db['sessions']),'submission_count':len(db['submissions'])}

    def add_asset(self, asset):
        db=self._load(); db['assets'].append(asset); self._save(db); return asset

    def list_assets(self, include_deleted=False):
        rows=self._load()['assets']
        return [dict(x) for x in rows if include_deleted or not x.get('deleted_at')]

    def set_asset_archived(self, asset_id, archived):
        db=self._load(); found=None
        for a in db['assets']:
            if a.get('id')==asset_id: a['archived']=bool(archived); found=dict(a)
        self._save(db); return found

    def mark_asset_deleted(self, asset_id):
        db=self._load(); found=None
        for a in db['assets']:
            if a.get('id')==asset_id:
                a['deleted_at']=iso(now_wib()); found=dict(a)
        self._save(db); return found

    def touch_assets_for_exam(self, exam_id, urls):
        urls={str(u) for u in urls if u}
        if not urls:return
        db=self._load(); changed=False
        for a in db['assets']:
            if a.get('public_url') in urls and not a.get('deleted_at'):
                a['exam_id']=exam_id; a['last_used_at']=iso(now_wib()); changed=True
        if changed:self._save(db)


# Serialize local JSON mock mutations across all request threads. This prevents
# lost check-ins/submissions during multi-student LAN development testing.
def _local_atomic(fn):
    def call(self,*args,**kwargs):
        with self.lock:return fn(self,*args,**kwargs)
    return call
for _method_name in ('save_exam','delete_exam','create_session','mark_session_submitted',
                     'create_submission','reset_session','add_asset','set_asset_archived',
                     'mark_asset_deleted','touch_assets_for_exam'):
    setattr(LocalBackend,_method_name,_local_atomic(getattr(LocalBackend,_method_name)))


class SupabaseBackend:
    mode = 'supabase'
    def __init__(self, url, service_key):
        self.url = url.rstrip('/')
        self.key = service_key

    def _req(self, method, table, query=None, body=None, prefer=None):
        qs = ''
        if query:
            parts=[]
            for k,v in query.items():
                parts.append(parse.quote(str(k), safe='')+'='+parse.quote(str(v), safe='*,().:-_'))
            qs='?'+ '&'.join(parts)
        url=f"{self.url}/rest/v1/{table}{qs}"
        headers={'apikey':self.key,'Authorization':f'Bearer {self.key}','Accept':'application/json'}
        if body is not None: headers['Content-Type']='application/json'
        if prefer: headers['Prefer']=prefer
        data=None if body is None else json.dumps(body,ensure_ascii=False).encode('utf-8')
        req=request.Request(url,data=data,headers=headers,method=method)
        try:
            with request.urlopen(req,timeout=20) as r:
                raw=r.read()
                if not raw:return None
                return json.loads(raw.decode('utf-8'))
        except error.HTTPError as e:
            detail=e.read().decode('utf-8','replace')
            raise BackendError(f'Supabase {method} {table} gagal ({e.code}): {detail[:600]}')
        except Exception as e:
            raise BackendError(f'Supabase tidak dapat dihubungi: {e}')

    def is_empty(self):
        rows=self._req('GET','exams',{'select':'id','limit':'1'}) or []
        return len(rows)==0

    def _hydrate_exam(self, row, include_keys=True):
        if not row:return None
        exam=dict(row)
        qs=self._req('GET','questions',{'exam_id':f"eq.{exam['id']}",'select':'*','order':'position.asc'}) or []
        exam['questions']=[]
        for q in qs:
            q=dict(q); q.pop('position',None); q.pop('exam_id',None)
            exam['questions'].append(q)
        if include_keys:
            ks=self._req('GET','question_keys',{'exam_id':f"eq.{exam['id']}",'select':'question_id,kind,answer,weight'}) or []
            exam['keys']={k['question_id']:{'kind':k['kind'],'answer':k['answer'],'weight':k['weight']} for k in ks}
        return exam

    def list_exams(self):
        rows=self._req('GET','exams',{'select':'*','order':'created_at.desc'}) or []
        out=[]
        for r in rows: out.append(self._hydrate_exam(r, include_keys=False))
        return out

    def get_exam_by_id(self, exam_id, include_keys=True):
        rows=self._req('GET','exams',{'id':f'eq.{exam_id}','select':'*','limit':'1'}) or []
        return self._hydrate_exam(rows[0],include_keys) if rows else None

    def get_exam_by_code(self, code, include_keys=True):
        rows=self._req('GET','exams',{'code':f'eq.{str(code or "").upper()}','select':'*','limit':'1'}) or []
        return self._hydrate_exam(rows[0],include_keys) if rows else None

    def save_exam(self, exam):
        row={k:v for k,v in exam.items() if k not in ('questions','keys')}
        self._req('POST','exams',{'on_conflict':'id'},row,'resolution=merge-duplicates,return=minimal')
        self._req('DELETE','questions',{'exam_id':f"eq.{exam['id']}"})
        questions=[]; keys=[]
        for pos,q in enumerate(exam.get('questions',[]),1):
            qr=dict(q); qr['exam_id']=exam['id']; qr['position']=pos; questions.append(qr)
            k=exam.get('keys',{}).get(q['id'])
            if k: keys.append({'question_id':q['id'],'exam_id':exam['id'],'kind':k['kind'],'answer':k['answer'],'weight':k['weight']})
        if questions:self._req('POST','questions',None,questions,'return=minimal')
        if keys:self._req('POST','question_keys',None,keys,'return=minimal')
        self.touch_assets_for_exam(exam['id'],[q.get('image_url','') for q in exam.get('questions',[])])
        return exam

    def delete_exam(self, exam_id):
        self._req('DELETE','exams',{'id':f'eq.{exam_id}'})

    def list_sessions(self, exam_id=None):
        q={'select':'*','order':'login_at.asc'}
        if exam_id:q['exam_id']=f'eq.{exam_id}'
        return self._req('GET','exam_sessions',q) or []

    def get_session(self, session_id):
        rows=self._req('GET','exam_sessions',{'session_id':f'eq.{session_id}','select':'*','limit':'1'}) or []
        return rows[0] if rows else None

    def find_active_session(self, exam_id, participant_number):
        rows=self._req('GET','exam_sessions',{'exam_id':f'eq.{exam_id}','participant_number':f'eq.{participant_number}','submitted':'eq.false','select':'*','limit':'1','order':'login_at.desc'}) or []
        return rows[0] if rows else None

    def find_any_session(self, exam_id, participant_number):
        rows=self._req('GET','exam_sessions',{'exam_id':f'eq.{exam_id}','participant_number':f'eq.{participant_number}','select':'*','limit':'1'}) or []
        return rows[0] if rows else None

    def find_session_submission(self, session_id):
        rows=self._req('GET','submissions',{'session_id':f'eq.{session_id}','select':'*','limit':'1'}) or []
        return rows[0] if rows else None

    def create_session(self, sess):
        self._req('POST','exam_sessions',None,sess,'return=minimal'); return sess

    def mark_session_submitted(self, session_id, submitted=True):
        self._req('PATCH','exam_sessions',{'session_id':f'eq.{session_id}'},{'submitted':bool(submitted)},'return=minimal')

    def list_submissions(self, exam_id=None):
        q={'select':'*','order':'submitted_at.asc'}
        if exam_id:q['exam_id']=f'eq.{exam_id}'
        return self._req('GET','submissions',q) or []

    def find_submission(self, session_id, idem):
        rows=self._req('GET','submissions',{'session_id':f'eq.{session_id}','idempotency_key':f'eq.{idem}','select':'*','limit':'1'}) or []
        return rows[0] if rows else None

    def create_submission(self, row):
        try:
            self._req('POST','submissions',None,row,'return=minimal')
        except BackendError as e:
            prior=self.find_submission(row.get('session_id'),row.get('idempotency_key'))
            if prior:return prior
            raise
        self.mark_session_submitted(row['session_id'],True); return row

    def reset_session(self, session_id):
        self._req('DELETE','submissions',{'session_id':f'eq.{session_id}'})
        self.mark_session_submitted(session_id,False); return True

    def overview(self):
        exams=self._req('GET','exams',{'select':'id,status'}) or []
        sessions=self._req('GET','exam_sessions',{'select':'session_id'}) or []
        subs=self._req('GET','submissions',{'select':'id'}) or []
        return {'exam_count':len(exams),'published_count':sum(x.get('status')=='published' for x in exams),'session_count':len(sessions),'submission_count':len(subs)}

    def add_asset(self, asset):
        self._req('POST','assets',None,asset,'return=minimal');return asset

    def list_assets(self, include_deleted=False):
        q={'select':'*','order':'created_at.desc'}
        if not include_deleted:q['deleted_at']='is.null'
        return self._req('GET','assets',q) or []

    def set_asset_archived(self, asset_id, archived):
        rows=self._req('PATCH','assets',{'id':f'eq.{asset_id}'},{'archived':bool(archived)},'return=representation') or []
        return rows[0] if rows else None

    def mark_asset_deleted(self, asset_id):
        rows=self._req('PATCH','assets',{'id':f'eq.{asset_id}'},{'deleted_at':iso(now_wib())},'return=representation') or []
        return rows[0] if rows else None

    def touch_assets_for_exam(self, exam_id, urls):
        for u in {str(x) for x in urls if x}:
            self._req('PATCH','assets',{'public_url':f'eq.{u}'},{'exam_id':exam_id,'last_used_at':iso(now_wib())},'return=minimal')


def make_backend(root: Path):
    url=os.environ.get('SUPABASE_URL','').strip()
    key=os.environ.get('SUPABASE_SERVICE_ROLE_KEY','').strip()
    if url and key:
        return SupabaseBackend(url,key)
    db=Path(os.environ.get('SMAGA_DB_FILE',str(root/'data'/'mock_db.json')))
    return LocalBackend(db)
