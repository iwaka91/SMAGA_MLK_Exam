from __future__ import annotations
import os,re,sys,urllib.request,urllib.parse,urllib.error,traceback,shutil,time
from pathlib import Path

ROOT=Path(__file__).resolve().parent
PUBLIC=ROOT/'public'
VENDOR=PUBLIC/'vendor'/'numbas'
TEMPLATE=PUBLIC/'index.template.html'
OUT=PUBLIC/'index.html'
DEMO='https://www.numbas.org.uk/demos/generic-runtime/'
UA='SMAGA-Maliku-Exam-Core/0.3.0 (+official Numbas generic runtime bootstrap)'


def get(url:str, timeout:int=20)->bytes:
    req=urllib.request.Request(url,headers={'User-Agent':UA,'Accept':'text/html,application/xhtml+xml,*/*;q=0.8'})
    print(f'      GET {url}', flush=True)
    t=time.time()
    with urllib.request.urlopen(req,timeout=timeout) as r:
        data=r.read()
    print(f'      OK  {len(data):,} bytes ({time.time()-t:.1f}s)', flush=True)
    return data

def text(url:str)->str:
    return get(url).decode('utf-8','replace')

def find_template(s:str)->str:
    m=re.search(r'(<template\b[^>]*\bid=["\']numbas-exam-template["\'][^>]*>.*?</template>)',s,re.I|re.S)
    if not m: raise RuntimeError('Template #numbas-exam-template tidak ditemukan pada demo resmi Numbas.')
    return m.group(1)

def find_asset(s:str,kind:str,required=True):
    candidates=[]
    if kind=='js':
        candidates+=re.findall(r'<script\b[^>]*\bsrc\s*=\s*["\']([^"\']+)["\'][^>]*>',s,re.I)
        candidates+=re.findall(r'<link\b[^>]*\bhref\s*=\s*["\']([^"\']+\.js(?:\?[^"\']*)?)["\'][^>]*>',s,re.I)
        candidates=[u for u in candidates if re.search(r'\.js(?:\?|$)',u,re.I)]
        def rank(u):
            x=u.lower(); return (0 if 'numbas' in x else 1,0 if 'runtime' in x else 1,len(x))
    else:
        candidates+=re.findall(r'<link\b[^>]*\bhref\s*=\s*["\']([^"\']+\.css(?:\?[^"\']*)?)["\'][^>]*>',s,re.I)
        def rank(u):
            x=u.lower(); return (0 if 'numbas' in x else 1,0 if 'runtime' in x else 1,len(x))
    seen=[]
    for u in sorted(candidates,key=rank):
        absu=urllib.parse.urljoin(DEMO,u)
        if absu not in seen: seen.append(absu)
    if seen:return seen[0]
    if required:raise RuntimeError(f'Asset {kind} wajib tidak ditemukan di demo resmi Numbas.')
    return None

def rewrite_template(template:str, css_rel:str)->str:
    template=re.sub(r'url\((["\']?)numbas\.css\1\)',f'url("{css_rel}")',template,flags=re.I)
    template=re.sub(r'@import\s+(["\'])numbas\.css\1',f'@import "{css_rel}"',template,flags=re.I)
    return template

def valid_cache(folder:Path):
    js=folder/'numbas.js'; demo=folder/'official-demo.html'
    if not (js.exists() and demo.exists()): return False
    try:
        head=js.read_bytes()[:500000]
        dh=demo.read_text(encoding='utf-8',errors='replace')
        return (b'Numbas' in head or b'numbas' in head.lower()) and 'numbas-exam-template' in dh
    except Exception:return False

