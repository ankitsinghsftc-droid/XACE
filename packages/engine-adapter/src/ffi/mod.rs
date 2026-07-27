// ============================================================================
// packages/engine-adapter/src/ffi/mod.rs
// ============================================================================
/*!
# ffi/mod.rs — FFI Module Declarations

Sub-modules of the XACE C ABI layer.

## Module Organisation

```text
ffi/
├── mod.rs            (this file)
├── error_codes.rs    XaceErrorCode enum
├── handle_types.rs   OpaqueWorld, FfiWorldHandle, Box<→>raw conversion
├── shared_buffer.rs  Pre-allocated delta buffer + input queue
├── ffi_transport.rs  Simulation core + IEngineAdapter implementation
└── xace_ffi.rs       #[no_mangle] extern "C" exports
```

## Safety Invariants (MUST MAINTAIN)

1. Every `pub extern "C"` function wraps its body in `catch_unwind`.
2. No Rust panic escapes an FFI boundary.
3. `OpaqueWorld*` is always a valid `Box<FfiWorldHandle>` or null.
4. Callers never construct `OpaqueWorld` directly.
5. `xace_shutdown()` is the only way to free an `OpaqueWorld*`.
6. All pointer arguments are null-checked before use.
*/

pub mod error_codes;
pub mod ffi_transport;
#[path = "handle_type.rs"]
pub mod handle_types;
pub mod shared_buffer;
pub mod xace_ffi;

#[cfg(test)]
#[path = "tests/test_ffi_determinism.rs"]
mod test_ffi_determinism;
#[cfg(test)]
#[path = "tests/test_ffi_memory.rs"]
mod test_ffi_memory;

// Re-export the most-used types at the ffi:: level
pub use error_codes::{XaceErrorCode, FFI_OK};
pub use handle_types::{FfiWorldHandle, OpaqueWorld};
pub use xace_ffi::*;
