//! # Protocol Handshake Integration Tests
//!
//! Tests the full handshake lifecycle:
//! - Matching versions accepted (all 3 fields validated independently)
//! - Each of the 3 version fields rejected independently when wrong
//! - World ID mismatch rejected
//! - Malformed payload handled gracefully
//! - Full client-server round-trip (Hello → Ack → parse)
//! - Reject payload carries correct expected-vs-received diagnostic info

#[cfg(test)]
mod tests {
    use xace_core::wire::wire_message::XACE_PROTOCOL_VERSION;

    use crate::transport::message_deserializer::MessageDeserializer;
    use crate::transport::message_serializer::MessageSerializer;
    use crate::transport::protocol_handshake::{
        HandshakeControlType, HandshakeHello, HandshakeReject, HandshakeResult,
        HandshakeState, ProtocolHandshake, RejectReason,
    };
    use xace_core::wire::wire_message::WireMessage;

    // ── Helpers ───────────────────────────────────────────────────────────────

    /// Standard server locked to schema "0.1.0", plan version 1, world "default".
    fn server() -> ProtocolHandshake {
        ProtocolHandshake::new_server("0.1.0", 1, "default", 1)
    }

    /// Builds a valid Hello frame for the matching server configuration.
    fn valid_hello(engine: &str) -> Vec<u8> {
        ProtocolHandshake::build_hello_frame("0.1.0", 1, "default", engine, "1.0.0").unwrap()
    }

    /// Builds a Hello with custom version fields for mismatch testing.
    fn hello_with(schema: &str, plan: u32, world: &str, proto: u32) -> Vec<u8> {
        let hello = HandshakeHello {
            control_type: HandshakeControlType::Hello,
            protocol_version: proto,
            schema_version: schema.into(),
            execution_plan_version: plan,
            world_id: world.into(),
            engine_name: "TestEngine".into(),
            adapter_version: "1.0.0".into(),
        };
        let payload = serde_json::to_string(&hello).unwrap();
        let msg = WireMessage::control(world, schema, plan, 0, payload);
        let mut ser = MessageSerializer::new();
        ser.serialize_unchecked(&msg).unwrap()
    }

    fn parse_reject(frame: &[u8]) -> HandshakeReject {
        let mut deser = MessageDeserializer::new();
        deser.push_bytes(frame);
        let msg = deser.try_extract_message().unwrap().unwrap();
        serde_json::from_str(&msg.payload).unwrap()
    }

    // =========================================================================
    // Successful Handshake
    // =========================================================================

    #[test]
    fn valid_hello_produces_ack_and_completed_state() {
        let mut hs = server();
        let frame = valid_hello("Unity-2022");
        let ack = hs.process_hello_frame(&frame).unwrap();
        assert_eq!(hs.state(), HandshakeState::Completed);
        assert!(hs.is_accepted());
        assert!(!ack.is_empty());
    }

    #[test]
    fn ack_frame_is_parseable_as_accepted_result() {
        let mut hs = server();
        let ack = hs.process_hello_frame(&valid_hello("Godot-4")).unwrap();
        let result = ProtocolHandshake::parse_response_frame(&ack).unwrap();
        assert!(result.is_accepted());
    }

    #[test]
    fn accepted_result_carries_engine_name() {
        let mut hs = server();
        hs.process_hello_frame(&valid_hello("UnrealEngine-5")).unwrap();
        assert_eq!(hs.result().unwrap().engine_name(), Some("UnrealEngine-5"));
    }

    #[test]
    fn accepted_result_carries_initial_sequence_id() {
        let mut hs = ProtocolHandshake::new_server("0.1.0", 1, "default", 42);
        hs.process_hello_frame(&valid_hello("Unity")).unwrap();
        if let Some(HandshakeResult::Accepted { initial_delta_sequence_id, .. }) = hs.result() {
            assert_eq!(*initial_delta_sequence_id, 42);
        } else {
            panic!("Expected Accepted result");
        }
    }

    #[test]
    fn ack_carries_correct_initial_sequence_id_to_client() {
        let mut hs = ProtocolHandshake::new_server("0.1.0", 1, "default", 99);
        let ack = hs.process_hello_frame(&valid_hello("Unity")).unwrap();
        let result = ProtocolHandshake::parse_response_frame(&ack).unwrap();
        if let HandshakeResult::Accepted { initial_delta_sequence_id, .. } = result {
            assert_eq!(initial_delta_sequence_id, 99);
        } else {
            panic!("Expected Accepted");
        }
    }

    // =========================================================================
    // Version Field 1: Protocol Version
    // =========================================================================

    #[test]
    fn wrong_protocol_version_produces_protocol_mismatch_reject() {
        let mut hs = server();
        // Build Hello with wrong protocol version
        let frame = hello_with("0.1.0", 1, "default", 999);
        let reject_frame = hs.process_hello_frame(&frame).unwrap();

        assert_eq!(hs.state(), HandshakeState::Rejected);
        let result = ProtocolHandshake::parse_response_frame(&reject_frame).unwrap();
        assert_eq!(result.reject_reason(), Some(&RejectReason::ProtocolVersionMismatch));
    }

