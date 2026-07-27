// Xace_embedded.cs
// Optional Unity embedded mode for the XACE native library.
//
// TCP bridge mode is the default live-engine path. Embedded mode is useful for
// deterministic local simulation inside Unity builds that ship with the XACE C
// ABI library. All calls must remain on one Unity thread.

using System;
using System.Runtime.InteropServices;
using System.Text;
using UnityEngine;

namespace XACE
{
    internal static class NativeMethods
    {
        private const string LibraryName = "xace";

        [DllImport(LibraryName, CallingConvention = CallingConvention.Cdecl)]
        internal static extern int xace_init(out IntPtr outWorld, ulong worldSeed, uint deltaBufferBytes);

        [DllImport(LibraryName, CallingConvention = CallingConvention.Cdecl)]
        internal static extern int xace_load_cgs(IntPtr world, byte[] cgsJson, uint cgsLen);

        [DllImport(LibraryName, CallingConvention = CallingConvention.Cdecl)]
        internal static extern int xace_shutdown(IntPtr world);

        [DllImport(LibraryName, CallingConvention = CallingConvention.Cdecl)]
        internal static extern int xace_apply_input(IntPtr world, byte[] inputPtr, uint inputLen);

        [DllImport(LibraryName, CallingConvention = CallingConvention.Cdecl)]
        internal static extern int xace_tick(IntPtr world);

        [DllImport(LibraryName, CallingConvention = CallingConvention.Cdecl)]
        internal static extern int xace_get_state_delta(IntPtr world, byte[] buffer, ref uint bufferSize);

        [DllImport(LibraryName, CallingConvention = CallingConvention.Cdecl)]
        internal static extern int xace_get_world_hash(IntPtr world, byte[] outHash, uint outLen);

        [DllImport(LibraryName, CallingConvention = CallingConvention.Cdecl)]
        internal static extern int xace_get_tick_number(IntPtr world, out ulong outTick);

        [DllImport(LibraryName, CallingConvention = CallingConvention.Cdecl)]
        internal static extern int xace_get_last_error(IntPtr world, byte[] buffer, uint bufferSize);

        [DllImport(LibraryName, CallingConvention = CallingConvention.Cdecl)]
        internal static extern uint xace_version();
    }

    public enum XaceErrorCode : int
    {
        Ok = 0,
        NullPointer = -1,
        InvalidHandle = -2,
        CgsParseError = -3,
        TickError = -4,
        BufferTooSmall = -5,
        IoError = -6,
        NotInitialized = -7,
        AlreadyInitialized = -8,
        DeterminismViolation = -9,
        Panic = -99
    }

    public sealed class XaceException : Exception
    {
        public XaceErrorCode ErrorCode { get; private set; }

        public XaceException(XaceErrorCode code, string message)
            : base("[XACE " + code + "] " + message)
        {
            ErrorCode = code;
        }
    }

    public sealed class XaceWorld : IDisposable
    {
        private const uint DefaultDeltaBufferBytes = 4u * 1024u * 1024u;

        private IntPtr handle;
        private bool disposed;
        private byte[] deltaBuffer;
        private uint deltaBufferSize;

        private XaceWorld(IntPtr handle, uint deltaBufferBytes)
        {
            this.handle = handle;
            deltaBufferSize = Math.Max(1024u, deltaBufferBytes);
            deltaBuffer = new byte[deltaBufferSize];
        }

        public static XaceWorld Create(ulong worldSeed = 42, uint deltaBufferBytes = DefaultDeltaBufferBytes)
        {
            var code = NativeMethods.xace_init(out var world, worldSeed, Math.Max(1024u, deltaBufferBytes));
            ThrowIfError(world, code, "xace_init");
            if (world == IntPtr.Zero)
                throw new XaceException(XaceErrorCode.InvalidHandle, "xace_init returned a null world handle");
            return new XaceWorld(world, deltaBufferBytes);
        }

        public bool IsDisposed { get { return disposed; } }

        public ulong TickNumber
        {
            get
            {
                ThrowIfDisposed();
                var code = NativeMethods.xace_get_tick_number(handle, out var tick);
                ThrowIfError(handle, code, "xace_get_tick_number");
                return tick;
            }
        }

        public string WorldHash
        {
            get
            {
                ThrowIfDisposed();
                var buffer = new byte[128];
                var code = NativeMethods.xace_get_world_hash(handle, buffer, (uint)buffer.Length);
                ThrowIfError(handle, code, "xace_get_world_hash");
                return NullTerminatedUtf8(buffer);
            }
        }

        public string LastError
        {
            get
            {
                if (handle == IntPtr.Zero)
                    return "world not initialized";
                var buffer = new byte[2048];
                var code = NativeMethods.xace_get_last_error(handle, buffer, (uint)buffer.Length);
                return code == 0 ? NullTerminatedUtf8(buffer) : "failed to query last error";
            }
        }

