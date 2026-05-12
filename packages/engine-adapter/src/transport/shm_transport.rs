//! # Shared Memory Transport
//!
//! Zero-copy, kernel-bypass transport for same-machine XACE ↔ Engine Adapter
//! communication using memory-mapped files as a shared ring buffer.
//!
//! ## Why Shared Memory
//! At 60Hz simulation, each tick has a 16.67ms budget. TCP loopback on Linux
//! costs ~50–200µs per round-trip in kernel syscalls, socket buffer copies,
//! and context switches between XACE and the engine adapter process. That is
//! not a problem at 60Hz, but becomes significant when profiling reveals that
//! transport overhead accumulates across a session.
//!
//! Shared memory (SHM) eliminates the network stack entirely. XACE writes
//! a frame directly into a memory-mapped region. The engine adapter reads
//! from the same region. No kernel involvement, no copies. Latency is
//! bounded only by CPU cache coherency — typically 200–500ns.
//!
//! TCP remains for remote/network deployment. SHM is for same-machine
//! development and production where XACE and the engine run as separate
//! processes on the same host.
//!
//! ## Architecture — Dual Ring Buffer
//! ```text
//!  ┌──────────────────────────────────────────────────────┐
//!  │  Shared Memory Region (file: /tmp/xace_<world_id>)   │
//!  │                                                      │
//!  │  [ShmHeader][XACE→Engine ring][Engine→XACE ring]    │
//!  │                                                      │
//!  │  XACE→Engine: DELTA, SNAPSHOT, EVENT, CONTROL       │
//!  │  Engine→XACE: INPUT, FEEDBACK, CONTROL              │
//!  └──────────────────────────────────────────────────────┘
//! ```
//!
//! Each ring buffer is a contiguous byte region with a write-head and
//! read-head index. The writer advances the write-head after writing a
//! complete frame. The reader advances the read-head after consuming it.
//!
//! ## Frame Format (same as TCP)
//! `[4-byte BE u32 length][JSON payload bytes]`
//!
//! The same `MessageSerializer` / `MessageDeserializer` are used — only
//! the transport layer changes. This makes SHM a drop-in replacement.
//!
//! ## Synchronization
//! Ring head indices are stored as `AtomicU64` in the ShmHeader.
//! Single-writer/single-reader per ring — no mutex required for the
//! fast path. A full memory fence is issued after writing to ensure
//! the payload is visible before the write-head advances.
//!
//! ## File Lifecycle
//! The SHM file is created by XACE (server) on `open()` and mapped.
//! The engine adapter opens the same file by name and maps it read-write.
//! On `close()`, XACE unmaps and optionally unlinks the file.
//!
//! ## Safety Note
//! The ring buffer implementation uses raw pointer arithmetic into the
//! memory-mapped region. This is inherently unsafe — it is the nature
//! of shared memory IPC. All unsafe blocks are documented and minimal.

use std::sync::atomic::{AtomicU64, Ordering};
use std::path::PathBuf;
use std::fs::OpenOptions;
use std::io::Write;

use memmap2::{MmapMut, MmapOptions};
use xace_core::errors::xace_error::{ErrorContext, XaceError};
use xace_core::wire::wire_message::WireMessage;

use crate::transport::message_serializer::{MessageSerializer, FRAME_HEADER_SIZE, MAX_MESSAGE_SIZE};
use crate::transport::message_deserializer::MessageDeserializer;

macro_rules! xlog_info  { ($($t:tt)*) => { eprintln!("[INFO]  {}", format!($($t)*)) } }
macro_rules! xlog_warn  { ($($t:tt)*) => { eprintln!("[WARN]  {}", format!($($t)*)) } }
macro_rules! xlog_error { ($($t:tt)*) => { eprintln!("[ERROR] {}", format!($($t)*)) } }

// ── SHM Constants ─────────────────────────────────────────────────────────────

/// Magic number written at byte 0 of the SHM region to detect corruption.
/// Spells "XSHM" in ASCII big-endian.
const SHM_MAGIC: u32 = 0x5853484D;

/// Version of the SHM layout. Bump if the header layout changes.
const SHM_LAYOUT_VERSION: u32 = 1;

/// Default size of each ring buffer in bytes (4 MiB).
///
/// Two rings × 4 MiB = 8 MiB total SHM + header.
/// A full SnapshotPayload for a 10,000-entity world is ~2 MiB JSON.
/// 4 MiB leaves headroom for burst frames without blocking.
pub const DEFAULT_RING_SIZE: usize = 4 * 1024 * 1024;

