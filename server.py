from __future__ import annotations

from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler
from pathlib import Path
from datetime import datetime, timedelta, timezone
from urllib.parse import urlparse, parse_qs, quote
import os, sys, subprocess, json, secrets, threading, webbrowser, csv, io, base64, re, zipfile, hashlib, random
import xml.etree.ElementTree as ET

from backend import make_backend, BackendError
from storage_manager import StorageManager
from security import production, assert_production_config, throttle, authorize, login_teacher, refresh_teacher, audit, AuthError

ROOT = Path(__file__).resolve().parent
PUBLIC = ROOT / 'public'

def load_env_file(path: Path):
    if not path.exists(): return
    for raw in path.read_text(encoding='utf-8').splitlines():
        line=raw.strip()
        if not line or line.startswith('#') or '=' not in line: continue
        k,v=line.split('=',1);k=k.strip();v=v.strip().strip('\"').strip("'")
        if k and k not in os.environ: os.environ[k]=v

load_env_file(ROOT/'.env')
os.chdir(PUBLIC)

APP_VERSION = '1.0.0-rc1'
PORT = int(os.environ.get('PORT') or os.environ.get('SMAGA_PORT','8788'))
DEMO_MODE = os.environ.get('SMAGA_DEMO_MODE','0' if production() else '1') != '0'
DEMO_START_DELAY_SECONDS = 8
ADMIN_PIN = os.environ.get('SMAGA_ADMIN_PIN','2026')
TZ_WIB = timezone(timedelta(hours=7))
ALLOWED_CLASSES = ['X1','X2','X3','XI A','XI B','XI C','XII A','XII B','XII C']
BACKEND = make_backend(ROOT)
STORAGE = StorageManager(ROOT, PUBLIC, BACKEND)
assert_production_config()


def now_wib(): return datetime.now(TZ_WIB)
def iso(dt): return dt.isoformat(timespec='seconds')
def slug_code(prefix='UJIAN'): return f"{prefix}{secrets.randbelow(9000)+1000}"


def make_default_questions():
    qs=[];keys={}
    contexts=[('Literasi','Teks informasi singkat untuk menguji engine. Pilih jawaban yang paling tepat.'),('Numerasi','Gunakan data sederhana pada stimulus untuk menentukan jawaban.')]
    for i in range(1,33):
        domain,stim=contexts[(i-1)%2];qid=f'Q{i:02d}'
        opts=[f'Opsi A nomor {i}',f'Opsi B nomor {i}',f'Opsi C nomor {i}',f'Opsi D nomor {i}']
        qs.append({'id':qid,'kind':'pg','type':'1_n_2','weight':1,'domain':domain,'label':f'{domain} • Pilihan Ganda','stimulus':stim,'question':f'Butir dummy {i}: manakah pilihan yang sesuai dengan informasi pada stimulus?','options':opts,'image_url':'','notes':'','visual':i in (4,12,20,28)})
        keys[qid]={'kind':'pg','answer':(i+1)%4,'weight':1}
    patterns=[[True,False,True,True],[False,True,True,False],[True,True,False,True],[False,True,False,True]]
    for i in range(33,41):
        domain='Literasi' if i%2 else 'Numerasi';qid=f'Q{i:02d}';opts=[f'Pernyataan {n} pada soal {i}' for n in range(1,5)]
        qs.append({'id':qid,'kind':'pgk','type':'m_n_2','weight':2,'domain':domain,'label':f'{domain} • Pilihan Ganda Kompleks','stimulus':'Perhatikan data/teks dummy pada stimulus. Pilih seluruh pernyataan yang benar.','question':f'Butir dummy {i}: pilih semua pernyataan yang benar.','options':opts,'image_url':'','notes':'','visual':i in (34,38,40)})
        keys[qid]={'kind':'pgk','answer':patterns[(i-33)%len(patterns)],'weight':2}
    return qs,keys


def seed_backend():
    try:
        if production() or not BACKEND.is_empty(): return
        qs,keys=make_default_questions();today=now_wib().date();start=datetime(today.year,today.month,today.day,8,5,tzinfo=TZ_WIB)
        exam={'id':'exam-akm-smaga-2026','code':'AKM26','title':'Turnamen AKM SMAGA 2026','description':'Template event pertama SMAGA Maliku Exam.','token':'AKM726','token_backup1':'','token_backup2':'','duration_seconds':5400,'status':'published','leaderboard':True,'show_result_to_student':True,'shuffle_questions':False,'scoring_mode':'custom','classes':ALLOWED_CLASSES,'start_at':iso(start),'end_at':iso(start+timedelta(minutes=90)),'questions':qs,'keys':keys,'created_at':iso(now_wib()),'updated_at':iso(now_wib())}
        BACKEND.save_exam(exam)
    except Exception as e:
        raise RuntimeError(f'Backend belum siap. Jika memakai Supabase, jalankan migration SQL terlebih dahulu. Detail: {e}')


