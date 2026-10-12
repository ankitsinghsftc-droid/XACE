import { ReplayInspector } from '../src/preview/replay_inspector';
const assert=(condition:unknown,message:string)=>{if(!condition)throw new Error(message);};
const wait=async(predicate:()=>boolean)=>{for(let i=0;i<600;i++){if(predicate())return;await new Promise(resolve=>setTimeout(resolve,25));}throw new Error('Browser proof timed out: '+document.body.textContent);};
const change=(selector:string,value:string)=>{const input=document.querySelector<HTMLInputElement>(selector)!;input.value=value;input.dispatchEvent(new Event('change'));};
const click=(selector:string)=>document.querySelector<HTMLButtonElement>(selector)!.click();
const inspector=new ReplayInspector();inspector.mount(document.body);
async function run(){
  await wait(()=>document.querySelectorAll('[data-recording] option').length>1);
  const before=await (await fetch('/api/debugger/live')).json();
  const id=document.querySelector<HTMLOptionElement>('[data-recording] option:nth-child(2)')!.value;
  change('[data-recording]',id);await wait(()=>!!document.querySelector('[data-event-search]'));
  change('[data-event-search]','third_attempt');click('[data-event-tick="9"]');await wait(()=>document.querySelector<HTMLInputElement>('[data-frame]')?.value==='9');
  click('[data-technical]');assert(document.body.textContent?.includes('reference.wall_runnable.v1'),'semantic capability missing');
  assert(document.body.textContent?.includes('System dependencies'),'dependency view missing');
  assert(document.body.textContent?.includes('Recorded component state'),'component/contact state missing');
  assert(document.body.textContent?.includes('wall_entity')&&document.body.textContent?.includes('chain')&&document.body.textContent?.includes('linear'),'contact/counter/velocity fields missing');
  click('[data-verify]');await wait(()=>document.body.textContent?.includes('Replay matches the recording.')===true);
  const report=await (await fetch('/api/debugger/export',{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify({id,tick:9})})).json();assert(report.tick===9&&report.epoch===1,'export identity missing');
  const guest=await fetch('/api/debugger/control',{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify({action:'pause',confirm_session_wide:true})});assert(guest.status===403,'guest controlled authority');
  click('[data-live]');await wait(()=>document.querySelector('[data-replay-mode]')?.textContent==='Live view');
  click('[data-capture]');await wait(()=>!!document.querySelector('[data-frame]'));click('[data-verify]');await wait(()=>document.body.textContent?.includes('Replay matches the recording.')===true);
  click('[data-live]');await wait(()=>document.querySelector('[data-replay-mode]')?.textContent==='Live view');
  const after=await (await fetch('/api/debugger/live')).json();assert(after.status.tick>before.status.tick&&!after.status.paused,'inspection paused/rewound live');
  document.body.dataset['testState']='passed';document.body.dataset['walkthrough']=JSON.stringify({event_tick:9,epoch:1,live_before:before.status.tick,live_after:after.status.tick,guest_refused:true,verified:true,exported:true,live_fork_verified:true});
}
run().catch(error=>{document.body.dataset['testState']='failed';document.body.append(String(error));});