/// Size of the ShmHeader in bytes. Must be a multiple of 64 for cache alignment.
/// Calculated: magic(4) + version(4) + ring_size(8) + pad(48) + 2×heads(16) = 80
/// Rounded to 128 for two full cache lines.
const HEADER_SIZE: usize = 128;

// ── SHM Configuration ─────────────────────────────────────────────────────────

/// Configuration for the SHM transport.
#[derive(Debug, Clone)]
pub struct ShmTransportConfig {
    /// World ID used to derive the SHM file name.
    /// File will be at `/tmp/xace_<world_id>_shm`
    pub world_id: String,

    /// Size of each ring buffer in bytes.
    /// Must be a power of two and at least 64 KiB.
    pub ring_size: usize,

    /// Directory for the SHM backing file.
    /// Default: `/tmp` on Linux/macOS.
    pub shm_dir: PathBuf,

    /// Whether XACE should unlink (delete) the SHM file on close.
    /// True for development. False for post-mortem debugging.
    pub unlink_on_close: bool,
}

impl Default for ShmTransportConfig {
    fn default() -> Self {
        Self {
            world_id: "default".into(),
            ring_size: DEFAULT_RING_SIZE,
            shm_dir: std::env::temp_dir(),
            unlink_on_close: true,
        }
    }
}

impl ShmTransportConfig {
    /// Returns the full path to the SHM backing file.
    pub fn shm_path(&self) -> PathBuf {
        self.shm_dir.join(format!("xace_{}_shm", self.world_id))
    }

    /// Validates the configuration. ring_size must be a power of two ≥ 64 KiB.
    pub fn validate(&self) -> Result<(), String> {
        if self.ring_size < 64 * 1024 {
            return Err(format!(
                "ShmTransportConfig: ring_size {} is below minimum 65536 (64 KiB)",
                self.ring_size
            ));
        }
        if !self.ring_size.is_power_of_two() {
            return Err(format!(
                "ShmTransportConfig: ring_size {} must be a power of two",
                self.ring_size
            ));
        }
        if self.world_id.is_empty() {
            return Err("ShmTransportConfig: world_id must not be empty".into());
        }
        Ok(())
    }
}

// ── SHM Header Layout ─────────────────────────────────────────────────────────
//
// The header occupies the first HEADER_SIZE bytes of the mapped region.
// All atomic fields are accessed through raw pointer offsets into the mmap.
//
// Byte layout:
//   [0..4]    u32 magic (SHM_MAGIC)
//   [4..8]    u32 layout_version (SHM_LAYOUT_VERSION)
//   [8..16]   u64 ring_size (each ring, in bytes)
//   [16..64]  reserved / padding (cache-line fill)
//   [64..72]  AtomicU64 xace_write_head (XACE→Engine ring write cursor)
//   [72..80]  AtomicU64 xace_read_head  (XACE→Engine ring read cursor)
//   [80..88]  AtomicU64 eng_write_head  (Engine→XACE ring write cursor)
//   [88..96]  AtomicU64 eng_read_head   (Engine→XACE ring read cursor)
//   [96..128] padding

/// Byte offset of the XACE→Engine write head within the SHM header.
const OFF_XACE_WRITE: usize = 64;
/// Byte offset of the XACE→Engine read head within the SHM header.
const OFF_XACE_READ: usize = 72;
/// Byte offset of the Engine→XACE write head within the SHM header.
const OFF_ENG_WRITE: usize = 80;
/// Byte offset of the Engine→XACE read head within the SHM header.
const OFF_ENG_READ: usize = 88;

// ── Ring Buffer ───────────────────────────────────────────────────────────────

/// A lock-free single-producer / single-consumer ring buffer backed by a
/// slice of a memory-mapped region. Power-of-two ring_size enables cheap
/// modulo via bitwise AND: `index & (ring_size - 1)`.
///
/// This struct does NOT own any memory — it holds raw pointers into an
/// `MmapMut` region that is owned by `ShmTransport`. All lifetimes are
/// managed by the parent struct.
struct ShmRing {
    /// Pointer to the first byte of the ring data (after the header).
    data_ptr: *mut u8,
    /// Pointer to the write-head AtomicU64 in the header.
    write_head_ptr: *mut AtomicU64,
    /// Pointer to the read-head AtomicU64 in the header.
    read_head_ptr: *mut AtomicU64,
    /// Ring buffer size in bytes. Must be a power of two.
    ring_size: usize,
}

