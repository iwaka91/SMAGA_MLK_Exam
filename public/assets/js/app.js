(() => {
'use strict';

const $ = id => document.getElementById(id);
const views=['bootView','loginView','waitingView','examView','reviewView','submittingView','resultView'];
const DB_NAME='smaga-maliku-exam-core-v04';
const DB_STORE='attempts';
const SESSION_LS='smagaCoreSessionV04';

let config=null;
let session=null;
let examPackage=null;
let engineEl=null;
let engineReady=false;
let currentIndex=0;
let flags={};
let serverOffsetMs=0;
let timerHandle=null;
let waitingHandle=null;
let autoSubmitting=false;
let lastSavedHash='';
let packageReady=false;

function showView(id){views.forEach(v=>$(v).classList.toggle('hidden',v!==id));}
function toast(msg,ms=2500){const t=$('toast');t.textContent=msg;t.classList.remove('hidden');clearTimeout(t._h);t._h=setTimeout(()=>t.classList.add('hidden'),ms)}
function fmtClock(ms){const d=new Date(ms);return d.toLocaleTimeString('id-ID',{hour:'2-digit',minute:'2-digit',second:'2-digit'}).replaceAll('.',':')}
function fmtDuration(sec){sec=Math.max(0,Math.floor(sec));const h=Math.floor(sec/3600),m=Math.floor((sec%3600)/60),s=sec%60;return `${String(h).padStart(2,'0')}:${String(m).padStart(2,'0')}:${String(s).padStart(2,'0')}`}
function serverNowMs(){return Date.now()+serverOffsetMs}
function isAnswered(ans,kind){if(kind==='pg') return Number.isInteger(ans);if(kind==='pgk') return Array.isArray(ans)&&ans.some(Boolean);return false}
function qidAt(i){return examPackage?.questions?.[i]?.id}
function currentQ(){return examPackage?.questions?.[currentIndex]}
function setExamBranding(title){
  const t=String(title||'SMAGA Maliku Exam');
  if($('loginExamTitle'))$('loginExamTitle').textContent=t;
  if($('waitingExamTitle'))$('waitingExamTitle').textContent=t.toUpperCase();
  if($('examTitleHeader'))$('examTitleHeader').textContent=t.toUpperCase();
}
async function previewExam(code){
  code=String(code||'').trim().toUpperCase();
  if(!code){setExamBranding('SMAGA Maliku Exam');return null}
  try{const d=await api('/api/exam-info?code='+encodeURIComponent(code));setExamBranding(d.title);return d}catch(e){setExamBranding('SMAGA Maliku Exam');return null}
}

async function api(url,opts={}){
  const r=await fetch(url,{cache:'no-store',...opts});
  let data={};try{data=await r.json()}catch(e){}
  if(!r.ok) throw new Error(data.error||`HTTP ${r.status}`);
  return data;
}

function openDB(){return new Promise((resolve,reject)=>{const r=indexedDB.open(DB_NAME,1);r.onupgradeneeded=()=>{if(!r.result.objectStoreNames.contains(DB_STORE))r.result.createObjectStore(DB_STORE)};r.onsuccess=()=>resolve(r.result);r.onerror=()=>reject(r.error)})}
async function dbPut(key,value){const db=await openDB();return new Promise((resolve,reject)=>{const tx=db.transaction(DB_STORE,'readwrite');tx.objectStore(DB_STORE).put(value,key);tx.oncomplete=()=>resolve();tx.onerror=()=>reject(tx.error)})}
async function dbGet(key){const db=await openDB();return new Promise((resolve,reject)=>{const tx=db.transaction(DB_STORE,'readonly');const r=tx.objectStore(DB_STORE).get(key);r.onsuccess=()=>resolve(r.result);r.onerror=()=>reject(r.error)})}
async function dbDel(key){const db=await openDB();return new Promise((resolve,reject)=>{const tx=db.transaction(DB_STORE,'readwrite');tx.objectStore(DB_STORE).delete(key);tx.oncomplete=()=>resolve();tx.onerror=()=>reject(tx.error)})}

function partAt(i){return engineEl?.exam?.questionList?.[i]?.parts?.[0]||null}
function matrixCopy(x){return Array.isArray(x)?x.map(r=>Array.isArray(r)?r.map(Boolean):r):x}
function normalisePart(part){
  if(!part)return null;
  const m=matrixCopy(part.stagedAnswer ?? part.studentAnswer ?? []);
  if(part.type==='1_n_2'){
    let idx=null;
    for(let i=0;i<m.length;i++){if(Array.isArray(m[i])&&m[i][0]){idx=i;break}}
    return idx;
  }
  if(part.type==='m_n_2') return m.map(r=>!!(Array.isArray(r)?r[0]:r));
  return m;
}
function setRadio(part,idx){if(!part||typeof part.storeTick!=='function')return false;part.storeTick({answer:idx,choice:0});return normalisePart(part)===idx}
function setCheck(part,idx,value){if(!part||typeof part.storeTick!=='function')return false;part.storeTick({answer:idx,choice:0,ticked:!!value});return true}
function applyAnswer(part,answer){
  if(!part)return false;
  if(part.type==='1_n_2'){if(answer===null||answer===undefined)return true;return setRadio(part,Number(answer))}
  if(part.type==='m_n_2'&&Array.isArray(answer)){answer.forEach((v,i)=>setCheck(part,i,!!v));return JSON.stringify(normalisePart(part))===JSON.stringify(answer.map(Boolean))}
  return false;
}
function serialiseAnswer(q,raw){
  const ids=Array.isArray(q.option_ids)?q.option_ids:[];
  if(q.kind==='pg') return Number.isInteger(raw)?(ids[raw]??raw):null;
  if(q.kind==='pgk'&&Array.isArray(raw)) return raw.map((v,i)=>v?ids[i]:null).filter(Boolean);
  return raw;
}
function deserialiseAnswer(q,stored){
  const ids=Array.isArray(q.option_ids)?q.option_ids:[];
  if(q.kind==='pg'){if(Number.isInteger(stored))return stored;if(typeof stored==='string')return ids.indexOf(stored);return null}
  if(q.kind==='pgk'){if(Array.isArray(stored)&&stored.every(x=>typeof x==='boolean'))return stored.map(Boolean);const set=new Set(Array.isArray(stored)?stored:[]);return ids.map(id=>set.has(id))}
  return stored;
}
function applyStoredAnswer(q,part,stored){return applyAnswer(part,deserialiseAnswer(q,stored))}
function answersArray(){return (examPackage?.questions||[]).map((q,i)=>({qid:q.id,type:q.type,answer:serialiseAnswer(q,normalisePart(partAt(i)))}))}
function answerMap(){return Object.fromEntries((examPackage?.questions||[]).map((q,i)=>[q.id,normalisePart(partAt(i))]))}
function answeredCount(){const m=answerMap();return examPackage.questions.reduce((n,q)=>n+(isAnswered(m[q.id],q.kind)?1:0),0)}

function buildNumbasDefinition(pkg){
  const questions=pkg.questions.map(q=>({
    name:q.id,
    statement:`<p>${escapeHtml(q.question)}</p>`,
    parts:[q.kind==='pg' ? {
      type:'1_n_2',prompt:'<p>Pilih satu jawaban.</p>',marks:Number(q.weight||1),
      choices:q.options,
      // Neutral matrix: official answer key is intentionally not shipped to the client.
      matrix:q.options.map(()=>0),
      shuffleChoices:false,displayType:'radiogroup',warningType:'none',showCellAnswerState:false,interpretedAnswerForm:'index'
    } : {
      type:'m_n_2',prompt:'<p>Pilih semua pernyataan yang benar.</p>',marks:Number(q.weight||1),maxMarks:Number(q.weight||1),
      choices:q.options,
      matrix:q.options.map(()=>0),markingMethod:'all-or-nothing',minAnswers:'0',maxAnswers:String(q.options.length),
      shuffleChoices:false,displayType:'checkbox',warningType:'none',showCellAnswerState:false,interpretedAnswerForm:'list of boolean'
    }]
  }));
  return {name:pkg.title,navigation:{showfrontpage:false,preventleave:false},question_groups:[{name:'SMAGA Package',questions}]};
}
function escapeHtml(s=''){return String(s).replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]))}

