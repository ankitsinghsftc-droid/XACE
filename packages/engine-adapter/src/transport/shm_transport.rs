//! Shared-memory transport for same-machine runtime/engine communication.
//!
//! The region is a memory-mapped file containing a small header plus two
//! single-producer/single-consumer byte rings. The runtime-created endpoint
//! writes to the XACE-to-engine ring and reads from the engine-to-XACE ring.
//! The engine-opened endpoint uses the opposite direction.

use std::fs::OpenOptions;
use std::path::PathBuf;
use std::sync::atomic::{fence, AtomicU64, Ordering};

use memmap2::{MmapMut, MmapOptions};
use xace_core::errors::xace_error::{ErrorContext, XaceError};
use xace_core::wire::wire_message::WireMessage;

use crate::adapter_contract::engine_adapter_interface::Transport;
use crate::transport::message_deserializer::{DeserializerMetrics, MessageDeserializer};
use crate::transport::message_serializer::{
    MessageSerializer, SerializerMetrics, FRAME_HEADER_SIZE, MAX_MESSAGE_SIZE,
};

const SHM_MAGIC: u32 = 0x5853_484D; // XSHM
const SHM_LAYOUT_VERSION: u32 = 1;
pub const DEFAULT_RING_SIZE: usize = 4 * 1024 * 1024;
const MIN_RING_SIZE: usize = 64 * 1024;
const HEADER_SIZE: usize = 128;
const OFF_MAGIC: usize = 0;
const OFF_VERSION: usize = 4;
const OFF_RING_SIZE: usize = 8;
const OFF_XACE_WRITE: usize = 64;
const OFF_XACE_READ: usize = 72;
const OFF_ENGINE_WRITE: usize = 80;
const OFF_ENGINE_READ: usize = 88;

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ShmTransportConfig {
    pub world_id: String,
    pub ring_size: usize,
    pub shm_dir: PathBuf,
    pub unlink_on_close: bool,
    pub engine_name: String,
}

impl Default for ShmTransportConfig {
    fn default() -> Self {
        Self {
            world_id: "default".to_string(),
            ring_size: DEFAULT_RING_SIZE,
            shm_dir: std::env::temp_dir(),
            unlink_on_close: true,
            engine_name: "EngineAdapter".to_string(),
        }
    }
}

impl ShmTransportConfig {
    pub fn shm_path(&self) -> PathBuf {
        self.shm_dir.join(format!("xace_{}_shm", self.world_id))
    }