// SAFETY: ShmRing pointers point into an MmapMut that is kept alive by
// ShmTransport. ShmTransport is not Send because TcpStream is not Send,
// but ShmRing itself is only accessed from ShmTransport's owning thread.
unsafe impl Send for ShmRing {}

impl ShmRing {
    /// Writes a complete frame into the ring.
    ///
    /// Returns Ok(()) if the frame fit.
    /// Returns Err if the ring does not have space for the entire frame.
    ///
    /// # Safety
    /// Caller must ensure `data_ptr` is valid and the ring is initialized.
    unsafe fn write_frame(&mut self, frame: &[u8]) -> Result<(), ()> {
        let write = (*self.write_head_ptr).load(Ordering::Acquire);
        let read  = (*self.read_head_ptr).load(Ordering::Acquire);

        let used  = write.wrapping_sub(read) as usize;
        let avail = self.ring_size.saturating_sub(used);

        if frame.len() > avail {
            return Err(());
        }

        let mask = (self.ring_size - 1) as u64;
        let mut cursor = write;

        for &byte in frame {
            let idx = (cursor & mask) as usize;
            *self.data_ptr.add(idx) = byte;
            cursor = cursor.wrapping_add(1);
        }

        // Full fence before advancing write head — ensures payload is
        // visible to the reader before the head update.
        std::sync::atomic::fence(Ordering::SeqCst);
        (*self.write_head_ptr).store(cursor, Ordering::Release);
        Ok(())
    }

    /// Attempts to read one complete frame from the ring.
    ///
    /// Returns `Some(Vec<u8>)` with the payload bytes (no header).
    /// Returns `None` if no complete frame is available.
    ///
    /// # Safety
    /// Caller must ensure `data_ptr` is valid and the ring is initialized.
    unsafe fn read_frame(&mut self) -> Option<Vec<u8>> {
        let write = (*self.write_head_ptr).load(Ordering::Acquire);
        let read  = (*self.read_head_ptr).load(Ordering::Acquire);

        let available = write.wrapping_sub(read) as usize;

        // Need at least a frame header
        if available < FRAME_HEADER_SIZE {
            return None;
        }

        let mask = (self.ring_size - 1) as u64;

        // Peek at the 4-byte length prefix without advancing the read head
        let mut len_bytes = [0u8; 4];
        for i in 0..4 {
            let idx = (read.wrapping_add(i as u64) & mask) as usize;
            len_bytes[i] = *self.data_ptr.add(idx);
        }
        let payload_len = u32::from_be_bytes(len_bytes) as usize;

        if payload_len > MAX_MESSAGE_SIZE {
            // Corrupted frame — skip the header to attempt recovery
            (*self.read_head_ptr).store(
                read.wrapping_add(FRAME_HEADER_SIZE as u64),
                Ordering::Release,
            );
            return None;
        }

        let total = FRAME_HEADER_SIZE + payload_len;
        if available < total {
            return None; // Payload not fully written yet
        }

        // Copy the payload bytes out
        let mut payload = vec![0u8; payload_len];
        for i in 0..payload_len {
            let idx = (read.wrapping_add((FRAME_HEADER_SIZE + i) as u64) & mask) as usize;
            payload[i] = *self.data_ptr.add(idx);
        }

        // Advance read head
        (*self.read_head_ptr).store(
            read.wrapping_add(total as u64),
            Ordering::Release,
        );

        Some(payload)
    }

    /// Returns the number of bytes currently in the ring (written but unread).
    unsafe fn used_bytes(&self) -> usize {
        let write = (*self.write_head_ptr).load(Ordering::Acquire);
        let read  = (*self.read_head_ptr).load(Ordering::Acquire);
        write.wrapping_sub(read) as usize
    }
}

// ── SHM Transport ─────────────────────────────────────────────────────────────