    #[test]
    fn protocol_version_check_is_independent_of_other_fields() {
        // All other fields correct, only protocol wrong
        let mut hs = server();
        let frame = hello_with("0.1.0", 1, "default", XACE_PROTOCOL_VERSION + 1);
        let reject_frame = hs.process_hello_frame(&frame).unwrap();
        let reject = parse_reject(&reject_frame);
        assert_eq!(reject.reason, RejectReason::ProtocolVersionMismatch);
        assert_eq!(reject.expected_protocol_version, XACE_PROTOCOL_VERSION);
    }

    // =========================================================================
    // Version Field 2: Schema Version
    // =========================================================================

    #[test]
    fn wrong_schema_version_produces_schema_mismatch_reject() {
        let mut hs = server();
        let frame = hello_with("9.9.9", 1, "default", XACE_PROTOCOL_VERSION);
        let reject_frame = hs.process_hello_frame(&frame).unwrap();

        assert_eq!(hs.state(), HandshakeState::Rejected);
        let result = ProtocolHandshake::parse_response_frame(&reject_frame).unwrap();
        assert_eq!(result.reject_reason(), Some(&RejectReason::SchemaVersionMismatch));
    }

    #[test]
    fn schema_reject_carries_both_expected_and_received_versions() {
        let mut hs = ProtocolHandshake::new_server("0.2.0", 1, "default", 1);
        let frame = hello_with("0.1.0", 1, "default", XACE_PROTOCOL_VERSION);
        let reject_frame = hs.process_hello_frame(&frame).unwrap();
        let reject = parse_reject(&reject_frame);

        assert_eq!(reject.expected_schema_version, "0.2.0");
        assert!(reject.detail.contains("0.1.0"), "Detail must mention received version");
        assert!(reject.detail.contains("0.2.0"), "Detail must mention expected version");
    }

    // =========================================================================
    // Version Field 3: ExecutionPlan Version
    // =========================================================================

    #[test]
    fn wrong_plan_version_produces_plan_mismatch_reject() {
        let mut hs = server();
        let frame = hello_with("0.1.0", 999, "default", XACE_PROTOCOL_VERSION);
        let reject_frame = hs.process_hello_frame(&frame).unwrap();

        assert_eq!(hs.state(), HandshakeState::Rejected);
        let result = ProtocolHandshake::parse_response_frame(&reject_frame).unwrap();
        assert_eq!(
            result.reject_reason(),
            Some(&RejectReason::ExecutionPlanVersionMismatch)
        );
    }

    #[test]
    fn plan_reject_carries_expected_and_received_plan_versions() {
        let mut hs = ProtocolHandshake::new_server("0.1.0", 5, "default", 1);
        let frame = hello_with("0.1.0", 3, "default", XACE_PROTOCOL_VERSION);
        let reject_frame = hs.process_hello_frame(&frame).unwrap();
        let reject = parse_reject(&reject_frame);

        assert_eq!(reject.expected_execution_plan_version, 5);
        assert!(reject.detail.contains("3"), "Detail must mention received plan version");
    }

    // =========================================================================
    // World ID Mismatch
    // =========================================================================

    #[test]
    fn wrong_world_id_produces_world_id_mismatch_reject() {
        let mut hs = server();
        let frame = hello_with("0.1.0", 1, "wrong-world", XACE_PROTOCOL_VERSION);
        let reject_frame = hs.process_hello_frame(&frame).unwrap();

        let result = ProtocolHandshake::parse_response_frame(&reject_frame).unwrap();
        assert_eq!(result.reject_reason(), Some(&RejectReason::WorldIdMismatch));
    }

    #[test]
    fn world_id_reject_carries_expected_world_id() {
        let mut hs = ProtocolHandshake::new_server("0.1.0", 1, "session-xyz", 1);
        let frame = hello_with("0.1.0", 1, "session-abc", XACE_PROTOCOL_VERSION);
        let reject_frame = hs.process_hello_frame(&frame).unwrap();
        let reject = parse_reject(&reject_frame);
        assert_eq!(reject.expected_world_id, "session-xyz");
    }

    // =========================================================================
    // Wrong Message Type
    // =========================================================================