def class_level(cls):
    if cls.startswith('XI '): return 'XI'
    if cls.startswith('XII '): return 'XII'
    return 'X'

def production_login_allowed(cls,n):
    d=n.date(); t=lambda h,m: datetime(d.year,d.month,d.day,h,m,tzinfo=TZ_WIB); level=class_level(cls)
    windows={'X':(t(7,0),t(7,15)),'XI':(t(7,16),t(7,30)),'XII':(t(7,31),t(7,44))};ws,we=windows[level];rs,re=t(7,45),t(8,0)
    return (ws<=n<=we) or (rs<=n<=re), {'level':level,'window_start':iso(ws),'window_end':iso(we),'recovery_start':iso(rs),'recovery_end':iso(re)}


def ensure_option_ids(q):
    opts=list(q.get('options') or [])
    ids=q.get('option_ids')
    if not isinstance(ids,list) or len(ids)!=len(opts) or len(set(map(str,ids)))!=len(opts):
        ids=[f"{q.get('id','Q')}-O{i+1}" for i in range(len(opts))]
    return [str(x) for x in ids]

def deterministic_shuffle(items, seed_text):
    out=list(items)
    seed=int.from_bytes(hashlib.sha256(str(seed_text).encode('utf-8')).digest()[:8],'big')
    random.Random(seed).shuffle(out)
    return out

def key_answer_ids(q,key):
    ids=ensure_option_ids(q);answer=key.get('answer') if isinstance(key,dict) else None
    if q.get('kind')=='pg':
        if isinstance(answer,str): return answer if answer in ids else None
        if isinstance(answer,int) and 0<=answer<len(ids): return ids[answer]
        return None
    if isinstance(answer,list) and all(isinstance(x,str) for x in answer): return [x for x in answer if x in ids]
    if isinstance(answer,list): return [ids[i] for i,v in enumerate(answer[:len(ids)]) if bool(v)]
    return []

def public_exam(exam, session_id=''):
    qs=[]
    for q0 in exam.get('questions',[]):
        q=dict(q0);q['option_ids']=ensure_option_ids(q)
        clean={k:v for k,v in q.items() if k not in ('key','correct','answer','notes','_imported')}
        pairs=list(zip(clean.get('options',[]),clean.get('option_ids',[])))
        if clean.get('shuffle_options') and len(pairs)>1:
            pairs=deterministic_shuffle(pairs,f"{session_id}|{clean.get('id')}|options")
        clean['options']=[x[0] for x in pairs];clean['option_ids']=[x[1] for x in pairs]
        qs.append(clean)
    if exam.get('shuffle_questions') and len(qs)>1:
        qs=deterministic_shuffle(qs,f"{session_id}|{exam.get('id')}|questions")
    return {'exam_id':exam['id'],'code':exam['code'],'title':exam['title'],'description':exam.get('description',''),'engine':'Numbas headless + SMAGA UI','duration_seconds':exam['duration_seconds'],'question_count':len(qs),'max_score':sum(int(q.get('weight',1)) for q in qs),'questions':qs,'leaderboard':bool(exam.get('leaderboard')),'shuffle_questions':bool(exam.get('shuffle_questions')),'scoring_mode':exam.get('scoring_mode','equal')}


def score_submission(exam,payload):
    answers={a.get('qid'):a.get('answer') for a in payload.get('answers',[]) if isinstance(a,dict)};score=0;detail=[];keys=exam.get('keys',{})
    for q in exam.get('questions',[]):
        qid=q['id'];k=keys.get(qid,{});got=answers.get(qid);kind=k.get('kind',q.get('kind'));weight=int(k.get('weight',q.get('weight',1)));ids=ensure_option_ids(q)
        expected=key_answer_ids(q,k)
        if kind=='pg':
            if isinstance(got,int) and 0<=got<len(ids): got=ids[got]
            ok=isinstance(got,str) and got==expected
        else:
            if isinstance(got,list) and got and all(isinstance(x,bool) for x in got): got=[ids[i] for i,v in enumerate(got[:len(ids)]) if v]
            got_ids=set(x for x in (got or []) if isinstance(x,str));ok=got_ids==set(expected or [])
        earned=weight if ok else 0;score+=earned;detail.append({'qid':qid,'correct':ok,'earned':earned,'max':weight})
    mx=sum(int(q.get('weight',1)) for q in exam.get('questions',[])) or 1
    return {'score_raw':score,'max_raw':mx,'score_100':round(score/mx*100,2),'correct_items':sum(1 for d in detail if d['correct']),'question_count':len(exam.get('questions',[])),'detail':detail}


def safe_json(handler,status,obj):
    body=json.dumps(obj,ensure_ascii=False).encode('utf-8');handler.send_response(status);handler.send_header('Content-Type','application/json; charset=utf-8');handler.send_header('Cache-Control','no-store');handler.send_header('X-Content-Type-Options','nosniff');handler.send_header('Content-Length',str(len(body)));handler.end_headers();handler.wfile.write(body)