async function createEngine(){
  await customElements.whenDefined('numbas-exam');
  $('engineHost').innerHTML='';
  engineEl=document.createElement('numbas-exam');
  engineEl.id='smagaNumbasEngine';engineEl.setAttribute('scorm','false');
  const script=document.createElement('script');script.type='application/numbas-exam';script.textContent=JSON.stringify(buildNumbasDefinition(examPackage));engineEl.appendChild(script);
  const readyPromise=new Promise((resolve,reject)=>{
    let done=false;
    const finish=()=>{if(done)return;const n=engineEl.exam?.questionList?.length||0;if(n===examPackage.questions.length){done=true;engineReady=true;resolve()} };
    engineEl.addEventListener('numbas:setExam',()=>setTimeout(finish,0));
    let tries=0;const h=setInterval(()=>{tries++;finish();if(done)clearInterval(h);else if(tries>60){clearInterval(h);reject(new Error('Engine Numbas tidak membentuk seluruh soal dalam 24 detik.'))}},400);
  });
  $('engineHost').appendChild(engineEl);
  await readyPromise;
}

function makeVisual(q){
  const seed=parseInt(q.id.slice(1),10)||1;const a=20+(seed*7)%25,b=15+(seed*11)%30,c=18+(seed*13)%25;
  return `<div class="visual-card"><svg viewBox="0 0 540 230" role="img" aria-label="Grafik dummy"><line x1="60" y1="180" x2="500" y2="180" stroke="#8aa0b8" stroke-width="2"/><line x1="60" y1="35" x2="60" y2="180" stroke="#8aa0b8" stroke-width="2"/><rect x="105" y="${180-a*3}" width="80" height="${a*3}" rx="7" fill="#4f8cff"/><rect x="235" y="${180-b*3}" width="80" height="${b*3}" rx="7" fill="#50bda0"/><rect x="365" y="${180-c*3}" width="80" height="${c*3}" rx="7" fill="#f0aa52"/><text x="145" y="215" text-anchor="middle" fill="#35506b">A</text><text x="275" y="215" text-anchor="middle" fill="#35506b">B</text><text x="405" y="215" text-anchor="middle" fill="#35506b">C</text><text x="145" y="${170-a*3}" text-anchor="middle" font-weight="700" fill="#17314d">${a}</text><text x="275" y="${170-b*3}" text-anchor="middle" font-weight="700" fill="#17314d">${b}</text><text x="405" y="${170-c*3}" text-anchor="middle" font-weight="700" fill="#17314d">${c}</text></svg></div>`
}

