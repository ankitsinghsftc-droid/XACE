"""
slot_extractor.py — SlotExtractor
=====================================
Extracts named parameter slots from a prompt + CGS context slice.

SlotExtractor is a deeper pass than IntentClassifier's shallow extraction.
It runs after ScopeResolver has identified the target actors and components,
so it knows which field names are valid for this intent and can match
prompt fragments against real CGS field vocabulary.

## Slot Types
    value_slot    — a numeric or string value to assign ("set health to 80" → 80.0)
    field_slot    — the CGS field being targeted ("health" → "current")
    actor_slot    — an entity name → actor_id reference
    condition_slot— an implied conditional fragment ("when dead", "only at night")
    id_slot       — a new ID for a structural create ("call it boss_zombie")

## Extraction Strategy
    1. Numeric extraction — all numbers in the prompt
    2. CGS field name matching — prompt words against known field vocabulary
    3. Actor name extraction — mentions of known actor IDs or display names
    4. Condition fragment detection — conditional language patterns
    5. New ID suggestion — snake_case slug from the prompt

## Confidence
Each extracted slot carries a confidence score:
    1.0 — exact match (number parsed cleanly, field found in CGS)
    0.8 — high confidence fuzzy (field synonym matched)
    0.6 — medium (heuristic guess, should clarify)
    below 0.5 → AmbiguityDetector will ask for confirmation
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from .intent_object import IntentObject, GDEIntentType
from .context_loader import CGSContextSlice


# ── Slot ──────────────────────────────────────────────────────────────────────

@dataclass
class ExtractedSlot:
    """One extracted parameter slot."""
    slot_type:  str        # "value" | "field" | "actor" | "condition" | "id"
    name:       str        # parameter name
    value:      Any        # extracted value
    type_hint:  str        # "float" | "int" | "str" | "bool" | ...
    confidence: float      # [0.0–1.0]
    raw_text:   str        # the prompt fragment that produced this slot
    notes:      str        = ""

    def __repr__(self) -> str:
        return (
            f"Slot({self.slot_type}:{self.name!r}="
            f"{self.value!r} conf={self.confidence:.2f})"
        )


# ── Field Name Vocabulary ─────────────────────────────────────────────────────
# Maps common English words to CGS component field names

_FIELD_SYNONYMS: dict[str, str] = {
    # COMP_HEALTH_V1
    "health":       "current",
    "hp":           "current",
    "life":         "current",
    "lives":        "current",
    "max health":   "max",
    "maximum health": "max",
    "max hp":       "max",
    "regen":        "regen_rate",
    "regeneration": "regen_rate",
    # COMP_VELOCITY_V1
    "speed":        "max_linear_speed",
    "velocity":     "max_linear_speed",
    "move speed":   "max_linear_speed",
    "movement speed": "max_linear_speed",
    # COMP_DAMAGE_V1
    "damage":       "amount",
    "attack":       "amount",
    "hit":          "amount",
    # COMP_AI_V1
    "detection":    "detection_radius",
    "sight":        "detection_radius",
    "vision":       "detection_radius",
    "aggression":   "aggression_level",
    "hostility":    "aggression_level",
}

# ── Condition Patterns ────────────────────────────────────────────────────────

_CONDITION_PATTERNS: list[re.Pattern] = [
    re.compile(r'\b(?:when|if|whenever|once|after)\b[^,.]+', re.I),
    re.compile(r'\b(?:on death|on damage|on hit|on pickup|on interact)\b', re.I),
    re.compile(r'\bonly (?:when|if|at|during)[^,.]+', re.I),
]

# ── Numeric Extraction ────────────────────────────────────────────────────────

_NUMERIC_RE = re.compile(r'(?<!\w)(-?\d+(?:\.\d+)?)(?!\w)')

# Percentage detection
_PERCENT_RE = re.compile(r'(-?\d+(?:\.\d+)?)\s*%')

# Range detection: "between 5 and 10"
_RANGE_RE = re.compile(r'\bbetween\s+(-?\d+(?:\.\d+)?)\s+and\s+(-?\d+(?:\.\d+)?)\b', re.I)

# ── New ID Slug ───────────────────────────────────────────────────────────────

_CALL_IT_RE = re.compile(r'\b(?:call it|name it|named|called)\s+([a-zA-Z0-9_\s]+)', re.I)
_SNAKE_CLEAN = re.compile(r'[^a-z0-9]+')


def _to_snake(text: str) -> str:
    return _SNAKE_CLEAN.sub("_", text.lower().strip()).strip("_")


# ── Slot Extractor ────────────────────────────────────────────────────────────

class SlotExtractor:
    """
    Extracts named parameter slots from a prompt + CGS context.

    Stateless — call extract() once per intent. Enriches the IntentObject
    with fully typed parameters and sets confidence accordingly.

    Usage
    -----
        extractor = SlotExtractor()
        slots     = extractor.extract(intent, cgs_slice)
        # intent.parameters is now populated with typed slots
    """

    def extract(
        self,
        intent:    IntentObject,
        cgs_slice: CGSContextSlice,
    ) -> list[ExtractedSlot]:
        """
        Extracts all slots from intent.raw_prompt using cgs_slice as vocabulary.
        Enriches intent.parameters in-place.
        Returns the full list of extracted slots for inspection.
        """
        text   = intent.raw_prompt
        slots: list[ExtractedSlot] = []

        slots.extend(self._extract_numeric_values(text, intent, cgs_slice))
        slots.extend(self._extract_field_names(text, intent, cgs_slice))
        slots.extend(self._extract_actor_refs(text, cgs_slice))
        slots.extend(self._extract_conditions(text))
        slots.extend(self._extract_new_id(text, intent))

        # Enrich intent parameters with high-confidence slots
        for slot in slots:
            if slot.confidence >= 0.6:
                intent.add_parameter(
                    name=slot.name,
                    value=slot.value,
                    type_hint=slot.type_hint,
                    confidence=slot.confidence,
                )

        return slots

    # ── Numeric Extraction ────────────────────────────────────────────────────

    @staticmethod
    def _extract_numeric_values(
        text:      str,
        intent:    IntentObject,
        cgs_slice: CGSContextSlice,
    ) -> list[ExtractedSlot]:
        slots: list[ExtractedSlot] = []

        # Percentage values → convert to 0–1 or multiply context
        for m in _PERCENT_RE.finditer(text):
            raw = float(m.group(1))
            slots.append(ExtractedSlot(
                slot_type="value",
                name="percent_value",
                value=raw / 100.0,
                type_hint="float",
                confidence=0.85,
                raw_text=m.group(),
                notes=f"Interpreted {m.group()} as {raw/100.0:.3f}",
            ))

        # Range extraction
        range_m = _RANGE_RE.search(text)
        if range_m:
            lo, hi = float(range_m.group(1)), float(range_m.group(2))
            mid    = (lo + hi) / 2
            slots.append(ExtractedSlot(
                slot_type="value",
                name="range_value",
                value=mid,
                type_hint="float",
                confidence=0.70,
                raw_text=range_m.group(),
                notes=f"Range {lo}–{hi}, using midpoint {mid}",
            ))
            return slots  # skip plain numeric extraction if range found

        # Plain numbers (filter out those already captured as percent)
        percent_positions = {m.start() for m in _PERCENT_RE.finditer(text)}
        count = 0
        for m in _NUMERIC_RE.finditer(text):
            if m.start() in percent_positions:
                continue
            raw_str = m.group(1)
            value   = float(raw_str) if "." in raw_str else int(raw_str)
            slots.append(ExtractedSlot(
                slot_type="value",
                name=f"numeric_value_{count}",
                value=value,
                type_hint="float" if isinstance(value, float) else "int",
                confidence=0.90,
                raw_text=raw_str,
            ))
            count += 1
            if count >= 3:
                break

        return slots

    # ── Field Name Extraction ─────────────────────────────────────────────────

    @staticmethod
    def _extract_field_names(
        text:      str,
        intent:    IntentObject,
        cgs_slice: CGSContextSlice,
    ) -> list[ExtractedSlot]:
        """
        Maps English field-synonym words in the prompt to CGS field names.
        Uses known vocabulary first, then exact-match against context slice fields.
        """
        slots: list[ExtractedSlot] = []
        text_lower = text.lower()

        # Vocabulary lookup (longest match first)
        for synonym, field_name in sorted(_FIELD_SYNONYMS.items(), key=lambda x: -len(x[0])):
            if synonym in text_lower:
                slots.append(ExtractedSlot(
                    slot_type="field",
                    name="target_field",
                    value=field_name,
                    type_hint="str",
                    confidence=0.85,
                    raw_text=synonym,
                    notes=f"'{synonym}' → '{field_name}' via synonym table",
                ))
                break  # one field per extraction pass

        # If nothing found via vocabulary, look in context slice fields
        if not slots:
            for comp_hint in cgs_slice.component_hints:
                for fld in comp_hint.get("fields", []):
                    leaf = fld.split(".")[-1]
                    if leaf.lower() in text_lower:
                        slots.append(ExtractedSlot(
                            slot_type="field",
                            name="target_field",
                            value=leaf,
                            type_hint="str",
                            confidence=0.75,
                            raw_text=leaf,
                            notes=f"Exact field name '{leaf}' found in prompt",
                        ))
                        break

        return slots

    # ── Actor Reference Extraction ────────────────────────────────────────────

    @staticmethod
    def _extract_actor_refs(
        text:      str,
        cgs_slice: CGSContextSlice,
    ) -> list[ExtractedSlot]:
        """Finds mentions of known actor IDs or their display-name fragments."""
        slots: list[ExtractedSlot] = []
        text_lower = text.lower()

        for actor_id in cgs_slice.all_actor_ids_in_mode:
            # Strip "actor_" prefix for matching ("actor_zombie" → "zombie")
            display = actor_id.replace("actor_", "").replace("_", " ")
            if display in text_lower or actor_id.lower() in text_lower:
                slots.append(ExtractedSlot(
                    slot_type="actor",
                    name="target_actor_id",
                    value=actor_id,
                    type_hint="str",
                    confidence=0.88,
                    raw_text=display,
                ))
                break

        return slots

    # ── Condition Extraction ──────────────────────────────────────────────────

    @staticmethod
    def _extract_conditions(text: str) -> list[ExtractedSlot]:
        """Extracts conditional language fragments."""
        slots: list[ExtractedSlot] = []
        for pattern in _CONDITION_PATTERNS:
            for m in pattern.finditer(text):
                fragment = m.group().strip()
                if len(fragment) > 3:
                    slots.append(ExtractedSlot(
                        slot_type="condition",
                        name="implied_condition",
                        value=fragment,
                        type_hint="str",
                        confidence=0.65,
                        raw_text=fragment,
                        notes="Condition fragment for rule generation",
                    ))
        return slots

    # ── New ID Extraction ─────────────────────────────────────────────────────

    @staticmethod
    def _extract_new_id(text: str, intent: IntentObject) -> list[ExtractedSlot]:
        """
        Extracts a designer-supplied ID for structural create intents.
        "add a zombie called night_crawler" → "night_crawler"
        """
        if not GDEIntentType.is_structural(intent.intent_type):
            return []

        m = _CALL_IT_RE.search(text)
        if m:
            raw_name = m.group(1).strip()
            slug     = _to_snake(raw_name)
            if slug:
                prefix = "actor" if "actor" in intent.intent_type.lower() else "item"
                return [ExtractedSlot(
                    slot_type="id",
                    name="new_entity_id",
                    value=f"{prefix}_{slug}",
                    type_hint="str",
                    confidence=0.90,
                    raw_text=raw_name,
                    notes=f"Suggested ID from prompt: '{prefix}_{slug}'",
                )]

        return []