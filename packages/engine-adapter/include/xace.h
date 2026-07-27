#include <cstdarg>
#include <cstdint>
#include <cstdlib>
#include <ostream>
#include <new>



constexpr static const uintptr_t FRAME_HEADER_SIZE = 4;

constexpr static const uintptr_t MAX_MESSAGE_SIZE = ((16 * 1024) * 1024);

constexpr static const uint32_t XACE_WIRE_MAGIC = 1480672069;

constexpr static const uintptr_t DEFAULT_RING_SIZE = ((4 * 1024) * 1024);

/// Opaque world type. Never instantiated — used only as a pointer target.
///
/// `*mut OpaqueWorld` in the C API corresponds to `*mut FfiWorldHandle` internally.
/// The zero-size array ensures C callers cannot create instances.
struct OpaqueWorld {
  uint8_t _private[0];
};

extern "C" {

/// Allocates a new XACE world. See xace.h for full documentation.
int32_t xace_init(OpaqueWorld **out_world, uint64_t world_seed, uint32_t delta_buf_bytes);

/// Loads CGS JSON into the world. See xace.h for full documentation.
int32_t xace_load_cgs(OpaqueWorld *world, const uint8_t *cgs_json, uint32_t cgs_len);

/// Frees the world handle. See xace.h for full documentation.
int32_t xace_shutdown(OpaqueWorld *world);

/// Enqueues input for the next tick. See xace.h for full documentation.
int32_t xace_apply_input(OpaqueWorld *world, const uint8_t *input_ptr, uint32_t input_len);

/// Advances simulation by one tick. See xace.h for full documentation.
int32_t xace_tick(OpaqueWorld *world);

/// Reads the state delta from the last tick. See xace.h for full documentation.
int32_t xace_get_state_delta(OpaqueWorld *world, uint8_t *buffer, uint32_t *buffer_size);

/// Returns the current world hash as a hex string. See xace.h.
int32_t xace_get_world_hash(OpaqueWorld *world, uint8_t *out_hash, uint32_t out_len);

/// Returns the current simulation tick count. See xace.h.
int32_t xace_get_tick_number(OpaqueWorld *world, uint64_t *out_tick);

/// Returns the last error message as a string. See xace.h.
int32_t xace_get_last_error(OpaqueWorld *world, uint8_t *buffer, uint32_t buffer_size);

/// Returns the XACE API version. Thread-safe. No world handle required.
uint32_t xace_version();

}  // extern "C"