function renderQuestion(){
  if(!engineReady||!examPackage)return;
  const q=currentQ();const part=partAt(currentIndex);const ans=normalisePart(part);
  $('activeNumber').textContent=String(currentIndex+1);
  $('answeredCount').textContent=`${answeredCount()}/${examPackage.questions.length}`;
  $('examParticipant').textContent=`${session.name} • ${session.class_name}`;
  const opts=q.options.map((t,i)=>{
    const selected=q.kind==='pg'?ans===i:(Array.isArray(ans)&&!!ans[i]);
    return `<label class="option ${selected?'selected':''}"><input type="${q.kind==='pg'?'radio':'checkbox'}" name="answer-${q.id}" data-index="${i}" ${selected?'checked':''}><span class="letter">${String.fromCharCode(65+i)}</span><span>${escapeHtml(t)}</span></label>`
  }).join('');
  const imageHtml=q.image_url?`<figure class="stimulus-image"><img src="${escapeHtml(q.image_url)}" alt="Gambar stimulus soal ${currentIndex+1}" loading="eager"></figure>`:'';
  $('questionArea').innerHTML=`<section class="stimulus-card"><div class="domain">${escapeHtml(q.domain)} • STIMULUS</div><h2>${escapeHtml(q.label)}</h2>${q.stimulus?`<p>${escapeHtml(q.stimulus)}</p>`:''}${imageHtml}${q.visual&&!q.image_url?makeVisual(q):''}</section><section class="question-card"><div class="question-meta"><span>Soal ${currentIndex+1}</span><span>${q.kind==='pg'?'Pilihan Ganda':'Pilihan Ganda Kompleks'} • ${Number(q.weight||1)} poin${q.shuffle_options?' • opsi diacak':''}</span></div><h3>${escapeHtml(q.question)}</h3><div class="options">${opts}</div></section>`;
  $('questionArea').querySelectorAll('input').forEach(inp=>inp.addEventListener('change',()=>{
    const i=Number(inp.dataset.index);
    if(q.kind==='pg')setRadio(part,i);else setCheck(part,i,inp.checked);
    renderQuestion();saveAttempt().catch(()=>{});renderNavigator();
  }));
  $('prevQuestion').disabled=currentIndex===0;
  $('nextQuestion').textContent=currentIndex===examPackage.questions.length-1?'Review →':'Berikutnya →';
  $('flagQuestion').classList.toggle('active',!!flags[q.id]);
  renderNavigator();
}

