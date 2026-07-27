"""
animation_contract_generator.py — Generates AnimationContract from COMP_ANIMATION_V2.

CLAUDE.md Audit 2: "animation_contract_generator.py — generates Animation
Contract from COMP_ANIMATION_V2 data."

## What This Generator Does
Reads COMP_ANIMATION_V2 component data from the CGS actor definition and
produces a complete AnimationContract that tells the engine adapter exactly
what the animation system requires.

## Input: COMP_ANIMATION_V2 (Audit 3 full spec)
```
controller_ref: AssetReference (ANIMATION_CONTROLLER type)
playback_speed: float
layers: dict { layer_name: { current_state, weight, mask, additive } }
parameters: dict { param_name: { value, type(BOOL/FLOAT/INT/TRIGGER) } }
blend_parameters: dict { tree_name: { x_parameter, y_parameter, blend_type } }
pending_events: list [{ event_id, state_name, trigger_at_normalized_time,
                        game_event_type, payload, is_consumed }]
ik_enabled: bool
```

## Output: AnimationContract
A versioned specification sent to the engine adapter at connection time
so it can validate its AnimationController asset matches what XACE expects.

## COMP_IK_V1 Integration (Audit 3)
If the actor definition also includes COMP_IK_V1, the generator extracts
the IK configuration and includes it in the contract's ik_config field.

## Contract Caching
Generated contracts are cached by (actor_id, schema_version). If neither
the actor definition nor the schema version has changed, the cached
contract is returned without re-generation.

## Error Handling
If COMP_ANIMATION_V2 is missing from an actor, returns None.
If required fields are absent or malformed, raises ValueError with
a specific message identifying the problematic field.
"""

from __future__ import annotations

from typing import Optional

from animation_contract import (
    AnimationContract,
    AnimationParameterType,
    BlendType,
    ContractAnimationEvent,
    ContractBlendTree,
    ContractIKConfig,
    ContractLayer,
    ContractParameter,
)

# ── COMP_ANIMATION_V2 type_id (from DCL character/ domain, type_id 121)
COMP_ANIMATION_V2_TYPE_ID = 121
COMP_IK_V1_TYPE_ID        = 122


# ── Generator ─────────────────────────────────────────────────────────────────

