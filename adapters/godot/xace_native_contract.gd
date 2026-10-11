extends RefCounted
# XP-016 presentation/session reader. Semantic nouns/capabilities remain opaque.
const MAX_EXACT := 9007199254740991
const SUPPORTED := ["session.projection.v1", "input.timed.v1", "world.aabb.v1", "world.semantic_bindings.v3"]
var world: Dictionary = {}
var bindings: Dictionary = {}
var offer: Dictionary = {}
var credential := ""
var peer_id := 0
var player_id := 0
var controller_id := 0
var stamp: Dictionary = {}
var recovering := true
var requested_tick := -1
var sent := false
var error := ""

# Session contract v1 has integer protocol metadata only. Godot's JSON parser
# creates floats; convert exact integers before sending a typed Rust offer.
static func protocol_integers(value: Variant) -> Variant:
	if value is float and exact(value, -MAX_EXACT):
		return int(value)
	if value is Dictionary:
		var result: Dictionary = {}
		for key in value:
			result[key] = protocol_integers(value[key])
		return result
	if value is Array:
		var result: Array = []
		for item in value:
			result.append(protocol_integers(item))
		return result
	return value

static func exact(value: Variant, minimum: int = 0) -> bool:
	return (value is int or value is float) and is_finite(float(value)) and float(value) >= float(minimum) and float(value) <= float(MAX_EXACT) and floor(float(value)) == float(value)

static func vector(value: Variant) -> bool:
	return value is Dictionary and exact(value.get("x"), -MAX_EXACT) and exact(value.get("y"), -MAX_EXACT) and exact(value.get("z"), -MAX_EXACT)

static func entities_valid(entities: Variant) -> bool:
	if not entities is Array:
		return false
	var parents: Dictionary = {}
	var last := 0
	for entity in entities:
		if not entity is Dictionary or not exact(entity.get("id"), 1) or int(entity.id) <= last or not entity.get("components") is Dictionary:
			return false
		last = int(entity.id)
		var components: Dictionary = entity.components
		for key in components:
			if not str(key).is_valid_int() or int(key) <= 0 or int(key) > 4294967295 or not components[key] is String or not JSON.parse_string(components[key]) is Dictionary:
				return false
		if not components.has("1"):
			parents[last] = 0
			continue
		var transform: Variant = JSON.parse_string(str(components.get("1", "")))
		if not transform is Dictionary or not vector(transform.get("position")) or not vector(transform.get("scale")) or not exact(transform.get("parent_entity_id")):
			return false
		for axis in ["x", "y", "z"]:
			if int(transform.scale[axis]) == 0:
				return false
		var q: Variant = transform.get("rotation")
		if not vector(q) or not exact(q.get("w"), -MAX_EXACT) or (int(q.x) == 0 and int(q.y) == 0 and int(q.z) == 0 and int(q.w) == 0):
			return false
		parents[last] = int(transform.parent_entity_id)
	for id in parents:
		var seen: Dictionary = {}
		var current: int = int(id)
		while current != 0:
			if seen.has(current) or not parents.has(current):
				return false
			seen[current] = true
			current = int(parents[current])
	return true

func configure(ticket: Dictionary, world_json: String) -> bool:
	error = "Malformed or unsupported native session"
	var candidate: Variant = JSON.parse_string(str(ticket.get("offer_json", "")))
	if ticket.get("schema") != "xace.session_ticket.v1" or not candidate is Dictionary or not candidate.get("contract") is Dictionary or not candidate.get("client") is Dictionary or not exact(ticket.get("peer_id"), 1) or not exact(ticket.get("controller_id"), 1) or str(ticket.get("credential", "")).is_empty():
		return false
	var contract: Dictionary = candidate.contract
	if contract.get("schema") != "xace.session_contract.v1" or not contract.get("required_capabilities") is Array or not contract.get("epoch") is Dictionary or not exact(contract.epoch.get("ruleset_epoch")):
		return false
	for cap in contract.required_capabilities:
		if not SUPPORTED.has(cap):
			return false
	var candidate_world: Variant = JSON.parse_string(world_json)
	if not candidate_world is Dictionary or candidate_world.get("schema") != "xace.world_contract.v3" or candidate_world.get("contract_version") != 3 or world_json.sha256_text() != str(contract.get("gameplay", {}).get("world", {}).get("artifact", {}).get("content_hash", "")) or not candidate_world.get("objects") is Array or not candidate_world.get("geometry_profiles") is Array:
		return false
	for profile in candidate_world.geometry_profiles:
		if not profile is Dictionary or not profile.get("required") is bool or (profile.required and profile.get("id") != "world.aabb.v1"):
			return false
	var ids: Dictionary = {}
	for object in candidate_world.objects:
		if not object is Dictionary or not object.get("id") is String or str(object.id).is_empty() or ids.has(object.id):
			return false
		ids[object.id] = true
		var geometry: Variant = object.get("geometry")
		if geometry != null and (not geometry is Dictionary or geometry.get("profile") != "world.aabb.v1"):
			return false
	offer = protocol_integers(candidate)
	offer.client.adapter.engine = "godot"
	offer.client.capabilities = SUPPORTED.duplicate()
	world = candidate_world
	credential = str(ticket.credential)
	peer_id = int(ticket.peer_id)
	controller_id = int(ticket.controller_id)
	stamp.clear()
	bindings.clear()
	player_id = 0
	fence()
	error = ""
	return true

