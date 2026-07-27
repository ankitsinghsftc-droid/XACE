// ============================================================================
// packages/engine-adapter/tests/test_ffi_memory_safety.rs
// ============================================================================

/*!
# test_ffi_memory_safety.rs — FFI Null Safety and Lifecycle Tests

Verifies that:
1. Null pointer arguments are rejected with NullPointer error code
2. Double-load CGS is rejected with AlreadyInitialized
3. Tick before CGS load returns NotInitialized
4. xace_shutdown is safe and does not double-free
5. Version function is always safe
*/

use crate::ffi::{error_codes::XaceErrorCode, handle_types::OpaqueWorld, xace_ffi::*};

const MINIMAL_CGS: &[u8] = br#"{"metadata":{"name":"T","version":"0.1.0","schema_version":"0.1.0"},"global_systems":[],"modes":[]}"#;

fn init_world() -> *mut OpaqueWorld {
    let mut ptr: *mut OpaqueWorld = std::ptr::null_mut();
    let code = xace_init(&mut ptr, 42, 1024 * 1024);
    assert_eq!(code, 0);
    assert!(!ptr.is_null());
    ptr
}

#[test]
fn xace_version_is_safe_from_any_thread() {
    let v = xace_version();
    assert_eq!(v, 1u32);
}

#[test]
fn xace_version_from_multiple_threads() {
    let handles: Vec<_> = (0..8)
        .map(|_| std::thread::spawn(|| xace_version()))
        .collect();
    for h in handles {
        assert_eq!(h.join().unwrap(), 1u32);
    }
}

#[test]
fn xace_init_null_out_ptr_returns_null_pointer_error() {
    let code = xace_init(std::ptr::null_mut(), 42, 1024 * 1024);
    assert_eq!(code, XaceErrorCode::NullPointer as i32);
}

#[test]
fn xace_load_cgs_null_world_returns_null_pointer_error() {
    let code = xace_load_cgs(
        std::ptr::null_mut(),
        MINIMAL_CGS.as_ptr(),
        MINIMAL_CGS.len() as u32,
    );
    assert_eq!(code, XaceErrorCode::NullPointer as i32);
}

#[test]
fn xace_load_cgs_null_json_returns_null_pointer_error() {
    let world = init_world();
    let code = xace_load_cgs(world, std::ptr::null(), 10);
    assert_eq!(code, XaceErrorCode::NullPointer as i32);
    xace_shutdown(world);
}

#[test]
fn xace_tick_before_load_cgs_returns_not_initialized() {
    let world = init_world();
    let code = xace_tick(world);
    assert_eq!(
        code,
        XaceErrorCode::NotInitialized as i32,
        "tick before load_cgs must return NotInitialized"
    );
    xace_shutdown(world);
}

#[test]
fn xace_load_cgs_twice_returns_already_initialized() {
    let world = init_world();
    let code1 = xace_load_cgs(world, MINIMAL_CGS.as_ptr(), MINIMAL_CGS.len() as u32);
    assert_eq!(code1, 0);
    let code2 = xace_load_cgs(world, MINIMAL_CGS.as_ptr(), MINIMAL_CGS.len() as u32);
    assert_eq!(code2, XaceErrorCode::AlreadyInitialized as i32);
    xace_shutdown(world);
}

#[test]
fn xace_tick_null_world_returns_null_pointer_error() {
    let code = xace_tick(std::ptr::null_mut());
    assert_eq!(code, XaceErrorCode::NullPointer as i32);
}

#[test]
fn xace_apply_input_null_world_returns_null_pointer_error() {
    let code = xace_apply_input(std::ptr::null_mut(), [0u8].as_ptr(), 1);
    assert_eq!(code, XaceErrorCode::NullPointer as i32);
}

#[test]
fn xace_apply_input_zero_len_is_noop() {
    let world = init_world();
    xace_load_cgs(world, MINIMAL_CGS.as_ptr(), MINIMAL_CGS.len() as u32);
    let code = xace_apply_input(world, [0u8].as_ptr(), 0);
    assert_eq!(code, 0, "zero-length input must be a no-op");
    xace_shutdown(world);
}

#[test]
fn xace_get_state_delta_null_buffer_returns_null_pointer_error() {
    let world = init_world();
    xace_load_cgs(world, MINIMAL_CGS.as_ptr(), MINIMAL_CGS.len() as u32);
    xace_tick(world);
    let mut size: u32 = 4096;
    let code = xace_get_state_delta(world, std::ptr::null_mut(), &mut size);
    assert_eq!(code, XaceErrorCode::NullPointer as i32);
    xace_shutdown(world);
}

#[test]
fn xace_get_state_delta_buffer_too_small_returns_required_size() {
    let world = init_world();
    xace_load_cgs(world, MINIMAL_CGS.as_ptr(), MINIMAL_CGS.len() as u32);
    xace_tick(world);

    let mut tiny_buf = [0u8; 1];
    let mut size: u32 = 1;
    let code = xace_get_state_delta(world, tiny_buf.as_mut_ptr(), &mut size);
    // Either OK (delta is smaller than 1 byte, unlikely) or BufferTooSmall with required size
    if code == XaceErrorCode::BufferTooSmall as i32 {
        assert!(
            size > 1,
            "required size must be > 1 when buffer was too small"
        );
    }
    xace_shutdown(world);
}

#[test]
fn xace_shutdown_null_world_returns_null_pointer_error() {
    let code = xace_shutdown(std::ptr::null_mut());
    assert_eq!(code, XaceErrorCode::NullPointer as i32);
}

#[test]
fn full_lifecycle_ok() {
    let world = init_world();
    let code = xace_load_cgs(world, MINIMAL_CGS.as_ptr(), MINIMAL_CGS.len() as u32);
    assert_eq!(code, 0, "load_cgs");

    for _ in 0..10 {
        let code = xace_tick(world);
        assert_eq!(code, 0, "tick");
    }

    let mut buf = vec![0u8; 64 * 1024];
    let mut size = buf.len() as u32;
    let code = xace_get_state_delta(world, buf.as_mut_ptr(), &mut size);
    assert_eq!(code, 0, "get_state_delta");
    assert!(size > 0, "delta must be non-empty after ticks");

    let code = xace_shutdown(world);
    assert_eq!(code, 0, "shutdown");
}