def import_existing_cache():
    # Gate B2 yang sebelumnya sukses biasanya diekstrak di folder Downloads yang sama.
    # Hindari scan seluruh profil Windows: cek hanya folder saudara berawalan smaga-maliku-exam-.
    base=ROOT.parent
    print('[CACHE] Mencari runtime Numbas dari Gate/Core sebelumnya di folder yang sama...', flush=True)
    candidates=[]
    try:
        for d in base.glob('smaga-maliku-exam-*'):
            if not d.is_dir() or d.resolve()==ROOT.resolve(): continue
            candidates += [d/'vendor'/'numbas', d/'public'/'vendor'/'numbas']
    except (OSError,PermissionError):
        candidates=[]
    for folder in candidates:
        if valid_cache(folder):
            print(f'[CACHE] Ditemukan: {folder}', flush=True)
            VENDOR.mkdir(parents=True,exist_ok=True)
            for name in ('numbas.js','numbas.css','official-demo.html','official-generic-runtime.txt'):
                src=folder/name
                if src.exists(): shutil.copy2(src,VENDOR/name)
            if not (VENDOR/'numbas.css').exists(): (VENDOR/'numbas.css').write_text('/* optional */\n',encoding='utf-8')
            return True
    print('[CACHE] Tidak menemukan cache lama yang valid.', flush=True)
    return False

def build_index():
    demo_path=VENDOR/'official-demo.html'; js_path=VENDOR/'numbas.js'; css_path=VENDOR/'numbas.css'
    demo_html=demo_path.read_text(encoding='utf-8',errors='replace')
    tpl=find_template(demo_html)
    css_rel=os.path.relpath(css_path,PUBLIC).replace('\\','/')
    js_rel=os.path.relpath(js_path,PUBLIC).replace('\\','/')
    tpl=rewrite_template(tpl,css_rel)
    page=TEMPLATE.read_text(encoding='utf-8')
    page=page.replace('{{NUMBAS_TEMPLATE}}',tpl).replace('{{NUMBAS_JS}}',js_rel)
    OUT.write_text(page,encoding='utf-8')

def prepare(force=False):
    VENDOR.mkdir(parents=True,exist_ok=True)
    marker=VENDOR/'official-generic-runtime.txt'; js_path=VENDOR/'numbas.js'; css_path=VENDOR/'numbas.css'; demo_path=VENDOR/'official-demo.html'
    if force:
        for p in (marker,js_path,css_path,demo_path):p.unlink(missing_ok=True)

    if not valid_cache(VENDOR):
        if not force and import_existing_cache():
            print('[1/4] Menggunakan cache runtime Numbas dari pengujian sebelumnya.', flush=True)
        else:
            print('[1/4] Mengambil generic runtime resmi Numbas...',flush=True)
            print('      Jika tahap ini lebih dari ~20 detik, request akan gagal otomatis.',flush=True)
            demo_html=text(DEMO); js_url=find_asset(demo_html,'js',True); css_url=find_asset(demo_html,'css',False)
            print('      JS :',js_url,flush=True);print('      CSS:',css_url or '[optional/tidak ditemukan]',flush=True)
            js_path.write_bytes(get(js_url))
            if css_url:
                try:css_path.write_bytes(get(css_url))
                except Exception as e:
                    print('[WARN] CSS gagal diambil, dilewati:',repr(e),flush=True)
                    css_path.write_text('/* optional */\n',encoding='utf-8')
            else:css_path.write_text('/* optional */\n',encoding='utf-8')
            demo_path.write_text(demo_html,encoding='utf-8')
            marker.write_text(f'Source: {DEMO}\nJS: {js_url}\nCSS: {css_url}\n',encoding='utf-8')
    else:
        print('[1/4] Runtime Numbas sudah ada di cache lokal Core ini.',flush=True)

    print('[2/4] Mengekstrak template resmi...',flush=True)
    print('[3/4] Membangun index.html...',flush=True)
    build_index()
    print('[4/4] Selesai:',OUT,flush=True)

if __name__=='__main__':
    try:prepare('--force' in sys.argv)
    except Exception as e:
        print('\n[FAIL] Bootstrap Numbas gagal:',repr(e),flush=True)
        if isinstance(e,(urllib.error.URLError,TimeoutError)):
            print('[DIAG] Koneksi ke Numbas timeout/gagal. Server Core tetap dapat dipakai untuk Admin/Live.',flush=True)
        print('[DIAG] URL:',DEMO,flush=True);traceback.print_exc();sys.exit(1)