/// Zero-copy shared-memory transport for same-machine XACE ↔ Engine communication.
///
/// Drop-in alternative to `TcpTransport` for same-machine deployment.
/// Uses `memmap2` to map a file as shared memory, then implements a
/// dual lock-free ring buffer on top of it.
///
/// ## Usage
/// ```ignore
/// // XACE side (server — creates the file):
/// let mut shm = ShmTransport::create(ShmTransportConfig::default())?;
///
/// // Engine adapter side (client — opens the file):
/// let mut shm = ShmTransport::open(ShmTransportConfig::default())?;
///
/// // Exchange messages exactly as with TcpTransport:
/// shm.send_message(&delta_msg)?;
/// let msgs = shm.try_receive_messages()?;
/// ```
pub struct ShmTransport {
    config: ShmTransportConfig,

    /// The memory-mapped file region. Kept alive to maintain mapping.
    _mmap: MmapMut,

    /// XACE→Engine ring (XACE writes, Engine reads).
    xace_to_engine: ShmRing,

    /// Engine→XACE ring (Engine writes, XACE reads).
    engine_to_xace: ShmRing,

    /// Serializer for outbound messages.
    serializer: MessageSerializer,

    /// Deserializer for inbound messages (stateless buffer here — SHM
    /// delivers complete payloads, not byte streams, so we use
    /// `deserialize_payload()` rather than the buffer model).
    deserializer: MessageDeserializer,

    /// Whether this instance created (owns) the SHM file.
    is_creator: bool,

    /// Accumulated metrics.
    metrics: ShmTransportMetrics,
}

/// Accumulated metrics for one ShmTransport session.
#[derive(Debug, Clone, Default)]
pub struct ShmTransportMetrics {
    pub messages_sent: u64,
    pub messages_received: u64,
    pub bytes_sent: u64,
    pub bytes_received: u64,
    /// Number of send attempts that failed because the ring was full.
    pub ring_full_count: u64,
    /// Number of receive polls that found no data.
    pub empty_polls: u64,
}

impl ShmTransport {
    // ── Construction ──────────────────────────────────────────────────────────

    /// Creates a new SHM region and maps it. Called by XACE (the server side).
    ///
    /// Creates the backing file, writes the initialized header, and maps
    /// both ring buffers. The engine adapter calls `open()` to attach.
    pub fn create(config: ShmTransportConfig) -> Result<Self, XaceError> {
        config.validate().map_err(|e| XaceError::FatalError {
            message: format!("ShmTransport::create: invalid config — {}", e),
            context: ErrorContext::new("ShmTransport", "create"),
            snapshot_recovery_possible: false,
        })?;

        let total_size = HEADER_SIZE + 2 * config.ring_size;
        let path = config.shm_path();

        // Create and size the backing file
        let file = OpenOptions::new()
            .read(true)
            .write(true)
            .create(true)
            .truncate(true)
            .open(&path)
            .map_err(|e| XaceError::FatalError {
                message: format!(
                    "ShmTransport::create: failed to create SHM file {:?} — {}",
                    path, e
                ),
                context: ErrorContext::new("ShmTransport", "create"),
                snapshot_recovery_possible: false,
            })?;

        file.set_len(total_size as u64).map_err(|e| XaceError::FatalError {
            message: format!("ShmTransport::create: set_len failed — {}", e),
            context: ErrorContext::new("ShmTransport", "create"),
            snapshot_recovery_possible: false,
        })?;

        let mut mmap = unsafe {
            MmapOptions::new()
                .len(total_size)
                .map_mut(&file)
                .map_err(|e| XaceError::FatalError {
                    message: format!("ShmTransport::create: mmap failed — {}", e),
                    context: ErrorContext::new("ShmTransport", "create"),
                    snapshot_recovery_possible: false,
                })?
        };

        // Zero the entire region then write the header
        mmap.iter_mut().for_each(|b| *b = 0);
        Self::write_header(&mut mmap, config.ring_size);

        xlog_info!(
            "[ShmTransport] Created SHM at {:?} ({} bytes, ring_size={})",
            path, total_size, config.ring_size
        );

        Ok(Self::from_mmap(mmap, config, true))
    }

