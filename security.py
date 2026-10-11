"""SMAGA Exam security boundary: auth, throttling, and audit (production)."""
from __future__ import annotations
from datetime import datetime, timezone
from urllib import request, error, parse
import json, os, threading, time, hashlib, re

_LOCK=threading.RLock()
_HITS={}
_AUTH_CACHE={}

class AuthError(Exception):
    def __init__(self,message='Autentikasi gagal',status=401):
        super().__init__(message);self.status=status

def production(): return os.getenv('SMAGA_ENV','development').strip().lower() == 'production'

def assert_production_config():
    if os.getenv('PORT') and not production():
        raise RuntimeError('PRODUCTION DIBLOKIR: host online terdeteksi, tetapi SMAGA_ENV bukan production.')
    if not production():return
    url=os.getenv('SUPABASE_URL','')
    key=os.getenv('SUPABASE_SERVICE_ROLE_KEY','')
    if not url.startswith('https://') or 'PROJECT-REF' in url or len(key)<25 or 'PASTE_' in key:
        raise RuntimeError('PRODUCTION DIBLOKIR: SUPABASE_URL dan SUPABASE_SERVICE_ROLE_KEY harus valid.')
    if os.getenv('SMAGA_DEMO_MODE','0')!='0':
        raise RuntimeError('PRODUCTION DIBLOKIR: SMAGA_DEMO_MODE harus 0.')
    public_url=os.getenv('SMAGA_PUBLIC_URL','')
    if public_url and not public_url.startswith('https://'):
        raise RuntimeError('PRODUCTION DIBLOKIR: SMAGA_PUBLIC_URL harus https://... bila diisi')

def throttle(key,max_hits,window_seconds):
    """Defense-in-depth for a single process. Configure upstream WAF for distributed abuse.

    Counter may overcount successful retries and is NOT a substitute for per-IP WAF.
    """
    now=time.monotonic()
    with _LOCK:
        if len(_HITS)>25000:
            for k,v in list(_HITS.items()):
                if v[0]+window_seconds<now: _HITS.pop(k,None)
        since,n=_HITS.get(key,(now,0))
        if now-since>window_seconds: since,n=now,0
        n+=1;_HITS[key]=(since,n)
        if n>max_hits: raise AuthError('Terlalu banyak percobaan. Tunggu beberapa menit.',429)

def _http_json(url,method='GET',body=None,token=None):
    key=os.getenv('SUPABASE_SERVICE_ROLE_KEY','')
    headers={'apikey':key,'Content-Type':'application/json'}
    if token:headers['Authorization']='Bearer '+token
    else:headers['Authorization']='Bearer '+key
    data=json.dumps(body).encode() if body is not None else None
    req=request.Request(url,data=data,headers=headers,method=method)
    try:
        with request.urlopen(req,timeout=8) as r:
            b=r.read(131072)
            return json.loads(b) if b else {}
    except error.HTTPError as e:
        raise AuthError('Email/password atau sesi tidak valid.',401) from e
    except (TimeoutError,OSError) as e:
        raise AuthError('Layanan login tidak dapat dihubungi. Coba lagi.',503) from e

def _supabase_base(): return os.environ['SUPABASE_URL'].rstrip('/')

def user_role(token):
    if not token or len(token)>8000:raise AuthError()
    digest=hashlib.sha256(token.encode()).hexdigest();now=time.monotonic()
    with _LOCK:
        if digest in _AUTH_CACHE and _AUTH_CACHE[digest][0]>now:return _AUTH_CACHE[digest][1]
    user=_http_json(_supabase_base()+'/auth/v1/user',token=token)
    uid=user.get('id')
    if not uid or not re.fullmatch(r'[a-fA-F0-9-]{36}',uid):raise AuthError()
    rows=_http_json(_supabase_base()+'/rest/v1/staff_roles?user_id=eq.'+uid+'&select=role,enabled&limit=1')
    role=rows[0]['role'] if isinstance(rows,list) and rows and rows[0].get('enabled') else None
    if role not in ('admin','teacher'):raise AuthError('Akun ini belum diberi izin guru/admin.',403)
    result={'user_id':uid,'role':role}
    with _LOCK:_AUTH_CACHE[digest]=(now+45,result)
    return result

def authorize(handler):
    if not production():
        return {'user_id':'local-demo','role':'admin'} if handler.headers.get('X-Admin-Pin','')==os.getenv('SMAGA_ADMIN_PIN','2026') else None
    auth=handler.headers.get('Authorization','')
    if not auth.startswith('Bearer '):return None
    try:return user_role(auth[7:])
    except AuthError:return None

def login_teacher(email,password):
    if not production():raise AuthError('Login email hanya tersedia pada mode produksi.',400)
    data=_http_json(_supabase_base()+'/auth/v1/token?grant_type=password',method='POST',body={'email':email,'password':password})
    token=data.get('access_token','')
    who=user_role(token)
    return {'access_token':token,'refresh_token':data.get('refresh_token',''),'expires_in':data.get('expires_in',3600),'role':who['role']}

def refresh_teacher(refresh_token):
    if not production():raise AuthError('Tidak tersedia dalam mode lokal.',400)
    data=_http_json(_supabase_base()+'/auth/v1/token?grant_type=refresh_token',method='POST',body={'refresh_token':refresh_token})
    who=user_role(data.get('access_token',''))
    return {'access_token':data['access_token'],'refresh_token':data.get('refresh_token',refresh_token),'expires_in':data.get('expires_in',3600),'role':who['role']}

def audit(backend,kind,who,details=None):
    if not production():return
    # Fail closed if audit storage fails for critical operations, so traces are not silently lost.
    backend._req('POST','audit_logs',None,{'action':kind,'actor_id':who.get('user_id'),'details':details or {}},'return=minimal')
