"""NEC-007 source-bound migration previews. No commit, native launch or writes.

Never use a source name as a gameplay classification. User choices are mandatory
for semantic roles, extra component values, mode settings and package selection.
Native captures and identity maps are supplied by the trusted editor host.
"""
from __future__ import annotations
import copy
import hashlib
import importlib
import json
from dataclasses import dataclass
from pathlib import Path
import subprocess
import sys

from authoring_identity import IdentityMap, require, exact
from native_authoring_contract import parse, Snapshot
from native_authoring_values import integer

ROOT = Path(__file__).resolve().parents[2]
for path in (ROOT, ROOT / "packages"):
    if str(path) not in sys.path: sys.path.append(str(path))
_gde = importlib.import_module("gde.src.domain_dsl.typed_operations.native_adoption_operations")
factory = importlib.import_module("schema-factory.src.portable_compilation")
from tools.cgs_schema_validate import compute_cgs_hash
encode, digest = _gde.encode, _gde.digest
SCHEMA = "xace.native_adoption_plan.v1"


def actor_id(mapping, key):
    return "native_" + mapping.namespace_id + "_" + key


def bridge(engine):
    require(engine in {"unity", "godot", "unreal"}, "unsupported native engine")
    return importlib.import_module(engine + "_authoring")


def _asset_source(engine, path):
    require(type(path) is str, "linked asset needs a native locator")
    if engine == "godot":
        require(path.startswith("res://"), "project Godot resource required"); path = path[6:]
    elif engine == "unreal":
        require(path.startswith("/Game/") and "." in path, "project Unreal resource required")
        path = "Content/" + path[6:].split(".")[0] + ".uasset"
    require(not path.startswith(("/", "\\")) and ":" not in path and "\\" not in path
            and all(p not in {"", ".", ".."} for p in path.split("/")), "invalid native asset path")
    return path


def _closure(keys, rows, mapping):
    pending = list(keys); result = set()
    while pending:
        key = pending.pop()
        require(key in rows and not rows[key]["deleted"], "missing live adoption dependency")
        if key in result: continue
        result.add(key); record = mapping.objects[key]
        pending.extend(r for r in (record.scene_id, record.prefab_id, rows[key]["parent_id"]) if r)
        pending.extend(edge["target"] for edge in rows[key]["dependencies"])
    return sorted(result)


@dataclass(frozen=True)
class AdoptionPlan:
    payload: bytes

    @property
    def sha256(self): return hashlib.sha256(self.payload).hexdigest()

    def to_dict(self): return json.loads(self.payload)