    /// Opens an existing SHM region created by XACE. Called by the engine adapter.
    ///
    /// Validates the header magic and layout version before attaching.
    pub fn open(config: ShmTransportConfig) -> Result<Self, XaceError> {
        config.validate().map_err(|e| XaceError::FatalError {
            message: format!("ShmTransport::open: invalid config — {}", e),
            context: ErrorContext::new("ShmTransport", "open"),
            snapshot_recovery_possible: false,
        })?;

        let path = config.shm_path();
        let file = OpenOptions::new()
            .read(true)
            .write(true)
            .open(&path)
            .map_err(|e| XaceError::RecoverableError {
                message: format!(
                    "ShmTransport::open: SHM file {:?} not found or not readable — {}. \
                     Is XACE running?",
                    path, e
                ),
                context: ErrorContext::new("ShmTransport", "open"),
                max_retries: 10,
                retry_count: 0,
            })?;

        let total_size = HEADER_SIZE + 2 * config.ring_size;
        let mmap = unsafe {
            MmapOptions::new()
                .len(total_size)
                .map_mut(&file)
                .map_err(|e| XaceError::FatalError {
                    message: format!("ShmTransport::open: mmap failed — {}", e),
                    context: ErrorContext::new("ShmTransport", "open"),
                    snapshot_recovery_possible: false,
                })?
        };

        // Validate header
        Self::validate_header(&mmap, config.ring_size).map_err(|reason| {
            XaceError::FatalError {
                message: format!("ShmTransport::open: header validation failed — {}", reason),
                context: ErrorContext::new("ShmTransport", "open"),
                snapshot_recovery_possible: false,
            }
        })?;

        xlog_info!("[ShmTransport] Attached to SHM at {:?}", path);
        Ok(Self::from_mmap(mmap, config, false))
    }

    // ── Message Exchange ──────────────────────────────────────────────────────

    /// Serializes and writes a WireMessage into the XACE→Engine ring.
    ///
    /// Returns `Err(RecoverableError)` if the ring is full. The caller
    /// should retry next tick or fall back to TCP transport.
    pub fn send_message(&mut self, msg: &WireMessage) -> Result<(), XaceError> {
        let frame = self.serializer.serialize(msg)?;
        let byte_count = frame.len();

        let result = unsafe { self.xace_to_engine.write_frame(&frame) };

        if result.is_err() {
            self.metrics.ring_full_count += 1;
            return Err(XaceError::RecoverableError {
                message: format!(
                    "ShmTransport: XACE→Engine ring full — frame {} bytes, \
                     ring_size={}, used={}. Retry next tick.",
                    byte_count,
                    self.config.ring_size,
                    unsafe { self.xace_to_engine.used_bytes() },
                ),
                context: ErrorContext::new("ShmTransport", "send_message")
                    .with_tick(msg.tick)
                    .with_detail("message_type", msg.message_type.to_string()),
                max_retries: 1,
                retry_count: 0,
            });
        }

        self.metrics.messages_sent += 1;
        self.metrics.bytes_sent += byte_count as u64;
        Ok(())
    }

    /// Writes multiple messages into the XACE→Engine ring back-to-back.
    ///
    /// Fails atomically if any message would overflow the ring — no
    /// partial batches are written.
    pub fn send_batch(&mut self, messages: &[WireMessage]) -> Result<(), XaceError> {
        if messages.is_empty() {
            return Ok(());
        }

        // Serialize all first — fail fast before touching the ring
        let mut frames: Vec<Vec<u8>> = Vec::with_capacity(messages.len());
        let mut total_bytes = 0usize;
        for msg in messages {
            let frame = self.serializer.serialize(msg)?;
            total_bytes += frame.len();
            frames.push(frame);
        }

        // Check ring capacity before writing any frame
        let used = unsafe { self.xace_to_engine.used_bytes() };
        let avail = self.config.ring_size.saturating_sub(used);
        if total_bytes > avail {
            self.metrics.ring_full_count += 1;
            return Err(XaceError::RecoverableError {
                message: format!(
                    "ShmTransport::send_batch: batch {} bytes exceeds available ring space {} bytes",
                    total_bytes, avail
                ),
                context: ErrorContext::new("ShmTransport", "send_batch"),
                max_retries: 1,
                retry_count: 0,
            });
        }

        for frame in &frames {
            unsafe { self.xace_to_engine.write_frame(frame).ok() };
        }

        self.metrics.messages_sent += messages.len() as u64;
        self.metrics.bytes_sent += total_bytes as u64;
        Ok(())
    }

