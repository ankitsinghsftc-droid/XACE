/*!
# xace_ffi.rs — C ABI Exports

Every function in this file is:
1. `#[no_mangle] pub extern "C"` — exported with C name mangling
2. Wrapped in `std::panic::catch_unwind` — no Rust panics cross FFI
3. Null-checked on every pointer argument
4. Matching `include/xace.h` exactly (cbindgen keeps them in sync)

## Naming Convention

All exports are prefixed with `xace_` to avoid symbol collisions with
other native libraries in the engine process.

## Unity Integration

```csharp
const string DLL = "xace";   // Unity finds xace.dll / libxace.so / libxace.dylib

[DllImport(DLL)] static extern int xace_init(out IntPtr world, ulong seed, uint deltaSize);
[DllImport(DLL)] static extern int xace_load_cgs(IntPtr world, byte[] json, uint len);
[DllImport(DLL)] static extern int xace_tick(IntPtr world);
[DllImport(DLL)] static extern int xace_get_state_delta(IntPtr world, byte[] buf, ref uint size);
[DllImport(DLL)] static extern int xace_apply_input(IntPtr world, byte[] input, uint len);
[DllImport(DLL)] static extern int xace_shutdown(IntPtr world);
[DllImport(DLL)] static extern int xace_get_world_hash(IntPtr world, byte[] buf, uint len);
[DllImport(DLL)] static extern int xace_get_tick_number(IntPtr world, out ulong tick);
[DllImport(DLL)] static extern int xace_get_last_error(IntPtr world, byte[] buf, uint len);
[DllImport(DLL)] static extern uint xace_version();
```
*/

use super::error_codes::{XaceErrorCode, FFI_OK};
use super::ffi_transport::{load_cgs_json, FfiSimulation};
use super::handle_types::{as_mut, box_into_raw, raw_into_box, FfiWorldHandle, OpaqueWorld};

// ── Convenience macro ─────────────────────────────────────────────────────────

/// Wraps a block in catch_unwind. Every FFI function uses this.
macro_rules! ffi_guard {
    ($body:block) => {{
        let result = std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| $body));
        match result {
            Ok(code) => code,
            Err(_) => XaceErrorCode::Panic as i32,
        }
    }};
}

/// Null-checks a pointer and returns the given error code if null.
macro_rules! check_null {
    ($ptr:expr) => {
        if $ptr.is_null() {
            return XaceErrorCode::NullPointer as i32;
        }
    };
}

/// Gets a mutable reference to the world handle, null-checked.
///
/// # Safety
/// Caller guarantees `ptr` was returned by `xace_init` and not yet freed.
macro_rules! world {
    ($ptr:expr) => {{
        check_null!($ptr);
        // SAFETY: ptr is non-null, was returned by xace_init (Box::into_raw),
        // and has not been freed (xace_shutdown not yet called).
        unsafe { as_mut($ptr) }
    }};
}

// ── Lifecycle ─────────────────────────────────────────────────────────────────

/// Allocates a new XACE world. See xace.h for full documentation.
#[no_mangle]
pub extern "C" fn xace_init(
    out_world: *mut *mut OpaqueWorld,
    world_seed: u64,
    delta_buf_bytes: u32,
) -> i32 {
    ffi_guard!({
        check_null!(out_world);

        let delta_size = if delta_buf_bytes == 0 {
            4 * 1024 * 1024
        } else {
            delta_buf_bytes
        };
        let handle = FfiWorldHandle::new(world_seed, delta_size);
        let raw_ptr = box_into_raw(handle);

        // SAFETY: out_world is non-null (checked above).
        unsafe {
            *out_world = raw_ptr;
        }
        FFI_OK
    })
}

/// Loads CGS JSON into the world. See xace.h for full documentation.
#[no_mangle]
pub extern "C" fn xace_load_cgs(world: *mut OpaqueWorld, cgs_json: *const u8, cgs_len: u32) -> i32 {
    ffi_guard!({
        let w = world!(world);
        check_null!(cgs_json);

        if w.cgs_loaded {
            w.set_error("CGS already loaded. Create a new world to change the schema.");
            return XaceErrorCode::AlreadyInitialized as i32;
        }

        // SAFETY: cgs_json is non-null (checked) and cgs_len is the caller's byte count.
        let cgs_bytes = unsafe { std::slice::from_raw_parts(cgs_json, cgs_len as usize) };
        let cgs_str = match std::str::from_utf8(cgs_bytes) {
            Ok(s) => s,
            Err(e) => {
                w.set_error(format!("CGS JSON is not valid UTF-8: {}", e));
                return XaceErrorCode::CgsParseError as i32;
            }
        };

        match load_cgs_json(cgs_str) {
            Ok(schema_version) => {
                w.schema_version = schema_version;
                w.cgs_loaded = true;
                w.clear_error();
                FFI_OK
            }
            Err(msg) => {
                w.set_error(msg);
                XaceErrorCode::CgsParseError as i32
            }
        }
    })
}

/// Frees the world handle. See xace.h for full documentation.
#[no_mangle]
pub extern "C" fn xace_shutdown(world: *mut OpaqueWorld) -> i32 {
    ffi_guard!({
        check_null!(world);
        // SAFETY: world was returned by xace_init (Box::into_raw) and is non-null.
        // After this, the pointer is dangling — caller must not use it.
        let _boxed = unsafe { raw_into_box(world) };
        // Box drops here, running FfiWorldHandle's destructor
        FFI_OK
    })
}

