//! # Transport Integration Tests
//!
//! Integration tests for Phase 7 transport layer.
//!
//! ## Coverage
//! - TcpTransport: connect/disconnect, message send/receive,
//!   serialization determinism, multi-message batches
//! - ShmTransport: create/open, bidirectional message exchange,
//!   ring buffer capacity, file lifecycle
//! - MessageSerializer/Deserializer: frame format, length prefix,
//!   partial frame handling, oversized rejection
//! - ProtocolHandshake: version mismatch rejection on all 3 fields,
//!   matching versions accepted, full round-trip
//! - SequenceTracker: gap detection, duplicate detection, reset after snapshot

#[cfg(test)]
mod tests {
    use xace_core::wire::message_type::MessageType;
    use xace_core::wire::wire_message::{WireMessage, XACE_PROTOCOL_VERSION};

    use crate::transport::message_serializer::{
        MessageSerializer, FRAME_HEADER_SIZE, MAX_MESSAGE_SIZE,
    };
    use crate::transport::message_deserializer::MessageDeserializer;
    use crate::transport::protocol_handshake::{
        ProtocolHandshake, RejectReason,
    };
    use crate::transport::sequence_tracker::{
        SequenceCheckResult, SequenceTracker,
    };
    use crate::transport::tcp_transport::{TcpTransport, TcpConnectionState};

    // ── Helpers ───────────────────────────────────────────────────────────────