function renderNavigator(){
  if(!examPackage||!engineReady)return;
  const m=answerMap();
  $('navGrid').innerHTML=examPackage.questions.map((q,i)=>{
    const answered=isAnswered(m[q.id],q.kind),flag=!!flags[q.id];
    return `<button class="nav-q ${answered?'answered':''} ${flag?'flagged':''} ${i===currentIndex?'active':''}" data-i="${i}">${i+1}</button>`
  }).join('');
  $('navGrid').querySelectorAll('button').forEach(b=>b.onclick=()=>{currentIndex=Number(b.dataset.i);closeNav();showView('examView');renderQuestion();saveAttempt().catch(()=>{})});
  $('answeredCount').textContent=`${answeredCount()}/${examPackage.questions.length}`;
}
function openNav(){$('navDrawer').classList.add('open');$('navBackdrop').classList.remove('hidden');$('navDrawer').setAttribute('aria-hidden','false')}
function closeNav(){$('navDrawer').classList.remove('open');$('navBackdrop').classList.add('hidden');$('navDrawer').setAttribute('aria-hidden','true')}

async function saveAttempt(force=false){
  if(!session||!engineReady)return;
  const data={version:2,session_id:session.session_id,currentIndex,flags,answers:answersArray(),saved_at:Date.now(),package_id:examPackage.exam_id};
  const hash=JSON.stringify({currentIndex,flags,answers:data.answers});
  if(!force&&hash===lastSavedHash)return;
  await dbPut(session.session_id,data);lastSavedHash=hash;
}
async function restoreAttempt(){
  const saved=await dbGet(session.session_id);if(!saved)return false;
  const amap=Object.fromEntries((saved.answers||[]).map(a=>[a.qid,a.answer]));
  examPackage.questions.forEach((q,i)=>applyStoredAnswer(q,partAt(i),amap[q.id]));
  flags=saved.flags||{};currentIndex=Math.max(0,Math.min(examPackage.questions.length-1,Number(saved.currentIndex)||0));
  lastSavedHash=JSON.stringify({currentIndex,flags,answers:answersArray()});
  return true;
}

function renderReview(){
  closeNav();showView('reviewView');const m=answerMap();const answered=answeredCount();const flagged=examPackage.questions.filter(q=>flags[q.id]).length;
  $('reviewTotal').textContent=examPackage.questions.length;$('reviewAnswered').textContent=answered;$('reviewUnanswered').textContent=examPackage.questions.length-answered;$('reviewFlagged').textContent=flagged;
  $('reviewGrid').innerHTML=examPackage.questions.map((q,i)=>`<button class="review-q ${isAnswered(m[q.id],q.kind)?'answered':''} ${flags[q.id]?'flagged':''}" data-i="${i}">${i+1}</button>`).join('');
  $('reviewGrid').querySelectorAll('button').forEach(b=>b.onclick=()=>{currentIndex=Number(b.dataset.i);showView('examView');renderQuestion()});
  $('submitWarning').textContent=answered<examPackage.questions.length?`Masih ada ${examPackage.questions.length-answered} soal belum dijawab. Anda tetap dapat mengirim setelah konfirmasi.`:'Seluruh soal sudah terjawab. Pastikan jawaban ragu-ragu sudah diperiksa.';
}

