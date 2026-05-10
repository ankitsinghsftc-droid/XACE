"""
intent_object.py — IntentObject
=================================
Structured representation of a classified designer intent.

IntentObject is the output of the GDE's intent classification pipeline
and the input to the transaction building pipeline. It carries:
    - What kind of schema operation the designer wants (intent_type)
    - Which part of the CGS is affected (scope)
    - What specifically to do (action)
    - Parameter values extracted from the prompt (parameters)
    - Any conditions the designer implied (conditions)
    - How confident the classifier was (confidence)

## Lifecycle
    raw prompt
        → IntentClassifier.classify()   → IntentObject
        → SlotExtractor.extract()       → IntentObject (enriched)
        → AmbiguityDetector.detect()    → IntentObject | ClarificationRequest
        → TransactionBuilder            → DSLTransaction

## Intent Types
See GDEIntentType for the full vocabulary. These are GDE-level intents
(schema operations) — they are more granular than PIL's 9 top-level
categories and are specific to the CGS domain.

## Scope Dict
The scope dict identifies the CGS region affected:
    {
        "mode_id":      "mode_default",   # which mode (or None for global)
        "actor_id":     "actor_player",   # which actor (or None)
        "system_id":    None,
        "component_type_ids": [100],      # which component types
        "path_hints":   ["components.100.defaults.current"],
    }

## Action Dict
The action dict describes the mutation:
    {
        "op_type":      "SET",
        "field":        "current",
        "value":        80.0,
        "type_hint":    "float",
    }
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


# ── GDE Intent Types ──────────────────────────────────────────────────────────

class GDEIntentType:
    """
    Vocabulary of GDE-level intent classifications.

    These are CGS-domain-specific. They differ from PIL's 9 top-level
    categories (CreateFeature, ModifyFeature, etc.) — each PIL category
    maps to one or more GDE intent types.
    """
    # Value mutations
    MODIFY_VALUE        = "ModifyValue"       # change a field: "make player faster"
    SET_VALUE           = "SetValue"          # set to exact value: "set health to 80"
    SCALE_VALUE         = "ScaleValue"        # multiply/divide: "double zombie speed"

    # Structural changes
    CREATE_ACTOR        = "CreateActor"       # add new actor: "add a boss enemy"
    REMOVE_ACTOR        = "RemoveActor"       # delete actor: "remove the shield pickup"
    ADD_COMPONENT       = "AddComponent"      # add component to actor
    REMOVE_COMPONENT    = "RemoveComponent"   # remove component from actor
    CREATE_SYSTEM       = "CreateSystem"      # add a new game system
    REMOVE_SYSTEM       = "RemoveSystem"      # remove a system

    # Rule/constraint operations
    DEFINE_RULE         = "DefineRule"        # add a new rule: "player dies at 0 health"
    MODIFY_RULE         = "ModifyRule"        # change an existing rule
    REMOVE_RULE         = "RemoveRule"        # delete a rule

    # Query / explain
    QUERY_VALUE         = "QueryValue"        # "what is the player's speed?"
    QUERY_EXPLAIN       = "QueryExplain"      # "how does the damage system work?"

    # Unknown / ambiguous
    UNKNOWN             = "Unknown"

    @classmethod
    def all_types(cls) -> frozenset[str]:
        return frozenset({
            cls.MODIFY_VALUE, cls.SET_VALUE, cls.SCALE_VALUE,
            cls.CREATE_ACTOR, cls.REMOVE_ACTOR,
            cls.ADD_COMPONENT, cls.REMOVE_COMPONENT,
            cls.CREATE_SYSTEM, cls.REMOVE_SYSTEM,
            cls.DEFINE_RULE, cls.MODIFY_RULE, cls.REMOVE_RULE,
            cls.QUERY_VALUE, cls.QUERY_EXPLAIN,
            cls.UNKNOWN,
        })

    @classmethod
    def is_destructive(cls, intent_type: str) -> bool:
        return intent_type in {
            cls.REMOVE_ACTOR, cls.REMOVE_COMPONENT,
            cls.REMOVE_SYSTEM, cls.REMOVE_RULE,
        }

    @classmethod
    def is_structural(cls, intent_type: str) -> bool:
        return intent_type in {
            cls.CREATE_ACTOR, cls.REMOVE_ACTOR,
            cls.ADD_COMPONENT, cls.REMOVE_COMPONENT,
            cls.CREATE_SYSTEM, cls.REMOVE_SYSTEM,
            cls.DEFINE_RULE, cls.REMOVE_RULE,
        }

    @classmethod
    def is_query(cls, intent_type: str) -> bool:
        return intent_type in {cls.QUERY_VALUE, cls.QUERY_EXPLAIN}


# ── Intent Object ─────────────────────────────────────────────────────────────

@dataclass
class IntentObject:
    """
    Structured representation of one classified designer intent.

    Produced by IntentClassifier, enriched by SlotExtractor,
    consumed by TransactionBuilder.

    Attributes
    ----------
    intent_type : str
        One of GDEIntentType constants.
    scope : dict[str, Any]
        CGS region this intent affects. See module docstring.
    action : dict[str, Any]
        What mutation to perform. See module docstring.
    parameters : list[dict[str, Any]]
        Extracted parameter slots (field names, values, types).
        Each dict: {"name": str, "value": Any, "type_hint": str, "confidence": float}
    conditions : list[str]
        Implied conditions from the prompt (e.g. "only when dead").
        Stored as raw strings — parsed into AST by RuleExpressionParser later.
    confidence : float
        Overall classification confidence in [0.0, 1.0].
    requires_clarification : bool
        True if AmbiguityDetector flagged this intent as too ambiguous
        to proceed without user confirmation.
    clarification_questions : list[str]
        Pending clarification questions. Populated by AmbiguityDetector.
    raw_prompt : str
        The original prompt text that produced this intent.
    session_id : str | None
        Builder session identifier for provenance.
    """

    intent_type:              str
    scope:                    dict[str, Any]        = field(default_factory=dict)
    action:                   dict[str, Any]        = field(default_factory=dict)
    parameters:               list[dict[str, Any]]  = field(default_factory=list)
    conditions:               list[str]             = field(default_factory=list)
    confidence:               float                 = 0.0
    requires_clarification:   bool                  = False
    clarification_questions:  list[str]             = field(default_factory=list)
    raw_prompt:               str                   = ""
    session_id:               str | None            = None

    # ── Convenience Accessors ─────────────────────────────────────────────────

    @property
    def is_confident(self) -> bool:
        """True if confidence is above the threshold for auto-proceed."""
        return self.confidence >= 0.70

    @property
    def is_destructive(self) -> bool:
        return GDEIntentType.is_destructive(self.intent_type)

    @property
    def is_structural(self) -> bool:
        return GDEIntentType.is_structural(self.intent_type)

    @property
    def is_query(self) -> bool:
        return GDEIntentType.is_query(self.intent_type)

    @property
    def mode_id(self) -> str | None:
        return self.scope.get("mode_id")

    @property
    def actor_id(self) -> str | None:
        return self.scope.get("actor_id")

    @property
    def system_id(self) -> str | None:
        return self.scope.get("system_id")

    @property
    def component_type_ids(self) -> list[int]:
        return self.scope.get("component_type_ids", [])

    @property
    def path_hints(self) -> list[str]:
        """Partially resolved path hints from slot extraction."""
        return self.scope.get("path_hints", [])

    def get_parameter(self, name: str) -> Any:
        """Returns the value of a named parameter, or None if not found."""
        for p in self.parameters:
            if p.get("name") == name:
                return p.get("value")
        return None

    def has_parameter(self, name: str) -> bool:
        return any(p.get("name") == name for p in self.parameters)

    def add_parameter(
        self,
        name:       str,
        value:      Any,
        type_hint:  str   = "",
        confidence: float = 1.0,
    ) -> None:
        """Adds or updates a named parameter slot."""
        for p in self.parameters:
            if p.get("name") == name:
                p["value"]      = value
                p["type_hint"]  = type_hint
                p["confidence"] = confidence
                return
        self.parameters.append({
            "name":       name,
            "value":      value,
            "type_hint":  type_hint,
            "confidence": confidence,
        })

    # ── Factories ─────────────────────────────────────────────────────────────

    @classmethod
    def unknown(cls, raw_prompt: str, session_id: str | None = None) -> "IntentObject":
        """Creates an IntentObject for an unclassifiable prompt."""
        return cls(
            intent_type=GDEIntentType.UNKNOWN,
            confidence=0.0,
            requires_clarification=True,
            raw_prompt=raw_prompt,
            session_id=session_id,
        )

    @classmethod
    def for_value_set(
        cls,
        raw_prompt:  str,
        mode_id:     str | None,
        actor_id:    str | None,
        type_ids:    list[int],
        field_name:  str,
        value:       Any,
        type_hint:   str   = "",
        confidence:  float = 0.8,
        session_id:  str | None = None,
    ) -> "IntentObject":
        """Creates an IntentObject for a simple field set mutation."""
        obj = cls(
            intent_type=GDEIntentType.SET_VALUE,
            scope={
                "mode_id":             mode_id,
                "actor_id":            actor_id,
                "component_type_ids":  type_ids,
            },
            action={
                "op_type":   "SET",
                "field":     field_name,
                "value":     value,
                "type_hint": type_hint,
            },
            confidence=confidence,
            raw_prompt=raw_prompt,
            session_id=session_id,
        )
        obj.add_parameter(field_name, value, type_hint, confidence)
        return obj

    def __repr__(self) -> str:
        conf = f"{self.confidence:.2f}"
        clarify = " [needs clarification]" if self.requires_clarification else ""
        return (
            f"IntentObject({self.intent_type!r}, "
            f"conf={conf}{clarify})"
        )