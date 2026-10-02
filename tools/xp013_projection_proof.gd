extends SceneTree

class ProbeTransport extends "res://xace_transport.gd":
	var sent: Array = []
	func _write_message(message: Dictionary) -> bool:
		sent.append(message)
		return true

func frame(generation: int, sequence: int, tick: int, kind: String = "tick_snapshot") -> Dictionary:
	var projection := JSON.stringify([{"id":1,"actor_id":"arbitrary_object","components":{"2":"{\"entity_name\":\"arbitrary_object\"}"}}])
	var stamp := {"schema":"xace.session_projection.v1","session_id":"session","authority_incarnation":"authority","ruleset_epoch":0,"connection_generation":generation,"baseline_id":"baseline-"+str(generation)+"-"+str(sequence),"sequence":sequence,"next_tick":tick,"projection_digest":projection.sha256_text()}
	return {"msg_type":kind,"sync_json":JSON.stringify(stamp),"projection_json":projection,"tick":tick-1}

func _initialize() -> void:
	var transport := ProbeTransport.new()
	transport.session_offer_json = JSON.stringify({"contract":{"epoch":{"session_id":"session","authority_incarnation":"authority","ruleset_epoch":0}}})
	assert(transport._verify_projection(frame(1,1,10,"handshake_ack"),true))
	assert(not transport._verify_projection(frame(1,1,10),false))
	assert(not transport._verify_projection(frame(1,3,12),false))
	assert(transport.sent.back().msg_type == "resync_request")
	assert(transport._projection_stamp.next_tick == 10)
	var corrupt := frame(1,2,11)
	corrupt.projection_json = "[]"
	assert(not transport._verify_projection(corrupt,false))
	assert(transport._projection_stamp.next_tick == 10)
	assert(transport._verify_projection(frame(1,3,12,"session_baseline"),false))
	assert(not transport._verify_projection(frame(1,2,11),false))
	assert(not transport._verify_projection(frame(1,1,0,"handshake_ack"),true))
	assert(transport._verify_projection(frame(2,1,12,"handshake_ack"),true))
	assert(not transport._verify_projection(frame(1,4,13),false))
	assert(transport._projection_stamp.next_tick == 12)
	transport.free()
	print("XP-013 Player projection proof: stale generation, stale baseline, gap, corrupted digest and verified recovery PASS")
	quit(0)
