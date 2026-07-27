/*!
# shared_buffer.rs — Shared Delta Buffer

Pre-allocated byte buffer for passing state deltas from XACE to the engine.

## Access Pattern (single-tick contract)

```text
engine calls:   xace_apply_input(...)
engine calls:   xace_tick()          ← XACE writes delta to SharedDeltaBuffer
engine calls:   xace_get_state_delta(out_buf, &out_len)   ← copies from SharedDeltaBuffer
engine reads:   out_buf[..out_len]  ← component deltas for this tick
```

This is strictly sequential. There is no concurrent access between tick and
get_state_delta — Unity's FixedUpdate runs on one thread and calls them in order.

## Zero Allocation on Hot Path

The buffer is allocated once in `xace_init()` (`delta_buf_bytes` parameter).
`write()` and `read()` never allocate. If the delta doesn't fit, `write()`
returns `BufferError::TooSmall` rather than growing the buffer.

This is a deliberate design choice for game engine use: unpredictable allocations
inside FixedUpdate cause GC pressure and frame spikes. Size the buffer generously
at startup (4 MB default covers all practical game state deltas at 60 Hz).
*/

use std::fmt;

// ── Buffer Error ──────────────────────────────────────────────────────────────

#[derive(Debug)]
pub enum BufferError {
    TooSmall { needed: usize, capacity: usize },
    Empty,
}

impl fmt::Display for BufferError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::TooSmall { needed, capacity } => write!(
                f,
                "Buffer too small: need {} bytes, capacity is {} bytes. \
                 Increase delta_buffer_bytes in engine_config.yaml.",
                needed, capacity
            ),
            Self::Empty => write!(f, "No delta available — call xace_tick() first."),
        }
    }
}

// ── Shared Delta Buffer ───────────────────────────────────────────────────────

/// Pre-allocated, fixed-capacity buffer for XACE → engine state deltas.
///
/// Not thread-safe. Designed for single-threaded FixedUpdate use.
pub struct SharedDeltaBuffer {
    inner: Vec<u8>,  // allocated once, never resized
    fill_len: usize, // bytes written in the last tick; 0 = no data yet
}

impl SharedDeltaBuffer {
    /// Allocates a new buffer with `capacity` bytes.
    ///
    /// # Panics
    /// Panics if `capacity == 0`.
    pub fn new(capacity: usize) -> Self {
        assert!(capacity > 0, "SharedDeltaBuffer capacity must be > 0");
        let mut inner = Vec::with_capacity(capacity);
        inner.resize(capacity, 0u8); // pre-commit the memory (no page faults later)
        Self { inner, fill_len: 0 }
    }

    /// Writes `data` into the buffer, replacing any previous tick's data.
    ///
    /// Returns `BufferError::TooSmall` if `data.len() > capacity`.
    /// On error, the buffer is left in its previous state.
    pub fn write(&mut self, data: &[u8]) -> Result<(), BufferError> {
        if data.len() > self.inner.capacity() {
            return Err(BufferError::TooSmall {
                needed: data.len(),
                capacity: self.inner.capacity(),
            });
        }
        // Safety: inner.len() == capacity (set at construction and never shrunk)
        self.inner[..data.len()].copy_from_slice(data);
        self.fill_len = data.len();
        Ok(())
    }

    /// Reads the last tick's delta into `out_buffer`.
    ///
    /// Returns the number of bytes written.
    ///
    /// Returns `BufferError::TooSmall` if `out_buffer.len() < self.fill_len`.
    /// In this case, `out_buffer` is unchanged and `fill_len()` tells the caller
    /// the minimum buffer size needed (matching `xace_get_state_delta` semantics).
    ///
    /// Returns `BufferError::Empty` if no tick has been executed yet.
    pub fn read(&self, out_buffer: &mut [u8]) -> Result<usize, BufferError> {
        if self.fill_len == 0 {
            return Err(BufferError::Empty);
        }
        if out_buffer.len() < self.fill_len {
            return Err(BufferError::TooSmall {
                needed: self.fill_len,
                capacity: out_buffer.len(),
            });
        }
        out_buffer[..self.fill_len].copy_from_slice(&self.inner[..self.fill_len]);
        Ok(self.fill_len)
    }

    /// Returns the number of valid bytes from the last tick.
    /// Zero means no tick has been executed yet.
    pub fn fill_len(&self) -> usize {
        self.fill_len
    }

    /// Returns the maximum capacity.
    pub fn capacity(&self) -> usize {
        self.inner.capacity()
    }

    /// Clears the buffer. Next read will return `BufferError::Empty`.
    pub fn clear(&mut self) {
        self.fill_len = 0;
    }
}

impl fmt::Debug for SharedDeltaBuffer {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(
            f,
            "SharedDeltaBuffer(fill={}/{} bytes)",
            self.fill_len,
            self.inner.capacity()
        )
    }
}

// ── Input Queue ───────────────────────────────────────────────────────────────

/// Queue of input bytes pending for the next tick.
///
/// The engine pushes input via xace_apply_input(); the tick drains it.
/// Multiple inputs per tick are supported (e.g. multiplayer game with several players).
pub struct InputQueue {
    pending: Vec<Vec<u8>>,
}

impl InputQueue {
    pub fn new() -> Self {
        Self {
            pending: Vec::with_capacity(8),
        }
    }

    /// Enqueues one input packet. Called by xace_apply_input().
    pub fn push(&mut self, data: Vec<u8>) {
        self.pending.push(data);
    }

    /// Drains all pending inputs. Called at the start of xace_tick().
    pub fn drain(&mut self) -> Vec<Vec<u8>> {
        std::mem::take(&mut self.pending)
    }

    pub fn len(&self) -> usize {
        self.pending.len()
    }
    pub fn is_empty(&self) -> bool {
        self.pending.is_empty()
    }
}

impl Default for InputQueue {
    fn default() -> Self {
        Self::new()
    }
}
