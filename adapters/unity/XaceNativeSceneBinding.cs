using UnityEngine;
namespace Xace.Adapter.Unity
{
    // Approved World object identity. No gameplay, discovery by name or authority.
    [DisallowMultipleComponent]
    public sealed class XaceNativeSceneBinding : MonoBehaviour
    {
        public string worldObjectId;
    }
}
