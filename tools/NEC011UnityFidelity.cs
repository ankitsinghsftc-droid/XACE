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
 static NEC011UnityFidelity(){EditorApplication.playModeStateChanged+=Changed;}
 public static void Run(){
  var args=Environment.GetCommandLineArgs();SessionState.SetString(Key,args[Array.IndexOf(args,"-xaceReport")+1]);
  Directory.CreateDirectory("Assets/Resources");
  var clip=new AnimationClip{legacy=true};clip.SetCurve("",typeof(Transform),"localPosition.x",AnimationCurve.Linear(0,0,1,1));AssetDatabase.CreateAsset(clip,"Assets/Resources/echo.anim");
  var audio=AudioClip.Create("tone",8000,1,8000,false);AssetDatabase.CreateAsset(audio,"Assets/Resources/tone.asset");AssetDatabase.SaveAssets();
  EditorApplication.EnterPlaymode();
 }
 static void Changed(PlayModeStateChange state){if(state!=PlayModeStateChange.EnteredPlayMode||String.IsNullOrEmpty(SessionState.GetString(Key,"")))return;EditorApplication.update+=Proof;}
 static void Proof(){EditorApplication.update-=Proof;try{
  var checks=new SortedDictionary<string,object>();
  var root=new GameObject("Fidelity");root.AddComponent<XaceTransport>().enabled=false;var adapter=root.AddComponent<XaceDeltaApplicator>();
  var actor=new GameObject("Echo");actor.AddComponent<Animation>();
  var map=(Dictionary<ulong,GameObject>)typeof(XaceDeltaApplicator).GetField("entityMap",BindingFlags.Instance|BindingFlags.NonPublic).GetValue(adapter);map.Add(42,actor);
  var method=typeof(XaceDeltaApplicator).GetMethod("ApplyPlaybackCommands",BindingFlags.Instance|BindingFlags.NonPublic);
  var results=new List<bool>();adapter.OnPlaybackCommandApplied+=(command,ok)=>results.Add(ok);
  Action<XacePlaybackCommand> apply=command=>method.Invoke(adapter,new object[]{new List<XacePlaybackCommand>{command}});
  var audio=new XacePlaybackCommand{entity_id=42,binding_id="audio",playback_kind="Audio",asset=new XaceAssetReference{id="tone",status="Linked",asset_type="AudioClip"}};
  audio.parameters["resource_path"]="tone";apply(audio);checks["audio_applied"]=results[results.Count-1];checks["audio_started"]=actor.GetComponent<AudioSource>().isPlaying;
  var anim=new XacePlaybackCommand{entity_id=42,binding_id="animation",playback_kind="Animation",semantic_action="echo",asset=new XaceAssetReference{id="echo",status="Linked",asset_type="AnimationClip"}};
  anim.parameters["resource_path"]="echo";apply(anim);checks["animation_applied"]=results[results.Count-1];checks["animation_started"]=actor.GetComponent<Animation>().IsPlaying("echo");
  actor.AddComponent<Animator>();anim.semantic_action="absent";anim.parameters["resource_path"]="absent";apply(anim);checks["missing_controller_refused"]=!results[results.Count-1];
  bool ok=true;foreach(var value in checks.Values)ok&=(bool)value;
  var report=new Dictionary<string,object>{{"ok",ok},{"engine","unity"},{"version",Application.unityVersion},{"checks",checks},{"actual_play_mode",true},{"audible_output_certified",false}};
  var type=typeof(XaceCanonical).Assembly.GetType("Xace.Adapter.Unity.XaceJson");File.WriteAllText(SessionState.GetString(Key,""),(string)type.GetMethod("Serialize",BindingFlags.Static|BindingFlags.Public).Invoke(null,new object[]{report}));SessionState.EraseString(Key);EditorApplication.Exit(ok?0:1);
 }catch(Exception error){Debug.LogException(error);EditorApplication.Exit(1);}}
}
