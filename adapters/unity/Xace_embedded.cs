// XaceEmbedded.cs — XACE Unity Integration
//
// Provides P/Invoke bindings to the XACE native library (xace.dll / libxace.so)
// and a high-level XaceWorld wrapper that safely manages the native handle.
//
// Usage in MonoBehaviour:
//   private XaceWorld _xace;
//
//   void Start() {
//       _xace = XaceWorld.Create(worldSeed: 42);
//       _xace.LoadCgs(System.IO.File.ReadAllText("Assets/xace_cgs.json"));
//   }
//
//   void FixedUpdate() {
//       // 1. Apply player input
//       _xace.ApplyInput(inputPacketBytes);
//
//       // 2. Tick simulation
//       _xace.Tick();
//
//       // 3. Get state delta and apply to scene
//       byte[] delta = _xace.GetStateDelta();
//       ApplyDeltaToScene(delta);
//   }
//
//   void OnDestroy() {
//       _xace.Dispose();
//   }
//
// Thread Safety:
//   XaceWorld is NOT thread-safe. Call all methods from the same thread
//   (Unity main thread / FixedUpdate). This mirrors the C API contract.

using System;
using System.Runtime.InteropServices;
using System.Text;
using UnityEngine;


namespace XACE
{
    // ── P/Invoke Declarations ─────────────────────────────────────────────────

    internal static class NativeMethods
    {
        // The library name without extension. Unity resolves platform-specifics:
        //   Windows: xace.dll
        //   macOS:   libxace.dylib
        //   Linux:   libxace.so
        private const string DLL = "xace";

        // ── Lifecycle ─────────────────────────────────────────────────────────

        [DllImport(DLL, CallingConvention = CallingConvention.Cdecl)]
        internal static extern int xace_init(
            out IntPtr outWorld,
            ulong      worldSeed,
            uint       deltaBufBytes);

        [DllImport(DLL, CallingConvention = CallingConvention.Cdecl)]
        internal static extern int xace_load_cgs(
            IntPtr  world,
            byte[]  cgsJson,
            uint    cgsLen);

        [DllImport(DLL, CallingConvention = CallingConvention.Cdecl)]
        internal static extern int xace_shutdown(IntPtr world);

        // ── Simulation Loop ───────────────────────────────────────────────────

        [DllImport(DLL, CallingConvention = CallingConvention.Cdecl)]
        internal static extern int xace_apply_input(
            IntPtr        world,
            byte[]        inputPtr,
            uint          inputLen);

        [DllImport(DLL, CallingConvention = CallingConvention.Cdecl)]
        internal static extern int xace_tick(IntPtr world);

        [DllImport(DLL, CallingConvention = CallingConvention.Cdecl)]
        internal static extern int xace_get_state_delta(
            IntPtr        world,
            byte[]        buffer,
            ref uint      bufferSize);

        // ── Diagnostics ───────────────────────────────────────────────────────

        [DllImport(DLL, CallingConvention = CallingConvention.Cdecl)]
        internal static extern int xace_get_world_hash(
            IntPtr world,
            byte[] outHash,
            uint   outLen);

        [DllImport(DLL, CallingConvention = CallingConvention.Cdecl)]
        internal static extern int xace_get_tick_number(
            IntPtr   world,
            out ulong outTick);

        [DllImport(DLL, CallingConvention = CallingConvention.Cdecl)]
        internal static extern int xace_get_last_error(
            IntPtr world,
            byte[] buffer,
            uint   bufferSize);

        [DllImport(DLL, CallingConvention = CallingConvention.Cdecl)]
        internal static extern uint xace_version();
    }


    // ── Error Codes (mirrors error_codes.rs) ──────────────────────────────────

    public enum XaceErrorCode : int
    {
        Ok                   =  0,
        NullPointer          = -1,
        InvalidHandle        = -2,
        CgsParseError        = -3,
        TickError            = -4,
        BufferTooSmall       = -5,
        IoError              = -6,
        NotInitialized       = -7,
        AlreadyInitialized   = -8,
        DeterminismViolation = -9,
        Panic                = -99,
    }


