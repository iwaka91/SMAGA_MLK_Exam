import { createClient } from 'npm:@supabase/supabase-js@2'

Deno.serve(async () => {
  const url = Deno.env.get('SUPABASE_URL')!
  const key = Deno.env.get('SUPABASE_SERVICE_ROLE_KEY')!
  const bucket = Deno.env.get('SMAGA_STORAGE_BUCKET') || 'exam-assets'
  const limit = Number(Deno.env.get('SMAGA_STORAGE_LIMIT_MB') || '1024') * 1024 * 1024
  const warnPct = Number(Deno.env.get('SMAGA_STORAGE_WARN_PCT') || '75')
  const retentionDays = Number(Deno.env.get('SMAGA_ASSET_RETENTION_DAYS') || '180')
  const orphanDays = Number(Deno.env.get('SMAGA_ORPHAN_RETENTION_DAYS') || '30')
  const supabase = createClient(url,key,{auth:{persistSession:false}})

  const {data:assets,error:aerr}=await supabase.from('assets').select('*').is('deleted_at',null).eq('archived',false)
  if(aerr) return new Response(JSON.stringify({error:aerr.message}),{status:500})
  const {data:exams,error:eerr}=await supabase.from('exams').select('id,end_at')
  if(eerr) return new Response(JSON.stringify({error:eerr.message}),{status:500})
  const examMap=new Map((exams||[]).map((x:any)=>[x.id,x]))
  const now=Date.now(), day=86400000
  let used=(assets||[]).reduce((s:number,a:any)=>s+Number(a.size_bytes||0),0)
  const candidates=(assets||[]).map((a:any)=>{
    let reason=''
    const created=new Date(a.created_at).getTime()
    if(!a.exam_id && now-created>orphanDays*day) reason='orphan'
    else if(a.exam_id){const ex:any=examMap.get(a.exam_id); const end=new Date(ex?.end_at||a.created_at).getTime(); if(now-end>retentionDays*day) reason='expired'}
    return {...a,reason}
  }).filter((a:any)=>a.reason).sort((a:any,b:any)=>new Date(a.last_used_at).getTime()-new Date(b.last_used_at).getTime())

  if((used/limit*100)>=warnPct){
    const known=new Set(candidates.map((x:any)=>x.id))
    const extra=(assets||[]).filter((a:any)=>!known.has(a.id)).sort((a:any,b:any)=>new Date(a.last_used_at).getTime()-new Date(b.last_used_at).getTime())
    for(const x of extra)candidates.push({...x,reason:'capacity'})
  }

  const target=limit*.65, removed:string[]=[], errors:any[]=[]
  for(const a of candidates){
    if(a.reason==='capacity' && used<=target) break
    const {error}=await supabase.storage.from(bucket).remove([a.storage_path])
    if(error){errors.push({id:a.id,error:error.message});continue}
    await supabase.from('assets').update({deleted_at:new Date().toISOString()}).eq('id',a.id)
    used-=Number(a.size_bytes||0);removed.push(a.id)
  }
  return Response.json({removed_count:removed.length,removed,errors,used_bytes:used})
})
