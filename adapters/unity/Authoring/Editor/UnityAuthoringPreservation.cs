using System;
using System.Globalization;
using System.Linq;
using System.Text.RegularExpressions;
using UnityEditor;
using UnityEngine;
using Object=UnityEngine.Object;
namespace Xace.Authoring.Editor
{
    // Pinned editor serialization with persistent references, never instance IDs.
    // No field is removed from an unowned component's serialized representation.
    public static class UnityAuthoringPreservation
    {
        static string Reference(int instance)
        {
            if(instance==0)return "null";
            var obj=EditorUtility.InstanceIDToObject(instance);
            AuthoringJson.Need(obj!=null,"Unresolved serialized reference");
            var go=obj as GameObject ?? (obj as Component)?.gameObject;
            var identity=go==null?null:go.GetComponent<XaceAuthoringIdentity>();
            if(identity!=null)
            {
                UnityAuthoringReader.Identity(identity);
                string suffix="gameobject";
                if(obj is Component component)
                {
                    int index=Array.IndexOf(go.GetComponents<Component>(),component);
                    AuthoringJson.Need(index>=0,"Component identity unavailable");
                    suffix=component.GetType().FullName+":"+index.ToString(CultureInfo.InvariantCulture);
                }
                return identity.NamespaceId+":"+identity.AuthoringId+":"+suffix;
            }
            return UnityAuthoringReader.Locator(obj);
        }
        public static string Fingerprint(Object component,bool mappedTransform=false,bool mappedMesh=false)
        {
            string json=EditorJsonUtility.ToJson(component,false);
            if(mappedTransform)
                json=Regex.Replace(json,@"(?<!\\)""m_Local(Position|Rotation|Scale|EulerAnglesHint)""\s*:\s*\{[^{}]*\},?","");
            if(mappedMesh)
                json=Regex.Replace(json,@"(?<!\\)""m_Mesh""\s*:\s*\{[^{}]*\},?","");
            // Match actual JSON keys, not escaped text inside string values.
            json=Regex.Replace(json,@"(?<!\\)""instanceID""\s*:\s*(-?\d+)",
                match=>"\"stableReference\":"+AuthoringJson.Encode(Reference(int.Parse(match.Groups[1].Value,CultureInfo.InvariantCulture))));
            return AuthoringJson.Hash("unity.stored_component.v1:"+component.GetType().FullName+":"+json);
        }
    }
}