    #[test]
    fn non_control_message_type_produces_unexpected_type_reject() {
        let mut hs = server();
        // Send a DELTA where a CONTROL/Hello is expected
        let msg = WireMessage::delta("default", "0.1.0", 1, 0, 0, r#"{"not":"hello"}"#);
        let mut ser = MessageSerializer::new();
        let frame = ser.serialize_unchecked(&msg).unwrap();
        let reject_frame = hs.process_hello_frame(&frame).unwrap();

        let result = ProtocolHandshake::parse_response_frame(&reject_frame).unwrap();
        assert_eq!(result.reject_reason(), Some(&RejectReason::UnexpectedMessageType));
    }

    // =========================================================================
    // Malformed Payload
    // =========================================================================

    #[test]
    fn garbage_control_payload_returns_err() {
        let mut hs = server();
        let msg = WireMessage::control(
            "default", "0.1.0", 1, 0, r#"{"not_hello":"garbage_data"}"#,
        );
        let mut ser = MessageSerializer::new();
        let frame = ser.serialize_unchecked(&msg).unwrap();
        // Cannot produce a Reject from completely unparseable content
        let result = hs.process_hello_frame(&frame);
        assert!(result.is_err());
    }

    #[test]
    fn incomplete_frame_bytes_return_err() {
        let mut hs = server();
        let partial = &valid_hello("Unity")[..3];
        assert!(hs.process_hello_frame(partial).is_err());
    }

    // =========================================================================
    // Full Client-Server Round-Trip
    // =========================================================================

    #[test]
    fn full_round_trip_accepted_all_engines() {
        for engine in &["Unity-2022", "Godot-4", "UnrealEngine-5"] {
            let hello = ProtocolHandshake::build_hello_frame(
                "0.1.0", 1, "default", engine, "1.0.0",
            ).unwrap();

            let mut srv = ProtocolHandshake::new_server("0.1.0", 1, "default", 10);
            let ack = srv.process_hello_frame(&hello).unwrap();
            assert!(srv.is_accepted(), "Server must accept {}", engine);

            let client_result = ProtocolHandshake::parse_response_frame(&ack).unwrap();
            assert!(client_result.is_accepted(), "Client must see Accepted for {}", engine);
        }
    }

    #[test]
    fn full_round_trip_rejected_schema_mismatch() {
        let hello = ProtocolHandshake::build_hello_frame(
            "0.9.0", 1, "default", "Unity", "1.0.0",
        ).unwrap();

        let mut srv = ProtocolHandshake::new_server("0.1.0", 1, "default", 1);
        let reject_frame = srv.process_hello_frame(&hello).unwrap();
        assert!(srv.is_rejected());

        let result = ProtocolHandshake::parse_response_frame(&reject_frame).unwrap();
        assert!(!result.is_accepted());
        assert_eq!(result.reject_reason(), Some(&RejectReason::SchemaVersionMismatch));
    }

    #[test]
    fn all_three_version_fields_checked_independently() {
        // Verify each field can independently cause rejection by testing one at a time
        let cases: Vec<(&str, u32, &str, u32, RejectReason)> = vec![
            // (schema, plan, world, proto, expected_rejection)
            ("9.9.9", 1, "default", XACE_PROTOCOL_VERSION,
             RejectReason::SchemaVersionMismatch),
            ("0.1.0", 999, "default", XACE_PROTOCOL_VERSION,
             RejectReason::ExecutionPlanVersionMismatch),
            ("0.1.0", 1, "wrong", XACE_PROTOCOL_VERSION,
             RejectReason::WorldIdMismatch),
        ];

        for (schema, plan, world, proto, expected_reason) in cases {
            let mut hs = server();
            let frame = hello_with(schema, plan, world, proto);
            let reject_frame = hs.process_hello_frame(&frame).unwrap();
            let result = ProtocolHandshake::parse_response_frame(&reject_frame).unwrap();
            assert_eq!(
                result.reject_reason(),
                Some(&expected_reason),
                "Expected {:?} for schema={} plan={} world={} proto={}",
                expected_reason, schema, plan, world, proto
            );
        }
    }

    // =========================================================================
    // State and Display
    // =========================================================================

    #[test]
    fn initial_state_is_awaiting_hello() {
        let hs = server();
        assert_eq!(hs.state(), HandshakeState::AwaitingHello);
        assert!(hs.result().is_none());
    }

    #[test]
    fn reject_reason_display_values() {
        assert_eq!(RejectReason::ProtocolVersionMismatch.to_string(),     "PROTOCOL_VERSION_MISMATCH");
        assert_eq!(RejectReason::SchemaVersionMismatch.to_string(),       "SCHEMA_VERSION_MISMATCH");
        assert_eq!(RejectReason::ExecutionPlanVersionMismatch.to_string(),"EXECUTION_PLAN_VERSION_MISMATCH");
        assert_eq!(RejectReason::WorldIdMismatch.to_string(),             "WORLD_ID_MISMATCH");
        assert_eq!(RejectReason::UnexpectedMessageType.to_string(),       "UNEXPECTED_MESSAGE_TYPE");
        assert_eq!(RejectReason::MalformedPayload.to_string(),            "MALFORMED_PAYLOAD");
    }

    #[test]
    fn handshake_state_display_values() {
        assert_eq!(HandshakeState::AwaitingHello.to_string(), "AWAITING_HELLO");
        assert_eq!(HandshakeState::Completed.to_string(),     "COMPLETED");
        assert_eq!(HandshakeState::Rejected.to_string(),      "REJECTED");
    }
}