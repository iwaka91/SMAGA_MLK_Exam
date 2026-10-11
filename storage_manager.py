from __future__ import annotations
from pathlib import Path
from datetime import datetime, timedelta, timezone
from urllib import request, parse, error
import os, re, base64, secrets, json, ipaddress, socket

TZ_WIB=timezone(timedelta(hours=7))
def now_wib(): return datetime.now(TZ_WIB)
def iso(dt): return dt.isoformat(timespec='seconds')

class StorageManager:
    def __init__(self, root: Path, public: Path, backend):
        self.root=Path(root);self.public=Path(public);self.backend=backend
        self.supabase_url=os.environ.get('SUPABASE_URL','').rstrip('/')
        self.service_key=os.environ.get('SUPABASE_SERVICE_ROLE_KEY','')
        self.bucket=os.environ.get('SMAGA_STORAGE_BUCKET','exam-assets')
        self.limit_bytes=int(float(os.environ.get('SMAGA_STORAGE_LIMIT_MB','1024'))*1024*1024)
        self.warn_pct=int(os.environ.get('SMAGA_STORAGE_WARN_PCT','75'))
        self.critical_pct=int(os.environ.get('SMAGA_STORAGE_CRITICAL_PCT','90'))
        self.retention_days=int(os.environ.get('SMAGA_ASSET_RETENTION_DAYS','180'))
        self.orphan_days=int(os.environ.get('SMAGA_ORPHAN_RETENTION_DAYS','30'))

    @property
    def mode(self):
        return 'supabase' if self.supabase_url and self.service_key and self.backend.mode=='supabase' else 'local'

    def _parse_data_url(self,data_url):
        m=re.match(r'^data:(image/(?:jpeg|jpg|png|webp|gif));base64,(.+)$',str(data_url),re.I|re.S)
        if not m:raise ValueError('Format gambar tidak didukung.')
        mime=m.group(1).lower();raw=base64.b64decode(m.group(2),validate=True)
        valid={'image/png':raw.startswith(b'\x89PNG\r\n\x1a\n'),'image/jpeg':raw.startswith(b'\xff\xd8\xff'),'image/jpg':raw.startswith(b'\xff\xd8\xff'),'image/webp':raw.startswith(b'RIFF') and raw[8:12]==b'WEBP','image/gif':raw.startswith((b'GIF87a',b'GIF89a'))}
        if not valid.get(mime,False):raise ValueError('Konten file tidak cocok dengan tipe gambar yang dinyatakan.')
        if len(raw)>4*1024*1024:raise ValueError('Gambar hasil kompres terlalu besar (maks. 4 MB).')
        ext={'image/jpeg':'jpg','image/jpg':'jpg','image/png':'png','image/webp':'webp','image/gif':'gif'}[mime]
        return mime,raw,ext

    def _safe_stem(self,filename):
        return re.sub(r'[^A-Za-z0-9_-]+','-',Path(str(filename)).stem).strip('-')[:48] or 'gambar'

    def _supabase_upload(self,path,raw,mime):
        url=f"{self.supabase_url}/storage/v1/object/{parse.quote(self.bucket,safe='')}/{parse.quote(path,safe='/')}"
        headers={'apikey':self.service_key,'Authorization':f'Bearer {self.service_key}','Content-Type':mime,'x-upsert':'false'}
        req=request.Request(url,data=raw,headers=headers,method='POST')
        try:
            with request.urlopen(req,timeout=30) as r:r.read()
        except error.HTTPError as e:
            raise RuntimeError(f'Upload Supabase Storage gagal ({e.code}): {e.read().decode("utf-8","replace")[:400]}')
        return f"{self.supabase_url}/storage/v1/object/public/{self.bucket}/{path}"

    def _supabase_remove(self,path):
        url=f"{self.supabase_url}/storage/v1/object/{parse.quote(self.bucket,safe='')}"
        headers={'apikey':self.service_key,'Authorization':f'Bearer {self.service_key}','Content-Type':'application/json'}
        data=json.dumps({'prefixes':[path]}).encode('utf-8')
        req=request.Request(url,data=data,headers=headers,method='DELETE')
        try:
            with request.urlopen(req,timeout=30) as r:r.read()
        except error.HTTPError as e:
            raise RuntimeError(f'Hapus Storage gagal ({e.code}): {e.read().decode("utf-8","replace")[:400]}')

    def upload_data_url(self,data_url,filename='gambar',exam_id=None,source='upload'):
        mime,raw,ext=self._parse_data_url(data_url)
        stamp=now_wib();stem=self._safe_stem(filename);token=secrets.token_hex(5)
        exam_folder=re.sub(r'[^A-Za-z0-9_-]+','-',str(exam_id or 'unassigned'))[:64]
        rel=f"{exam_folder}/{stamp:%Y/%m}/{stem}-{token}.{ext}"
        if self.mode=='supabase':
            public_url=self._supabase_upload(rel,raw,mime);storage_path=rel
        else:
            folder=self.public/'uploads'/exam_folder/f'{stamp:%Y%m}';folder.mkdir(parents=True,exist_ok=True)
            path=folder/f'{stem}-{token}.{ext}';path.write_bytes(raw)
            public_url='/'+str(path.relative_to(self.public)).replace('\\','/');storage_path=str(path.relative_to(self.public)).replace('\\','/')
        asset={'id':secrets.token_hex(16),'exam_id':exam_id or None,'storage_path':storage_path,'public_url':public_url,'mime':mime,'size_bytes':len(raw),'source':source,'archived':False,'created_at':iso(stamp),'last_used_at':iso(stamp),'deleted_at':None}
        self.backend.add_asset(asset)
        return asset

    def _is_private_host(self,host):
        try:
            ips=socket.getaddrinfo(host,None)
            for item in ips:
                ip=ipaddress.ip_address(item[4][0])
                if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved:return True
        except Exception:return True
        return False

    def mirror_url(self,url,exam_id=None):
        u=parse.urlparse(str(url).strip())
        if u.scheme not in ('http','https') or not u.hostname:raise ValueError('URL gambar tidak valid.')
        if self._is_private_host(u.hostname):raise ValueError('Host lokal/private tidak diizinkan.')
        req=request.Request(url,headers={'User-Agent':'SMAGA-Maliku-Exam/1.0-RC1'})
        class RejectRedirect(request.HTTPRedirectHandler):
            def redirect_request(self, req, fp, code, msg, headers, newurl):
                raise ValueError('Pengalihan URL ditolak untuk keamanan. Gunakan URL gambar final.')
        safe_opener=request.build_opener(RejectRedirect)
        try:
            with safe_opener.open(req,timeout=15) as r:
                mime=(r.headers.get_content_type() or '').lower()
                if mime not in ('image/jpeg','image/png','image/webp','image/gif'):raise ValueError('URL tersebut bukan file gambar langsung. Gunakan URL JPG/PNG/WebP/GIF atau upload file.')
                raw=r.read(4*1024*1024+1)
        except ValueError:raise
        except Exception as e:raise ValueError(f'Gagal mengambil gambar: {e}')
        if len(raw)>4*1024*1024:raise ValueError('Gambar terlalu besar (maks. 4 MB setelah download).')
        ext={'image/jpeg':'jpg','image/png':'png','image/webp':'webp','image/gif':'gif'}[mime]
        data_url=f'data:{mime};base64,'+base64.b64encode(raw).decode('ascii')
        filename=Path(u.path).name or f'gambar.{ext}'
        return self.upload_data_url(data_url,filename,exam_id,source='mirror')

    def stats(self):
        assets=self.backend.list_assets(False);used=sum(int(a.get('size_bytes') or 0) for a in assets)
        pct=round((used/self.limit_bytes*100),2) if self.limit_bytes else 0
        return {'mode':self.mode,'bucket':self.bucket if self.mode=='supabase' else 'local uploads','used_bytes':used,'limit_bytes':self.limit_bytes,'used_pct':pct,'file_count':len(assets),'archived_count':sum(bool(a.get('archived')) for a in assets),'orphan_count':sum(not a.get('exam_id') for a in assets),'warn_pct':self.warn_pct,'critical_pct':self.critical_pct,'retention_days':self.retention_days,'orphan_days':self.orphan_days}

    def _parse_dt(self,s):
        try:
            d=datetime.fromisoformat(str(s).replace('Z','+00:00'))
            return d.replace(tzinfo=TZ_WIB) if d.tzinfo is None else d.astimezone(TZ_WIB)
        except:return now_wib()

    def cleanup_candidates(self,force_capacity=False):
        assets=self.backend.list_assets(False);now=now_wib();exams={e['id']:e for e in self.backend.list_exams()};c=[]
        referenced_urls={q.get('image_url') for e in exams.values() for q in e.get('questions',[]) if q.get('image_url')}
        for a in assets:
            if a.get('archived'):continue
            # Images referenced by a question must NEVER be removed silently.
            if a.get('public_url') in referenced_urls: continue
            created=self._parse_dt(a.get('created_at'));reason=None
            if not a.get('exam_id') and now-created>timedelta(days=self.orphan_days):reason=f'orphan > {self.orphan_days} hari'
            elif a.get('exam_id'):
                ex=exams.get(a['exam_id']);end=self._parse_dt(ex.get('end_at')) if ex else created
                if ex and end>now:continue # future/running exam protection
                if now-end>timedelta(days=self.retention_days):reason=f'ujian selesai > {self.retention_days} hari'
            if reason:c.append({**a,'cleanup_reason':reason})
        c.sort(key=lambda x:self._parse_dt(x.get('last_used_at') or x.get('created_at')))
        stats=self.stats()
        if force_capacity or stats['used_pct']>=self.warn_pct:
            known={x['id'] for x in c}
            # Capacity pressure may remove orphan/unused assets ONLY, never assets
            # still referenced by a question, even if storage stays above threshold.
            for a in sorted([x for x in assets if not x.get('archived') and x.get('id') not in known and x.get('public_url') not in referenced_urls and not x.get('exam_id')],key=lambda x:self._parse_dt(x.get('last_used_at') or x.get('created_at'))):
                c.append({**a,'cleanup_reason':'kapasitas storage (tidak terpakai)'});known.add(a['id'])
        return c

    def cleanup_preview(self):
        c=self.cleanup_candidates();return {'stats':self.stats(),'candidate_count':len(c),'reclaim_bytes':sum(int(x.get('size_bytes') or 0) for x in c),'candidates':c[:100]}

    def cleanup_run(self,target_pct=65):
        stats=self.stats();c=self.cleanup_candidates();removed=[];errors=[];used=stats['used_bytes'];target=int(self.limit_bytes*target_pct/100)
        for a in c:
            # If below warning threshold, remove only age/orphan candidates. Capacity-only candidates stop at target.
            if str(a.get('cleanup_reason','')).startswith('kapasitas storage') and used<=target:break
            try:
                if self.mode=='supabase':self._supabase_remove(a['storage_path'])
                else:
                    p=self.public/a['storage_path']
                    if p.exists():p.unlink()
                self.backend.mark_asset_deleted(a['id']);removed.append(a['id']);used-=int(a.get('size_bytes') or 0)
            except Exception as e:errors.append({'id':a.get('id'),'error':str(e)})
        return {'removed_count':len(removed),'removed_ids':removed,'errors':errors,'stats':self.stats()}