        public static uint NativeVersion
        {
            get { return NativeMethods.xace_version(); }
        }

        public void LoadCgs(string cgsJson)
        {
            ThrowIfDisposed();
            if (string.IsNullOrWhiteSpace(cgsJson))
                throw new ArgumentException("CGS JSON must not be empty", nameof(cgsJson));
            var bytes = Encoding.UTF8.GetBytes(cgsJson);
            var code = NativeMethods.xace_load_cgs(handle, bytes, (uint)bytes.Length);
            ThrowIfError(handle, code, "xace_load_cgs");
        }

        public void ApplyInput(byte[] inputPacket)
        {
            ThrowIfDisposed();
            if (inputPacket == null || inputPacket.Length == 0)
                return;
            var code = NativeMethods.xace_apply_input(handle, inputPacket, (uint)inputPacket.Length);
            ThrowIfError(handle, code, "xace_apply_input");
        }

        public void ApplyInputJson(string inputPacketJson)
        {
            if (string.IsNullOrWhiteSpace(inputPacketJson))
                return;
            ApplyInput(Encoding.UTF8.GetBytes(inputPacketJson));
        }

        public void Tick()
        {
            ThrowIfDisposed();
            var code = NativeMethods.xace_tick(handle);
            ThrowIfError(handle, code, "xace_tick");
        }

        public ArraySegment<byte> GetStateDelta()
        {
            ThrowIfDisposed();
            var size = deltaBufferSize;
            var code = NativeMethods.xace_get_state_delta(handle, deltaBuffer, ref size);
            if (code == (int)XaceErrorCode.BufferTooSmall)
            {
                if (size <= deltaBufferSize)
                    size = deltaBufferSize * 2u;
                deltaBufferSize = size;
                deltaBuffer = new byte[deltaBufferSize];
                code = NativeMethods.xace_get_state_delta(handle, deltaBuffer, ref size);
            }
            ThrowIfError(handle, code, "xace_get_state_delta");
            return new ArraySegment<byte>(deltaBuffer, 0, checked((int)size));
        }

        public byte[] CopyStateDelta()
        {
            var segment = GetStateDelta();
            var copy = new byte[segment.Count];
            Buffer.BlockCopy(segment.Array, segment.Offset, copy, 0, segment.Count);
            return copy;
        }

        public void Dispose()
        {
            if (!disposed)
            {
                if (handle != IntPtr.Zero)
                {
                    NativeMethods.xace_shutdown(handle);
                    handle = IntPtr.Zero;
                }
                disposed = true;
            }
            GC.SuppressFinalize(this);
        }

        ~XaceWorld()
        {
            Dispose();
        }

        private void ThrowIfDisposed()
        {
            if (disposed || handle == IntPtr.Zero)
                throw new ObjectDisposedException(nameof(XaceWorld));
        }

        private static void ThrowIfError(IntPtr world, int code, string operation)
        {
            if (code == 0)
                return;

            var errorCode = (XaceErrorCode)code;
            var detail = "";
            if (world != IntPtr.Zero)
            {
                var buffer = new byte[2048];
                if (NativeMethods.xace_get_last_error(world, buffer, (uint)buffer.Length) == 0)
                    detail = NullTerminatedUtf8(buffer);
            }

            throw new XaceException(
                errorCode,
                string.IsNullOrEmpty(detail) ? operation + " returned " + errorCode : operation + ": " + detail
            );
        }

        private static string NullTerminatedUtf8(byte[] buffer)
        {
            var len = 0;
            while (len < buffer.Length && buffer[len] != 0)
                len++;
            return Encoding.UTF8.GetString(buffer, 0, len);
        }
    }

    public abstract class XaceMonoBehaviour : MonoBehaviour
    {
        [Header("XACE Embedded")]
        [SerializeField] private ulong worldSeed = 42;
        [SerializeField] private uint deltaBufferBytes = 4u * 1024u * 1024u;
        [SerializeField] private TextAsset cgsAsset;
        [SerializeField] private bool tickInFixedUpdate = true;

        protected XaceWorld Xace { get; private set; }

        protected virtual void Start()
        {
            Xace = XaceWorld.Create(worldSeed, deltaBufferBytes);
            if (cgsAsset != null)
                Xace.LoadCgs(cgsAsset.text);
        }

        protected virtual void FixedUpdate()
        {
            if (tickInFixedUpdate)
                TickEmbeddedWorld();
        }

        protected void TickEmbeddedWorld()
        {
            if (Xace == null || Xace.IsDisposed)
                return;
            CollectAndApplyInput(Xace);
            Xace.Tick();
            OnXaceTick(Xace.GetStateDelta());
        }

        protected virtual void CollectAndApplyInput(XaceWorld world)
        {
        }

        protected abstract void OnXaceTick(ArraySegment<byte> stateDelta);

        protected virtual void OnDestroy()
        {
            if (Xace != null)
            {
                Xace.Dispose();
                Xace = null;
            }
        }
    }
}
