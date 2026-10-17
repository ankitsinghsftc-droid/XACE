// Host-owned context only. Text content prevents native names becoming markup.
let review = null;
let choices = {};
let approval = null;
let applyAvailable = false;
const byId = id => document.getElementById(id);
const text = (tag, value, parent) => { const el=document.createElement(tag); el.textContent=value; parent.append(el); return el; };
const reasons={same_field:'Both versions changed this value',delete_edit:'One version deleted an object that the other edited',reparent_interaction:'Hierarchy and object edits need a joint decision',dependency_change:'Related objects changed',native_owned:'The engine owns this value'};
const lossMessages={unresolved_conflict:'Choose how to resolve the conflicts below.',runtime_parent_binding_required:'This hierarchy needs a verified runtime binding before it can be used.',structural_materialization_requires_coordinator:'Creating, removing, or restructuring these objects is not supported by the current mapping.',field_mapping_not_certified:'This type of change is not supported by the current mapping.',unprojected_canonical_world_change:'A world change needs an additional reviewed mapping.',critical_native_behavior:'Unsupported native behavior must be reviewed in the engine.',unstable_document:'Save or discard unsaved engine changes, then reload this review.',play_mode_capture:'Stop the game before reviewing saved changes.',native_code_retained:'Native code is retained in the engine; it has not been converted.'};
function fixed(value) {
  const n=BigInt(value),sign=n<0n?'-':'',absolute=n<0n?-n:n;
  const fraction=(absolute%1000000n).toString().padStart(6,'0').replace(/0+$/,'');
  return sign+(absolute/1000000n).toString()+(fraction?'.'+fraction:'');
}
function displayValue(conflict,value) {
  if(conflict.path[1]==='transform.position' && typeof value==='string')return fixed(value)+' m';
  if(conflict.path[1]==='transform.scale' && typeof value==='string')return fixed(value)+' ×';
  return JSON.stringify(value,null,2);
}
async function request(action, body) {
  const response=await fetch('/api/native-reconciliation'+(action?'/'+action:''), {
    method:action?'POST':'GET', credentials:'same-origin', cache:'no-store',
    headers:{'x-xace-agent-auth':'1', ...(action?{'content-type':'application/json'}:{})},
    ...(action?{body:JSON.stringify(body)}:{})
  });
  const result=await response.json();
  if (!response.ok) throw new Error(result.message || 'Review unavailable.');
  return result;
}
function render() {
  approval=null;byId('apply').disabled=true;byId('apply').hidden=!applyAvailable;
  const r=review.report;
  byId('summary').textContent=r.noop?'No synchronized changes.':`${r.merge.conflicts.length} conflicts · ${r.merge.canonical_proposals.length} proposed XACE edits · ${r.merge.native_proposals.length} proposed engine edits`;
  byId('losses').replaceChildren(); byId('conflicts').replaceChildren();
  for (const loss of r.losses) {
    const item=text('p',lossMessages[loss.code] || (loss.severity==='blocking'?'This change needs additional verification before approval.':'Native content has been retained; see technical details.'),byId('losses'));
    item.className='issue';
  }
  for (const conflict of r.merge.conflicts) {
    const panel=text('section','',byId('conflicts'));
    text('h2',reasons[conflict.reason] || 'Review this change',panel);
    const name=r.merge.engine[conflict.object_id]?.fields?.['native.name'] || 'Selected object';
    const field=conflict.path[1]==='transform.position'?'Position':conflict.path[1]==='transform.scale'?'Scale':conflict.path[1]==='transform.rotation'?'Rotation':'Object details';
    text('p',`${name} · ${field}${conflict.path[2]?' · '+conflict.path[2].toUpperCase():''}`,panel);
    const versions=text('div','',panel); versions.className='versions';
    for (const [name,key] of [['Last verified','base'],['XACE','xace'],['Engine','engine']]) {
      const column=text('div','',versions);text('h3',name,column);text('pre',displayValue(conflict,conflict[key]),column);
    }
    const label=text('label','Choose the version to propose ',panel);
    const select=document.createElement('select');select.setAttribute('aria-label',`${conflict.reason} ${conflict.object_id}`);label.append(select);
    for(const [value,title] of [['','Keep unresolved'],...conflict.allowed.map(x=>[x,x==='xace'?'Use XACE':'Use engine'])]) {
      const option=text('option',title,select);option.value=value;
    }
    select.value=choices[conflict.id] || '';
    select.onchange=()=>{approval=null;byId('apply').disabled=true;if(select.value)choices[conflict.id]=select.value;else delete choices[conflict.id];byId('approve').disabled=true;byId('status').textContent='Choices changed. Review them before approving.';};
  }
  byId('proposal').textContent=JSON.stringify({identities:r.identities,conflicts:r.merge.conflicts,losses:r.losses,typed_operations:r.typed_operations,native_write_preview:r.native_write_preview},null,2);
  byId('resolve').disabled=false;byId('cancel').disabled=false;byId('approve').disabled=!r.reviewable;
  byId('status').textContent=r.reviewable?'Ready for review approval. Nothing has been saved.':'Review is blocked. Resolve conflicts and listed requirements first.';
}
async function run(work) {
  for(const id of ['refresh','resolve','approve','apply','cancel'])byId(id).disabled=true;
  try {await work();} catch(error) {byId('status').textContent=error.message;byId('approve').disabled=true;approval=null;byId('apply').disabled=true;}
  finally {byId('refresh').disabled=false;if(review)byId('cancel').disabled=false;}
}
async function showRecovery() {
  const state=await request('status',{}),panel=byId('recovery');
  panel.replaceChildren();panel.hidden=!state.play_build_blocked;
  if(!state.play_build_blocked)return false;
  text('h2','An interrupted save needs attention',panel);
  text('p','Play and further changes stay blocked until the saved files are verified. Newer engine edits will be preserved.',panel);
  for(const item of state.pending) {
    const row=text('div','',panel);text('p',item.transaction_id+' ? '+item.state,row);
    if(item.state==='corrupt_or_incomplete') {text('p','The saved recovery record needs inspection before it can be used.',row);continue;}
    for(const [action,label] of [['resume','Finish approved save'],['rollback','Restore before this save']]) {
      const button=text('button',label,row);
      button.onclick=()=>run(async()=>{
        for(const control of panel.querySelectorAll('button'))control.disabled=true;
        const result=await request('recover',{transaction_id:item.transaction_id,recovery_action:action});
        byId('status').textContent=result.state==='committed'?'Saved changes verified. Load current changes to continue.':'Previous files restored. Load current changes to continue.';
        await showRecovery();
      });
    }
  }
  byId('status').textContent='Resolve the interrupted save before reviewing further changes.';
  return true;
}
byId('refresh').onclick=()=>run(async()=>{
  if(await showRecovery()){approval=null;return;}
  if(review)await request('cancel',{token:review.token});review=null;
  review=await request('',null);applyAvailable=review.apply_available===true;choices={};render();
});
byId('resolve').onclick=()=>run(async()=>{review=await request('resolve',{token:review.token,proposal_digest:review.proposal_digest,resolutions:choices});render();});
byId('approve').onclick=()=>run(async()=>{const result=await request('approve',{token:review.token,proposal_digest:review.proposal_digest});byId('status').textContent='Review approval recorded. Project files and the active game are unchanged.';byId('proposal').textContent=JSON.stringify(result,null,2);approval=result;byId('apply').disabled=!applyAvailable;});
byId('cancel').onclick=()=>run(async()=>{await request('cancel',{token:review.token});review=null;choices={};for(const id of ['summary','losses','conflicts','proposal'])byId(id).replaceChildren();byId('status').textContent='Review cancelled. Both projects are unchanged.';});

byId('apply').onclick=()=>run(async()=>{if(!approval)throw new Error('Approve the current review first.');const result=await request('apply',{approval,proposal_digest:review.proposal_digest});approval=null;review=null;byId('status').textContent=result.state==='noop'?'Already synchronized. No files changed.':'Changes saved and verified. The active game has not restarted.';byId('proposal').textContent=JSON.stringify(result,null,2);});
