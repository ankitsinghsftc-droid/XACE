// ============================================================================
// packages/engine-adapter/src/ffi/error_codes.rs
// ============================================================================
/*!
# error_codes.rs — FFI Error Codes
 
C-compatible error code enum. Every exported FFI function returns one of these
as an `i32`. Negative values are errors; zero is success; positive values are
reserved for future use.
 
## Critical: catch_unwind Requirement
 
Every `pub extern "C"` function MUST wrap its body in `std::panic::catch_unwind`.
A Rust panic crossing FFI is undefined behaviour — it will:
- Segfault the Unity process on Windows (MSVC unwind model incompatible)
- Corrupt the C++ stack on Unreal
- Produce undefined results on any platform
 
The pattern (mandatory in every exported function):
 
```rust
#[no_mangle]
pub extern "C" fn xace_tick(world: *mut OpaqueWorld) -> i32 {
    let result = std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| {
        // ... safe body ...
        XaceErrorCode::Ok as i32
    }));
    match result {
        Ok(code) => code,
        Err(_)   => XaceErrorCode::Panic as i32,
    }
}
```
*/
 
/// Return codes for all XACE FFI functions.
///
/// All XACE exported functions return `XaceErrorCode` (as `i32`).
/// Callers MUST check for `Ok` (0) before reading output parameters.
#[repr(i32)]
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum XaceErrorCode {
    /// Operation succeeded.
    Ok                   =  0,
    /// A pointer argument (world or buffer) is null.
    NullPointer          = -1,
    /// World pointer does not refer to a valid XACE world.
    InvalidHandle        = -2,
    /// CGS JSON is malformed or fails schema validation.
    CgsParseError        = -3,
    /// A runtime error occurred during xace_tick().
    TickError            = -4,
    /// Caller-provided buffer is too small for the requested data.
    BufferTooSmall       = -5,
    /// A filesystem or serialization error occurred.
    IoError              = -6,
    /// Operation called before xace_load_cgs().
    NotInitialized       = -7,
    /// xace_load_cgs() was called more than once on the same world.
    AlreadyInitialized   = -8,
    /// A determinism rule (D1-D15) was violated.
    /// The world is halted — do not call xace_tick() again.
    DeterminismViolation = -9,
    /// A Rust panic was caught by catch_unwind.
    /// This indicates an XACE bug — file a report with the crash dump.
    Panic                = -99,
}
 
impl XaceErrorCode {
    pub fn is_ok(self) -> bool   { self == Self::Ok }
    pub fn as_i32(self) -> i32  { self as i32 }
}
 
/// Returns `XaceErrorCode::Ok` as a raw i32. Used at the end of FFI functions.
pub const FFI_OK: i32 = XaceErrorCode::Ok as i32;