// ── Simulation Loop ───────────────────────────────────────────────────────────

/// Enqueues input for the next tick. See xace.h for full documentation.
#[no_mangle]
pub extern "C" fn xace_apply_input(
    world: *mut OpaqueWorld,
    input_ptr: *const u8,
    input_len: u32,
) -> i32 {
    ffi_guard!({
        let w = world!(world);
        check_null!(input_ptr);

        if input_len == 0 {
            return FFI_OK; // empty input is valid — no-op
        }

        // SAFETY: input_ptr is non-null (checked), caller owns the buffer.
        let input_data = unsafe { std::slice::from_raw_parts(input_ptr, input_len as usize) };
        w.input_queue.push(input_data.to_vec());
        FFI_OK
    })
}

/// Advances simulation by one tick. See xace.h for full documentation.
#[no_mangle]
pub extern "C" fn xace_tick(world: *mut OpaqueWorld) -> i32 {
    ffi_guard!({
        let w = world!(world);

        match FfiSimulation::tick(w) {
            Ok(()) => FFI_OK,
            Err(XaceErrorCode::DeterminismViolation) => XaceErrorCode::DeterminismViolation as i32,
            Err(XaceErrorCode::NotInitialized) => XaceErrorCode::NotInitialized as i32,
            Err(e) => {
                w.set_error(format!("Tick error: {:?}", e));
                XaceErrorCode::TickError as i32
            }
        }
    })
}

/// Reads the state delta from the last tick. See xace.h for full documentation.
#[no_mangle]
pub extern "C" fn xace_get_state_delta(
    world: *mut OpaqueWorld,
    buffer: *mut u8,
    buffer_size: *mut u32,
) -> i32 {
    ffi_guard!({
        let w = world!(world);
        check_null!(buffer);
        check_null!(buffer_size);

        // SAFETY: buffer and buffer_size are non-null (checked above).
        let out_len = unsafe { *buffer_size } as usize;
        let out_buf = unsafe { std::slice::from_raw_parts_mut(buffer, out_len) };

        match w.delta_buffer.read(out_buf) {
            Ok(written) => {
                // SAFETY: buffer_size is non-null.
                unsafe {
                    *buffer_size = written as u32;
                }
                FFI_OK
            }
            Err(super::shared_buffer::BufferError::TooSmall { needed, .. }) => {
                // Tell caller how large the buffer needs to be
                unsafe {
                    *buffer_size = needed as u32;
                }
                XaceErrorCode::BufferTooSmall as i32
            }
            Err(super::shared_buffer::BufferError::Empty) => {
                unsafe {
                    *buffer_size = 0;
                }
                FFI_OK // no-op tick or first tick: empty delta is valid
            }
        }
    })
}

// ── Diagnostics ───────────────────────────────────────────────────────────────

/// Returns the current world hash as a hex string. See xace.h.
#[no_mangle]
pub extern "C" fn xace_get_world_hash(
    world: *mut OpaqueWorld,
    out_hash: *mut u8,
    out_len: u32,
) -> i32 {
    ffi_guard!({
        let w = world!(world);
        check_null!(out_hash);

        let hash_bytes = w.world_hash.as_bytes();
        let copy_len = (out_len as usize).saturating_sub(1).min(hash_bytes.len());

        if copy_len == 0 {
            return XaceErrorCode::BufferTooSmall as i32;
        }

        // SAFETY: out_hash is non-null (checked), caller allocated out_len bytes.
        unsafe {
            std::ptr::copy_nonoverlapping(hash_bytes.as_ptr(), out_hash, copy_len);
            *out_hash.add(copy_len) = 0; // null-terminate
        }
        FFI_OK
    })
}

/// Returns the current simulation tick count. See xace.h.
#[no_mangle]
pub extern "C" fn xace_get_tick_number(world: *mut OpaqueWorld, out_tick: *mut u64) -> i32 {
    ffi_guard!({
        let w = world!(world);
        check_null!(out_tick);
        // SAFETY: out_tick is non-null.
        unsafe {
            *out_tick = w.tick_number;
        }
        FFI_OK
    })
}

/// Returns the last error message as a string. See xace.h.
#[no_mangle]
pub extern "C" fn xace_get_last_error(
    world: *mut OpaqueWorld,
    buffer: *mut u8,
    buffer_size: u32,
) -> i32 {
    ffi_guard!({
        let w = world!(world);
        check_null!(buffer);

        let msg = if w.last_error.is_empty() {
            "ok"
        } else {
            &w.last_error
        };
        let bytes = msg.as_bytes();
        let copy = (buffer_size as usize).saturating_sub(1).min(bytes.len());

        // SAFETY: buffer is non-null (checked), caller allocated buffer_size bytes.
        unsafe {
            std::ptr::copy_nonoverlapping(bytes.as_ptr(), buffer, copy);
            *buffer.add(copy) = 0;
        }
        FFI_OK
    })
}

/// Returns the XACE API version. Thread-safe. No world handle required.
#[no_mangle]
pub extern "C" fn xace_version() -> u32 {
    1u32
}
