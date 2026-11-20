const chartRoot=document.getElementById('chart-data');
if(chartRoot){
  const info=JSON.parse(chartRoot.textContent)||{};
  const module=location.pathname.startsWith('/module/')?location.pathname.slice(8)||'1':'1';
  const source=document.getElementById('source'),csv=document.getElementById('csv'),notice=document.getElementById('notice');
  if(source&&csv){
    source.onchange=async()=>{if(!source.files.length)return;const bytes=await source.files[0].arrayBuffer();try{csv.value=new TextDecoder('utf-8',{fatal:true}).decode(bytes)}catch{csv.value=new TextDecoder('gb18030').decode(bytes)}};
    const restore=document.getElementById('restore');
    if(restore)restore.addEventListener('click',async()=>{try{const reply=await fetch('/api/sample?module='+module);csv.value=(await reply.json()).text;if(notice)notice.textContent='样例已就绪'}catch{if(notice)notice.textContent='样例读取失败，请重试'}});
    const form=document.getElementById('plan-form');
    if(form)form.onsubmit=async event=>{event.preventDefault();event.submitter.disabled=true;if(notice)notice.textContent=module==='8'?'正在核对班组工时…':'正在安排航次…';try{const run=await post('/api/run',{text:csv.value});window.location.assign(window.location.pathname+'?run_id='+run.id)}catch(error){if(notice)notice.textContent=error.message;event.submitter.disabled=false}};
  }
  document.querySelectorAll('[data-decision]').forEach(button=>button.addEventListener('click',async()=>{
    try{
      const run=await post('/api/review',{id:info.id,revision:info.revision,decision:button.dataset.decision});
      info.revision=run.revision;
      if(notice)notice.textContent=run.decision+' / 修订 '+run.revision;
      if(button.dataset.decision==='通过')window.location.reload();
    }catch(error){if(notice)notice.textContent=error.message}
  }));
}
async function post(url,payload){const response=await fetch(url,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)}),data=await response.json();if(!response.ok)throw Error(data.message||'计划处理失败');return data}
