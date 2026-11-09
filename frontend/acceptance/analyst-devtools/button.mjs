// Owner-operated local UI only. No Console, authentication reads or automatic GET.
export function mountButton({document, run, now, expiresAt, schedule}) {
  if (now()>=expiresAt || document.getElementById('powerflow-local-analyst-check')) return;
  const panel=document.createElement('section');
  panel.id='powerflow-local-analyst-check';
  panel.className='panel';
  panel.setAttribute('aria-label','Local Analyst authorization test');
  const title=document.createElement('h2');
  title.textContent='Local-only Analyst authorization test';
  const button=document.createElement('button');
  button.type='button';button.textContent='Run Analyst authorization check once';
  const output=document.createElement('pre');output.setAttribute('aria-live','polite');
  panel.append(title,button,output);
  document.body.prepend(panel);
  let used=false;
  button.addEventListener('click',async()=>{
    if(used||now()>=expiresAt)return;
    used=true;button.disabled=true;
    let result={httpStatus:null,adminDataDisclosed:null,result:'FAIL'};
    try { result=await run(); } catch {}
    output.textContent=JSON.stringify(result);
  });
  schedule(()=>{button.disabled=true;},Math.max(0,expiresAt-now()));
}