    // ── Exception ─────────────────────────────────────────────────────────────

    public sealed class XaceException : Exception
    {
        public XaceErrorCode ErrorCode { get; }

        public XaceException(XaceErrorCode code, string message)
            : base($"[XACE {code}] {message}")
        {
            ErrorCode = code;
        }
    }


    // ── XaceWorld — High-Level Managed Wrapper ────────────────────────────────

    /// Thread-safe: NO. Call from Unity main thread / FixedUpdate only.
    /// IDisposable: call Dispose() in OnDestroy() or use a 'using' statement.
    public sealed class XaceWorld : IDisposable
    {
        private IntPtr _handle;
        private bool   _disposed;

        // Delta buffer is reused across calls to avoid GC pressure
        private byte[] _deltaBuffer;
        private uint   _deltaBufferSize;

        // ── Factory ───────────────────────────────────────────────────────────

        /// Creates a new XACE world.
        ///
        /// <param name="worldSeed">Determinism seed. Same seed + same CGS = same simulation.</param>
        /// <param name="deltaBufBytes">Pre-allocated delta buffer size. Default: 4 MB.</param>
        public static XaceWorld Create(ulong worldSeed = 42, uint deltaBufBytes = 4u * 1024 * 1024)
        {
            var code = NativeMethods.xace_init(out var handle, worldSeed, deltaBufBytes);
            ThrowIfError(handle, code, "xace_init");
            return new XaceWorld(handle, deltaBufBytes);
        }

        private XaceWorld(IntPtr handle, uint deltaBufBytes)
        {
            _handle          = handle;
            _deltaBufferSize = deltaBufBytes;
            _deltaBuffer     = new byte[deltaBufBytes];
        }

        // ── Lifecycle ─────────────────────────────────────────────────────────

        /// Loads the Canonical Game Schema (CGS) JSON into the world.
        /// Must be called before Tick(). Can only be called once per world.
        public void LoadCgs(string cgsJson)
        {
            ThrowIfDisposed();
            var bytes = Encoding.UTF8.GetBytes(cgsJson);
            var code  = NativeMethods.xace_load_cgs(_handle, bytes, (uint)bytes.Length);
            ThrowIfError(_handle, code, "xace_load_cgs");
        }

        // ── Simulation Loop ───────────────────────────────────────────────────

        /// Enqueues player/network input for the next tick.
        /// Call before Tick(). Multiple inputs per tick are supported.
        public void ApplyInput(byte[] inputPacket)
        {
            if (inputPacket == null || inputPacket.Length == 0) return;
            ThrowIfDisposed();
            var code = NativeMethods.xace_apply_input(_handle, inputPacket, (uint)inputPacket.Length);
            ThrowIfError(_handle, code, "xace_apply_input");
        }

        /// Advances the simulation by exactly one tick.
        /// Call from FixedUpdate() — do not skip ticks.
        public void Tick()
        {
            ThrowIfDisposed();
            var code = NativeMethods.xace_tick(_handle);
            ThrowIfError(_handle, code, "xace_tick");
        }

        /// Returns the state delta from the last tick as a raw byte array.
        /// The engine decodes this to apply component changes to its scene graph.
        /// The returned array is reused — copy it if you need to keep it across calls.
        public ArraySegment<byte> GetStateDelta()
        {
            ThrowIfDisposed();
            uint size = _deltaBufferSize;

            var code = NativeMethods.xace_get_state_delta(_handle, _deltaBuffer, ref size);

            if (code == (int)XaceErrorCode.BufferTooSmall)
            {
                // Grow the buffer and retry
                _deltaBuffer     = new byte[size];
                _deltaBufferSize = size;
                code = NativeMethods.xace_get_state_delta(_handle, _deltaBuffer, ref size);
            }

            ThrowIfError(_handle, code, "xace_get_state_delta");
            return new ArraySegment<byte>(_deltaBuffer, 0, (int)size);
        }

        // ── Diagnostics ───────────────────────────────────────────────────────

