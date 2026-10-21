use serde_json::{json,Value};
use std::io::Write;
use std::process::{Command,Stdio};
fn run(commands:Vec<Value>)->std::process::Output {
 let root=std::path::Path::new(env!("CARGO_MANIFEST_DIR")).join("fixtures");
 let mut child=Command::new(env!("CARGO_BIN_EXE_xace_echo_host")).arg("--echo-session").arg(root.join("game.cgs.json")).arg(root.join("execution_plan.json")).stdin(Stdio::piped()).stdout(Stdio::piped()).stderr(Stdio::piped()).spawn().unwrap();
 {let mut input=child.stdin.take().unwrap();for row in commands {writeln!(input,"{row}").unwrap();}}
 child.wait_with_output().unwrap()
}
#[test] fn player_creates_graph_sends_pulse_and_rewinds_every_hash_and_event(){
 let graph=json!({"schema_version":1,"nodes":[1,2,3],"edges":[{"id":1,"source":1,"target":2,"delay":2,"gain":1000000,"route":1},{"id":2,"source":2,"target":3,"delay":1,"gain":-1000000,"route":1}],"threshold":1000000});
 let mut commands=vec![json!({"action":"tick","tick":0,"graph":{"tick":0,"id":1,"graph":graph}}),json!({"action":"tick","tick":1,"pulse":{"tick":1,"id":1,"node":1,"amplitude":1000000}}),json!({"action":"checkpoint","tick":2})];
 for tick in 2..7 {commands.push(json!({"action":"tick","tick":tick}));}
 commands.push(json!({"action":"inspect"}));commands.push(json!({"action":"rewind","tick":7}));
 for tick in 2..7 {commands.push(json!({"action":"tick","tick":tick}));}commands.push(json!({"action":"inspect"}));
 let result=run(commands);assert!(result.status.success(),"{}",String::from_utf8_lossy(&result.stderr));
 let rows:Vec<Value>=String::from_utf8(result.stdout).unwrap().lines().map(|s|serde_json::from_str(s).unwrap()).collect();
 assert_eq!(&rows[3..8],&rows[10..15]);assert_eq!(rows[8],rows[15]);assert_eq!(rows[15]["state"]["data"]["energy"]["3"],-1000000);assert_eq!(rows[15]["state"]["data"]["graph"],graph);
}
#[test] fn wrong_tick_and_missing_checkpoint_refuse(){for commands in [vec![json!({"action":"tick","tick":9})],vec![json!({"action":"rewind","tick":0})]] {assert!(!run(commands).status.success());}}
#[test] fn expired_rewind_refuses(){let mut commands=vec![json!({"action":"checkpoint","tick":0})];for tick in 0..121 {commands.push(json!({"action":"tick","tick":tick}));}commands.push(json!({"action":"rewind","tick":121}));let result=run(commands);assert!(!result.status.success());assert!(String::from_utf8_lossy(&result.stderr).contains("horizon"));}
