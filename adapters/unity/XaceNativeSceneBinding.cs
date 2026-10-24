using System;
using System.Collections.Generic;
using UnityEngine;
namespace Xace.Adapter.Unity
{
    // Approved World object identity. No gameplay, discovery by name or authority.
    [DisallowMultipleComponent]
    public sealed class XaceNativeSceneBinding : MonoBehaviour
    {
        public string worldObjectId;
        public static void ValidateWorld(string json, Dictionary<string,GameObject> bindings)
        {
            var world=XaceCanonical.Parse(json);
            if(XaceCanonical.Text(world,"schema")!="xace.world_contract.v3")throw new InvalidOperationException("Native World v3 required");
            var objects=(List<object>)world["objects"];
            if(objects.Count!=bindings.Count)throw new InvalidOperationException("Native bindings do not cover exactly the approved World");
            var seen=new HashSet<string>(StringComparer.Ordinal);
            foreach(var value in objects)
            {
                var item=XaceCanonical.Object(value);string id=XaceCanonical.Text(item,"id");
                if(!seen.Add(id)||!bindings.TryGetValue(id,out var go)||go==null)throw new InvalidOperationException("Missing or duplicate native World object: "+id);
                var transform=XaceCanonical.Object(item["transform"]);
                if(Vector3.Distance(go.transform.position,XaceCanonical.Vector(XaceCanonical.Object(transform["position"])))>0.00001f)throw new InvalidOperationException("Native starting transform differs from approved World: "+id);
                string expected="";var relations=XaceCanonical.Object(item["relationships"]);
                if(relations.TryGetValue("xace.authoring_parent.v1",out var raw))
                {var parents=(List<object>)raw;if(parents.Count!=1)throw new InvalidOperationException("Exactly one native parent required");expected=Convert.ToString(parents[0]);}
                string actual="";
                for(var parent=go.transform.parent;parent!=null;parent=parent.parent){var binding=parent.GetComponent<XaceNativeSceneBinding>();if(binding!=null){actual=binding.worldObjectId;break;}}
                if(actual!=expected)throw new InvalidOperationException("Native parent differs from approved World: "+id);
            }
        }
    }
}
