from __future__ import annotations
import json, os, subprocess, sys, tempfile, time, base64, io, zipfile
from pathlib import Path
from urllib.request import Request, urlopen

ROOT=Path(__file__).resolve().parent
PORT=8796
BASE=f'http://127.0.0.1:{PORT}'
PIN='2026'

def req(path,method='GET',payload=None,admin=False,headers=None):
    body=None;h={'Accept':'application/json'}
    if payload is not None: body=json.dumps(payload).encode();h['Content-Type']='application/json'
    if admin:h['X-Admin-Pin']=PIN
    if headers:h.update(headers)
    r=Request(BASE+path,data=body,headers=h,method=method)
    with urlopen(r,timeout=5) as res:
        ctype=res.headers.get('Content-Type','');data=res.read()
        return json.loads(data.decode()) if 'json' in ctype else data

def wait_server():
    for _ in range(60):
        try:
            if req('/api/health').get('ok'):return
        except Exception:time.sleep(.1)
    raise RuntimeError('Server test tidak siap')

def main():
    with tempfile.TemporaryDirectory() as td:
        env=os.environ.copy();env.pop('SUPABASE_URL',None);env.pop('SUPABASE_SERVICE_ROLE_KEY',None)
        env.update({'SMAGA_PORT':str(PORT),'SMAGA_SKIP_NUMBAS':'1','SMAGA_NO_BROWSER':'1','SMAGA_DB_FILE':str(Path(td)/'test_db.json'),'SMAGA_STORAGE_LIMIT_MB':'1'})
        p=subprocess.Popen([sys.executable,str(ROOT/'server.py')],cwd=ROOT,env=env,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True)
        try:
            wait_server()
            exam={
                'title':'E2E V0.6 Generic','description':'Scoring equal + key IDs + shuffle','code':'E2E60','token':'TES123','token_backup1':'CAD123','token_backup2':'CAD456','duration_minutes':30,
                'status':'published','leaderboard':True,'show_result_to_student':True,'shuffle_questions':True,'scoring_mode':'equal','classes':['XI A'],
                'questions':[
                    {'id':'Q001','kind':'pg','weight':7,'domain':'Umum','stimulus':'2 + 2','question':'Hasil 2 + 2 adalah ...','options':['3','4','5','6'],'key':1,'shuffle_options':True,'image_url':'https://example.invalid/q1.jpg','notes':'CATATAN RAHASIA GURU'},
                    {'id':'Q002','kind':'pgk','weight':9,'domain':'Umum','stimulus':'Pilih semua bilangan genap.','question':'Pernyataan yang benar?','options':['2','3','4','5'],'key':[True,False,True,False],'shuffle_options':True},
                ]
            }
            png='iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAusB9Wl2ZuoAAAAASUVORK5CYII='
            up=req('/api/admin/upload-image','POST',{'filename':'pixel.png','data_url':'data:image/png;base64,'+png},admin=True)
            exam['questions'][0]['image_url']=up['url']

            # XLSX template still imports and exposes new Acak Opsi column.
            template=(ROOT/'public'/'templates'/'template-soal-smaga-exam.xlsx').read_bytes()
            zin=zipfile.ZipFile(io.BytesIO(template),'r');files={n:zin.read(n) for n in zin.namelist()};zin.close()
            files['xl/worksheets/sheet1.xml']=files['xl/worksheets/sheet2.xml']
            out=io.BytesIO()
            with zipfile.ZipFile(out,'w',zipfile.ZIP_DEFLATED) as z:
                for n,b in files.items():z.writestr(n,b)
            imported=req('/api/admin/import-xlsx','POST',{'filename':'sample.xlsx','file_base64':base64.b64encode(out.getvalue()).decode()},admin=True)
            assert imported['count']==2 and imported['rows'][0].get('acak_opsi')=='Ya'

            saved=req('/api/admin/save-exam','POST',exam,admin=True);exam_id=saved['exam']['id']
            assert saved['max_score']==2, saved
            custom={**exam,'id':None,'title':'E2E Bobot Khusus','code':'E2EC6','scoring_mode':'custom','questions':[dict(exam['questions'][0],weight=1),dict(exam['questions'][1],weight=2)]}
            custom.pop('id',None)
            custom_saved=req('/api/admin/save-exam','POST',custom,admin=True)
            assert custom_saved['max_score']==3, custom_saved
            stored=req('/api/admin/exam?id='+exam_id,admin=True)
            assert stored['scoring_mode']=='equal' and stored['shuffle_questions'] is True
            assert all(q['weight']==1 for q in stored['questions'])
            assert all(len(q.get('option_ids',[]))==4 for q in stored['questions'])
            assert isinstance(stored['keys']['Q001']['answer'],str)
            assert all(isinstance(x,str) for x in stored['keys']['Q002']['answer'])

            login=req('/api/login','POST',{'exam_code':'E2E60','number':'001','name':'Siswa Parsial','class_name':'XI A','token':'CAD123'})
            package=req(login['package_url']);package_again=req(login['package_url'])
            assert package==package_again, 'Shuffle paket harus deterministik untuk sesi yang sama'
            raw=json.dumps(package).lower()
            assert 'keys' not in raw and 'catatan rahasia guru' not in raw
            assert package['question_count']==2 and package['max_score']==2 and package['shuffle_questions'] is True
            byid={q['id']:q for q in package['questions']}
            assert all(len(q['option_ids'])==len(q['options']) for q in byid.values())

            pg_key=stored['keys']['Q001']['answer'];pgk_keys=stored['keys']['Q002']['answer']
            # PG benar, PGK hanya sebagian -> PGK tetap 0. Total 1/2 = 50.
            payload={'attempt_id':login['session_id']+'-FINAL','session_id':login['session_id'],'answers':[{'qid':'Q001','type':'1_n_2','answer':pg_key},{'qid':'Q002','type':'m_n_2','answer':pgk_keys[:1]}]}
            result=req('/api/submit','POST',payload,headers={'Idempotency-Key':payload['attempt_id']})
            assert result['score_raw']==1 and result['max_raw']==2 and result['score_100']==50, result
            replay=req('/api/submit','POST',payload,headers={'Idempotency-Key':payload['attempt_id']});assert replay['idempotent_replay'] is True

            login2=req('/api/login','POST',{'exam_code':'E2E60','number':'002','name':'Siswa Benar','class_name':'XI A','token':'TES123'})
            payload2={'attempt_id':login2['session_id']+'-FINAL','session_id':login2['session_id'],'answers':[{'qid':'Q001','type':'1_n_2','answer':pg_key},{'qid':'Q002','type':'m_n_2','answer':pgk_keys}]}
            result2=req('/api/submit','POST',payload2,headers={'Idempotency-Key':payload2['attempt_id']})
            assert result2['score_raw']==2 and result2['max_raw']==2 and result2['score_100']==100, result2

            qr=req('/api/qr?code=E2E60');assert qr[:8]==b'\x89PNG\r\n\x1a\n'
            results=req('/api/admin/results?exam_id='+exam_id,admin=True);live=req('/api/live?exam_id='+exam_id)
            assert len(results)==2 and live['submitted']==2 and live['top10'][0]['score_100']==100
            print('E2E V0.6 PASS')
            print('Equal scoring 1/2 + PGK all-or-nothing + stable option IDs + deterministic shuffle + XLSX + token cadangan + submit/live: OK')
        finally:
            p.terminate()
            try:p.wait(timeout=3)
            except subprocess.TimeoutExpired:p.kill()
            if p.returncode not in (0,-15,1):
                print(p.stdout.read() if p.stdout else '')

if __name__=='__main__':main()