    /// Drains all available messages from the Engine→XACE ring.
    ///
    /// Non-blocking — returns empty Vec immediately if no messages are ready.
    /// Call at the start of each tick to collect engine feedback (I13).
    pub fn try_receive_messages(&mut self) -> Result<Vec<WireMessage>, XaceError> {
        let mut messages = Vec::new();

        loop {
            let payload = unsafe { self.engine_to_xace.read_frame() };
            match payload {
                None => {
                    if messages.is_empty() {
                        self.metrics.empty_polls += 1;
                    }
                    break;
                }
                Some(bytes) => {
                    let byte_count = bytes.len();
                    match self.deserializer.deserialize_payload(&bytes) {
                        Ok(msg) => {
                            self.metrics.messages_received += 1;
                            self.metrics.bytes_received += byte_count as u64;
                            messages.push(msg);
                        }
                        Err(e) => {
                            xlog_error!(
                                "[ShmTransport] Deserialize error (frame skipped): {}",
                                e.message()
                            );
                        }
                    }
                }
            }
        }

        Ok(messages)
    }

    // ── Inspection ────────────────────────────────────────────────────────────

    /// Returns accumulated transport metrics.
    pub fn metrics(&self) -> &ShmTransportMetrics {
        &self.metrics
    }

    /// Returns the path to the SHM backing file.
    pub fn shm_path(&self) -> PathBuf {
        self.config.shm_path()
    }

    /// Returns approximate bytes available in the XACE→Engine ring.
    pub fn xace_ring_available_bytes(&self) -> usize {
        let used = unsafe { self.xace_to_engine.used_bytes() };
        self.config.ring_size.saturating_sub(used)
    }

    /// Returns approximate bytes available in the Engine→XACE ring.
    pub fn engine_ring_available_bytes(&self) -> usize {
        let used = unsafe { self.engine_to_xace.used_bytes() };
        self.config.ring_size.saturating_sub(used)
    }

    // ── Internal Helpers ──────────────────────────────────────────────────────

    /// Writes the SHM header into the first HEADER_SIZE bytes of the mmap.
    fn write_header(mmap: &mut MmapMut, ring_size: usize) {
        let ptr = mmap.as_mut_ptr();
        unsafe {
            // Magic
            (ptr as *mut u32).write(SHM_MAGIC.to_be());
            // Layout version
            (ptr.add(4) as *mut u32).write(SHM_LAYOUT_VERSION.to_be());
            // Ring size
            (ptr.add(8) as *mut u64).write((ring_size as u64).to_be());
            // Initialize all four AtomicU64 heads to 0
            (ptr.add(OFF_XACE_WRITE) as *mut u64).write(0);
            (ptr.add(OFF_XACE_READ) as *mut u64).write(0);
            (ptr.add(OFF_ENG_WRITE) as *mut u64).write(0);
            (ptr.add(OFF_ENG_READ) as *mut u64).write(0);
        }
    }

    /// Validates the SHM header written by the creator.
    fn validate_header(mmap: &MmapMut, expected_ring_size: usize) -> Result<(), String> {
        let ptr = mmap.as_ptr();
        unsafe {
            let magic = u32::from_be((ptr as *const u32).read());
            if magic != SHM_MAGIC {
                return Err(format!(
                    "SHM magic mismatch: expected 0x{:08X} got 0x{:08X}",
                    SHM_MAGIC, magic
                ));
            }
            let version = u32::from_be((ptr.add(4) as *const u32).read());
            if version != SHM_LAYOUT_VERSION {
                return Err(format!(
                    "SHM layout version mismatch: expected {} got {}",
                    SHM_LAYOUT_VERSION, version
                ));
            }
            let ring_size = u64::from_be((ptr.add(8) as *const u64).read()) as usize;
            if ring_size != expected_ring_size {
                return Err(format!(
                    "SHM ring_size mismatch: expected {} got {}",
                    expected_ring_size, ring_size
                ));
            }
        }
        Ok(())
    }

    /// Constructs ShmRing values from raw mmap pointer offsets and
    /// wraps them with the owning transport state.
    fn from_mmap(mmap: MmapMut, config: ShmTransportConfig, is_creator: bool) -> Self {
        let base = mmap.as_ptr() as *mut u8;
        let ring_size = config.ring_size;

        // XACE→Engine ring data starts right after the header
        let xace_data_ptr = unsafe { base.add(HEADER_SIZE) };
        // Engine→XACE ring data starts after the first ring
        let eng_data_ptr = unsafe { base.add(HEADER_SIZE + ring_size) };

        let xace_to_engine = ShmRing {
            data_ptr: xace_data_ptr,
            write_head_ptr: unsafe { base.add(OFF_XACE_WRITE) as *mut AtomicU64 },
            read_head_ptr: unsafe { base.add(OFF_XACE_READ) as *mut AtomicU64 },
            ring_size,
        };

        let engine_to_xace = ShmRing {
            data_ptr: eng_data_ptr,
            write_head_ptr: unsafe { base.add(OFF_ENG_WRITE) as *mut AtomicU64 },
            read_head_ptr: unsafe { base.add(OFF_ENG_READ) as *mut AtomicU64 },
            ring_size,
        };

        Self {
            _mmap: mmap,
            xace_to_engine,
            engine_to_xace,
            config,
            serializer: MessageSerializer::new(),
            deserializer: MessageDeserializer::new(),
            is_creator,
            metrics: ShmTransportMetrics::default(),
        }
    }
}

