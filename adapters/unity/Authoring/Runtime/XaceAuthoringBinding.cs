using UnityEngine;

namespace Xace.Authoring
{
    // Explicit semantic declarations; this component never plays or handles input.
    [DisallowMultipleComponent]
    public sealed class XaceAuthoringBinding : MonoBehaviour
    {
        public string InputAction;
        public string BindingId;
        public string EventName;
        public string PlaybackKind;
        public Object Resource;
    }
}