def read_json(handler):
    n=int(handler.headers.get('Content-Length','0'))
    if n<0 or n>12*1024*1024:raise ValueError('Payload terlalu besar.')
    raw=handler.rfile.read(n);return json.loads(raw.decode('utf-8') or '{}')
def admin_ok(handler):
    handler._staff = authorize(handler)
    return bool(handler._staff)

def safe_student_result(row,show):
    # Never transmit scoring details or answer-key indicators to participant clients.
    data={k:row.get(k) for k in ('session_id','exam_id','submitted_at','accepted','idempotent_replay','show_result_to_student')}
    data['show_result_to_student']=bool(show)
    if show:data.update({k:row.get(k) for k in ('score_raw','max_raw','score_100','correct_items','question_count')})
    return data

def parse_exam_dt(raw):
    dt=datetime.fromisoformat(str(raw).replace('Z','+00:00'))
    return dt.replace(tzinfo=TZ_WIB) if dt.tzinfo is None else dt.astimezone(TZ_WIB)

def csv_bytes(rows,headers):
    s=io.StringIO();w=csv.DictWriter(s,fieldnames=headers);w.writeheader();w.writerows(rows);return ('\ufeff'+s.getvalue()).encode('utf-8')


def _xlsx_col_index(ref):
    letters=''.join(c for c in str(ref) if c.isalpha()).upper();n=0
    for c in letters:n=n*26+(ord(c)-64)
    return max(0,n-1)

def parse_xlsx_first_sheet(raw):
    ns='{http://schemas.openxmlformats.org/spreadsheetml/2006/main}'
    try:z=zipfile.ZipFile(io.BytesIO(raw))
    except Exception as e:raise ValueError(f'File XLSX tidak valid: {e}')
    shared=[]
    if 'xl/sharedStrings.xml' in z.namelist():
        root=ET.fromstring(z.read('xl/sharedStrings.xml'))
        for si in root.findall(f'{ns}si'):shared.append(''.join(t.text or '' for t in si.iter(f'{ns}t')))
    sheet_path='xl/worksheets/sheet1.xml'
    if sheet_path not in z.namelist():raise ValueError('Worksheet pertama tidak ditemukan.')
    root=ET.fromstring(z.read(sheet_path));matrix=[]
    for row in root.findall(f'.//{ns}row'):
        cells={};maxc=-1
        for c in row.findall(f'{ns}c'):
            idx=_xlsx_col_index(c.attrib.get('r','A1'));maxc=max(maxc,idx);typ=c.attrib.get('t','')
            if typ=='inlineStr':val=''.join(t.text or '' for t in c.iter(f'{ns}t'))
            else:
                v=c.find(f'{ns}v');txt='' if v is None else (v.text or '')
                if typ=='s' and txt:
                    try:val=shared[int(txt)]
                    except:val=''
                else:val=txt
            cells[idx]=val
        if maxc>=0:matrix.append([cells.get(i,'') for i in range(maxc+1)])
    if not matrix:return []
    start=next((i for i,r in enumerate(matrix) if any(str(x).strip() for x in r)),None)
    if start is None:return []
    def norm(x):return re.sub(r'[^a-z0-9]+','_',str(x).strip().lower()).strip('_')
    headers=[norm(x) for x in matrix[start]];rows=[]
    for r in matrix[start+1:]:
        obj={headers[i]:(r[i] if i<len(r) else '') for i in range(len(headers)) if headers[i]}
        if any(str(v).strip() for k,v in obj.items() if k not in ('no','nomor')):rows.append(obj)
    return rows


def exam_summary(e):
    return {k:e.get(k) for k in ['id','code','title','description','token','token_backup1','token_backup2','duration_seconds','status','leaderboard','show_result_to_student','shuffle_questions','scoring_mode','classes','start_at','end_at','created_at','updated_at']} | {'question_count':len(e.get('questions',[])),'max_score':sum(int(q.get('weight',1)) for q in e.get('questions',[]))}