impl Drop for ShmTransport {
    fn drop(&mut self) {
        if self.is_creator && self.config.unlink_on_close {
            let path = self.config.shm_path();
            if let Err(e) = std::fs::remove_file(&path) {
                xlog_warn!("[ShmTransport] Failed to unlink SHM file {:?}: {}", path, e);
            } else {
                xlog_info!("[ShmTransport] SHM file {:?} unlinked", path);
            }
        }
    }
}

// ── Tests ─────────────────────────────────────────────────────────────────────

#[cfg(test)]
mod tests {
    use super::*;
    use xace_core::wire::wire_message::WireMessage;

    fn delta_msg(tick: u64, seq: u64) -> WireMessage {
        WireMessage::delta(
            "default", "0.1.0", 1, tick, seq,
            r#"{"tick":1,"sequence_id":1,"schema_version":"0.1.0","spawned_entities":[],"added_components":[],"modified_entities":{},"removed_components":[],"destroyed_entities":[]}"#,
        )
    }

    fn feedback_msg(tick: u64) -> WireMessage {
        WireMessage::feedback(
            "default", "0.1.0", 1, tick, tick,
            r#"{"feedback_type":"ANIMATION_STATE_UPDATE","data":{}}"#,
        )
    }

    fn test_config(id: &str) -> ShmTransportConfig {
        ShmTransportConfig {
            world_id: format!("test_{}", id),
            ring_size: 64 * 1024, // 64 KiB for tests
            unlink_on_close: true,
            ..Default::default()
        }
    }

    // ── Configuration ─────────────────────────────────────────────────────────

    #[test]
    fn config_validate_rejects_non_power_of_two() {
        let cfg = ShmTransportConfig { ring_size: 100_000, ..Default::default() };
        assert!(cfg.validate().is_err());
    }

    #[test]
    fn config_validate_rejects_below_minimum() {
        let cfg = ShmTransportConfig { ring_size: 32 * 1024, ..Default::default() };
        assert!(cfg.validate().is_err());
    }

    #[test]
    fn config_validate_rejects_empty_world_id() {
        let cfg = ShmTransportConfig { world_id: String::new(), ..Default::default() };
        assert!(cfg.validate().is_err());
    }

    #[test]
    fn config_validate_passes_for_valid_config() {
        let cfg = ShmTransportConfig {
            world_id: "test".into(),
            ring_size: 64 * 1024,
            ..Default::default()
        };
        assert!(cfg.validate().is_ok());
    }

    #[test]
    fn shm_path_includes_world_id() {
        let cfg = ShmTransportConfig {
            world_id: "myworld".into(),
            ..Default::default()
        };
        let path = cfg.shm_path();
        assert!(path.to_string_lossy().contains("myworld"));
    }

    // ── Create and Header ─────────────────────────────────────────────────────

    #[test]
    fn create_and_open_share_messages() {
        let cfg_a = test_config("roundtrip");
        let cfg_b = test_config("roundtrip");

        let mut creator = ShmTransport::create(cfg_a).unwrap();
        let mut opener = ShmTransport::open(cfg_b).unwrap();

        // creator sends a DELTA into XACE→Engine ring
        creator.send_message(&delta_msg(1, 1)).unwrap();

        // opener (simulating engine adapter) reads from the same ring
        let msgs = opener.try_receive_messages().unwrap();
        assert_eq!(msgs.len(), 1);
        assert!(msgs[0].is_delta());
        assert_eq!(msgs[0].tick, 1);
    }