function startExam(){
  clearInterval(waitingHandle);setExamBranding(examPackage?.title);showView('examView');renderQuestion();startTimer();
}
function waitingTick(){
  const startMs=Date.parse(session.start_at);const diff=Math.ceil((startMs-serverNowMs())/1000);
  $('waitCountdown').textContent=fmtDuration(diff);$('waitServerClock').textContent=fmtClock(serverNowMs());
  if(diff<=0)startExam();
}
function showWaiting(){
  setExamBranding(examPackage?.title);showView('waitingView');$('waitName').textContent=session.name;$('waitClass').textContent=session.class_name;$('waitPackageCount').textContent=`${examPackage.questions.length} soal • siap`;waitingTick();waitingHandle=setInterval(waitingTick,500);
}
function startTimer(){
  clearInterval(timerHandle);timerHandle=setInterval(timerTick,500);timerTick();
}
function timerTick(){
  const endMs=Date.parse(session.end_at);const remain=Math.ceil((endMs-serverNowMs())/1000);
  $('examTimer').textContent=fmtDuration(remain);$('serverClock').textContent=`Server ${fmtClock(serverNowMs())}`;
  const card=$('timerCard');card.classList.toggle('warning',remain<=15*60&&remain>5*60);card.classList.toggle('danger',remain<=5*60);card.classList.toggle('critical',remain<=60);
  if(remain<=0&&!autoSubmitting){clearInterval(timerHandle);autoSubmit()}
}

function buildSubmission(){return {attempt_id:`${session.session_id}-FINAL`,session_id:session.session_id,client_time:new Date().toISOString(),flags,answers:answersArray()}}
async function submitFinal(auto=false){
  if(autoSubmitting)return;autoSubmitting=true;closeNav();showView('submittingView');$('submitStatusTitle').textContent=auto?'Waktu habis. Mengirim jawaban…':'Mengirim jawaban…';$('submitStatusText').textContent='Jangan tutup halaman sampai server mengonfirmasi.';$('retrySubmitBtn').classList.add('hidden');
  const payload=buildSubmission();await saveAttempt(true);await dbPut(`pending:${session.session_id}`,payload);
  try{
    const data=await api('/api/submit',{method:'POST',headers:{'Content-Type':'application/json','Idempotency-Key':payload.attempt_id},body:JSON.stringify(payload)});
    await dbDel(`pending:${session.session_id}`);await dbPut(`result:${session.session_id}`,data);localStorage.removeItem(SESSION_LS);renderResult(data);autoSubmitting=false;
  }catch(e){
    $('submitStatusTitle').textContent='Jawaban belum terkonfirmasi';$('submitStatusText').textContent=`${e.message}. Jawaban tetap tersimpan di perangkat. Sambungkan internet/server lalu coba lagi.`;$('retrySubmitBtn').classList.remove('hidden');autoSubmitting=false;
  }
}
function autoSubmit(){submitFinal(true)}
function renderResult(data){showView('resultView');if($('resultExamTitle'))$('resultExamTitle').textContent=examPackage?.title||'Terima kasih';$('resultIdentity').textContent=`${data.name} • ${data.class_name}`;if(data.show_result_to_student===false){$('resultScoreLabel').textContent='Status';$('resultScore').textContent='TERKIRIM';$('resultRaw').textContent='Nilai menunggu dibuka oleh guru/operator.';$('resultNote').textContent='Jawaban sudah diterima server. Nilai tidak ditampilkan untuk ujian ini.'}else{$('resultScoreLabel').textContent='Nilai';$('resultScore').textContent=data.score_100.toLocaleString('id-ID',{maximumFractionDigits:2});$('resultRaw').textContent=`Skor mentah ${data.score_raw}/${data.max_raw}`;$('resultNote').textContent='Jawaban dan nilai sudah dikonfirmasi server.'}}
function goHomeAfterSubmit(){session=null;examPackage=null;engineReady=false;flags={};currentIndex=0;location.href=location.origin+'/'}
function closeAfterSubmit(){const before=window.closed;window.close();setTimeout(()=>{if(!window.closed&&!before)$('closeHelp').classList.remove('hidden')},450)}

async function prepareSession(sess){
  session=sess;localStorage.setItem(SESSION_LS,JSON.stringify(session));
  const st=Date.parse(session.server_time);if(Number.isFinite(st))serverOffsetMs=st-Date.now();
  $('bootText').textContent='Mengambil paket soal…';examPackage=await api(session.package_url||'/api/package');packageReady=true;setExamBranding(examPackage.title);
  $('bootText').textContent='Menyiapkan Numbas headless engine…';await createEngine();
  await restoreAttempt();
  const now=serverNowMs();if(now<Date.parse(session.start_at))showWaiting();else if(now>=Date.parse(session.end_at))autoSubmit();else startExam();
}