    pub fn validate(&self) -> Result<(), String> {
        if self.world_id.trim().is_empty() {
            return Err("world_id must not be empty".to_string());
        }
        if self.ring_size < MIN_RING_SIZE {
            return Err(format!(
                "ring_size {} is below minimum {}",
                self.ring_size, MIN_RING_SIZE
            ));
        }
        if !self.ring_size.is_power_of_two() {
            return Err(format!(
                "ring_size {} must be a power of two",
                self.ring_size
            ));
        }
        if self.engine_name.trim().is_empty() {
            return Err("engine_name must not be empty".to_string());
        }
        Ok(())
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum ShmEndpointRole {
    Runtime,
    Engine,
}

#[derive(Debug, Clone, Default, PartialEq, Eq)]
pub struct ShmTransportMetrics {
    pub messages_sent: u64,
    pub messages_received: u64,
    pub bytes_sent: u64,
    pub bytes_received: u64,
    pub ring_full_count: u64,
    pub empty_polls: u64,
    pub deserialize_failures: u64,
    pub corrupted_frames: u64,
}

struct ShmRing {
    data_ptr: *mut u8,
    write_head_ptr: *mut AtomicU64,
    read_head_ptr: *mut AtomicU64,
    ring_size: usize,
}

// SAFETY: Pointers are into the owning `MmapMut`, which lives as long as the
// transport. Public operations require `&mut self`, preserving SPSC access.
unsafe impl Send for ShmRing {}
unsafe impl Sync for ShmRing {}

impl ShmRing {
    unsafe fn write_frame(&mut self, frame: &[u8]) -> Result<(), ()> {
        if frame.is_empty() || frame.len() > self.ring_size {
            return Err(());
        }

        let write = (*self.write_head_ptr).load(Ordering::Acquire);
        let read = (*self.read_head_ptr).load(Ordering::Acquire);
        let used = write.wrapping_sub(read) as usize;
        let available = self.ring_size.saturating_sub(used);
        if frame.len() > available {
            return Err(());
        }

        let mask = (self.ring_size - 1) as u64;
        let mut cursor = write;
        for byte in frame {
            *self.data_ptr.add((cursor & mask) as usize) = *byte;
            cursor = cursor.wrapping_add(1);
        }
        fence(Ordering::SeqCst);
        (*self.write_head_ptr).store(cursor, Ordering::Release);
        Ok(())
    }

    unsafe fn read_frame(&mut self) -> Result<Option<Vec<u8>>, ShmRingReadError> {
        let write = (*self.write_head_ptr).load(Ordering::Acquire);
        let read = (*self.read_head_ptr).load(Ordering::Acquire);
        let available = write.wrapping_sub(read) as usize;
        if available < FRAME_HEADER_SIZE {
            return Ok(None);
        }

        let mask = (self.ring_size - 1) as u64;
        let mut len_bytes = [0u8; FRAME_HEADER_SIZE];
        for i in 0..FRAME_HEADER_SIZE {
            len_bytes[i] = *self
                .data_ptr
                .add((read.wrapping_add(i as u64) & mask) as usize);
        }

        let payload_len = u32::from_be_bytes(len_bytes) as usize;
        if payload_len == 0 || payload_len > MAX_MESSAGE_SIZE || payload_len > self.ring_size {
            (*self.read_head_ptr).store(
                read.wrapping_add(FRAME_HEADER_SIZE as u64),
                Ordering::Release,
            );
            return Err(ShmRingReadError::CorruptedLength(payload_len));
        }

        let total = FRAME_HEADER_SIZE + payload_len;
        if available < total {
            return Ok(None);
        }

        let mut frame = vec![0u8; total];
        for i in 0..total {
            frame[i] = *self
                .data_ptr
                .add((read.wrapping_add(i as u64) & mask) as usize);
        }
        (*self.read_head_ptr).store(read.wrapping_add(total as u64), Ordering::Release);
        Ok(Some(frame))
    }

    unsafe fn used_bytes(&self) -> usize {
        let write = (*self.write_head_ptr).load(Ordering::Acquire);
        let read = (*self.read_head_ptr).load(Ordering::Acquire);
        write.wrapping_sub(read) as usize
    }
}

#[derive(Debug, Clone, PartialEq, Eq)]
enum ShmRingReadError {
    CorruptedLength(usize),
}

pub struct ShmTransport {
    config: ShmTransportConfig,
    _mmap: MmapMut,
    xace_to_engine: ShmRing,
    engine_to_xace: ShmRing,
    role: ShmEndpointRole,
    serializer: MessageSerializer,
    deserializer: MessageDeserializer,
    metrics: ShmTransportMetrics,
}

// SAFETY: Access to ring mutation requires `&mut self`; raw pointers target the
// mmap owned by this struct and are not exposed.
unsafe impl Send for ShmTransport {}
unsafe impl Sync for ShmTransport {}

impl ShmTransport {
    pub fn create(config: ShmTransportConfig) -> Result<Self, XaceError> {
        Self::map(config, ShmEndpointRole::Runtime, true)
    }

    pub fn open(config: ShmTransportConfig) -> Result<Self, XaceError> {
        Self::map(config, ShmEndpointRole::Engine, false)
    }

    pub fn send_message(&mut self, msg: &WireMessage) -> Result<(), XaceError> {
        let frame = self.serializer.serialize(msg)?;
        self.write_to_outbound_ring(&frame).map_err(|used| {
            self.metrics.ring_full_count += 1;
            recoverable(
                "send_message",
                format!(
                    "outbound ring full: frame={} bytes ring_size={} used={}",
                    frame.len(),
                    self.config.ring_size,
                    used
                ),
            )
        })?;

        self.metrics.messages_sent += 1;
        self.metrics.bytes_sent += frame.len() as u64;
        Ok(())
    }

    pub fn send_batch(&mut self, messages: &[WireMessage]) -> Result<(), XaceError> {
        if messages.is_empty() {
            return Ok(());
        }
        let batch = self.serializer.serialize_batch(messages)?;
        self.write_to_outbound_ring(&batch).map_err(|used| {
            self.metrics.ring_full_count += 1;
            recoverable(
                "send_batch",
                format!(
                    "outbound ring full for batch: bytes={} ring_size={} used={}",
                    batch.len(),
                    self.config.ring_size,
                    used
                ),
            )
        })?;

        self.metrics.messages_sent += messages.len() as u64;
        self.metrics.bytes_sent += batch.len() as u64;
        Ok(())
    }

    pub fn try_receive_messages(&mut self) -> Result<Vec<WireMessage>, XaceError> {
        let mut messages = Vec::new();
        loop {
            let frame = unsafe { self.inbound_ring().read_frame() };
            match frame {
                Ok(Some(frame)) => {
                    let bytes = frame.len();
                    match self.deserializer.deserialize_frame(&frame) {
                        Ok(message) => {
                            self.metrics.messages_received += 1;
                            self.metrics.bytes_received += bytes as u64;
                            messages.push(message);
                        }
                        Err(err) => {
                            self.metrics.deserialize_failures += 1;
                            if err.is_fatal() {
                                return Err(err);
                            }
                        }
                    }
                }
                Ok(None) => {
                    if messages.is_empty() {
                        self.metrics.empty_polls += 1;
                    }
                    break;
                }
                Err(ShmRingReadError::CorruptedLength(_)) => {
                    self.metrics.corrupted_frames += 1;
                    self.metrics.deserialize_failures += 1;
                    break;
                }
            }
        }
        Ok(messages)
    }

    pub fn role(&self) -> ShmEndpointRole {
        self.role
    }

    pub fn is_connected(&self) -> bool {
        self.config.shm_path().exists()
    }

    pub fn metrics(&self) -> &ShmTransportMetrics {
        &self.metrics
    }

    pub fn serializer_metrics(&self) -> &SerializerMetrics {
        self.serializer.metrics()
    }

    pub fn deserializer_metrics(&self) -> &DeserializerMetrics {
        self.deserializer.metrics()
    }

    pub fn config(&self) -> &ShmTransportConfig {
        &self.config
    }

    pub fn shm_path(&self) -> PathBuf {
        self.config.shm_path()
    }

    pub fn outbound_available_bytes(&self) -> usize {
        self.config
            .ring_size
            .saturating_sub(unsafe { self.outbound_ring_ref().used_bytes() })
    }

    pub fn inbound_available_bytes(&self) -> usize {
        self.config
            .ring_size
            .saturating_sub(unsafe { self.inbound_ring_ref().used_bytes() })
    }

    pub fn xace_ring_available_bytes(&self) -> usize {
        self.config
            .ring_size
            .saturating_sub(unsafe { self.xace_to_engine.used_bytes() })
    }

    pub fn engine_ring_available_bytes(&self) -> usize {
        self.config
            .ring_size
            .saturating_sub(unsafe { self.engine_to_xace.used_bytes() })
    }

    fn map(
        config: ShmTransportConfig,
        role: ShmEndpointRole,
        create: bool,
    ) -> Result<Self, XaceError> {
        config.validate().map_err(|detail| fatal("map", detail))?;
        std::fs::create_dir_all(&config.shm_dir).map_err(|err| {
            fatal(
                "map",
                format!(
                    "failed to create shm directory {:?}: {}",
                    config.shm_dir, err
                ),
            )
        })?;

        let path = config.shm_path();
        let total_size = HEADER_SIZE + 2 * config.ring_size;
        let file = if create {
            let file = OpenOptions::new()
                .read(true)
                .write(true)
                .create(true)
                .truncate(true)
                .open(&path)
                .map_err(|err| fatal("create", format!("failed to create {:?}: {}", path, err)))?;
            file.set_len(total_size as u64)
                .map_err(|err| fatal("create", format!("failed to size {:?}: {}", path, err)))?;
            file
        } else {
            OpenOptions::new()
                .read(true)
                .write(true)
                .open(&path)
                .map_err(|err| recoverable("open", format!("failed to open {:?}: {}", path, err)))?
        };

        let mut mmap = unsafe {
            MmapOptions::new()
                .len(total_size)
                .map_mut(&file)
                .map_err(|err| fatal("map", format!("failed to mmap {:?}: {}", path, err)))?
        };

        if create {
            mmap.fill(0);
            Self::write_header(&mut mmap, config.ring_size);
        } else {
            Self::validate_header(&mmap, config.ring_size).map_err(|detail| {
                fatal("open", format!("SHM header validation failed: {}", detail))
            })?;
        }

        Ok(Self::from_mmap(mmap, config, role))
    }

    fn write_to_outbound_ring(&mut self, frame: &[u8]) -> Result<(), usize> {
        let used = unsafe { self.outbound_ring_ref().used_bytes() };
        unsafe { self.outbound_ring().write_frame(frame).map_err(|_| used) }
    }

    fn outbound_ring(&mut self) -> &mut ShmRing {
        match self.role {
            ShmEndpointRole::Runtime => &mut self.xace_to_engine,
            ShmEndpointRole::Engine => &mut self.engine_to_xace,
        }
    }

    fn inbound_ring(&mut self) -> &mut ShmRing {
        match self.role {
            ShmEndpointRole::Runtime => &mut self.engine_to_xace,
            ShmEndpointRole::Engine => &mut self.xace_to_engine,
        }
    }

    fn outbound_ring_ref(&self) -> &ShmRing {
        match self.role {
            ShmEndpointRole::Runtime => &self.xace_to_engine,
            ShmEndpointRole::Engine => &self.engine_to_xace,
        }
    }

    fn inbound_ring_ref(&self) -> &ShmRing {
        match self.role {
            ShmEndpointRole::Runtime => &self.engine_to_xace,
            ShmEndpointRole::Engine => &self.xace_to_engine,
        }
    }

    fn write_header(mmap: &mut MmapMut, ring_size: usize) {
        mmap[OFF_MAGIC..OFF_MAGIC + 4].copy_from_slice(&SHM_MAGIC.to_be_bytes());
        mmap[OFF_VERSION..OFF_VERSION + 4].copy_from_slice(&SHM_LAYOUT_VERSION.to_be_bytes());
        mmap[OFF_RING_SIZE..OFF_RING_SIZE + 8].copy_from_slice(&(ring_size as u64).to_be_bytes());
        for offset in [
            OFF_XACE_WRITE,
            OFF_XACE_READ,
            OFF_ENGINE_WRITE,
            OFF_ENGINE_READ,
        ] {
            mmap[offset..offset + 8].copy_from_slice(&0u64.to_ne_bytes());
        }
    }

    fn validate_header(mmap: &MmapMut, expected_ring_size: usize) -> Result<(), String> {
        let magic = u32::from_be_bytes(mmap[OFF_MAGIC..OFF_MAGIC + 4].try_into().unwrap());
        if magic != SHM_MAGIC {
            return Err(format!(
                "magic mismatch: expected {SHM_MAGIC:#x}, got {magic:#x}"
            ));
        }
        let version = u32::from_be_bytes(mmap[OFF_VERSION..OFF_VERSION + 4].try_into().unwrap());
        if version != SHM_LAYOUT_VERSION {
            return Err(format!(
                "layout version mismatch: expected {}, got {}",
                SHM_LAYOUT_VERSION, version
            ));
        }
        let ring_size =
            u64::from_be_bytes(mmap[OFF_RING_SIZE..OFF_RING_SIZE + 8].try_into().unwrap()) as usize;
        if ring_size != expected_ring_size {
            return Err(format!(
                "ring size mismatch: expected {}, got {}",
                expected_ring_size, ring_size
            ));
        }
        Ok(())
    }

    fn from_mmap(mmap: MmapMut, config: ShmTransportConfig, role: ShmEndpointRole) -> Self {
        let base = mmap.as_ptr() as *mut u8;
        let ring_size = config.ring_size;
        let xace_data_ptr = unsafe { base.add(HEADER_SIZE) };
        let engine_data_ptr = unsafe { base.add(HEADER_SIZE + ring_size) };

        Self {
            _mmap: mmap,
            xace_to_engine: ShmRing {
                data_ptr: xace_data_ptr,
                write_head_ptr: unsafe { base.add(OFF_XACE_WRITE) as *mut AtomicU64 },
                read_head_ptr: unsafe { base.add(OFF_XACE_READ) as *mut AtomicU64 },
                ring_size,
            },
            engine_to_xace: ShmRing {
                data_ptr: engine_data_ptr,
                write_head_ptr: unsafe { base.add(OFF_ENGINE_WRITE) as *mut AtomicU64 },
                read_head_ptr: unsafe { base.add(OFF_ENGINE_READ) as *mut AtomicU64 },
                ring_size,
            },
            config,
            role,
            serializer: MessageSerializer::new(),
            deserializer: MessageDeserializer::new(),
            metrics: ShmTransportMetrics::default(),
        }
    }
}

impl Transport for ShmTransport {
    fn send_message(&mut self, msg: &WireMessage) -> Result<(), XaceError> {
        ShmTransport::send_message(self, msg)
    }

    fn send_batch(&mut self, messages: &[WireMessage]) -> Result<(), XaceError> {
        ShmTransport::send_batch(self, messages)
    }

    fn try_receive_messages(&mut self) -> Result<Vec<WireMessage>, XaceError> {
        ShmTransport::try_receive_messages(self)
    }

    fn is_connected(&self) -> bool {
        ShmTransport::is_connected(self)
    }

    fn engine_name(&self) -> &str {
        &self.config.engine_name
    }
}

impl Drop for ShmTransport {
    fn drop(&mut self) {
        if self.role == ShmEndpointRole::Runtime && self.config.unlink_on_close {
            let _ = std::fs::remove_file(self.config.shm_path());
        }
    }
}

fn recoverable(operation: &'static str, message: impl Into<String>) -> XaceError {
    XaceError::RecoverableError {
        message: format!("ShmTransport: {}", message.into()),
        context: ErrorContext::new("ShmTransport", operation),
        max_retries: 3,
        retry_count: 0,
    }
}

fn fatal(operation: &'static str, message: impl Into<String>) -> XaceError {
    XaceError::FatalError {
        message: format!("ShmTransport: {}", message.into()),
        context: ErrorContext::new("ShmTransport", operation),
        snapshot_recovery_possible: false,
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn config(name: &str) -> ShmTransportConfig {
        ShmTransportConfig {
            world_id: format!("test_{}_{}", name, std::process::id()),
            ring_size: MIN_RING_SIZE,
            unlink_on_close: true,
            ..Default::default()
        }
    }

    fn delta(tick: u64, seq: u64) -> WireMessage {
        WireMessage::delta("default", "0.1.0", 1, tick, seq, r#"{"kind":"delta"}"#)
    }

    fn feedback(tick: u64, seq: u64) -> WireMessage {
        WireMessage::feedback("default", "0.1.0", 1, tick, seq, r#"{"kind":"feedback"}"#)
    }

    #[test]
    fn runtime_and_engine_exchange_bidirectionally() {
        let cfg = config("bidir");
        let mut runtime = ShmTransport::create(cfg.clone()).unwrap();
        let mut engine = ShmTransport::open(cfg).unwrap();

        runtime.send_message(&delta(1, 1)).unwrap();
        let engine_messages = engine.try_receive_messages().unwrap();
        assert_eq!(engine_messages.len(), 1);
        assert!(engine_messages[0].is_delta());

        engine.send_message(&feedback(2, 1)).unwrap();
        let runtime_messages = runtime.try_receive_messages().unwrap();
        assert_eq!(runtime_messages.len(), 1);
        assert!(runtime_messages[0].is_feedback());
    }

    #[test]
    fn send_batch_delivers_all_messages() {
        let cfg = config("batch");
        let mut runtime = ShmTransport::create(cfg.clone()).unwrap();
        let mut engine = ShmTransport::open(cfg).unwrap();

        runtime.send_batch(&[delta(1, 1), delta(2, 2)]).unwrap();
        let messages = engine.try_receive_messages().unwrap();
        assert_eq!(messages.len(), 2);
        assert_eq!(runtime.metrics().messages_sent, 2);
    }

    #[test]
    fn creator_unlinks_file_on_drop() {
        let cfg = config("unlink");
        let path = cfg.shm_path();
        {
            let _runtime = ShmTransport::create(cfg).unwrap();
            assert!(path.exists());
        }
        assert!(!path.exists());
    }

    #[test]
    fn invalid_config_is_rejected() {
        let cfg = ShmTransportConfig {
            ring_size: 1000,
            ..Default::default()
        };
        assert!(cfg.validate().is_err());
    }
}