class Handler(SimpleHTTPRequestHandler):
    def end_headers(self):
        self.send_header('Cache-Control','no-store, no-cache, must-revalidate, max-age=0');self.send_header('Pragma','no-cache');self.send_header('Expires','0');super().end_headers()
    def log_message(self,format,*args):sys.stdout.write('[HTTP] '+(format%args)+'\n')

    def do_GET(self):
        parsed=urlparse(self.path);path=parsed.path;qs=parse_qs(parsed.query)
        try:
            if path=='/api/server-time':
                n=now_wib();return safe_json(self,200,{'server_time':iso(n),'unix_ms':int(n.timestamp()*1000),'timezone':'Asia/Jakarta'})
            if path=='/api/config':
                n=now_wib();return safe_json(self,200,{'app':f'SMAGA Maliku Exam Core V{APP_VERSION}','demo_mode':DEMO_MODE,'backend_mode':BACKEND.mode,'storage_mode':STORAGE.mode,'admin_auth_mode':'email' if production() else 'pin','token_hint':'AKM726' if DEMO_MODE else None,'default_exam_code':'AKM26' if DEMO_MODE else '','server_time':iso(n),'classes':ALLOWED_CLASSES})
            if path=='/api/health':return safe_json(self,200,{'ok':True,'app_version':APP_VERSION,'server_time':iso(now_wib()),'mode':'demo' if DEMO_MODE else 'production','backend':BACKEND.mode,'storage':STORAGE.mode})
            if path=='/api/exam-info':
                code=(qs.get('code') or [''])[0];exam=BACKEND.get_exam_by_code(code,include_keys=False)
                if not exam or exam.get('status')!='published':return safe_json(self,404,{'error':'Ujian tidak ditemukan atau belum dipublikasikan.'})
                return safe_json(self,200,{'id':exam['id'],'code':exam['code'],'title':exam['title'],'description':exam.get('description',''),'duration_seconds':exam.get('duration_seconds',0),'question_count':len(exam.get('questions',[])),'classes':exam.get('classes',[]),'leaderboard':bool(exam.get('leaderboard'))})
            if path=='/api/qr':
                code=(qs.get('code') or [''])[0].upper();host=self.headers.get('Host',f'localhost:{PORT}');scheme='https' if self.headers.get('X-Forwarded-Proto','').lower()=='https' else 'http';base=os.environ.get('SMAGA_PUBLIC_URL',f'{scheme}://{host}').rstrip('/');target=f'{base}/?exam={quote(code)}'
                if not code:return safe_json(self,400,{'error':'Kode ujian wajib.'})
                try:
                    import qrcode
                    img=qrcode.make(target);buf=io.BytesIO();img.save(buf,format='PNG');body=buf.getvalue();self.send_response(200);self.send_header('Content-Type','image/png');self.send_header('Content-Length',str(len(body)));self.end_headers();self.wfile.write(body);return
                except Exception as e:return safe_json(self,500,{'error':'Generator QR membutuhkan paket qrcode/Pillow pada Python.','detail':str(e),'url':target})
            if path=='/api/package':
                sid=(qs.get('session_id') or [''])[0];sess=BACKEND.get_session(sid)
                if not sess:return safe_json(self,401,{'error':'Sesi ujian tidak valid.'})
                exam=BACKEND.get_exam_by_id(sess['exam_id'],include_keys=False)
                if not exam:return safe_json(self,404,{'error':'Ujian tidak ditemukan.'})
                return safe_json(self,200,public_exam(exam,sid))
            if path.startswith('/api/admin/'):
                if not admin_ok(self):return safe_json(self,401,{'error':'PIN admin tidak valid.'})
                if path=='/api/admin/overview':return safe_json(self,200,{**BACKEND.overview(),'server_time':iso(now_wib()),'backend_mode':BACKEND.mode,'storage_mode':STORAGE.mode})
                if path=='/api/admin/exams':return safe_json(self,200,[exam_summary(e) for e in BACKEND.list_exams()])
                if path=='/api/admin/exam':
                    exam_id=(qs.get('id') or [''])[0];e=BACKEND.get_exam_by_id(exam_id,include_keys=True)
                    if not e:return safe_json(self,404,{'error':'Ujian tidak ditemukan.'})
                    return safe_json(self,200,e)
                if path=='/api/admin/participants':return safe_json(self,200,BACKEND.list_sessions((qs.get('exam_id') or [''])[0] or None))
                if path=='/api/admin/results':return safe_json(self,200,BACKEND.list_submissions((qs.get('exam_id') or [''])[0] or None))
                if path=='/api/admin/export.csv':
                    exam_id=(qs.get('exam_id') or [''])[0];rows=BACKEND.list_submissions(exam_id or None);out=[{'nomor':r.get('participant_number'),'nama':r.get('name'),'kelas':r.get('class_name'),'nilai':r.get('score_100'),'skor_mentah':r.get('score_raw'),'maksimum':r.get('max_raw'),'waktu_kirim':r.get('submitted_at')} for r in rows];body=csv_bytes(out,['nomor','nama','kelas','nilai','skor_mentah','maksimum','waktu_kirim']);self.send_response(200);self.send_header('Content-Type','text/csv; charset=utf-8');self.send_header('Content-Disposition','attachment; filename="hasil-smaga-exam.csv"');self.send_header('Content-Length',str(len(body)));self.end_headers();self.wfile.write(body);return
                if path=='/api/admin/storage':return safe_json(self,200,{'stats':STORAGE.stats(),'assets':STORAGE.backend.list_assets(False)[:200]})
                if path=='/api/admin/storage/cleanup-preview':return safe_json(self,200,STORAGE.cleanup_preview())
            if path=='/api/live':
                if production() and not admin_ok(self):return safe_json(self,401,{'error':'Live Board hanya untuk petugas. Login sebagai guru/admin di perangkat ini.'})
                exam_id=(qs.get('exam_id') or [''])[0];exam_code=(qs.get('exam_code') or [''])[0];exam=BACKEND.get_exam_by_id(exam_id,False) if exam_id else (BACKEND.get_exam_by_code(exam_code,False) if exam_code else next((e for e in BACKEND.list_exams() if e.get('status')=='published'),None))
                if not exam:return safe_json(self,404,{'error':'Ujian aktif tidak ditemukan.'})
                sessions=BACKEND.list_sessions(exam['id']);subs=BACKEND.list_submissions(exam['id']);top_raw=sorted(subs,key=lambda x:(-float(x.get('score_100',0)),str(x.get('name',''))))[:10];top=[{k:r.get(k) for k in ['name','class_name','score_100','score_raw','max_raw','submitted_at']} for r in top_raw];byc={}
                for r in subs:byc.setdefault(r['class_name'],[]).append(float(r.get('score_100',0)))
                classes=[{'class_name':c,'average':round(sum(v)/len(v),2),'submitted':len(v)} for c,v in byc.items()];classes.sort(key=lambda x:(-x['average'],x['class_name']))
                return safe_json(self,200,{'exam':{k:exam.get(k) for k in ['id','code','title','token','start_at','end_at','status']},'server_time':iso(now_wib()),'checked_in':len(sessions),'submitted':len(subs),'top10':top,'classes':classes})
            return super().do_GET()
        except AuthError as e:return safe_json(self,e.status,{'error':str(e)})
        except BackendError as e:return safe_json(self,503,{'error':'Backend Supabase bermasalah.','detail':str(e)})
        except Exception as e:return safe_json(self,500,{'error':'Terjadi kesalahan server.','detail':str(e)})

    def do_POST(self):
        parsed=urlparse(self.path);path=parsed.path
        try:
            if path=='/api/admin/auth/login':
                throttle('teacherlogin:'+str(self.client_address[0]),15,300)
                p=read_json(self);return safe_json(self,200,login_teacher(str(p.get('email','')),str(p.get('password',''))))
            if path=='/api/admin/auth/refresh':
                p=read_json(self);return safe_json(self,200,refresh_teacher(str(p.get('refresh_token',''))))
            if path=='/api/login':
                client=self.client_address[0];throttle('login-ip:'+client,600,300)
                p=read_json(self);name=str(p.get('name','')).strip();number=str(p.get('number','')).strip();cls=str(p.get('class_name','')).strip();token=str(p.get('token','')).strip().upper();code=str(p.get('exam_code','AKM26')).strip().upper();throttle('participant:'+code+':'+number,12,600)
                if not name or not number or cls not in ALLOWED_CLASSES:return safe_json(self,400,{'error':'Identitas peserta belum lengkap.'})
                exam=BACKEND.get_exam_by_code(code,True)
                if not exam or exam.get('status')!='published':return safe_json(self,404,{'error':'Kode ujian tidak ditemukan atau belum dipublikasikan.'})
                if cls not in exam.get('classes',ALLOWED_CLASSES):return safe_json(self,403,{'error':'Kelas Anda tidak termasuk peserta ujian ini.'})
                valid_tokens={str(exam.get('token','')).upper(),str(exam.get('token_backup1','')).upper(),str(exam.get('token_backup2','')).upper()};valid_tokens.discard('')
                if token not in valid_tokens:return safe_json(self,403,{'error':'Token tidak valid.'})
                n=now_wib()
                if DEMO_MODE:start=n+timedelta(seconds=DEMO_START_DELAY_SECONDS);end=start+timedelta(seconds=int(exam.get('duration_seconds',3600)));login_window='DEMO'
                else:
                    start=parse_exam_dt(exam['start_at']);end=parse_exam_dt(exam['end_at']);login_window='GENERAL'
                    if end<=start:return safe_json(self,400,{'error':'Jadwal ujian tidak valid. Hubungi guru.'})
                    if exam['id']=='exam-akm-smaga-2026' or exam['code']=='AKM26':
                        if n.date()!=start.date():return safe_json(self,403,{'error':'Tanggal ujian belum sesuai jadwal.'})
                        allowed,detail=production_login_allowed(cls,n)
                        if not allowed:return safe_json(self,403,{'error':'Di luar jendela login angkatan.',**detail})
                        login_window=detail['level']
                    elif not(start-timedelta(minutes=60)<=n<=start):
                        return safe_json(self,403,{'error':'Check-in dibuka 60 menit sebelum ujian dimulai dan ditutup saat ujian mulai.'})
                sess=BACKEND.find_active_session(exam['id'],number)
                if not sess:
                    prior_session=BACKEND.find_any_session(exam['id'],number)
                    if prior_session:return safe_json(self,409,{'error':'Nomor peserta ini sudah digunakan atau sudah mengirim jawaban. Hubungi guru jika perlu reset.'})
                if not sess:
                    sess={'session_id':secrets.token_urlsafe(18),'exam_id':exam['id'],'participant_number':number,'name':name,'class_name':cls,'login_at':iso(n),'start_at':iso(start),'end_at':iso(end),'login_window':login_window,'submitted':False};BACKEND.create_session(sess)
                return safe_json(self,200,{**sess,'exam_title':exam['title'],'exam_code':exam['code'],'server_time':iso(n),'package_url':f"/api/package?session_id={quote(sess['session_id'])}",'question_count':len(exam.get('questions',[])),'max_score':sum(int(q.get('weight',1)) for q in exam.get('questions',[]))})
            if path=='/api/submit':
                p=read_json(self);sid=str(p.get('session_id',''));idem=str(self.headers.get('Idempotency-Key') or p.get('attempt_id',''))
                if not sid or not idem or len(idem)>128:return safe_json(self,400,{'error':'Sesi/attempt ID tidak lengkap.'})
                sess=BACKEND.get_session(sid)
                if not sess:return safe_json(self,404,{'error':'Sesi peserta tidak ditemukan.'})
                a=p.get('answers')
                if not isinstance(a,list) or len(a)>500:return safe_json(self,400,{'error':'Format jawaban tidak valid.'})
                fingerprint=hashlib.sha256(json.dumps(a,sort_keys=True,separators=(',',':')).encode()).hexdigest()
                prior=BACKEND.find_submission(sid,idem)
                if prior:
                    if prior.get('payload_hash') and prior['payload_hash']!=fingerprint:return safe_json(self,409,{'error':'Attempt ID yang sama digunakan untuk jawaban berbeda.'})
                    return safe_json(self,200,safe_student_result({**prior,'idempotent_replay':True},prior.get('show_result_to_student')))
                if sess.get('submitted') or BACKEND.find_session_submission(sid):
                    return safe_json(self,409,{'error':'Sesi sudah selesai. Pengiriman kedua ditolak.'})
                n=now_wib();end=parse_exam_dt(sess['end_at']);start=parse_exam_dt(sess['start_at'])
                if not DEMO_MODE and n<start:return safe_json(self,403,{'error':'Ujian belum dimulai.'})
                if not DEMO_MODE and n>end+timedelta(minutes=2):return safe_json(self,403,{'error':'Batas pengiriman sudah lewat. Hubungi pengawas.'})
                exam=BACKEND.get_exam_by_id(sess['exam_id'],True)
                if not exam:return safe_json(self,404,{'error':'Ujian tidak ditemukan.'})
                allowed_qids={q['id'] for q in exam['questions']}
                if len({x.get('qid') for x in a if isinstance(x,dict)})!=len(a) or any(not isinstance(x,dict) or x.get('qid') not in allowed_qids for x in a):
                    return safe_json(self,400,{'error':'Daftar jawaban tidak valid/duplikat.'})
                result=score_submission(exam,p)
                out={**result,'exam_id':exam['id'],'session_id':sid,'idempotency_key':idem,'payload_hash':fingerprint,'participant_number':sess['participant_number'],'name':sess['name'],'class_name':sess['class_name'],'submitted_at':iso(n),'accepted':True,'idempotent_replay':False,'show_result_to_student':bool(exam.get('show_result_to_student',True))}
                stored=BACKEND.create_submission(out)
                return safe_json(self,200,safe_student_result(stored,exam.get('show_result_to_student',True)))
            if path.startswith('/api/admin/'):
                if not admin_ok(self):return safe_json(self,401,{'error':'PIN admin tidak valid.'})
                p=read_json(self)
                if path=='/api/admin/import-xlsx':
                    raw=base64.b64decode(str(p.get('file_base64','')),validate=False)
                    if len(raw)>8*1024*1024:return safe_json(self,413,{'error':'XLSX terlalu besar (maks. 8 MB).'})
                    rows=parse_xlsx_first_sheet(raw);return safe_json(self,200,{'rows':rows,'count':len(rows)})
                if path=='/api/admin/upload-image':
                    audit(BACKEND,'asset.upload',self._staff)
                    asset=STORAGE.upload_data_url(p.get('data_url',''),p.get('filename','gambar'),p.get('exam_id') or None,'upload');return safe_json(self,200,{'url':asset['public_url'],'bytes':asset['size_bytes'],'mime':asset['mime'],'asset_id':asset['id'],'storage_mode':STORAGE.mode})
                if path=='/api/admin/mirror-image':
                    audit(BACKEND,'asset.mirror',self._staff)
                    asset=STORAGE.mirror_url(p.get('url',''),p.get('exam_id') or None);return safe_json(self,200,{'url':asset['public_url'],'bytes':asset['size_bytes'],'mime':asset['mime'],'asset_id':asset['id'],'storage_mode':STORAGE.mode})
                if path=='/api/admin/storage/archive':
                    audit(BACKEND,'asset.archive',self._staff,{'asset_id':str(p.get('asset_id',''))})
                    row=BACKEND.set_asset_archived(str(p.get('asset_id','')),bool(p.get('archived')));return safe_json(self,200,{'asset':row})
                if path=='/api/admin/storage/cleanup-run':
                    if production() and self._staff['role']!='admin':return safe_json(self,403,{'error':'Hanya admin boleh cleanup.'})
                    audit(BACKEND,'asset.cleanup',self._staff)
                    return safe_json(self,200,STORAGE.cleanup_run(int(p.get('target_pct') or 65)))
                if path=='/api/admin/save-exam':
                    exam_id=str(p.get('id') or f"exam-{secrets.token_hex(5)}");existing=BACKEND.get_exam_by_id(exam_id,True);code=str(p.get('code') or slug_code('EX')).upper().replace(' ','')[:12];token=str(p.get('token') or secrets.token_hex(3)).upper()[:12];token_backup1=str(p.get('token_backup1') or '').upper().replace(' ','')[:12];token_backup2=str(p.get('token_backup2') or '').upper().replace(' ','')[:12]
                    other=BACKEND.get_exam_by_code(code,False)
                    if other and other.get('id')!=exam_id:return safe_json(self,409,{'error':'Kode ujian sudah digunakan.'})
                    if existing and BACKEND.list_sessions(exam_id):return safe_json(self,409,{'error':'Ujian sudah memiliki peserta. Duplikasi ujian untuk mengubah soal/kunci.'})
                    questions=[];keys={};scoring_mode='custom' if p.get('scoring_mode')=='custom' else 'equal'
                    for idx,q in enumerate(p.get('questions') or [],1):
                        kind='pgk' if q.get('kind')=='pgk' else 'pg';qid=q.get('id') or f'Q{idx:03d}';opts=[str(x).strip() for x in (q.get('options') or []) if str(x).strip()]
                        if len(opts)<2:return safe_json(self,400,{'error':f'{qid}: minimal 2 opsi.'})
                        option_ids=q.get('option_ids') if isinstance(q.get('option_ids'),list) else []
                        if len(option_ids)!=len(opts) or len(set(map(str,option_ids)))!=len(opts):option_ids=[f'{qid}-O{i+1}' for i in range(len(opts))]
                        option_ids=[str(x) for x in option_ids]
                        requested_weight=max(1,int(q.get('weight') or 1));weight=requested_weight if scoring_mode=='custom' else 1
                        clean={'id':qid,'kind':kind,'type':'m_n_2' if kind=='pgk' else '1_n_2','weight':weight,'domain':q.get('domain','Umum'),'label':q.get('label') or ('Pilihan Ganda Kompleks' if kind=='pgk' else 'Pilihan Ganda'),'stimulus':q.get('stimulus',''),'question':q.get('question',''),'options':opts,'option_ids':option_ids,'shuffle_options':bool(q.get('shuffle_options')),'image_url':str(q.get('image_url') or ''),'notes':str(q.get('notes') or ''),'visual':False};questions.append(clean);key=q.get('key')
                        if kind=='pg':
                            if isinstance(key,str) and key in option_ids:key_id=key
                            elif isinstance(key,int) and 0<=key<len(opts):key_id=option_ids[key]
                            else:return safe_json(self,400,{'error':f'{qid}: pilih satu kunci jawaban PG.'})
                            keys[qid]={'kind':'pg','answer':key_id,'weight':clean['weight']}
                        else:
                            if isinstance(key,list) and all(isinstance(x,str) for x in key):key_ids=[x for x in key if x in option_ids]
                            elif isinstance(key,list) and len(key)==len(opts):key_ids=[option_ids[i] for i,v in enumerate(key) if bool(v)]
                            else:return safe_json(self,400,{'error':f'{qid}: pilih minimal satu kunci jawaban PGK.'})
                            if not key_ids:return safe_json(self,400,{'error':f'{qid}: pilih minimal satu kunci jawaban PGK.'})
                            keys[qid]={'kind':'pgk','answer':key_ids,'weight':clean['weight']}
                    if not questions:return safe_json(self,400,{'error':'Minimal satu soal diperlukan.'})
                    audit(BACKEND,'exam.save',self._staff,{'exam_id':exam_id,'question_count':len(questions)})
                    duration=max(1,int(p.get('duration_minutes') or 60))*60;exam={'id':exam_id,'code':code,'title':str(p.get('title') or 'Ujian Tanpa Judul'),'description':str(p.get('description') or ''),'token':token,'token_backup1':token_backup1,'token_backup2':token_backup2,'duration_seconds':duration,'status':p.get('status') if p.get('status') in ('draft','published') else 'draft','leaderboard':bool(p.get('leaderboard')),'show_result_to_student':bool(p.get('show_result_to_student')),'shuffle_questions':bool(p.get('shuffle_questions')),'scoring_mode':scoring_mode,'classes':[c for c in p.get('classes',[]) if c in ALLOWED_CLASSES] or ALLOWED_CLASSES,'start_at':p.get('start_at') or iso(now_wib()+timedelta(hours=1)),'end_at':p.get('end_at') or iso(now_wib()+timedelta(hours=2)),'questions':questions,'keys':keys,'created_at':existing.get('created_at') if existing else iso(now_wib()),'updated_at':iso(now_wib())};BACKEND.save_exam(exam);return safe_json(self,200,{'saved':True,'exam':{k:exam[k] for k in ['id','code','title','token','token_backup1','token_backup2','status']},'question_count':len(questions),'max_score':sum(q['weight'] for q in questions),'backend_mode':BACKEND.mode})
                if path=='/api/admin/delete-exam':
                    exam_id=str(p.get('id',''))
                    if exam_id=='exam-akm-smaga-2026':return safe_json(self,403,{'error':'Template Turnamen AKM demo tidak dapat dihapus.'})
                    if production() and self._staff['role']!='admin':return safe_json(self,403,{'error':'Hanya admin boleh menghapus ujian.'})
                    audit(BACKEND,'exam.delete',self._staff,{'exam_id':exam_id});BACKEND.delete_exam(exam_id);return safe_json(self,200,{'deleted':True})
                if path=='/api/admin/reset-session':
                    if production() and self._staff['role']!='admin':return safe_json(self,403,{'error':'Hanya admin boleh reset peserta.'})
                    audit(BACKEND,'session.reset',self._staff,{'session_id':str(p.get('session_id',''))});return safe_json(self,200,{'reset':BACKEND.reset_session(str(p.get('session_id','')))})
            return safe_json(self,404,{'error':'Endpoint tidak ditemukan'})
        except AuthError as e:return safe_json(self,e.status,{'error':str(e)})
        except BackendError as e:return safe_json(self,503,{'error':'Backend Supabase bermasalah.','detail':str(e)})
        except ValueError as e:return safe_json(self,400,{'error':str(e)})
        except Exception as e:return safe_json(self,500,{'error':'Terjadi kesalahan server.','detail':str(e)})


