"""Local security regressions. Production Supabase/Auth must still be tested online."""
import json, os, subprocess, sys, tempfile, time
from pathlib import Path
from urllib.request import Request,urlopen
from urllib.error import HTTPError
ROOT=Path(__file__).resolve().parents[1];PORT=8798;BASE=f'http://127.0.0.1:{PORT}'

def request(path,method='GET',p=None,pin=False):
    head={'Content-Type':'application/json'}
    if pin:head['X-Admin-Pin']='2026'
    try:
        with urlopen(Request(BASE+path,method=method,headers=head,data=json.dumps(p).encode() if p is not None else None),timeout=8) as r:
            return r.status,json.loads(r.read())
    except HTTPError as e:return e.code,json.loads(e.read())

def main():
    # A deployment must not run as production without the required secret config.
    env=os.environ.copy()
    env.update({'SMAGA_ENV':'production','SMAGA_DEMO_MODE':'0','SMAGA_SKIP_NUMBAS':'1','SMAGA_NO_BROWSER':'1'})
    env.pop('SUPABASE_URL',None);env.pop('SUPABASE_SERVICE_ROLE_KEY',None)
    p=subprocess.run([sys.executable,str(ROOT/'server.py')],cwd=ROOT,env=env,timeout=8,capture_output=True,text=True)
    assert p.returncode!=0 and 'PRODUCTION DIBLOKIR' in (p.stdout+p.stderr),p.stdout+p.stderr
    env=os.environ.copy();env.update({'PORT':'9999','SMAGA_ENV':'development','SMAGA_SKIP_NUMBAS':'1','SMAGA_NO_BROWSER':'1'})
    p=subprocess.run([sys.executable,str(ROOT/'server.py')],cwd=ROOT,env=env,timeout=8,capture_output=True,text=True)
    assert p.returncode!=0 and 'PRODUCTION DIBLOKIR' in (p.stdout+p.stderr),p.stdout+p.stderr
    with tempfile.TemporaryDirectory() as tmp:
        env=os.environ.copy();env.update({'SMAGA_ENV':'development','SMAGA_PORT':str(PORT),'SMAGA_SKIP_NUMBAS':'1','SMAGA_NO_BROWSER':'1','SMAGA_DB_FILE':str(Path(tmp)/'db.json')})
        env.pop('SUPABASE_URL',None);env.pop('SUPABASE_SERVICE_ROLE_KEY',None)
        srv=subprocess.Popen([sys.executable,str(ROOT/'server.py')],cwd=ROOT,env=env,stdout=subprocess.PIPE,stderr=subprocess.STDOUT)
        try:
            for i in range(40):
                try:
                    if request('/api/health')[0]==200:break
                except Exception:time.sleep(.1)
            assert request('/api/admin/exams')[0]==401
            assert request('/api/admin/exams',pin=True)[0]==200
            exam={'title':'Sec Regression','code':'SEC01','token':'SEC123','duration_minutes':20,'status':'published','classes':['X1'],'show_result_to_student':False,'questions':[{'id':'Q1','kind':'pg','options':['Benar','Salah'],'question':'Pilih benar','key':0}]}
            code,ed=request('/api/admin/save-exam','POST',exam,pin=True);assert code==200,ed
            code,login=request('/api/login','POST',{'exam_code':'SEC01','number':'SEC001','name':'Test Student','class_name':'X1','token':'SEC123'});assert code==200,login
            code,pkg=request(login['package_url']);assert code==200 and 'keys' not in pkg
            attempt={'session_id':login['session_id'],'attempt_id':'ATT01','answers':[{'qid':'Q1','answer':0}]}
            code,out=request('/api/submit','POST',attempt);assert code==200 and out['show_result_to_student'] is False and 'score_100' not in out,out
            code,replay=request('/api/submit','POST',attempt);assert code==200 and replay['idempotent_replay'] is True
            code,fail=request('/api/submit','POST',{**attempt,'answers':[{'qid':'Q1','answer':1}]});assert code==409,fail
            code,fail=request('/api/submit','POST',{**attempt,'attempt_id':'ATT02'});assert code==409,fail
            print('SECURITY LOCAL PASS | production fail-closed, admin gate, no answers, hidden score, idempotency, duplicate rejected')
        finally:
            srv.terminate();srv.wait(timeout=3)
if __name__=='__main__':main()
