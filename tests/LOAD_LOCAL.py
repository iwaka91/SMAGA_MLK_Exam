"""Synthetic LOCAL load test (not proof of Supabase production capacity).
Usage: python tests/LOAD_LOCAL.py [participants]
"""
import os,sys,json,tempfile,time,subprocess,concurrent.futures
from pathlib import Path
from urllib.request import Request,urlopen
from urllib.error import HTTPError
ROOT=Path(__file__).resolve().parents[1];PORT=8799;BASE=f'http://127.0.0.1:{PORT}'

def req(path,method='GET',data=None,admin=False):
    h={'Content-Type':'application/json'}
    if admin:h['X-Admin-Pin']='2026'
    b=json.dumps(data).encode() if data is not None else None
    with urlopen(Request(BASE+path,data=b,method=method,headers=h),timeout=25) as r:return json.loads(r.read())

def main():
    n=int(sys.argv[1]) if len(sys.argv)>1 else 200
    with tempfile.TemporaryDirectory() as tmp:
        env=os.environ.copy();env.update({'SMAGA_ENV':'development','SMAGA_PORT':str(PORT),'SMAGA_SKIP_NUMBAS':'1','SMAGA_NO_BROWSER':'1','SMAGA_DB_FILE':str(Path(tmp)/'db.json')})
        env.pop('SUPABASE_URL',None);env.pop('SUPABASE_SERVICE_ROLE_KEY',None)
        p=subprocess.Popen([sys.executable,str(ROOT/'server.py')],cwd=ROOT,env=env,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        try:
            for x in range(60):
                try:
                    if req('/api/health')['ok']:break
                except Exception:time.sleep(.2)
            exam={'title':'Load smoke','code':'LOAD01','token':'LOADSEC','duration_minutes':90,'status':'published','show_result_to_student':True,'classes':['X1'],'questions':[{'id':'Q1','kind':'pg','options':['Benar','Salah'],'question':'1+1 = 2','key':0}]}
            req('/api/admin/save-exam','POST',exam,True)
            def login(i):
                try:return req('/api/login','POST',{'exam_code':'LOAD01','number':str(100000+i),'name':f'Test {i}','class_name':'X1','token':'LOADSEC'})
                except Exception as e:return e
            begin=time.monotonic()
            with concurrent.futures.ThreadPoolExecutor(max_workers=24) as pool:
                sessions=list(pool.map(login,range(n)))
            dtlogin=time.monotonic()-begin
            success=[x for x in sessions if isinstance(x,dict) and x.get('session_id')];fail=[str(x) for x in sessions if x not in success]
            def submit(s):
                try:return req('/api/submit','POST',{'session_id':s['session_id'],'attempt_id':'once-'+s['session_id'],'answers':[{'qid':'Q1','answer':0}]})
                except Exception as e:return e
            begin=time.monotonic()
            with concurrent.futures.ThreadPoolExecutor(max_workers=24) as pool:
                outs=list(pool.map(submit,success))
            dtsubmit=time.monotonic()-begin
            good=[x for x in outs if isinstance(x,dict) and x.get('score_100')==100]
            print(json.dumps({'target':n,'login_ok':len(success),'submit_ok':len(good),'login_seconds':round(dtlogin,2),'submit_seconds':round(dtsubmit,2),'errors':fail[:5]+[str(x) for x in outs if x not in good][:5]},indent=2))
            assert len(success)==n and len(good)==n,'Local load failed'
        finally:
            p.terminate();p.wait(timeout=6)
if __name__=='__main__':main()
