/** Creator inspection operates on immutable recordings, never the live timeline. */
type Inspection = {
  session?:{epoch?:{session_id?:string;authority_incarnation?:string}};
  id:string; tick:number; epoch:number; first_tick:number; last_tick:number;
  events:Array<{tick:number;index:number;label:string;entity:number}>;
  epochs:Array<{tick:number;activation_id:string;migration:number[]}>;
  inputs:unknown[]; selected_events:unknown[]; components:Array<{id:string;label:string;entities:Record<string,unknown>}>;
  world:unknown; dependencies:unknown; access:unknown; membership:unknown; seed:number; trace_note:string;
};
const escape=(value:unknown)=>String(value).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]!));
export class ReplayInspector {
  private root:HTMLElement|null=null;
  private recordings:Array<{id:string;label:string}>=[];
  private view:Inspection|null=null;
  private busy=false;
  private technical=false;
  private entity='';
  private search='';
  private message='Choose a recording. The live game keeps running.';
  private mode='replay';
  private creatorToken='';
  private confirmed=false;
  private generation=0;
  constructor(private readonly onMode:(live:boolean)=>void=()=>{}){}
  mount(container:HTMLElement):void {
    this.root=document.createElement('section');this.root.className='xb-dbg';this.root.setAttribute('aria-label','Replay inspection');container.appendChild(this.root);
    this.onMode(false);this.render();void this.perform(async()=>{const data=await this.request('/recordings');this.recordings=data.recordings;});
  }
  unmount():void {this.generation++;this.creatorToken='';this.root?.remove();this.root=null;}
  private async request(path:string,data?:unknown):Promise<any> {
    const response=await fetch('/api/debugger'+path,data===undefined?undefined:{method:'POST',headers:{'content-type':'application/json',...(path==='/control'?{'x-xace-creator-token':this.creatorToken}:{})},body:JSON.stringify(data)});
    const result=await response.json();if(!response.ok)throw new Error(result.detail||'This action could not finish. Your live game is unchanged.');return result;
  }
  private async perform(task:()=>Promise<void>):Promise<void> {
    if(this.busy)return;const generation=this.generation;this.busy=true;this.render();
    try{await task();}catch(error){this.message=error instanceof Error?error.message:'Unable to inspect this recording.';}
    finally{if(generation===this.generation){this.busy=false;this.render();}}
  }
  private async inspect(id:string,tick?:number):Promise<void>{this.view=await this.request('/inspect',{id,...(tick===undefined?{}:{tick})});this.mode='replay';this.onMode(false);this.message='Recorded view. Your live game is unchanged.';}
  private render():void {
    if(!this.root)return;const controlsOpen=this.root.querySelector('details')?.open??false;const view=this.view;const disabled=this.busy?'disabled':'';
    const events=view?.events.filter(e=>e.label.toLowerCase().includes(this.search.toLowerCase()))??[];
    this.root.innerHTML=`<h3>Inspect your game</h3><p data-replay-mode>${this.mode==='replay'?'Isolated recording':'Live view'}</p>
      <p role="status">${escape(this.busy?'Working…':this.message)}</p>
      <label>Recording <select data-recording ${disabled}><option value="">Choose a recording</option>${this.recordings.map(r=>`<option value="${escape(r.id)}" ${r.id===view?.id?'selected':''}>${escape(r.label)}</option>`).join('')}</select></label>
      <button data-capture ${disabled}>Inspect a copy of the live game</button><label>Open a saved recording <input data-import type="file" accept=".json" ${disabled}></label>
      <div><button data-live ${disabled}>Return to live</button><button data-discard ${disabled}>Discard inspection</button></div>
      ${view&&this.mode==='replay'?`<p>Session: ${escape(view.session?.epoch?.session_id?.slice(0,12)||'standalone recording')}</p><p>Frame <strong>${view.tick}</strong> · Rules version <strong>${view.epoch}</strong></p>
      <p>Rules changed at frames ${view.epochs.map(e=>e.tick).join(', ')||'—'}. These markers describe the recording.</p>
      <label>Frame <input data-frame type="number" min="${view.first_tick}" max="${view.last_tick}" value="${view.tick}" ${disabled}></label>
      <button data-verify ${disabled}>Replay through this frame</button><button data-export ${disabled}>Export proof summary</button>
      <label>Find an event <input data-event-search value="${escape(this.search)}" ${disabled}></label>
      <div data-recorded-events>${events.slice(0,200).map(e=>`<button data-event-tick="${e.tick}" data-event-entity="${e.entity}" ${disabled}>Frame ${e.tick}: ${escape(e.label)}</button>`).join('')||'No matching events.'}</div>
      <p>${view.inputs.length} recorded input packet(s) at this frame. ${view.selected_events.length} event(s).</p>
      <label>Object <select data-entity><option value="">All objects</option>${[...new Set(view.components.flatMap(c=>Object.keys(c.entities)))].sort((a,b)=>Number(a)-Number(b)).map(id=>`<option ${id===this.entity?'selected':''}>${escape(id)}</option>`).join('')}</select></label>
      <label><input type="checkbox" data-technical ${this.technical?'checked':''}> Show technical details</label>
      ${this.technical?`<div data-technical-view><h4>Inputs and events</h4><pre>${escape(JSON.stringify({inputs:view.inputs,events:view.selected_events},null,2))}</pre>
      <h4>Recorded component state and contact fields</h4><pre>${escape(JSON.stringify(view.components.map(c=>({...c,entities:this.entity?{[this.entity]:c.entities[this.entity]}:c.entities})),null,2))}</pre>
      <h4>World objects, surfaces and capabilities</h4><pre>${escape(JSON.stringify(view.world,null,2))}</pre>
      <h4>System dependencies and declared reads/writes</h4><pre>${escape(JSON.stringify({dependencies:view.dependencies,access:view.access},null,2))}</pre>
      <h4>Migration and input membership</h4><pre>${escape(JSON.stringify({epochs:view.epochs,membership:view.membership,seed:view.seed},null,2))}</pre><p>${escape(view.trace_note)}</p></div>`:''}`:''}
      <details ${controlsOpen?'open':''}><summary>Creator session controls</summary><p>These actions affect everyone playing. Recorded views never restore the live game.</p>
      <label>Creator key <input data-creator-key type="password" autocomplete="off" value="${escape(this.creatorToken)}"></label>
      <label><input data-confirm-session type="checkbox" ${this.confirmed?'checked':''}> I confirm this affects the whole session.</label>
      <button data-session="pause" ${disabled||(!this.creatorToken||!this.confirmed?'disabled':'')}>Pause everyone</button>
      <button data-session="play" ${disabled||(!this.creatorToken||!this.confirmed?'disabled':'')}>Resume everyone</button></details>`;
    this.root.querySelector<HTMLSelectElement>('[data-recording]')?.addEventListener('change',e=>{const id=(e.target as HTMLSelectElement).value;if(id)void this.perform(()=>this.inspect(id));});
    this.root.querySelector('[data-capture]')?.addEventListener('click',()=>void this.perform(async()=>{const result=await this.request('/capture',{});this.recordings=(await this.request('/recordings')).recordings;await this.inspect(result.recording_id);}));
    this.root.querySelector<HTMLInputElement>('[data-import]')?.addEventListener('change',e=>{const file=(e.target as HTMLInputElement).files?.[0];if(file)void this.perform(async()=>{const response=await fetch('/api/debugger/import',{method:'POST',headers:{'content-type':'application/json'},body:file});const result=await response.json();if(!response.ok)throw new Error(result.detail||'Unable to open recording.');this.recordings=(await this.request('/recordings')).recordings;await this.inspect(result.recording_id);});});
    this.root.querySelector('[data-live]')?.addEventListener('click',()=>void this.perform(async()=>{const live=await this.request('/live');this.mode='live';this.onMode(true);this.message=live.ruleset?.phase==='preparing'?`A rules change is applying at frame ${live.ruleset.activation_tick}.`:live.message||`Live game at frame ${live.status.tick??'unknown'}.`; }));
    this.root.querySelector('[data-discard]')?.addEventListener('click',()=>{this.view=null;this.entity='';this.mode='live';this.onMode(true);this.message='Inspection discarded. The live game was not changed.';this.render();});
    this.root.querySelector<HTMLInputElement>('[data-frame]')?.addEventListener('change',e=>{if(view)void this.perform(()=>this.inspect(view.id,Number((e.target as HTMLInputElement).value)));});
    this.root.querySelector<HTMLInputElement>('[data-event-search]')?.addEventListener('change',e=>{this.search=(e.target as HTMLInputElement).value;this.render();});
    this.root.querySelectorAll<HTMLButtonElement>('[data-event-tick]').forEach(button=>button.addEventListener('click',()=>{this.entity=button.dataset['eventEntity']||'';if(view)void this.perform(()=>this.inspect(view.id,Number(button.dataset['eventTick'])));}));
    this.root.querySelector('[data-verify]')?.addEventListener('click',()=>void this.perform(async()=>{if(view){const result=await this.request('/verify',{id:view.id,tick:view.tick});this.message=result.message+(result.report.first_divergence?` First difference: frame ${result.report.first_divergence.tick}.`:'');}}));
    this.root.querySelector('[data-export]')?.addEventListener('click',()=>void this.perform(async()=>{if(view){const report=await this.request('/export',{id:view.id,tick:view.tick});const url=URL.createObjectURL(new Blob([JSON.stringify(report,null,2)],{type:'application/json'}));const link=document.createElement('a');link.href=url;link.download='xace-replay-proof.json';link.click();URL.revokeObjectURL(url);this.message='Proof summary exported without session credentials.';}}));
    this.root.querySelector<HTMLInputElement>('[data-technical]')?.addEventListener('change',e=>{this.technical=(e.target as HTMLInputElement).checked;this.render();});
    this.root.querySelector<HTMLSelectElement>('[data-entity]')?.addEventListener('change',e=>{this.entity=(e.target as HTMLSelectElement).value;this.render();});
    this.root.querySelector<HTMLInputElement>('[data-creator-key]')?.addEventListener('change',e=>{this.creatorToken=(e.target as HTMLInputElement).value;this.render();});
    this.root.querySelector<HTMLInputElement>('[data-confirm-session]')?.addEventListener('change',e=>{this.confirmed=(e.target as HTMLInputElement).checked;this.render();});
    this.root.querySelectorAll<HTMLButtonElement>('[data-session]').forEach(button=>button.addEventListener('click',()=>void this.perform(async()=>{const reply=await this.request('/control',{action:button.dataset['session'],confirm_session_wide:this.confirmed});this.message=reply.accepted?'Session control applied.':reply.reason||'Session control was refused.';this.confirmed=false;})));
  }
}