def ensure_numbas():
    if os.environ.get('SMAGA_SKIP_NUMBAS')=='1':print('[BOOT] Skip bootstrap Numbas (SMAGA_SKIP_NUMBAS=1).',flush=True);return
    print('[BOOT] Menyiapkan Numbas generic runtime resmi...',flush=True);subprocess.check_call([sys.executable,str(ROOT/'bootstrap_numbas.py')])

def cleanup_worker():
    interval_hours=max(1,int(os.environ.get('SMAGA_CLEANUP_INTERVAL_HOURS','12')))
    def run():
        while True:
            import time;time.sleep(interval_hours*3600)
            try:
                preview=STORAGE.cleanup_preview()
                if preview['candidate_count'] and (preview['stats']['used_pct']>=STORAGE.warn_pct or any(x.get('cleanup_reason','').startswith(('orphan','ujian')) for x in preview['candidates'])):
                    result=STORAGE.cleanup_run();print(f"[CLEANUP] removed={result['removed_count']} storage={result['stats']['used_pct']}%",flush=True)
            except Exception as e:print('[CLEANUP WARN]',repr(e),flush=True)
    threading.Thread(target=run,daemon=True).start()

class SmagaHTTPServer(ThreadingHTTPServer):
    request_queue_size=256
    daemon_threads=True

