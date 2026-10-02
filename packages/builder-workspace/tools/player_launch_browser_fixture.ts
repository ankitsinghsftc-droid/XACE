import { EngineViewport } from '../src/preview/engine_viewport';
const assert = (ok: unknown, message: string) => { if (!ok) throw new Error(message); };
const settle = async () => { for (let i=0;i<8;i++) await new Promise(resolve => setTimeout(resolve,0)); };
const requests: string[] = [];
let fail = true;
window.fetch = async (url, init) => {
  const path=String(url); requests.push(path);
  if (path==='/api/player') return new Response(JSON.stringify({capability:'session-cap'}));
  assert((init?.headers as Record<string,string>)['x-xace-player-capability']==='session-cap','missing capability');
  assert(JSON.parse(String(init?.body)).cgs_hash==='saved-hash','missing saved identity');
  if (path.endsWith('/invite')) return new Response(JSON.stringify({ok:true,code:'XACE1-proof',message:'Share this code.'}));
  if (path.endsWith('/join')) assert(JSON.parse(String(init?.body)).code === 'XACE1-proof','join code missing');
  if (fail) return new Response(JSON.stringify({message:'Update your game package and Retry.'}),{status:400});
  return new Response(JSON.stringify({ok:true,state:path.endsWith('/stop')?'stopped':'playing'}));
};
const noop=()=>()=>{};
const deps={cgsStore:{cgs:{modes:[]},state:{hash:'saved-hash'},subscribe:noop},uiStore:{select:noop},client:{onRuntimeStatus:noop,onEngineTick:noop,send:()=>{throw new Error('Play bypassed native broker');}}};
const viewport=new EngineViewport(deps as any);
try {
  viewport.mount(document.body);
  const play=document.querySelector<HTMLButtonElement>('[data-action="play"]')!;
  play.click(); assert(play.disabled,'busy state missing');play.click();await settle();
  assert(requests.filter(p=>p.endsWith('/play')).length===1,'duplicate request while busy');
  assert(play.textContent==='RETRY PLAY','retry missing');
  assert(document.body.textContent?.includes('Update your game package'),'actionable error missing');
  fail=false;play.click();await settle();assert(document.body.textContent?.includes('Your game is open'),'success missing');
  document.querySelector<HTMLButtonElement>('[data-player-invite]')!.click();await settle();
  assert(document.querySelector<HTMLInputElement>('[data-session-code]')!.value==='XACE1-proof','invite not displayed');
  document.querySelector<HTMLButtonElement>('[data-player-join]')!.click();await settle();
  assert(requests.some(p=>p.endsWith('/join')),'join missing');
  document.querySelector<HTMLButtonElement>('[data-player-stop]')!.click();await settle();
  assert(document.body.textContent?.includes('Game closed'),'stop missing');
  assert(!play.disabled,'play not reenabled');
  viewport.unmount();document.body.dataset.testState='passed';
} catch(error) {document.body.dataset.testState='failed';document.body.textContent=String(error);throw error;}
