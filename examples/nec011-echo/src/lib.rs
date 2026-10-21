//! Bounded delayed-echo graph gameplay. No gameplay state lives in the executor.
use serde::{Deserialize, Serialize};
use std::collections::BTreeMap;
use xace_core::contracts::interfaces::{ISystem, ISystemContext};
use xace_core::errors::xace_error::{XaceError, ErrorContext};
use xace_core::events::{event_struct::Event, event_type::EventType};
use xace_core::runtime::phase_enum::PhaseEnum;
pub const STATE:u32=10020;
pub const CONFIG:u32=10021;
pub const INPUT:u32=10022;
pub const SYSTEM:&str="nec011.echo_graph.v1";
const SCALE:i64=1_000_000;
const LIMIT:i64=1_000_000_000_000;
fn bad(message:&str)->XaceError { XaceError::ValidationFailure {message:message.into(), context:ErrorContext::new(SYSTEM,"execute"),rule_violated:"EchoGraphV1".into(),failed_path:SYSTEM.into()} }
fn require(ok:bool,message:&str)->Result<(),XaceError>{if ok {Ok(())} else {Err(bad(message))}}
#[derive(Clone,Debug,Serialize,Deserialize,PartialEq,Eq)]
#[serde(deny_unknown_fields)]
pub struct Edge {pub id:u32,pub source:u32,pub target:u32,pub delay:u64,pub gain:i64,pub route:u8}
#[derive(Clone,Debug,Serialize,Deserialize,PartialEq,Eq)]
#[serde(deny_unknown_fields)]
pub struct Config {pub schema_version:u32,pub nodes:Vec<u32>,pub edges:Vec<Edge>,pub threshold:i64}
#[derive(Clone,Debug,Serialize,Deserialize,PartialEq,Eq)]
#[serde(deny_unknown_fields)]
pub struct Pulse {pub due:u64,pub node:u32,pub sequence:u64,pub amplitude:i64}
#[derive(Clone,Debug,Serialize,Deserialize,PartialEq,Eq)]
#[serde(deny_unknown_fields)]
pub struct Input {pub tick:u64,pub id:u64,pub node:u32,pub amplitude:i64}
#[derive(Clone,Debug,Default,Serialize,Deserialize,PartialEq,Eq)]
#[serde(deny_unknown_fields)]
pub struct State {#[serde(default)] pub graph:Option<Config>,#[serde(default)] pub last_graph_input:Option<GraphInput>,pub last_tick:Option<u64>,pub next_sequence:u64,pub last_input:Option<Input>,pub energy:BTreeMap<u32,i64>,pub pending:Vec<Pulse>}
#[derive(Clone,Debug,Serialize,Deserialize,PartialEq,Eq)]
#[serde(deny_unknown_fields)]
pub struct GraphInput {pub tick:u64,pub id:u64,pub graph:Config}
/// Graph edits are timed player inputs, carried in snapshotted state, not CGS mutations.
pub fn step_with_graph(config:&Config,original:&State,input:Option<&Input>,edit:Option<&GraphInput>,tick:u64)->Result<(State,Vec<(u32,i64)>),XaceError>{
    let mut candidate=original.clone();
    if let Some(edit)=edit {
        if candidate.last_graph_input.as_ref().map(|last|last.id)==Some(edit.id){require(candidate.last_graph_input.as_ref()==Some(edit),"conflicting graph input")?;}
        else {
            require(edit.tick==tick && edit.id>0 && candidate.last_graph_input.as_ref().map_or(true,|last|edit.id>last.id),"graph input tick/identity")?;
            edit.graph.validate()?;
            candidate.graph=Some(edit.graph.clone());candidate.last_graph_input=Some(edit.clone());
        }
    }
    step(config,&candidate,input,tick)
}
impl Config {
    pub fn validate(&self)->Result<(),XaceError>{
        require(self.schema_version==1 && !self.nodes.is_empty() && self.nodes.len()<=64 && self.edges.len()<=256,"graph bounds")?;
        require(self.nodes.iter().all(|n|*n>0) && self.nodes.windows(2).all(|w|w[0]<w[1]),"sorted unique nodes")?;
        require((1..=LIMIT).contains(&self.threshold),"threshold bounds")?;
        require(self.edges.windows(2).all(|w|w[0].id<w[1].id),"sorted unique edges")?;
        for e in &self.edges {require(self.nodes.binary_search(&e.source).is_ok() && self.nodes.binary_search(&e.target).is_ok() && (1..=60).contains(&e.delay) && (-2*SCALE..=2*SCALE).contains(&e.gain) && e.route<=1,"edge bounds")?;}
        Ok(())
    }
}
fn enqueue(state:&mut State,due:u64,node:u32,amplitude:i64)->Result<(),XaceError>{
    require(state.pending.len()<4096 && (-LIMIT..=LIMIT).contains(&amplitude),"pulse queue/amplitude bound")?;
    let sequence=state.next_sequence;state.next_sequence=sequence.checked_add(1).ok_or_else(||bad("sequence overflow"))?;
    state.pending.push(Pulse{due,node,sequence,amplitude});Ok(())
}
/// Pure candidate calculation. Failure leaves the caller's state unchanged.
pub fn step(config:&Config,original:&State,input:Option<&Input>,tick:u64)->Result<(State,Vec<(u32,i64)>),XaceError>{
    let config=original.graph.as_ref().unwrap_or(config);
    config.validate()?;
    require(original.last_tick.map_or(true,|last|last.checked_add(1)==Some(tick)),"nonsequential tick")?;
    require(original.pending.len()<=4096 && original.energy.len()<=64,"state bounds")?;
    for (&node,&value) in &original.energy {require(config.nodes.binary_search(&node).is_ok() && (-LIMIT..=LIMIT).contains(&value),"energy state bounds")?;}
    let mut sequences=std::collections::BTreeSet::new();
    for p in &original.pending {require(p.due>=tick && p.due<=tick.saturating_add(60) && config.nodes.binary_search(&p.node).is_ok() && (-LIMIT..=LIMIT).contains(&p.amplitude) && p.sequence<original.next_sequence && sequences.insert(p.sequence),"pending state bounds")?;}
    let mut state=original.clone();
    if let Some(i)=input {
        if state.last_input.as_ref().map(|last|last.id)==Some(i.id) {require(state.last_input.as_ref()==Some(i),"conflicting duplicate input")?;}
        else {
            require(i.tick==tick && i.id>0 && state.last_input.as_ref().map_or(true,|last|i.id>last.id) && config.nodes.binary_search(&i.node).is_ok(),"input tick/identity")?;
            enqueue(&mut state,tick,i.node,i.amplitude)?;state.last_input=Some(i.clone());
        }
    }
    state.pending.sort_by_key(|p|(p.due,p.node,p.sequence));
    let mut arrivals:BTreeMap<u32,i64>=BTreeMap::new();let mut remaining=Vec::new();
    for p in state.pending.drain(..) {
        if p.due==tick {let value=arrivals.entry(p.node).or_default();*value=value.checked_add(p.amplitude).ok_or_else(||bad("arrival overflow"))?;require((-LIMIT..=LIMIT).contains(value),"arrival bound")?;}
        else {remaining.push(p);}
    }
    state.pending=remaining;let mut events=Vec::new();
    for (node,amount) in arrivals {
        let energy=state.energy.entry(node).or_default();*energy=energy.checked_add(amount).ok_or_else(||bad("energy overflow"))?;require((-LIMIT..=LIMIT).contains(energy),"energy bound")?;
        let route=if *energy>=config.threshold {1} else {0};events.push((node,amount));
        for edge in config.edges.iter().filter(|e|e.source==node && e.route==route) {
            let amplitude=(amount as i128)*(edge.gain as i128)/(SCALE as i128);
            require((-LIMIT as i128..=LIMIT as i128).contains(&amplitude),"gain overflow")?;
            enqueue(&mut state,tick.checked_add(edge.delay).ok_or_else(||bad("tick overflow"))?,edge.target,amplitude as i64)?;
        }
    }
    state.pending.sort_by_key(|p|(p.due,p.node,p.sequence));state.last_tick=Some(tick);Ok((state,events))
}
#[derive(Deserialize)] #[serde(deny_unknown_fields)]
struct Row<T> { data:T }
pub struct EchoSystem;
impl ISystem for EchoSystem {
    fn system_id(&self)->&str {SYSTEM}
    fn declared_reads(&self)->&[u32] {&[STATE,CONFIG,INPUT]}
    fn declared_writes(&self)->&[u32] {&[STATE]}
    fn execute(&self,ctx:&mut dyn ISystemContext)->Result<(),XaceError>{
        let mut ids=ctx.query_entities(&[STATE,CONFIG,INPUT])?;ids.sort_unstable();
        for id in ids {
            let config:Row<Config>=serde_json::from_str(ctx.get_component(id,CONFIG)?.ok_or_else(||bad("missing config"))?).map_err(|_|bad("invalid config"))?;
            let state:Row<State>=serde_json::from_str(ctx.get_component(id,STATE)?.ok_or_else(||bad("missing state"))?).map_err(|_|bad("invalid state"))?;
            #[derive(Deserialize)] #[serde(deny_unknown_fields)] struct InputRow {pulse:Option<Input>,#[serde(default)] graph:Option<GraphInput>}
            let input:Row<InputRow>=serde_json::from_str(ctx.get_component(id,INPUT)?.ok_or_else(||bad("missing input"))?).map_err(|_|bad("invalid input"))?;
            let (next,events)=step_with_graph(&config.data,&state.data,input.data.pulse.as_ref(),input.data.graph.as_ref(),ctx.current_tick())?;
            ctx.submit_mutation(id,STATE,serde_json::to_string(&serde_json::json!({"data":next})).map_err(|_|bad("state serialization"))?)?;
            for (node,amount) in events {
                ctx.emit_event(Event::broadcast(id,EventType::Domain("nec011.echo_arrival.v1".into()),ctx.current_tick(),PhaseEnum::Simulation).with_payload("node",node.to_string()).with_payload("amplitude",amount.to_string()))?;
            }
        }
        Ok(())
    }
}
#[cfg(test)] mod tests {
use super::*;
fn config()->Config {Config{schema_version:1,nodes:vec![1,2,3],edges:vec![Edge{id:1,source:1,target:2,delay:2,gain:SCALE,route:0},Edge{id:2,source:2,target:3,delay:1,gain:-SCALE,route:1}],threshold:SCALE}}
#[test] fn delayed_queue_and_threshold_routing_are_deterministic(){let mut c=config();c.edges[0].route=1;let input=Input{tick:0,id:1,node:1,amplitude:SCALE};let (s,e)=step(&c,&State::default(),Some(&input),0).unwrap();assert_eq!(e,vec![(1,SCALE)]);assert_eq!(s.pending[0].due,2);let (s,_)=step(&c,&s,Some(&input),1).unwrap();let snapshot=s.clone();let (s,e)=step(&c,&s,Some(&input),2).unwrap();assert_eq!(e,vec![(2,SCALE)]);let (s,e)=step(&c,&s,None,3).unwrap();assert_eq!(e,vec![(3,-SCALE)]);let (replay,_)=step(&c,&snapshot,Some(&input),2).unwrap();assert_eq!(step(&c,&replay,None,3).unwrap().0,s);}
#[test] fn invalid_input_and_overflow_preserve_original(){let c=config();let s=State::default();let input=Input{tick:1,id:1,node:1,amplitude:SCALE};assert!(step(&c,&s,Some(&input),0).is_err());assert_eq!(s,State::default());let mut overflow=s.clone();overflow.energy.insert(1,LIMIT);assert!(step(&c,&overflow,Some(&Input{tick:0,..input}),0).is_err());assert_eq!(overflow.energy[&1],LIMIT);}
#[test] fn simultaneous_arrivals_use_sequence_order_and_sum_once() {
    let c=config();
    let original=State{next_sequence:3,pending:vec![Pulse{due:0,node:1,sequence:2,amplitude:SCALE},Pulse{due:0,node:1,sequence:0,amplitude:SCALE},Pulse{due:0,node:1,sequence:1,amplitude:-SCALE}],..State::default()};
    let (next,events)=step(&c,&original,None,0).unwrap();
    assert_eq!(events,vec![(1,SCALE)]);assert_eq!(next.energy[&1],SCALE);
    let mut reordered=original.clone();reordered.pending.reverse();
    assert_eq!(step(&c,&reordered,None,0).unwrap(),(next,events));
}
#[test] fn queue_exhaustion_and_sequence_overflow_refuse_atomically() {
    let c=config();let input=Input{tick:0,id:1,node:1,amplitude:1};
    let full=State{next_sequence:4096,pending:(0..4096).map(|sequence|Pulse{due:1,node:1,sequence,amplitude:1}).collect(),..State::default()};
    let before=full.clone();assert!(step(&c,&full,Some(&input),0).is_err());assert_eq!(full,before);
    let overflow=State{next_sequence:u64::MAX,..State::default()};
    assert!(step(&c,&overflow,Some(&input),0).is_err());assert_eq!(overflow.next_sequence,u64::MAX);
}
#[test] fn player_graph_edits_refuse_conflicts_and_dangling_pending_nodes_atomically(){
    let c=config();let edit=GraphInput{tick:0,id:1,graph:c.clone()};
    let (state,_)=step_with_graph(&c,&State::default(),None,Some(&edit),0).unwrap();
    let before=state.clone();let mut conflict=edit.clone();conflict.graph.threshold+=1;
    assert!(step_with_graph(&c,&state,None,Some(&conflict),1).is_err());assert_eq!(state,before);
    let (held,_)=step_with_graph(&c,&state,None,Some(&edit),1).unwrap();assert_eq!(held.graph,Some(c.clone()));
    let mut queued=held.clone();queued.next_sequence=1;queued.pending.push(Pulse{due:3,node:3,sequence:0,amplitude:1});
    let mut smaller=c.clone();smaller.nodes=vec![1];smaller.edges.clear();let remove=GraphInput{tick:2,id:2,graph:smaller};
    let before=queued.clone();assert!(step_with_graph(&c,&queued,None,Some(&remove),2).is_err());assert_eq!(queued,before);
}
#[test] fn delayed_cycles_remain_bounded_and_replayable() {
    let c=Config{schema_version:1,nodes:vec![1],edges:vec![Edge{id:1,source:1,target:1,delay:1,gain:SCALE,route:0}],threshold:LIMIT};
    let input=Input{tick:0,id:1,node:1,amplitude:1};
    let (mut state,_)=step(&c,&State::default(),Some(&input),0).unwrap();
    let checkpoint=state.clone();let mut expected=Vec::new();
    for tick in 1..61 {let (next,event)=step(&c,&state,None,tick).unwrap();assert_eq!(next.pending.len(),1);expected.push((next.clone(),event));state=next;}
    let mut replay=checkpoint;for (index,expected) in expected.into_iter().enumerate(){let actual=step(&c,&replay,None,index as u64+1).unwrap();assert_eq!(actual,expected);replay=actual.0;}
}

}