        /// Returns the current world hash (hex string, 64 chars for SHA-256).
        /// Compare against TCP mode hash for determinism verification.
        public string WorldHash
        {
            get
            {
                ThrowIfDisposed();
                var buf  = new byte[128];
                var code = NativeMethods.xace_get_world_hash(_handle, buf, (uint)buf.Length);
                ThrowIfError(_handle, code, "xace_get_world_hash");
                return Encoding.UTF8.GetString(buf).TrimEnd('\0');
            }
        }

        /// Returns the current simulation tick number.
        public ulong TickNumber
        {
            get
            {
                ThrowIfDisposed();
                var code = NativeMethods.xace_get_tick_number(_handle, out var tick);
                ThrowIfError(_handle, code, "xace_get_tick_number");
                return tick;
            }
        }

        /// Returns the last error message from the native library.
        public string LastError
        {
            get
            {
                if (_handle == IntPtr.Zero) return "world not initialized";
                var buf  = new byte[1024];
                var code = NativeMethods.xace_get_last_error(_handle, buf, (uint)buf.Length);
                return code == 0
                    ? Encoding.UTF8.GetString(buf).TrimEnd('\0')
                    : "error retrieving last error";
            }
        }

        /// Returns the XACE C API version.
        public static uint NativeVersion => NativeMethods.xace_version();

        // ── IDisposable ───────────────────────────────────────────────────────

        public void Dispose()
        {
            if (!_disposed && _handle != IntPtr.Zero)
            {
                NativeMethods.xace_shutdown(_handle);
                _handle  = IntPtr.Zero;
                _disposed = true;
            }
            GC.SuppressFinalize(this);
        }

        ~XaceWorld() { Dispose(); }

        // ── Internal ──────────────────────────────────────────────────────────

        private void ThrowIfDisposed()
        {
            if (_disposed)
                throw new ObjectDisposedException(nameof(XaceWorld));
        }

        private static void ThrowIfError(IntPtr world, int code, string funcName)
        {
            if (code == 0) return;

            var errorCode = (XaceErrorCode)code;
            string detail = string.Empty;

            // Try to get a detailed error message from the world if it's valid
            if (world != IntPtr.Zero)
            {
                var buf = new byte[512];
                NativeMethods.xace_get_last_error(world, buf, (uint)buf.Length);
                detail = Encoding.UTF8.GetString(buf).TrimEnd('\0');
            }

            throw new XaceException(errorCode,
                string.IsNullOrEmpty(detail)
                    ? $"{funcName} returned {errorCode}"
                    : $"{funcName}: {detail}");
        }
    }


    // ── XaceMonoBehaviour — Drop-in MonoBehaviour Integration ─────────────────

    /// Optional base class for Unity components that manage an XACE world.
    /// Handles lifecycle (Create/Dispose) and provides FixedUpdate integration.
    ///
    /// Usage:
    ///   public class MyGameManager : XaceMonoBehaviour
    ///   {
    ///       protected override void OnXaceTick(ArraySegment<byte> stateDelta) {
    ///           // Apply stateDelta to your scene objects
    ///       }
    ///   }
    public abstract class XaceMonoBehaviour : MonoBehaviour
    {
        [Header("XACE Configuration")]
        [SerializeField] private ulong worldSeed = 42;
        [SerializeField] private TextAsset cgsAsset;

        protected XaceWorld Xace { get; private set; }

        protected virtual void Start()
        {
            Xace = XaceWorld.Create(worldSeed);
            if (cgsAsset != null)
            {
                Xace.LoadCgs(cgsAsset.text);
            }
        }

        protected virtual void FixedUpdate()
        {
            if (Xace == null) return;
            CollectAndApplyInput();
            Xace.Tick();
            var delta = Xace.GetStateDelta();
            OnXaceTick(delta);
        }

        /// Override to collect input from Unity's input system and apply it.
        protected virtual void CollectAndApplyInput() { }

        /// Override to process the state delta returned by each tick.
        protected abstract void OnXaceTick(ArraySegment<byte> stateDelta);

        protected virtual void OnDestroy()
        {
            Xace?.Dispose();
            Xace = null;
        }
    }
}