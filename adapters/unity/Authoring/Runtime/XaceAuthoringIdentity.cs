using UnityEngine;

namespace Xace.Authoring
{
    // Serialized authoring metadata only. No callbacks, transport or gameplay logic.
    [DisallowMultipleComponent]
    public sealed class XaceAuthoringIdentity : MonoBehaviour
    {
        public string NamespaceId;
        public string AuthoringId;
        public string Kind = "object";
        public string Generation = "1";
        public string PrefabId;
    }
}