func _bind(map: Variant, entities: Array) -> bool:
	if not map is Dictionary:
		return false
	var by_id: Dictionary = {}
	for entity in entities:
		by_id[int(entity.id)] = entity
	var next: Dictionary = {}
	for object in world.objects:
		var raw: Variant = map.get(object.id)
		if not raw is String or not raw.is_valid_int() or not exact(int(raw), 1) or not by_id.has(int(raw)):
			return false
		var id := int(raw)
		if object.get("geometry") != null:
			var collider: Variant = JSON.parse_string(str(by_id[id].components.get("4", "")))
			if not collider is Dictionary or collider.get("shape") != "BOX":
				return false
			for field in ["size", "offset", "is_trigger", "layer_mask"]:
				# World Contract v3 defines absent collider layer_mask as layer 1.
				if collider.get(field, 1 if field == "layer_mask" else null) != object.geometry[field]:
					return false
		next[object.id] = id
	bindings = next
	return true

func verify(message: Dictionary) -> String:
	error = "Invalid live projection"
	var initial: bool = message.get("msg_type") == "handshake_ack"
	var baseline: bool = message.get("msg_type") == "session_baseline"
	var candidate: Variant = JSON.parse_string(str(message.get("sync_json", "")))
	if not candidate is Dictionary or candidate.size() != 9 or candidate.get("schema") != "xace.session_projection.v1" or str(candidate.get("baseline_id", "")).is_empty():
		return "reject"
	for key in ["session_id", "authority_incarnation", "ruleset_epoch"]:
		if candidate.get(key) != offer.contract.epoch.get(key):
			return "reject"
	for key in ["connection_generation", "sequence", "next_tick", "ruleset_epoch"]:
		if not exact(candidate.get(key), 0 if key in ["next_tick", "ruleset_epoch"] else 1):
			return "reject"
	var generation := int(candidate.connection_generation)
	var sequence := int(candidate.sequence)
	var tick := int(candidate.next_tick)
	if (initial and generation <= int(stamp.get("connection_generation", 0))) or (not initial and (generation != int(stamp.get("connection_generation", 0)) or sequence <= int(stamp.get("sequence", 0)))):
		return "drop"
	if not initial and not baseline and (recovering or sequence != int(stamp.get("sequence", 0)) + 1 or tick != int(stamp.get("next_tick", 0)) + 1):
		fence()
		return "recover"
	var raw := str(message.get("projection_json", ""))
	var entities: Variant = JSON.parse_string(raw)
	if not entities is Array or raw.sha256_text() != str(candidate.get("projection_digest", "")):
		if initial:
			return "reject"
		fence()
		return "recover"
	if not entities_valid(entities):
		return "reject"
	if not initial and tick < int(stamp.get("next_tick", 0)):
		return "drop"
	if initial:
		for key in ["session_id", "authority_incarnation", "ruleset_epoch"]:
			if message.get(key) != offer.contract.epoch.get(key):
				return "reject"
		if message.get("cgs_hash") != offer.contract.gameplay.cgs.cgs_hash:
			return "reject"
		if not exact(message.get("assigned_player_id"), 1) or message.get("assigned_peer_id") != peer_id or (player_id != 0 and int(message.assigned_player_id) != player_id) or str(message.get("reconnect_credential", "")).is_empty():
			return "reject"
		var owned := false
		for entity in entities:
			if int(entity.id) == int(message.assigned_player_id):
				var input: Variant = JSON.parse_string(str(entity.components.get("6", "")))
				owned = input is Dictionary and input.get("controller_id") == controller_id and input.get("control_type") == "HUMAN"
		if not owned or not _bind(message.get("world_bindings"), entities):
			return "reject"
		player_id = int(message.assigned_player_id)
		credential = str(message.reconnect_credential)
	elif not baseline and (not exact(message.get("tick")) or int(message.tick) != tick - 1):
		return "reject"
	message["initial_entities" if initial else "entities"] = entities
	message["sync"] = candidate
	stamp = candidate.duplicate(true)
	recovering = false
	requested_tick = -1
	sent = false
	error = ""
	return "accept"

func request(tick: int) -> bool:
	if recovering or tick != int(stamp.get("next_tick", -1)) or requested_tick == tick:
		return false
	requested_tick = tick
	sent = false
	return true

func can_send(packet: Dictionary) -> bool:
	return not recovering and not sent and packet.get("tick") == requested_tick and requested_tick == int(stamp.get("next_tick", -1)) and packet.get("peer_id") == peer_id and packet.get("player_id") == player_id

func fence() -> void:
	recovering = true
	requested_tick = -1