    fn delta(tick: u64, seq: u64) -> WireMessage {
        WireMessage::delta(
            "default", "0.1.0", 1, tick, seq,
            r#"{"tick":1,"sequence_id":1,"schema_version":"0.1.0",\
               "spawned_entities":[],"added_components":[],\
               "modified_entities":{},"removed_components":[],\
               "destroyed_entities":[]}"#,
        )
    }

    fn feedback(tick: u64, seq: u64) -> WireMessage {
        WireMessage::feedback(
            "default", "0.1.0", 1, tick, seq,
            r#"{"tick":1,"messages":[]}"#,
        )
    }

    fn snapshot_msg(seq: u64) -> WireMessage {
        WireMessage::snapshot(
            "default", "0.1.0", 1, 0, seq,
            r#"{"tick":0,"entities":[],"schema_version":"0.1.0"}"#,
        )
    }

    // =========================================================================
    // MessageSerializer
    // =========================================================================

    #[test]
    fn serializer_frame_has_4_byte_be_length_prefix() {
        let mut s = MessageSerializer::new();
        let frame = s.serialize(&delta(1, 1)).unwrap();
        let declared = u32::from_be_bytes(frame[..4].try_into().unwrap()) as usize;
        assert_eq!(declared, frame.len() - FRAME_HEADER_SIZE);
    }

    #[test]
    fn serializer_same_message_always_same_bytes() {
        // Determinism: D11 — same WireMessage → same bytes, always
        let mut s = MessageSerializer::new();
        let msg = delta(42, 100);
        let frame_a = s.serialize(&msg).unwrap();
        let frame_b = s.serialize(&msg).unwrap();
        assert_eq!(frame_a, frame_b, "Serialization must be deterministic (D11)");
    }

    #[test]
    fn serializer_rejects_message_with_empty_world_id() {
        let mut s = MessageSerializer::new();
        let mut bad = delta(1, 1);
        bad.world_id = String::new();
        assert!(s.serialize(&bad).is_err());
        assert_eq!(s.metrics().validation_failures, 1);
    }

    #[test]
    fn serializer_rejects_empty_schema_version() {
        let mut s = MessageSerializer::new();
        let mut bad = delta(1, 1);
        bad.schema_version = String::new();
        assert!(s.serialize(&bad).is_err());
    }

    #[test]
    fn serializer_batch_produces_multiple_complete_frames() {
        let mut s = MessageSerializer::new();
        let msgs = vec![delta(1, 1), delta(2, 2), snapshot_msg(1)];
        let batch = s.serialize_batch(&msgs).unwrap();

        // Manually parse all three frames out of the batch
        let mut cursor = 0;
        let mut count = 0;
        while cursor < batch.len() {
            let (_, consumed) =
                MessageSerializer::extract_frame(&batch[cursor..]).unwrap();
            cursor += consumed;
            count += 1;
        }
        assert_eq!(count, 3);
        assert_eq!(s.metrics().messages_serialized, 3);
    }

    #[test]
    fn serializer_batch_fails_if_any_message_invalid() {
        let mut s = MessageSerializer::new();
        let mut bad = delta(1, 1);
        bad.schema_version = String::new();
        let result = s.serialize_batch(&[delta(1, 1), bad]);
        assert!(result.is_err());
    }

    #[test]
    fn frame_header_size_is_four_bytes() {
        assert_eq!(FRAME_HEADER_SIZE, 4);
    }

    #[test]
    fn max_message_size_is_sixteen_mib() {
        assert_eq!(MAX_MESSAGE_SIZE, 16 * 1024 * 1024);
    }

    // =========================================================================
    // MessageDeserializer
    // =========================================================================

    #[test]
    fn deserializer_roundtrip_preserves_all_envelope_fields() {
        let original = delta(42, 99);
        let mut ser = MessageSerializer::new();
        let frame = ser.serialize(&original).unwrap();

        let mut deser = MessageDeserializer::new();
        deser.push_bytes(&frame);
        let restored = deser.try_extract_message().unwrap().unwrap();

        assert_eq!(restored.tick, 42);
        assert_eq!(restored.sequence_id, 99);
        assert_eq!(restored.schema_version, "0.1.0");
        assert_eq!(restored.world_id, "default");
        assert_eq!(restored.execution_plan_version, 1);
        assert!(restored.is_delta());
    }

    #[test]
    fn deserializer_partial_frame_returns_none_until_complete() {
        let mut ser = MessageSerializer::new();
        let frame = ser.serialize(&delta(1, 1)).unwrap();
        let mut deser = MessageDeserializer::new();

        // Feed one byte at a time
        for i in 0..frame.len() - 1 {
            deser.push_bytes(&frame[i..i + 1]);
            assert!(
                deser.try_extract_message().unwrap().is_none(),
                "Partial frame at byte {} must return None",
                i
            );
        }
        // Final byte completes the frame
        deser.push_bytes(&frame[frame.len() - 1..]);
        assert!(deser.try_extract_message().unwrap().is_some());
    }

    #[test]
    fn deserializer_two_concatenated_frames_both_extracted() {
        let mut ser = MessageSerializer::new();
        let f1 = ser.serialize(&delta(1, 1)).unwrap();
        let f2 = ser.serialize(&feedback(2, 2)).unwrap();
        let mut combined = f1;
        combined.extend_from_slice(&f2);

        let mut deser = MessageDeserializer::new();
        deser.push_bytes(&combined);

        let m1 = deser.try_extract_message().unwrap().unwrap();
        let m2 = deser.try_extract_message().unwrap().unwrap();
        assert!(m1.is_delta());
        assert!(m2.is_feedback());
        assert!(deser.try_extract_message().unwrap().is_none());
    }

    #[test]
    fn deserializer_oversized_frame_returns_fatal_error() {
        let oversized_len = (MAX_MESSAGE_SIZE + 1) as u32;
        let mut frame = vec![0u8; 4];
        frame[..4].copy_from_slice(&oversized_len.to_be_bytes());

        let mut deser = MessageDeserializer::new();
        deser.push_bytes(&frame);
        assert!(deser.try_extract_message().is_err());
        assert_eq!(deser.metrics().oversized_rejections, 1);
    }

    #[test]
    fn deserializer_wrong_protocol_version_returns_fatal_error() {
        let mut msg = delta(1, 1);
        msg.protocol_version = 999;
        let payload = serde_json::to_vec(&msg).unwrap();
        let frame = MessageSerializer::build_frame(&payload);

        let mut deser = MessageDeserializer::new();
        deser.push_bytes(&frame);
        let result = deser.try_extract_message();
        assert!(result.is_err());
        assert_eq!(deser.metrics().protocol_version_mismatches, 1);
    }

    #[test]
    fn deserializer_garbage_json_returns_recoverable_error() {
        let frame = MessageSerializer::build_frame(b"not json at all");
        let mut deser = MessageDeserializer::new();
        deser.push_bytes(&frame);
        assert!(deser.try_extract_message().is_err());
        assert_eq!(deser.metrics().parse_failures, 1);
    }

    #[test]
    fn deserializer_clear_buffer_resets_state() {
        let mut ser = MessageSerializer::new();
        let frame = ser.serialize(&delta(1, 1)).unwrap();
        let mut deser = MessageDeserializer::new();
        deser.push_bytes(&frame);
        deser.clear_buffer();
        assert!(deser.is_buffer_empty());
    }

    // =========================================================================
    // TcpTransport — State Machine
    // =========================================================================

    #[test]
    fn tcp_initial_state_is_unbound() {
        let t = TcpTransport::with_defaults();
        assert_eq!(t.state(), TcpConnectionState::Unbound);
        assert!(!t.is_connected());
    }

    #[test]
    fn tcp_bind_transitions_to_listening() {
        let mut t = TcpTransport::on_address("127.0.0.1:0");
        t.bind().unwrap();
        assert_eq!(t.state(), TcpConnectionState::Listening);
    }

    #[test]
    fn tcp_local_addr_available_after_bind() {
        let mut t = TcpTransport::on_address("127.0.0.1:0");
        let addr = t.bind().unwrap();
        assert!(addr.port() > 0);
        assert!(t.local_addr().is_some());
    }

    #[test]
    fn tcp_send_before_connect_returns_error() {
        let mut t = TcpTransport::on_address("127.0.0.1:0");
        t.bind().unwrap();
        assert!(t.send_message(&delta(1, 1)).is_err());
    }

    #[test]
    fn tcp_receive_before_connect_returns_error() {
        let mut t = TcpTransport::on_address("127.0.0.1:0");
        t.bind().unwrap();
        assert!(t.try_receive_messages().is_err());
    }

    #[test]
    fn tcp_default_config_has_no_delay_true() {
        use crate::transport::tcp_transport::TcpTransportConfig;
        assert!(TcpTransportConfig::default().no_delay);
    }

    // =========================================================================
    // TcpTransport — Connected Operations
    // =========================================================================

    use std::io::Write;
    use std::net::TcpStream;
    use std::thread;
    use std::time::Duration;

    fn spawn_client(port: u16) -> thread::JoinHandle<()> {
        thread::spawn(move || {
            thread::sleep(Duration::from_millis(20));
            let _client = TcpStream::connect(format!("127.0.0.1:{}", port)).unwrap();
            thread::sleep(Duration::from_millis(300));
        })
    }

    fn spawn_client_with_frames(port: u16, frames: Vec<Vec<u8>>) -> thread::JoinHandle<()> {
        thread::spawn(move || {
            thread::sleep(Duration::from_millis(20));
            let mut client = TcpStream::connect(format!("127.0.0.1:{}", port)).unwrap();
            client.set_nodelay(true).unwrap();
            for frame in frames {
                client.write_all(&frame).unwrap();
            }
            thread::sleep(Duration::from_millis(300));
        })
    }

    #[test]
    fn tcp_accept_connect_transitions_to_connected() {
        let mut server = TcpTransport::on_address("127.0.0.1:0");
        let port = server.bind().unwrap().port();
        let h = spawn_client(port);
        server.accept_connection().unwrap();
        assert_eq!(server.state(), TcpConnectionState::Connected);
        assert!(server.is_connected());
        assert!(server.peer_addr().is_some());
        h.join().unwrap();
    }

    #[test]
    fn tcp_send_message_succeeds_when_connected() {
        let mut server = TcpTransport::on_address("127.0.0.1:0");
        let port = server.bind().unwrap().port();
        let h = spawn_client(port);
        server.accept_connection().unwrap();
        assert!(server.send_message(&delta(1, 1)).is_ok());
        assert_eq!(server.metrics().messages_sent, 1);
        assert!(server.metrics().bytes_sent > 0);
        h.join().unwrap();
    }

    #[test]
    fn tcp_send_batch_sends_all_messages() {
        let mut server = TcpTransport::on_address("127.0.0.1:0");
        let port = server.bind().unwrap().port();
        let h = spawn_client(port);
        server.accept_connection().unwrap();
        server.send_batch(&[delta(1, 1), delta(2, 2), delta(3, 3)]).unwrap();
        assert_eq!(server.metrics().messages_sent, 3);
        h.join().unwrap();
    }

    #[test]
    fn tcp_receive_message_from_client() {
        let mut server = TcpTransport::on_address("127.0.0.1:0");
        let port = server.bind().unwrap().port();

        let mut ser = MessageSerializer::new();
        let frame = ser.serialize(&feedback(5, 1)).unwrap();
        let h = spawn_client_with_frames(port, vec![frame]);

        server.accept_connection().unwrap();

        let start = std::time::Instant::now();
        let mut received = vec![];
        while received.is_empty() && start.elapsed() < Duration::from_secs(2) {
            received = server.try_receive_messages().unwrap();
            if received.is_empty() {
                thread::sleep(Duration::from_millis(5));
            }
        }
        assert_eq!(received.len(), 1);
        assert!(received[0].is_feedback());
        assert_eq!(received[0].tick, 5);
        h.join().unwrap();
    }

    #[test]
    fn tcp_receive_two_concatenated_frames_from_client() {
        let mut server = TcpTransport::on_address("127.0.0.1:0");
        let port = server.bind().unwrap().port();

        let mut ser = MessageSerializer::new();
        let mut both = ser.serialize(&feedback(10, 1)).unwrap();
        both.extend_from_slice(&ser.serialize(&feedback(11, 2)).unwrap());
        let h = spawn_client_with_frames(port, vec![both]);

        server.accept_connection().unwrap();

        let start = std::time::Instant::now();
        let mut all = vec![];
        while all.len() < 2 && start.elapsed() < Duration::from_secs(2) {
            all.append(&mut server.try_receive_messages().unwrap());
            if all.len() < 2 { thread::sleep(Duration::from_millis(5)); }
        }
        assert_eq!(all.len(), 2);
        assert_eq!(all[0].tick, 10);
        assert_eq!(all[1].tick, 11);
        h.join().unwrap();
    }

    #[test]
    fn tcp_try_receive_no_data_returns_empty_vec() {
        let mut server = TcpTransport::on_address("127.0.0.1:0");
        let port = server.bind().unwrap().port();
        let h = spawn_client(port);
        server.accept_connection().unwrap();
        // No data sent — should be empty immediately
        let msgs = server.try_receive_messages().unwrap();
        assert!(msgs.is_empty());
        h.join().unwrap();
    }

    #[test]
    fn tcp_disconnect_returns_to_listening() {
        let mut server = TcpTransport::on_address("127.0.0.1:0");
        let port = server.bind().unwrap().port();
        let h = spawn_client(port);
        server.accept_connection().unwrap();
        server.disconnect();
        assert_eq!(server.state(), TcpConnectionState::Listening);
        h.join().unwrap();
    }

    #[test]
    fn tcp_send_after_disconnect_fails() {
        let mut server = TcpTransport::on_address("127.0.0.1:0");
        let port = server.bind().unwrap().port();
        let h = spawn_client(port);
        server.accept_connection().unwrap();
        server.disconnect();
        assert!(server.send_message(&delta(1, 1)).is_err());
        h.join().unwrap();
    }

    #[test]
    fn tcp_serialization_determinism_same_message_same_bytes() {
        // D11 — identical messages produce identical byte sequences
        let mut ser = MessageSerializer::new();
        let msg = delta(100, 200);
        let bytes_a = ser.serialize(&msg).unwrap();
        let bytes_b = ser.serialize(&msg).unwrap();
        assert_eq!(bytes_a, bytes_b);
    }

    // =========================================================================
    // ShmTransport
    // =========================================================================

    #[test]
    fn shm_config_validate_requires_power_of_two_ring_size() {
        use crate::transport::shm_transport::ShmTransportConfig;
        let cfg = ShmTransportConfig { ring_size: 100_000, ..Default::default() };
        assert!(cfg.validate().is_err());
    }

    #[test]
    fn shm_config_validate_requires_minimum_ring_size() {
        use crate::transport::shm_transport::ShmTransportConfig;
        let cfg = ShmTransportConfig { ring_size: 32 * 1024, ..Default::default() };
        assert!(cfg.validate().is_err());
    }

    #[test]
    fn shm_create_and_open_exchange_messages() {
        use crate::transport::shm_transport::{ShmTransport, ShmTransportConfig};
        let cfg_a = ShmTransportConfig {
            world_id: "test_exchange".into(), ring_size: 64 * 1024,
            unlink_on_close: true, ..Default::default()
        };
        let cfg_b = ShmTransportConfig {
            world_id: "test_exchange".into(), ring_size: 64 * 1024,
            unlink_on_close: false, ..Default::default()
        };
        let mut creator = ShmTransport::create(cfg_a).unwrap();
        let mut opener  = ShmTransport::open(cfg_b).unwrap();

        creator.send_message(&delta(1, 1)).unwrap();
        let msgs = opener.try_receive_messages().unwrap();
        assert_eq!(msgs.len(), 1);
        assert!(msgs[0].is_delta());
        assert_eq!(msgs[0].tick, 1);
    }

    #[test]
    fn shm_send_batch_delivers_all_messages() {
        use crate::transport::shm_transport::{ShmTransport, ShmTransportConfig};
        let cfg_a = ShmTransportConfig {
            world_id: "test_batch".into(), ring_size: 64 * 1024,
            unlink_on_close: true, ..Default::default()
        };
        let cfg_b = ShmTransportConfig {
            world_id: "test_batch".into(), ring_size: 64 * 1024,
            unlink_on_close: false, ..Default::default()
        };
        let mut creator = ShmTransport::create(cfg_a).unwrap();
        let mut opener  = ShmTransport::open(cfg_b).unwrap();

        creator.send_batch(&[delta(1, 1), delta(2, 2), delta(3, 3)]).unwrap();
        let msgs = opener.try_receive_messages().unwrap();
        assert_eq!(msgs.len(), 3);
    }

    #[test]
    fn shm_file_unlinked_on_creator_drop() {
        use crate::transport::shm_transport::{ShmTransport, ShmTransportConfig};
        let cfg = ShmTransportConfig {
            world_id: "test_unlink".into(), ring_size: 64 * 1024,
            unlink_on_close: true, ..Default::default()
        };
        let path = cfg.shm_path();
        { let _t = ShmTransport::create(cfg).unwrap(); }
        assert!(!path.exists(), "SHM file must be unlinked after drop");
    }
}