//! Cross-module drift guard: the frozen profile references the shipped protocols.
use xace_core::wire::session_contract::*;
use xace_network_core::input::input_packet::INPUT_PACKET_SCHEMA_VERSION;
use xace_network_core::session::LAUNCH_TOPOLOGY_ID;
use xace_runtime_core::engine_protocol::{DEFAULT_TICK_RATE, PROTOCOL_VERSION};

#[test]
fn frozen_profile_reuses_existing_protocol_and_topology_versions() {
    let json: serde_json::Value = serde_json::from_str(include_str!(
        "../../core/tests/fixtures/session_contract_v1/golden_vectors.json"
    ))
    .unwrap();
    let contract: SessionContract = serde_json::from_value(json["authority"].clone()).unwrap();
    assert_eq!(SESSION_TOPOLOGY_ID, LAUNCH_TOPOLOGY_ID);
    assert_eq!(SESSION_TICK_RATE, DEFAULT_TICK_RATE);
    assert_eq!(
        contract.gameplay.runtime.engine_protocol_version,
        PROTOCOL_VERSION
    );
    assert_eq!(
        contract.gameplay.input.packet_schema_version,
        INPUT_PACKET_SCHEMA_VERSION
    );
}