async function tryRestoreSession(){
  const raw=localStorage.getItem(SESSION_LS);if(!raw)return false;
  try{const s=JSON.parse(raw);if(!s?.session_id)return false;await prepareSession(s);return true}catch(e){console.warn('Restore session gagal',e);localStorage.removeItem(SESSION_LS);return false}
}

async function init(){
  showView('bootView');
  try{
    config=await api('/api/config');
    const server=Date.parse(config.server_time);if(Number.isFinite(server))serverOffsetMs=server-Date.now();
    const select=$('participantClass');config.classes.forEach(c=>{const o=document.createElement('option');o.value=c;o.textContent=c;select.appendChild(o)});
    if(config.demo_mode){$('demoHint').classList.remove('hidden');$('demoHint').innerHTML=`Mode demo aktif • kode: <b>${config.default_exam_code}</b> • token: <b>${config.token_hint}</b> • tes mulai ±8 detik setelah login.`}
    const qp=new URLSearchParams(location.search); $('examCode').value=(qp.get('exam')||config.default_exam_code||'').toUpperCase(); await previewExam($('examCode').value); if(await tryRestoreSession())return;
    showView('loginView');
  }catch(e){$('bootText').textContent='Gagal menyiapkan aplikasi: '+e.message;}
}

$('examCode').addEventListener('change',e=>previewExam(e.target.value));
$('examCode').addEventListener('blur',e=>previewExam(e.target.value));
$('loginForm').addEventListener('submit',async e=>{
  e.preventDefault();$('loginError').classList.add('hidden');$('loginBtn').disabled=true;$('loginBtn').textContent='Menyiapkan…';
  try{
    const data=await api('/api/login',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({exam_code:$('examCode').value,number:$('participantNumber').value,name:$('participantName').value,class_name:$('participantClass').value,token:$('participantToken').value})});
    showView('bootView');$('bootText').textContent='Validasi berhasil. Menyiapkan paket…';await prepareSession(data);
  }catch(e){showView('loginView');$('loginError').textContent=e.message;$('loginError').classList.remove('hidden')}
  finally{$('loginBtn').disabled=false;$('loginBtn').textContent='Masuk & Siapkan Paket'}
});

$('openNavBtn').onclick=openNav;$('closeNavBtn').onclick=closeNav;$('navBackdrop').onclick=closeNav;
$('prevQuestion').onclick=()=>{if(currentIndex>0){currentIndex--;renderQuestion();saveAttempt().catch(()=>{})}};
$('nextQuestion').onclick=()=>{if(currentIndex<examPackage.questions.length-1){currentIndex++;renderQuestion();saveAttempt().catch(()=>{})}else renderReview()};
$('flagQuestion').onclick=()=>{const q=currentQ();flags[q.id]=!flags[q.id];renderQuestion();saveAttempt().catch(()=>{})};
$('reviewBtn').onclick=renderReview;$('backToExam').onclick=()=>{showView('examView');renderQuestion()};
$('finalSubmitBtn').onclick=()=>{const missing=examPackage.questions.length-answeredCount();const msg=missing>0?`Masih ada ${missing} soal belum dijawab. Tetap kirim jawaban?`:'Kirim jawaban sekarang? Setelah terkirim, jawaban tidak dapat diubah.';if(confirm(msg))submitFinal(false)};
$('retrySubmitBtn').onclick=()=>submitFinal(false);
$('homeAfterSubmit').onclick=goHomeAfterSubmit;$('closeAfterSubmit').onclick=closeAfterSubmit;

window.addEventListener('beforeunload',()=>{if(session&&engineReady)saveAttempt(true).catch(()=>{})});
window.addEventListener('online',()=>{if(!$('retrySubmitBtn').classList.contains('hidden'))toast('Koneksi tersedia. Anda dapat mencoba mengirim lagi.')});
setInterval(()=>{if(session&&engineReady)saveAttempt().catch(()=>{})},1500);

init();
})();