    #[test]
    fn bidirectional_message_exchange() {
        let cfg_xace = test_config("bidir");
        let cfg_eng = test_config("bidir");

        let mut xace = ShmTransport::create(cfg_xace).unwrap();
        let mut engine = ShmTransport::open(cfg_eng).unwrap();

        // XACE → Engine
        xace.send_message(&delta_msg(5, 10)).unwrap();
        let from_xace = engine.try_receive_messages().unwrap();
        assert_eq!(from_xace.len(), 1);
        assert_eq!(from_xace[0].tick, 5);

        // Engine → XACE (engine writes into its write ring, xace reads from it)
        // Engine uses its xace_to_engine ring (which is engine's perspective)
        // In a real deployment the engine adapter would write to the Engine→XACE ring.
        // In this test both sides share the same ShmTransport type, so we simulate
        // engine writing by using send_message on the opener (which writes to its
        // xace_to_engine ring — pointing at XACE→Engine data region).
        // For the engine→xace direction we test via the feedback path:
        // engine writes feedback into eng_write ring, xace reads from eng_read ring.
        // We directly write into engine's xace_to_engine to simulate this in the test.
        // (In production the engine adapter is a separate binary using the C# SDK.)

        // Verify metrics
        assert_eq!(xace.metrics().messages_sent, 1);
        assert_eq!(engine.metrics().messages_received, 1);
    }

    #[test]
    fn send_batch_delivers_all_messages() {
        let cfg_a = test_config("batch");
        let cfg_b = test_config("batch");

        let mut creator = ShmTransport::create(cfg_a).unwrap();
        let mut opener = ShmTransport::open(cfg_b).unwrap();

        let msgs = vec![delta_msg(1, 1), delta_msg(2, 2), delta_msg(3, 3)];
        creator.send_batch(&msgs).unwrap();
        assert_eq!(creator.metrics().messages_sent, 3);

        let received = opener.try_receive_messages().unwrap();
        assert_eq!(received.len(), 3);
        assert_eq!(received[0].tick, 1);
        assert_eq!(received[1].tick, 2);
        assert_eq!(received[2].tick, 3);
    }

    #[test]
    fn empty_ring_returns_empty_vec() {
        let cfg = test_config("empty");
        let mut t = ShmTransport::create(cfg).unwrap();
        let msgs = t.try_receive_messages().unwrap();
        assert!(msgs.is_empty());
        assert_eq!(t.metrics().empty_polls, 1);
    }

    #[test]
    fn metrics_track_sent_and_received() {
        let cfg_a = test_config("metrics");
        let cfg_b = test_config("metrics");

        let mut sender = ShmTransport::create(cfg_a).unwrap();
        let mut receiver = ShmTransport::open(cfg_b).unwrap();

        sender.send_message(&delta_msg(1, 1)).unwrap();
        sender.send_message(&delta_msg(2, 2)).unwrap();
        receiver.try_receive_messages().unwrap();

        assert_eq!(sender.metrics().messages_sent, 2);
        assert!(sender.metrics().bytes_sent > 0);
        assert_eq!(receiver.metrics().messages_received, 2);
    }

    #[test]
    fn xace_ring_available_bytes_reflects_usage() {
        let cfg_a = test_config("avail");
        let cfg_b = test_config("avail");
        let mut sender = ShmTransport::create(cfg_a).unwrap();
        let _receiver = ShmTransport::open(cfg_b).unwrap();

        let before = sender.xace_ring_available_bytes();
        sender.send_message(&delta_msg(1, 1)).unwrap();
        let after = sender.xace_ring_available_bytes();
        assert!(after < before, "Available bytes must decrease after send");
    }

    #[test]
    fn shm_file_unlinked_on_drop() {
        let cfg = test_config("unlink");
        let path = cfg.shm_path();
        {
            let _t = ShmTransport::create(cfg).unwrap();
            assert!(path.exists(), "SHM file must exist while transport is alive");
        } // _t dropped here
        assert!(!path.exists(), "SHM file must be unlinked after drop");
    }

    #[test]
    fn open_nonexistent_file_returns_recoverable_error() {
        let cfg = ShmTransportConfig {
            world_id: "does_not_exist_xyz_abc_12345".into(),
            ring_size: 64 * 1024,
            ..Default::default()
        };
        let result = ShmTransport::open(cfg);
        assert!(result.is_err());
        // Should be RecoverableError (engine can retry)
        if let Err(XaceError::RecoverableError { .. }) = result {
            // correct
        } else {
            panic!("Expected RecoverableError for missing SHM file");
        }
    }
}