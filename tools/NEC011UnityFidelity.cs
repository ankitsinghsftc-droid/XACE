using System;
using System.Collections.Generic;
using System.IO;
using System.Reflection;
using UnityEditor;
using UnityEngine;
using Xace.Adapter.Unity;
[InitializeOnLoad]
public static class NEC011UnityFidelity {
 const string Key="NEC011Fidelity";
 static NEC011UnityFidelity(){EditorApplication.update+=AwaitPlay;}
 static void AwaitPlay(){if(EditorApplication.isPlaying&&!String.IsNullOrEmpty(SessionState.GetString(Key,""))){EditorApplication.update-=AwaitPlay;Proof();}}
 public static void Run(){
  var args=Environment.GetCommandLineArgs();SessionState.SetString(Key,args[Array.IndexOf(args,"-xaceReport")+1]);
  Directory.CreateDirectory("Assets/Resources");
  var clip=new AnimationClip{legacy=true};clip.SetCurve("",typeof(Transform),"localPosition.x",AnimationCurve.Linear(0,0,1,1));AssetDatabase.CreateAsset(clip,"Assets/Resources/echo.anim");
  AssetDatabase.CreateAsset(AudioClip.Create("emptySerialized",8000,1,8000,false),"Assets/Resources/emptySerialized.asset");
  WriteWave("Assets/Resources/tone.wav",0);WriteWave("Assets/Resources/replacement.wav",8192);AssetDatabase.ImportAsset("Assets/Resources/tone.wav",ImportAssetOptions.ForceSynchronousImport);AssetDatabase.ImportAsset("Assets/Resources/replacement.wav",ImportAssetOptions.ForceSynchronousImport);AssetDatabase.SaveAssets();
  EditorApplication.EnterPlaymode();
 }
 static void WriteWave(string path,short firstSample){
  using(var w=new BinaryWriter(File.Create(path))){w.Write(System.Text.Encoding.ASCII.GetBytes("RIFF"));w.Write(16036);w.Write(System.Text.Encoding.ASCII.GetBytes("WAVEfmt "));w.Write(16);w.Write((short)1);w.Write((short)1);w.Write(8000);w.Write(16000);w.Write((short)2);w.Write((short)16);w.Write(System.Text.Encoding.ASCII.GetBytes("data"));w.Write(16000);for(int i=0;i<8000;i++)w.Write(i==0?firstSample:(short)0);}
 }
 static void Changed(PlayModeStateChange state){if(state!=PlayModeStateChange.EnteredPlayMode||String.IsNullOrEmpty(SessionState.GetString(Key,"")))return;EditorApplication.update+=Proof;}
 static async void Proof(){EditorApplication.update-=Proof;try{
  var checks=new SortedDictionary<string,object>();
  var root=new GameObject("Fidelity");root.AddComponent<XaceTransport>().enabled=false;var adapter=root.AddComponent<XaceDeltaApplicator>();
  var actor=new GameObject("Echo");actor.AddComponent<Animation>();
  var map=(Dictionary<ulong,GameObject>)typeof(XaceDeltaApplicator).GetField("entityMap",BindingFlags.Instance|BindingFlags.NonPublic).GetValue(adapter);map.Add(42,actor);
  var method=typeof(XaceDeltaApplicator).GetMethod("ApplyPlaybackCommands",BindingFlags.Instance|BindingFlags.NonPublic);
  var results=new List<bool>();adapter.OnPlaybackCommandApplied+=(command,ok)=>results.Add(ok);
  Action<XacePlaybackCommand> apply=command=>method.Invoke(adapter,new object[]{new List<XacePlaybackCommand>{command}});
  var audio=new XacePlaybackCommand{entity_id=42,binding_id="audio",playback_kind="Audio",asset=new XaceAssetReference{id="tone",status="Linked",asset_type="AudioClip"}};
  audio.parameters["resource_path"]="tone";apply(audio);checks["audio_applied"]=results[results.Count-1];checks["audio_started"]=actor.GetComponent<AudioSource>().isPlaying;
  actor.GetComponent<AudioSource>().Stop();await System.Threading.Tasks.Task.Delay(30);audio.parameters["resource_path"]="replacement";apply(audio);checks["replacement_applied"]=results[results.Count-1];checks["replacement_resource_loaded"]=Resources.Load<AudioClip>("replacement")!=null&&Resources.Load<AudioClip>("replacement").length>=0.99f;await System.Threading.Tasks.Task.Delay(30);checks["replacement_played"]=actor.GetComponent<AudioSource>().isPlaying;
  audio.parameters["resource_path"]="emptySerialized";apply(audio);checks["zero_duration_resource_refused"]=Resources.Load<AudioClip>("emptySerialized").length==0&&!results[results.Count-1];
  var anim=new XacePlaybackCommand{entity_id=42,binding_id="animation",playback_kind="Animation",semantic_action="echo",asset=new XaceAssetReference{id="echo",status="Linked",asset_type="AnimationClip"}};
  anim.parameters["resource_path"]="echo";apply(anim);checks["animation_applied"]=results[results.Count-1];checks["animation_started"]=actor.GetComponent<Animation>().IsPlaying("echo");
  actor.AddComponent<Animator>();anim.semantic_action="absent";anim.parameters["resource_path"]="absent";apply(anim);checks["missing_controller_refused"]=!results[results.Count-1];
  actor.GetComponent<AudioSource>().clip=Resources.Load<AudioClip>("tone");audio.parameters["resource_path"]="absent";audio.parameters["xace_binding_status"]="resolved";apply(audio);checks["missing_audio_refused"]=!results[results.Count-1];
  var status=typeof(XaceDeltaApplicator).GetMethod("SemanticBindingStatus",BindingFlags.Static|BindingFlags.NonPublic);checks["declared_resolved_cannot_hide_failure"]=(string)status.Invoke(null,new object[]{audio,false})=="missing";
  audio.parameters["xace_binding_status"]="fallback";checks["failed_fallback_blocks"]=(string)status.Invoke(null,new object[]{audio,false})=="missing";
  audio.parameters["xace_binding_required"]="true";audio.parameters["allow_fallback"]="true";apply(audio);checks["required_binding_refuses_fallback"]=!results[results.Count-1]&&(string)status.Invoke(null,new object[]{audio,false})=="missing";
  var collector=root.AddComponent<XaceInputCollector>();collector.enabled=false;
  collector.liveBindings=new[]{new XaceLiveInputBinding{action="move_x",nativeSelector="MoveRight",kind="axis_1d"},new XaceLiveInputBinding{action="Jump",nativeSelector="JumpButton",kind="button"}};
  var inputEvent=new UnityEngine.Events.UnityEvent<string,float>();inputEvent.AddListener((selector,value)=>{if(!collector.SubmitNativeAction(selector,value))throw new Exception("Native event rejected");});
  inputEvent.Invoke("MoveRight",0.75f);inputEvent.Invoke("JumpButton",1f);
  var mapped=collector.CollectDeclaredLiveActions();
  checks["native_event_declared_packet_mapping"]=mapped.Length==2&&mapped[0].action=="Jump"&&mapped[0].value==1&&mapped[1].action=="move_x"&&mapped[1].value==0.75f;
  checks["unknown_nonfinite_input_refused"]=!collector.SubmitNativeAction("undeclared",1)&&!collector.SubmitNativeAction("MoveRight",float.NaN);
  inputEvent.Invoke("MoveRight",0);inputEvent.Invoke("JumpButton",0);var released=collector.CollectDeclaredLiveActions();checks["native_event_release"]=released[0].phase=="cancelled"&&released[1].phase=="cancelled";
  collector.liveBindings=new[]{new XaceLiveInputBinding{action="same"},new XaceLiveInputBinding{action="same"}};bool duplicate=false;try{collector.CollectDeclaredLiveActions();}catch(FormatException){duplicate=true;}checks["duplicate_input_mapping_refused"]=duplicate;
  bool ok=true;foreach(var value in checks.Values)ok&=(bool)value;
  var sampled=new List<object>();foreach(var action in mapped)sampled.Add(action.ToDictionary());
  var report=new Dictionary<string,object>{{"sampled_actions",sampled},{"ok",ok},{"engine","unity"},{"version",Application.unityVersion},{"checks",checks},{"actual_play_mode",true},{"audible_output_certified",false}};
  var type=typeof(XaceCanonical).Assembly.GetType("Xace.Adapter.Unity.XaceJson");File.WriteAllText(SessionState.GetString(Key,""),(string)type.GetMethod("Serialize",BindingFlags.Static|BindingFlags.Public).Invoke(null,new object[]{report}));SessionState.EraseString(Key);EditorApplication.Exit(ok?0:1);
 }catch(Exception error){Debug.LogException(error);EditorApplication.Exit(1);}}
}