def plan_adoption(native_inventory: bytes, mapping: IdentityMap, current_cgs: dict, *,
                  selection: list[str], choices: dict, expected_source_digest: str,
                  expected_cgs_digest: str, trusted_project: bool,
                  accepted_loss_digest: str | None = None, gameplay_catalog=None,
                  native_target: Snapshot | None = None) -> AdoptionPlan:
    """Deterministic data-only preview. Blocked plans retain itemized manual work.

    Source/CGS freshness is checked before deriving any records. A planner result
    cannot authorize persistence, runtime activation or a reconciliation baseline.
    """
    require(trusted_project is True, "trusted native extraction required")
    require(hashlib.sha256(native_inventory).hexdigest() == expected_source_digest, "stale native source")
    require(digest(current_cgs) == expected_cgs_digest, "stale current CGS")
    require(current_cgs.get("metadata", {}).get("cgs_hash") == compute_cgs_hash(current_cgs), "invalid current CGS hash")
    reader = bridge(mapping.engine)
    inspected = reader.capture(native_inventory, mapping, enable_writes=True)
    inspection = parse(inspected.payload); rows = inspection["normalized"]
    require(type(selection) is list and selection and selection == sorted(set(selection))
            and len(selection) <= 128, "select 1..128 unique sorted native objects")
    require(all(k in rows and mapping.objects[k].kind not in {"scene", "prefab_definition"}
                and not rows[k]["deleted"] for k in selection), "select live native instances")
    exact(choices, {"mode_id", "new_mode", "world_contract", "objects", "packages", "legacy_dispositions"})
    _gde.identifier(choices["mode_id"]); mode_id = choices["mode_id"]
    require(type(choices["objects"]) is dict and set(choices["objects"]) == set(selection), "each selected object needs explicit choices")
    require(type(choices["packages"]) is list and len(choices["packages"]) <= 32, "package selection limit")
    for raw in choices["packages"]:
        require(gameplay_catalog is not None and type(raw) is dict and raw.get("kind") == "install_gameplay_package", "host typed package selection required")
        descriptor = gameplay_catalog.resolve(raw["package_id"], raw["package_hash"])
        require(not descriptor["capability_declarations"] and not raw.get("capability_targets"), "adoption package capability materialization requires a separate reviewed World mapping")
    scope = _closure(selection, rows, mapping)
    losses = [copy.deepcopy(r) for r in inspection["losses"] if not r["object_id"] or r["object_id"] in scope]
    def loss(code, key="", field="", severity="blocking", detail=""):
        losses.append(dict(code=code, object_id=key, field=field, severity=severity, detail=detail))
    if any(r["severity"] == "review" for r in losses):
        if accepted_loss_digest != inspected.loss_digest: loss("unreviewed_precision_loss")
    else: require(accepted_loss_digest is None, "unexpected precision acknowledgement")
    # A review is bound to a particular native behavior hash; it cannot claim code was disabled.
    dispositions = choices["legacy_dispositions"]
    require(type(dispositions) is list, "legacy dispositions must be a list")
    manual = []; seen = set()
    for item in dispositions:
        exact(item, {"object_id", "opaque_id", "sha256", "action"})
        key = item["object_id"]; pair = (key, item["opaque_id"])
        require(pair not in seen and key in rows, "duplicate/unknown legacy disposition"); seen.add(pair)
        opaque = next((o for o in rows[key]["opaque"] if o["id"] == item["opaque_id"]), None)
        require(opaque is not None and opaque["sha256"] == item["sha256"], "stale legacy behavior review")
        require(item["action"] in {"retain_native", "exclude", "disable_before_play"}, "unsupported legacy disposition")
        manual.append(dict(item, executable=False, verification="native recapture required"))
    for key in scope:
        for opaque in rows[key]["opaque"]:
            if opaque["critical"] and (key, opaque["id"]) not in seen: loss("legacy_review_required", key, opaque["id"])
    operations = []; provenance = []; assets = {}; desired = []; playback_bindings = {}
    existing_mode = next((m for m in current_cgs["modes"] if m["id"] == mode_id), None)
    def emit(kind, **values):
        operations.append(dict(operation_id="adopt." + str(len(operations)), kind=kind, **values))
    if existing_mode is None:
        mode = choices["new_mode"]
        require(type(mode) is dict and mode.get("id") == mode_id, "explicit empty mode settings required")
        emit("create_mode", mode=copy.deepcopy(mode)); existing_mode = mode
    else: require(choices["new_mode"] is None or choices["new_mode"]["id"] == mode_id, "mode choice mismatch")
    contract = existing_mode.get("world", {}).get("contract")
    if contract is None:
        contract = choices["world_contract"]
        require(type(contract) is dict and contract.get("contract_version") == 3 and contract.get("objects") == [], "explicit empty World v3 schema required")
        emit("initialize_world", mode_id=mode_id, contract=copy.deepcopy(contract))
    elif choices["world_contract"] is not None:
        require({k:v for k,v in contract.items() if k != "objects"} ==
                {k:v for k,v in choices["world_contract"].items() if k != "objects"}, "World declaration conflict")
    existing_actors = _gde.index(existing_mode["actors"])
    existing_objects = _gde.index(contract["objects"])
    registered_assets = _gde.index(current_cgs.get("assets", []))
    from native_instance_transforms import PROFILE as hierarchy_profile, resolve as resolve_hierarchy
    declared_profile=current_cgs.get('native_instance_profile')
    require(declared_profile is None or declared_profile==hierarchy_profile,'Unsupported native instance profile')
    hierarchy_world=None
    if declared_profile==hierarchy_profile:
        try:
            local={key:dict(**{name:{axis:integer(value) for axis,value in rows[key]['fields']['transform.'+name].items()} for name in ['position','rotation','scale']},parent_entity_id=0) for key in selection}
            hierarchy_world=resolve_hierarchy(local,{key:rows[key]['parent_id'] for key in selection})
        except (ValueError,KeyError,TypeError):loss('hierarchy_profile_refused')
    for key in selection:
        choice = choices["objects"][key]
        exact(choice, {"actor_type", "control_type", "components", "semantic_type", "properties", "capabilities", "geometry_profile", "asset_role", "playback"})
        fields = rows[key]["fields"]; aid = actor_id(mapping, key)
        require(type(choice["components"]) is list, "explicit component records required")
        require(all(c.get("type_id") != 1 for c in choice["components"]), "native transform cannot be overridden")
        required = {"transform.position", "transform.rotation", "transform.scale"}
        if not required <= fields.keys():
            loss("incomplete_transform", key); continue
        transform = {name: {axis: integer(value) for axis, value in fields["transform."+name].items()}
                     for name in ("position", "rotation", "scale")}
        transform["parent_entity_id"] = 0
        if hierarchy_world is not None:transform=hierarchy_world[key]
        parent = rows[key]["parent_id"]
        relationships = {}
        if parent is not None:
            # Never smuggle an authoring ID into a runtime EntityID field.
            if hierarchy_world is None:loss("runtime_parent_binding_required", key, "parent_id")
            if parent in selection: relationships[_gde.PARENT_ROLE] = [actor_id(mapping, parent)]
            else: loss("parent_not_selected", key, "parent_id")
        bindings = {}
        ref = fields.get("presentation.asset")
        if ref:
            require(choice["asset_role"] is not None, "explicit presentation role required")
            asset = dict(id=ref["asset_id"], asset_type=ref["asset_type"], status=ref["status"],
                         source=_asset_source(mapping.engine, ref["resolved_path"]) if ref["status"] == "LINKED" else "")
            require(asset["id"] not in assets or assets[asset["id"]] == asset, "ambiguous native asset")
            assets[asset["id"]] = asset
            bindings[choice["asset_role"]] = {k:asset[k] for k in ("id", "asset_type", "status")}
            provenance.append(dict(target="assets."+asset["id"], origin="native_capture", object_id=key, field="presentation.asset", source_value=copy.deepcopy(ref)))
            if ref["status"] != "LINKED": loss("asset_not_ready", key, "presentation.asset")
        else: require(choice["asset_role"] is None, "presentation role has no native asset")
        playback = fields.get("binding.playback")
        if choice["playback"] is not None:
            require(playback is not None, "playback choice has no captured binding")
            option = choice["playback"]
            exact(option, {"semantic_action", "entity_selector", "parameters", "enabled", "priority"})
            ref = playback["asset"]
            asset = dict(id=ref["asset_id"],asset_type=ref["asset_type"],status=ref["status"],source=_asset_source(mapping.engine,ref["resolved_path"]) if ref["status"] == "LINKED" else "")
            require(asset["id"] not in assets or assets[asset["id"]] == asset, "ambiguous playback asset"); assets[asset["id"]] = asset
            option = copy.deepcopy(option)
            require("resource_path" not in option["parameters"] or option["parameters"]["resource_path"] == ref["resolved_path"], "playback locator differs from capture")
            option["parameters"]["resource_path"] = ref["resolved_path"]
            binding = dict(binding_id=playback["binding_id"],event_name=playback["event_name"],playback_kind=playback["playback_kind"],asset=dict(id=asset["id"],asset_type="".join(part.title() for part in asset["asset_type"].split("_")),status=asset["status"].title()),**copy.deepcopy(option))
            require(binding["binding_id"] not in playback_bindings or playback_bindings[binding["binding_id"]] == binding, "conflicting playback binding")
            playback_bindings[binding["binding_id"]] = binding
            provenance.append(dict(target="semantic_bindings."+binding["binding_id"],origin="native_capture_and_explicit_user_choice",object_id=key,source_value=copy.deepcopy(playback),choice=copy.deepcopy(option)))
            if ref["status"] != "LINKED": loss("asset_not_ready", key, "binding.playback")
        actor = dict(id=aid, actor_type=copy.deepcopy(choice["actor_type"]), control_type=choice["control_type"], spawn_count=1,
                     components=[dict(type_id=1, name="COMP_TRANSFORM_V1", defaults=transform)] + copy.deepcopy(choice["components"]))
        obj = dict(id=aid, actor_id=aid, instance_index=0, semantic_type=choice["semantic_type"], properties=copy.deepcopy(choice["properties"]),
                   capabilities=copy.deepcopy(choice["capabilities"]), relationships=relationships, asset_bindings=bindings, geometry_profile=choice["geometry_profile"])
        desired.append((key, actor, obj))
        for name in sorted(required):
            record=dict(target=aid+".components.1."+name[10:], origin="native_capture", object_id=key, field=name, source_value=copy.deepcopy(fields[name]))
            if hierarchy_world is not None:
                record.update(origin="declared_static_hierarchy_projection", profile=hierarchy_profile, projected_value=copy.deepcopy(transform[name[10:]]))
            provenance.append(record)
        provenance.append(dict(target=aid+".authoring_parent", origin="native_capture", object_id=key, source_value=parent, runtime_binding=("resolved_static_world" if hierarchy_world is not None else "unassigned") if parent else "root"))
        provenance.append(dict(target=aid+".classification_components_world", origin="explicit_user_choice", object_id=key, source_value=copy.deepcopy(choice)))
        for name in fields:
            if name in required or name == "presentation.asset" or (name == "binding.playback" and choice["playback"] is not None): continue
            if name.startswith("native."): loss("native_owned_retained", key, name, "info")
            else: loss("unmapped_native_field", key, name, "blocking", "No gameplay behavior is inferred; retain native and review separately")
    for aid, asset in sorted(assets.items()):
        if aid in registered_assets:
            require(registered_assets[aid] == {k:v for k,v in asset.items() if k != "source" or v}, "existing asset conflicts with adoption")
        else:
            raw = dict(operation_id="asset."+aid, kind="add_asset", explanation="Register captured native asset", asset_id=aid,
                       asset_type=asset["asset_type"], status=asset["status"], source=asset["source"])
            emit("legacy", operation=raw)
    existing_bindings = _gde.index(current_cgs.get("semantic_bindings", {}).get("bindings", []), "binding_id")
    for bid,binding in sorted(playback_bindings.items()):
        if bid in existing_bindings: require(existing_bindings[bid] == binding, "existing playback binding differs; reconciliation required")
        else: emit("set_playback_binding", binding_id=bid, expected_digest=None, binding=binding)
    installed_packages = set()
    package_components = {}
    for raw in choices["packages"]:
        require(gameplay_catalog is not None, "host gameplay catalog required")
        require(type(raw) is dict and raw.get("kind") == "install_gameplay_package", "typed package selection required")
        descriptor = gameplay_catalog.resolve(raw["package_id"], raw["package_hash"])
        require(raw.get("template_id") == "", "adoption never fabricates a catalog template")
        tids = {s["type_id"] for s in descriptor["component_schemas"]}
        for aid in raw["actor_ids"]: package_components.setdefault(aid, set()).update(tids)
        if any(m["id"] == mode_id for m in current_cgs["modes"]) and all(aid in existing_actors for aid in raw["actor_ids"]):
            stripped = copy.deepcopy(current_cgs)
            mode = next(m for m in stripped["modes"] if m["id"] == mode_id)
            for actor in mode["actors"]:
                if actor["id"] in raw["actor_ids"]: actor["components"] = [c for c in actor["components"] if c["type_id"] not in tids]
            system_ids = {s["id"] for s in descriptor["systems"]}
            mode["systems"] = [s for s in mode["systems"] if s["id"] not in system_ids]
            try: reapplied = _gde.TypedOperationExecutor(gameplay_catalog).execute(dict(schema="xace.typed_cgs_operation_batch.v1",request_id="nec.adoption",prompt_id="nec.adoption",summary="Verify repeated package adoption",operations=[raw]),stripped).proposed_cgs
            except ValueError: reapplied = None
            if reapplied is not None:
                # Reapplication appends records; restore the original ordering before
                # comparing so multiple independent packages also repeat as a no-op.
                replay_mode = next(m for m in reapplied["modes"] if m["id"] == mode_id)
                system_order = {s["id"]:i for i,s in enumerate(existing_mode["systems"])}
                replay_mode["systems"].sort(key=lambda s:system_order.get(s["id"],len(system_order)))
                for actor in replay_mode["actors"]:
                    order = {c["type_id"]:i for i,c in enumerate(existing_actors[actor["id"]]["components"])}
                    actor["components"].sort(key=lambda c:order.get(c["type_id"],len(order)))
                reapplied["metadata"]["cgs_hash"] = compute_cgs_hash(reapplied)
            if reapplied == current_cgs: installed_packages.add(digest(raw))
    for key, actor, obj in desired:
        if actor["id"] in existing_actors:
            existing = copy.deepcopy(existing_actors[actor["id"]])
            existing["components"] = [c for c in existing["components"] if c["type_id"] not in package_components.get(actor["id"], set())]
            require(existing == actor, "existing actor differs; reconciliation required")
        else: emit("create_actor", mode_id=mode_id, actor=actor)
        if obj["id"] in existing_objects:
            require(existing_objects[obj["id"]] == obj, "existing World object differs; reconciliation required")
        else: emit("create_world_object", mode_id=mode_id, object=obj)
    for raw in choices["packages"]:
        require(type(raw) is dict and raw.get("kind") == "install_gameplay_package" and raw.get("mode_id") == mode_id
                and raw.get("template_id") == "" and set(raw.get("actor_ids", [])) <= {a["id"] for _,a,_ in desired}, "package must target the explicitly adopted slice without a template")
        if digest(raw) not in installed_packages: emit("legacy", operation=copy.deepcopy(raw))
        provenance.append(dict(target="package."+raw["package_id"], origin="explicit_user_choice", source_value=copy.deepcopy(raw)))
    batch = dict(schema=_gde.SCHEMA, expected_cgs_digest=expected_cgs_digest, operations=operations)
    candidate = None; compiled = None
    try:
        result = _gde.NativeAdoptionExecutor(validate=factory.compile_portable_cgs, gameplay_catalog=gameplay_catalog).execute(batch, current_cgs)
        candidate = result.proposed_cgs; package = factory.compile_portable_cgs(candidate)
        systems = package.to_sgc_input()
        for system in systems:
            if 1 in system.get("reads", []) or 1 in system.get("writes", []):
                loss("uncertified_structured_transform_system", field=system["id"], detail="Native World transforms require a separately verified structured-field executor contract")
        compiled = dict(cgs_hash=package.cgs_hash, systems=systems,
                        world=package.world_contract.content() if package.world_contract else None)
    except (ValueError, TypeError, KeyError) as exc:
        loss("gde_factory_rejected", detail=str(exc)[:1024])
    native_writes = []
    if native_target is not None:
        base = inspected.admit(accepted_loss_digest)
        native_writes.append(json.loads(reader.write_request(native_inventory, base, native_target, mapping)))
    scope_dispositions = [dict(object_id=k, disposition="adopt" if k in selection else "required_native_dependency" if k in scope else "excluded_native",
                              native_unchanged=True) for k in sorted(rows)]
    report = dict(schema=SCHEMA, preview_only=True, can_commit=False, play_eligible=False,
                  eligibility_reason="Preview only; coordinator, native readiness and activation gates remain required",
                  source_digest=expected_source_digest, source=copy.deepcopy(inspection["capture"]["source"]),
                  mapping_digest=mapping.mapping_digest(), current_cgs_digest=expected_cgs_digest,
                  choice_digest=digest(choices), choices=copy.deepcopy(choices),
                  mapping_profile=dict(version="native.adoption.mapping.v1",actor_id="native_<namespace>_<authoring_id>",spawn_count=1,instance_index=0,numeric_profile=inspection["numeric_profile"]),
                  accepted_loss_digest=accepted_loss_digest, selected=selection, dependency_closure=scope,
                  dispositions=scope_dispositions, legacy_disablement_plan=manual,
                  losses=sorted(losses, key=encode), provenance=provenance,
                  typed_operations=batch, proposed_cgs=candidate, compiled=compiled,
                  native_write_preview=native_writes, noop=not operations and not native_writes,
                  candidate_valid=candidate is not None and not any(r["severity"] == "blocking" for r in losses))
    return AdoptionPlan(encode(report))