def main():
    seed_backend();runtime_ready=True
    try:ensure_numbas()
    except Exception as e:
        runtime_ready=False;print('\n[WARN] Runtime Numbas belum siap:',repr(e),flush=True);print('[WARN] Server tetap dijalankan agar Admin dan Live Board dapat diuji.',flush=True)
    if production() and not runtime_ready:raise RuntimeError('Runtime Numbas tidak tersedia. Deployment production dibatalkan.')
    cleanup_worker()
    try:httpd=SmagaHTTPServer(('0.0.0.0',PORT),Handler)
    except OSError as e:print(f'[FAIL] Port {PORT} tidak dapat digunakan: {e}',flush=True);input('Tekan Enter untuk keluar...');raise SystemExit(2)
    url=f'http://localhost:{PORT}/?v=CORE060'
    print('\n==========================================');print(' SMAGA MALIKU EXAM V1.0 RC1');print('==========================================')
    print(('[OK]' if runtime_ready else '[WAIT]')+' Student :',url);print('[OK] Admin   :',f'http://localhost:{PORT}/admin.html');print('[OK] Live    :',f'http://localhost:{PORT}/live.html');print(f'[DATA] Backend : {BACKEND.mode}');print(f'[ASSET] Storage: {STORAGE.mode}');print('[DEMO] Exam code: AKM26 | token: AKM726');print('==========================================\n')
    if os.environ.get('SMAGA_NO_BROWSER')!='1':threading.Timer(0.8,lambda:webbrowser.open(f'http://localhost:{PORT}/admin.html')).start()
    try:httpd.serve_forever()
    except KeyboardInterrupt:pass
    finally:httpd.server_close()

if __name__=='__main__':main()
