// ============================================================================
// packages/engine-adapter/src/ffi/handle_types.rs
// ============================================================================

/*!
# handle_types.rs — FFI Handle Types

Manages the lifetime of `FfiWorldHandle` across the FFI boundary.

## The Canonical Rust FFI Handle Pattern

The C API exposes `XaceWorld*` — an opaque pointer. Unity never sees the Rust
types inside. The lifecycle is:

```c
XaceWorld* world = nullptr;
xace_init(&world, seed, buf_size);   // Rust: Box::into_raw(Box::new(FfiWorldHandle { ... }))
xace_tick(world);
xace_shutdown(world);                // Rust: drop(Box::from_raw(world))
```

## Safety

`Box::into_raw` leaks the allocation — C now "owns" the pointer.
`Box::from_raw` in `xace_shutdown` reclaims it and runs Drop.

Between `xace_init` and `xace_shutdown`, the pointer is valid and the
`FfiWorldHandle` lives on the Rust heap. No garbage collector touches it.

The caller (Unity C# or Unreal C++) is responsible for exactly-once
`xace_shutdown` per `xace_init`. A `IDisposable` / `RAII` wrapper is
provided in `XaceEmbedded.cs` to enforce this.
*/

use super::shared_buffer::{InputQueue, SharedDeltaBuffer};

// ── Opaque World Type ─────────────────────────────────────────────────────────

/// Opaque world type. Never instantiated — used only as a pointer target.
///
/// `*mut OpaqueWorld` in the C API corresponds to `*mut FfiWorldHandle` internally.
/// The zero-size array ensures C callers cannot create instances.
#[repr(C)]
pub struct OpaqueWorld {
    _private: [u8; 0],
}

// ── World Handle ──────────────────────────────────────────────────────────────

/// The actual state stored behind the opaque `XaceWorld*` pointer.
///
/// Allocated on the Rust heap via `Box::new(FfiWorldHandle { ... })`.
/// Freed via `Box::from_raw(ptr)` in `xace_shutdown`.
pub struct FfiWorldHandle {
    // ── Configuration ──────────────────────────────────────────────────────
    pub world_seed: u64,
    pub cgs_loaded: bool,
    pub schema_version: String,

    // ── Simulation State ───────────────────────────────────────────────────
    pub tick_number: u64,
    pub world_hash: String, // hex-encoded hash after last tick

    // ── Buffers ────────────────────────────────────────────────────────────
    pub delta_buffer: SharedDeltaBuffer,
    pub input_queue: InputQueue,

    // ── Error State ────────────────────────────────────────────────────────
    pub last_error: String,
    pub halted: bool, // true after determinism violation
}

impl FfiWorldHandle {
    pub fn new(world_seed: u64, delta_buf_bytes: u32) -> Self {
        Self {
            world_seed,
            cgs_loaded: false,
            schema_version: String::new(),
            tick_number: 0,
            world_hash: "0".repeat(64),
            delta_buffer: SharedDeltaBuffer::new(delta_buf_bytes as usize),
            input_queue: InputQueue::new(),
            last_error: String::new(),
            halted: false,
        }
    }

    pub fn set_error(&mut self, msg: impl Into<String>) {
        self.last_error = msg.into();
    }

    pub fn clear_error(&mut self) {
        self.last_error.clear();
    }

    /// Formats the last error into a caller-provided buffer.
    /// Returns the number of bytes written (capped at `buf_size - 1` for null terminator).
    pub fn write_last_error(&self, buffer: *mut i8, buf_size: u32) -> u32 {
        if buffer.is_null() || buf_size == 0 {
            return 0;
        }
        let msg = if self.last_error.is_empty() {
            "no error"
        } else {
            &self.last_error
        };
        let bytes = msg.as_bytes();
        let copy = (buf_size as usize - 1).min(bytes.len());
        // SAFETY: buffer is non-null and buf_size > 0 (checked above)
        unsafe {
            std::ptr::copy_nonoverlapping(bytes.as_ptr() as *const i8, buffer, copy);
            *buffer.add(copy) = 0; // null-terminate
        }
        copy as u32
    }
}

// ── Handle Conversion Helpers ─────────────────────────────────────────────────

/// Allocates a FfiWorldHandle on the heap and returns a raw pointer for C.
/// Caller (xace_init) passes this to C via `*out_world = ...`.
pub fn box_into_raw(handle: FfiWorldHandle) -> *mut OpaqueWorld {
    Box::into_raw(Box::new(handle)) as *mut OpaqueWorld
}

/// Converts a raw pointer back to an owned Box, which will be dropped.
///
/// # Safety
/// `ptr` must be a pointer returned by `box_into_raw` that has not yet been freed.
pub unsafe fn raw_into_box(ptr: *mut OpaqueWorld) -> Box<FfiWorldHandle> {
    Box::from_raw(ptr as *mut FfiWorldHandle)
}

/// Obtains a mutable reference to the world behind an opaque pointer.
///
/// # Safety
/// `ptr` must be non-null and point to a valid `FfiWorldHandle`.
pub unsafe fn as_mut<'a>(ptr: *mut OpaqueWorld) -> &'a mut FfiWorldHandle {
    &mut *(ptr as *mut FfiWorldHandle)
}

/// Macro: null-check a pointer, set an error on the world handle, return error code.
/// Usage: `guard_null!(ptr, XaceErrorCode::NullPointer)`
#[macro_export]
macro_rules! guard_null {
    ($ptr:expr, $code:expr) => {
        if $ptr.is_null() {
            return $code as i32;
        }
    };
}