class AnimationContractGenerator:
    """
    Generates AnimationContract values from COMP_ANIMATION_V2 component data.

    ## Usage
    ```python
    generator = AnimationContractGenerator(schema_version="0.1.0")

    # actor_components is a dict of {type_id: component_data_dict}
    contract = generator.generate(
        actor_id="character_knight",
        controller_asset_id="character_knight_anim_v1",
        actor_components=actor_definition.components,
    )
    ```
    """

    def __init__(self, schema_version: str = "0.1.0") -> None:
        self._schema_version = schema_version
        # Cache: (actor_id, schema_version) → AnimationContract
        self._cache: dict[tuple[str, str], AnimationContract] = {}
        self._generation_count: int = 0

    # ── Primary API ───────────────────────────────────────────────────────

    def generate(
        self,
        actor_id: str,
        controller_asset_id: str,
        actor_components: dict,
        force_regenerate: bool = False,
    ) -> Optional[AnimationContract]:
        """
        Generates an AnimationContract from COMP_ANIMATION_V2 data.

        Args:
            actor_id: The actor archetype ID (e.g. "character_knight").
            controller_asset_id: The animation controller asset_id.
            actor_components: Dict of {component_type_id: component_data_dict}
                              from the actor definition in the CGS.
            force_regenerate: If True, bypasses the cache and regenerates.

        Returns:
            AnimationContract if COMP_ANIMATION_V2 is present, else None.

        Raises:
            ValueError if COMP_ANIMATION_V2 data is malformed.
        """
        cache_key = (actor_id, self._schema_version)

        # Return cached contract if available and not forced
        if not force_regenerate and cache_key in self._cache:
            return self._cache[cache_key]

        # Extract COMP_ANIMATION_V2 data
        anim_data = actor_components.get(COMP_ANIMATION_V2_TYPE_ID)
        if anim_data is None:
            return None  # Actor has no animation component

        # Extract COMP_IK_V1 data if present
        ik_data = actor_components.get(COMP_IK_V1_TYPE_ID)

        # Determine next contract version
        existing = self._cache.get(cache_key)
        next_version = (existing.contract_version + 1) if existing else 1

        contract = self._build_contract(
            actor_id=actor_id,
            controller_asset_id=controller_asset_id,
            anim_data=anim_data,
            ik_data=ik_data,
            contract_version=next_version,
        )

        self._cache[cache_key] = contract
        self._generation_count += 1
        return contract

    def generate_from_component_json(
        self,
        actor_id: str,
        controller_asset_id: str,
        anim_component_json: dict,
        ik_component_json: Optional[dict] = None,
    ) -> AnimationContract:
        """
        Generates directly from deserialized COMP_ANIMATION_V2 JSON.

        Used when the component data is already available as a dict
        rather than going through the actor_components lookup.
        """
        return self._build_contract(
            actor_id=actor_id,
            controller_asset_id=controller_asset_id,
            anim_data=anim_component_json,
            ik_data=ik_component_json,
            contract_version=1,
        )

    def invalidate_cache(self, actor_id: str) -> None:
        """
        Removes the cached contract for the given actor.
        Call when COMP_ANIMATION_V2 or COMP_IK_V1 is modified for an actor.
        """
        key = (actor_id, self._schema_version)
        self._cache.pop(key, None)

    def invalidate_all(self) -> None:
        """Clears the entire contract cache. Called on schema version bump."""
        self._cache.clear()

    # ── Inspection ────────────────────────────────────────────────────────

    def generation_count(self) -> int:
        return self._generation_count

    def cached_actor_ids(self) -> list[str]:
        """Returns actor_ids with cached contracts, sorted (D11)."""
        return sorted(actor_id for actor_id, _ in self._cache.keys())

    # ── Internal Build ────────────────────────────────────────────────────

    def _build_contract(
        self,
        actor_id: str,
        controller_asset_id: str,
        anim_data: dict,
        ik_data: Optional[dict],
        contract_version: int,
    ) -> AnimationContract:
        """Constructs an AnimationContract from raw component dicts."""

        layers      = self._extract_layers(anim_data)
        parameters  = self._extract_parameters(anim_data)
        blend_trees = self._extract_blend_trees(anim_data)
        events      = self._extract_animation_events(anim_data)
        ik_config   = self._extract_ik_config(ik_data) if ik_data else None

        return AnimationContract(
            actor_id=actor_id,
            controller_asset_id=controller_asset_id,
            contract_version=contract_version,
            schema_version=self._schema_version,
            layers=layers,
            parameters=parameters,
            blend_trees=blend_trees,
            animation_events=events,
            ik_config=ik_config,
        )

    def _extract_layers(self, anim_data: dict) -> list[ContractLayer]:
        """
        Extracts layer definitions from COMP_ANIMATION_V2.layers dict.

        COMP_ANIMATION_V2.layers format:
        { layer_name: { current_state, weight, mask, additive } }
        """
        layers_raw = anim_data.get("layers", {})
        if not isinstance(layers_raw, dict):
            raise ValueError(
                "COMP_ANIMATION_V2.layers must be a dict of "
                "{layer_name: {current_state, weight, mask, additive}}"
            )

        layers = []
        # Sorted for determinism (D11)
        for layer_name in sorted(layers_raw.keys()):
            layer_data = layers_raw[layer_name]
            if not isinstance(layer_data, dict):
                raise ValueError(
                    f"COMP_ANIMATION_V2.layers['{layer_name}'] must be a dict"
                )
            layers.append(ContractLayer(
                layer_name=layer_name,
                default_state=layer_data.get("current_state", "Idle"),
                required_states=layer_data.get("required_states", []),
                weight=float(layer_data.get("weight", 1.0)),
                mask=layer_data.get("mask"),
                additive=bool(layer_data.get("additive", False)),
            ))

        # If no layers defined, add a default base layer
        if not layers:
            layers.append(ContractLayer(
                layer_name="base",
                default_state="Idle",
                required_states=["Idle"],
            ))

        return layers

    def _extract_parameters(self, anim_data: dict) -> list[ContractParameter]:
        """
        Extracts parameter declarations from COMP_ANIMATION_V2.parameters dict.

        COMP_ANIMATION_V2.parameters format:
        { param_name: { value, type(BOOL/FLOAT/INT/TRIGGER) } }
        """
        params_raw = anim_data.get("parameters", {})
        if not isinstance(params_raw, dict):
            raise ValueError(
                "COMP_ANIMATION_V2.parameters must be a dict of "
                "{param_name: {value, type}}"
            )

        parameters = []
        for param_name in sorted(params_raw.keys()):  # D11
            param_data = params_raw[param_name]
            if not isinstance(param_data, dict):
                raise ValueError(
                    f"COMP_ANIMATION_V2.parameters['{param_name}'] must be a dict"
                )
            type_str = param_data.get("type", "FLOAT").upper()
            try:
                param_type = AnimationParameterType(type_str)
            except ValueError:
                raise ValueError(
                    f"Unknown animation parameter type '{type_str}' "
                    f"for parameter '{param_name}'. "
                    f"Valid types: {[t.value for t in AnimationParameterType]}"
                )
            parameters.append(ContractParameter(
                name=param_name,
                param_type=param_type,
                default_value=param_data.get("value"),
            ))

        return parameters

    def _extract_blend_trees(self, anim_data: dict) -> list[ContractBlendTree]:
        """
        Extracts blend tree declarations from COMP_ANIMATION_V2.blend_parameters.

        COMP_ANIMATION_V2.blend_parameters format:
        { tree_name: { x_parameter, y_parameter, blend_type } }
        """
        blend_raw = anim_data.get("blend_parameters", {})
        if not isinstance(blend_raw, dict):
            return []

        blend_trees = []
        for tree_name in sorted(blend_raw.keys()):  # D11
            tree_data = blend_raw[tree_name]
            if not isinstance(tree_data, dict):
                continue
            blend_type_str = tree_data.get("blend_type", "SIMPLE_DIRECTIONAL").upper()
            try:
                blend_type = BlendType(blend_type_str)
            except ValueError:
                blend_type = BlendType.SIMPLE_DIRECTIONAL

            blend_trees.append(ContractBlendTree(
                tree_name=tree_name,
                x_parameter=tree_data.get("x_parameter", ""),
                y_parameter=tree_data.get("y_parameter", ""),
                blend_type=blend_type,
            ))

        return blend_trees

    def _extract_animation_events(self, anim_data: dict) -> list[ContractAnimationEvent]:
        """
        Extracts animation event declarations from COMP_ANIMATION_V2.pending_events.

        pending_events format:
        [{ event_id, state_name, trigger_at_normalized_time,
           game_event_type, payload, is_consumed }]
        """
        events_raw = anim_data.get("pending_events", [])
        if not isinstance(events_raw, list):
            return []

        events = []
        for event_data in events_raw:
            if not isinstance(event_data, dict):
                continue
            if event_data.get("is_consumed", False):
                continue  # Skip already-consumed events

            event_id = event_data.get("event_id", "")
            state_name = event_data.get("state_name", "")
            if not event_id or not state_name:
                continue  # Skip malformed events

            trigger_time = float(event_data.get("trigger_at_normalized_time", 0.0))
            if not (0.0 <= trigger_time <= 1.0):
                raise ValueError(
                    f"Animation event '{event_id}': trigger_at_normalized_time "
                    f"{trigger_time} must be in [0.0, 1.0]"
                )

            events.append(ContractAnimationEvent(
                event_id=event_id,
                state_name=state_name,
                layer_name=event_data.get("layer_name", "base"),
                trigger_at_normalized_time=trigger_time,
                game_event_type=event_data.get("game_event_type", ""),
            ))

        # Sort by (state_name, trigger_time) for determinism (D11)
        events.sort(key=lambda e: (e.state_name, e.trigger_at_normalized_time))
        return events

    def _extract_ik_config(self, ik_data: dict) -> Optional[ContractIKConfig]:
        """
        Extracts IK configuration from COMP_IK_V1 data (Audit 3).

        COMP_IK_V1.ik_mode values:
        DISABLED|LOOK_AT|HANDS|FEET|HANDS_AND_FEET|FULL_BODY
        """
        if not isinstance(ik_data, dict):
            return None

        ik_mode = ik_data.get("ik_mode", "DISABLED").upper()
        if ik_mode == "DISABLED":
            return None  # No IK needed

        return ContractIKConfig(
            ik_mode=ik_mode,
            has_look_at="look_at_target_entity" in ik_data and bool(
                ik_data.get("look_at_weight", 0.0)
            ),
            has_left_hand="left_hand_target_entity" in ik_data and bool(
                ik_data.get("left_hand_weight", 0.0)
            ),
            has_right_hand="right_hand_target_entity" in ik_data and bool(
                ik_data.get("right_hand_weight", 0.0)
            ),
            has_foot_placement=bool(ik_data.get("foot_placement_enabled", False)),
            carry_ik_preset=ik_data.get("carry_ik_preset")
                if ik_data.get("carry_ik_preset") != "NONE" else None,
            solve_order=ik_data.get("solve_order", "FABRIK"),
        )