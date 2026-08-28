"""
Deterministic Task 36 prompt classifier gate.

The classifier is intentionally conservative. It loads the Task 35 prompt
capability matrix, classifies a prompt before PIL/provider execution, and
returns a JSON-safe result that Builder can attach to every prompt response.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from prompt_capability_matrix import load_prompt_capability_matrix


RESULT_SCHEMA = "xace.prompt_classifier_result.v1"
_PROCEED_CATEGORY_IDS = {"certified_supported", "constrained"}


@dataclass(frozen=True)
class PromptClassifierResult:
    category_id: str
    category_label: str
    builder_decision: str
    builder_result_kind: str
    provider_call_policy: str
    mutation_policy: str
    product_wording: str
    builder_copy: str
    matrix_hash: str
    matrix_version: int
    confidence: float
    reason: str
    route: str
    matched_example_id: str = ""
    signals: tuple[str, ...] = field(default_factory=tuple)

    @property
    def may_continue_to_pil(self) -> bool:
        return self.category_id in _PROCEED_CATEGORY_IDS

    @property
    def provider_call_allowed(self) -> bool:
        return self.may_continue_to_pil and self.provider_call_policy.startswith("allowed")

    @property
    def mutation_allowed(self) -> bool:
        return self.may_continue_to_pil and not self.mutation_policy.startswith("must_not")

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": RESULT_SCHEMA,
            "matrix_hash": self.matrix_hash,
            "matrix_version": self.matrix_version,
            "category_id": self.category_id,
            "category_label": self.category_label,
            "builder_decision": self.builder_decision,
            "builder_result_kind": self.builder_result_kind,
            "provider_call_policy": self.provider_call_policy,
            "mutation_policy": self.mutation_policy,
            "product_wording": self.product_wording,
            "builder_copy": self.builder_copy,
            "confidence": self.confidence,
            "reason": self.reason,
            "route": self.route,
            "matched_example_id": self.matched_example_id,
            "signals": list(self.signals),
            "provider_call_allowed": self.provider_call_allowed,
            "mutation_allowed": self.mutation_allowed,
            "may_continue_to_pil": self.may_continue_to_pil,
        }

    def to_pil_result(self) -> dict[str, Any]:
        classifier = self.to_dict()
        base = {
            "turn_index": 0,
            "intent_category": f"PromptCapability:{self.category_id}",
            "confidence": self.confidence,
            "mode_profile_warnings": [],
            "classifier": classifier,
        }
        if self.category_id == "clarification_required":
            return {
                **base,
                "kind": "clarification",
                "reason": self.reason,
                "clarification_session_id": "",
                "questions": [_clarification_question(self)],
            }
        return {
            **base,
            "kind": "blocked",
            "reason": self.reason,
            "guard": "prompt_classifier_gate",
            "code": _blocked_code(self.category_id),
            "action": _blocked_action(self),
            "unsupported": self.category_id in {"blocked", "unsupported", "experimental"},
        }


def classify_prompt(prompt: str) -> PromptClassifierResult:
    matrix = load_prompt_capability_matrix()
    categories = {category["id"]: category for category in matrix["categories"]}
    normalized = _normalize(prompt)

    if not normalized:
        return _result(
            matrix,
            categories["clarification_required"],
            confidence=1.0,
            reason="This prompt is empty. Describe one specific gameplay edit.",
            route="clarification",
            signals=("empty_prompt",),
        )

    exact = _match_matrix_example(matrix, normalized)
    if exact is not None:
        category, example = exact
        return _result(
            matrix,
            category,
            confidence=1.0,
            reason=category["builder_copy"],
            route=str(example.get("expected_builder_route") or category["builder_result_kind"]),
            matched_example_id=str(example.get("id") or ""),
            signals=("matrix_example",),
        )

    for category_id, confidence, signals in _PATTERN_CLASSIFIERS:
        if _signals_match(normalized, signals):
            category = categories[category_id]
            return _result(
                matrix,
                category,
                confidence=confidence,
                reason=category["builder_copy"],
                route=_route_for_pattern(category, signals, normalized),
                signals=tuple(name for name, _pattern in signals),
            )

    return _result(
        matrix,
        categories["clarification_required"],
        confidence=0.72,
        reason=categories["clarification_required"]["builder_copy"],
        route="clarification",
        signals=("fallback_ambiguous",),
    )


def _result(
    matrix: dict[str, Any],
    category: dict[str, Any],
    *,
    confidence: float,
    reason: str,
    route: str,
    matched_example_id: str = "",
    signals: tuple[str, ...] = (),
) -> PromptClassifierResult:
    return PromptClassifierResult(
        category_id=str(category["id"]),
        category_label=str(category["label"]),
        builder_decision=str(category["builder_decision"]),
        builder_result_kind=str(category["builder_result_kind"]),
        provider_call_policy=str(category["provider_call_policy"]),
        mutation_policy=str(category["mutation_policy"]),
        product_wording=str(category["product_wording"]),
        builder_copy=str(category["builder_copy"]),
        matrix_hash=str(matrix["matrix_hash"]),
        matrix_version=int(matrix.get("version", 0) or 0),
        confidence=confidence,
        reason=reason,
        route=route,
        matched_example_id=matched_example_id,
        signals=signals,
    )


def _match_matrix_example(
    matrix: dict[str, Any],
    normalized_prompt: str,
) -> tuple[dict[str, Any], dict[str, Any]] | None:
    for category in matrix["categories"]:
        for example in category.get("examples", []):
            if _normalize(str(example.get("prompt") or "")) == normalized_prompt:
                return category, example
    return None


def _normalize(text: str) -> str:
    lowered = text.strip().lower()
    lowered = lowered.replace("`", "")
    return re.sub(r"\s+", " ", lowered)


def _signals_match(normalized_prompt: str, signals: tuple[tuple[str, re.Pattern[str]], ...]) -> bool:
    return any(pattern.search(normalized_prompt) for _name, pattern in signals)


def _route_for(category: dict[str, Any]) -> str:
    decision = str(category.get("builder_decision") or "")
    if decision == "accept_mutation_preview":
        return "mutation_preview"
    if decision == "accept_with_constraints":
        return "mutation_or_clarification"
    if decision == "ask_clarification":
        return "clarification"
    if decision == "refuse_unsupported":
        return "unsupported"
    if decision == "hide_or_gate_experimental":
        return "experimental"
    return "blocked"


def _route_for_pattern(
    category: dict[str, Any],
    signals: tuple[tuple[str, re.Pattern[str]], ...],
    normalized_prompt: str,
) -> str:
    if str(category.get("id") or "") == "certified_supported":
        matched = {name for name, pattern in signals if pattern.search(normalized_prompt)}
        if "certified_inventory_component" in matched or "certified_pickup_actor" in matched:
            return "mutation_preview_with_sgc"
    return _route_for(category)


def _clarification_question(result: PromptClassifierResult) -> dict[str, Any]:
    return {
        "question_id": "prompt-capability-scope",
        "question_type": "SCOPE_SELECT",
        "prompt": "Which supported target, value, or existing primitive should this prompt change?",
        "options": [
            "Choose a target actor or component",
            "Choose a numeric value to edit",
            "Choose an existing supported primitive",
        ],
        "hint": result.reason,
        "parameter_key": "prompt_scope",
    }


def _blocked_code(category_id: str) -> str:
    return {
        "blocked": "PROMPT_BLOCKED_BY_CAPABILITY_MATRIX",
        "unsupported": "PROMPT_UNSUPPORTED_BY_CAPABILITY_MATRIX",
        "experimental": "PROMPT_EXPERIMENTAL_NOT_ENABLED",
    }.get(category_id, "PROMPT_CLASSIFIER_BLOCKED")


def _blocked_action(result: PromptClassifierResult) -> str:
    if result.category_id == "experimental":
        return "Use a certified supported or constrained prompt until this category has launch proof."
    if result.category_id == "unsupported":
        return "Use a CGS-backed gameplay edit instead of engine-native code, external services, filesystem, network, or packaging work."
    return "Start with one specific gameplay, actor, component, system, asset, audio, or animation edit."


def _p(expr: str) -> re.Pattern[str]:
    return re.compile(expr, re.IGNORECASE)


_PATTERN_CLASSIFIERS: tuple[tuple[str, float, tuple[tuple[str, re.Pattern[str]], ...]], ...] = (
    (
        "unsupported",
        0.99,
        (
            ("prompt_injection", _p(r"\b(?:ignore|forget|bypass)\b.{0,40}\b(?:instructions|guard|gate|policy|safety|classifier|parser)\b")),
            ("secret_or_file_exfiltration", _p(r"\b(?:read|scan|exfiltrate|upload|send|steal)\b.{0,50}\b(?:desktop|files?|secrets?|api keys?|env|environment|\.env|credentials?)\b")),
            ("code_execution", _p(r"\b(?:os\.system|subprocess|eval\(|exec\(|rm -rf|curl |powershell|cmd\.exe|chmod|sudo)\b")),
            ("path_traversal", _p(r"(?:\.\./|/etc/passwd|c:\\\\users\\\\)")),
            ("unknown_cgs_path_mutation", _p(r"\b(?:force|apply|commit)\b.{0,50}\b(?:set|mutation)\b.{0,50}\b(?:unknown cgs path|modes\.[\w.]+)\b")),
            ("automatic_project_conversion", _p(r"\b(?:automatically|auto)\b.{0,40}\b(?:convert|port|migrate)\b.{0,40}\b(?:entire|whole|engine-native|unity project|unreal project)\b")),
        ),
    ),
    (
        "blocked",
        0.95,
        (
            ("complete_game_scope", _p(r"\b(?:complete|entire|full|finished)\b.{0,50}\b(?:online game|game|project)\b")),
            ("all_content_scope", _p(r"\ball\b.{0,40}\b(?:art|audio|animation|servers?|stores?|levels?|assets?)\b")),
        ),
    ),
    (
        "unsupported",
        0.96,
        (
            ("engine_native_code", _p(r"(?:\bmonobehaviour\b|\bgdscript\b|\bblueprint\b|\bunreal\s+c\+\+|\bunity script\b|\bengine-native script\b)")),
            ("hosted_service", _p(r"\b(?:hosted matchmaking|payment system|billing|storefront|dedicated server|backend service|database service)\b")),
            ("direct_filesystem_or_network", _p(r"\b(?:read files?|write files?|delete files?|network access|http request|download\b.{0,40}\b(?:internet|external|market prices)|download from|upload to)\b")),
            ("unproven_packaging", _p(r"\b(?:publish|package|ship|deploy)\b.{0,40}\b(?:every platform|steam|app store|google play|console)\b")),
            ("automatic_project_conversion", _p(r"\b(?:automatically|auto)\b.{0,40}\b(?:convert|port|migrate)\b.{0,40}\b(?:entire|whole|engine-native|unity project|unreal project)\b")),
        ),
    ),
    (
        "clarification_required",
        0.88,
        (
            ("ambiguous_difficulty", _p(r"\bmake\b.{0,30}\b(?:harder|easier|better|more fun|more interesting)\b")),
            ("ambiguous_addition", _p(r"^(?:add|create|make|build)\s+(?:inventory|crafting|combat|multiplayer|ai|enemies|quests?)\.?$")),
            ("ambiguous_improve", _p(r"\b(?:improve|fix|balance|polish)\b.{0,25}\b(?:game|combat|movement|enemies|inventory|level)\b")),
        ),
    ),
    (
        "constrained",
        0.84,
        (
            ("bounded_stamina", _p(r"\badd\b.{0,30}\bstamina\b.{0,40}\bplayer\b")),
            ("bounded_pickup_variant", _p(r"\badd\b.{0,25}\bhealth pickup\b")),
            ("bounded_asset_link", _p(r"\blink\b.{0,40}\b(?:mesh|asset|reference)\b")),
        ),
    ),
    (
        "certified_supported",
        0.94,
        (
            ("certified_player_speed", _p(r"\b(?:set|change|update)\b.{0,30}\bplayer\b.{0,30}\b(?:movement )?speed\b.{0,20}\bto\b\s+\d+(?:\.\d+)?\b")),
            ("certified_inventory_component", _p(r"\badd\b.{0,20}\b(?:general )?inventory component\b.{0,20}\bplayer\b")),
            ("certified_pickup_actor", _p(r"\badd\b.{0,20}\b(?:one )?(?:generic )?pickup\b.{0,40}\bplayer\b")),
        ),
    ),
    (
        "experimental",
        0.86,
        (
            ("experimental_quest", _p(r"\bbranching quest\b|\bquest chain\b")),
            ("experimental_raid", _p(r"\bnetworked raid\b|\bsynced boss phases\b")),
            ("experimental_genre_loop", _p(r"\bcomplete survival crafting loop\b|\bfrom scratch\b.{0,30}\b(?:survival|crafting)\b")),
        ),
    ),
)