def verify_plan(plan: AdoptionPlan, *args, **kwargs):
    """Recompute before review/use; a stored self-digest is not a trust boundary."""
    require(type(plan) is AdoptionPlan, "typed adoption plan required")
    expected = plan_adoption(*args, **kwargs)
    require(plan.payload == expected.payload, "stale/tampered adoption plan")
    return expected


def compile_execution_preview(plan: AdoptionPlan, *, sgc_executable: Path, context: dict):
    """Explicit host tool invocation; does not execute any imported project code."""
    verify_plan(plan, **context)
    report = plan.to_dict()
    require(report["candidate_valid"], "blocked adoption cannot pass execution-plan preview")
    package = factory.compile_portable_cgs(report["proposed_cgs"])
    envelope = dict(systems=package.to_sgc_input(), schema_version=package.schema_version,
                    cgs_hash=package.cgs_hash, plan_version=1)
    proc = subprocess.run([str(sgc_executable)], input=encode(envelope), capture_output=True, timeout=30)
    require(proc.returncode == 0, "SGC rejected adoption: " + proc.stderr.decode(errors="replace")[:1024])
    return dict(schema="xace.native_adoption_compilation.v1", plan_digest=plan.sha256,
                execution_plan=json.loads(proc.stdout), world=report["compiled"]["world"], activation_performed=False)
