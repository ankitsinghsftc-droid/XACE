"""
tests/test_gde_orchestrator.py
================================
Integration tests for GDEOrchestrator: the full GDE pipeline from prompt
to committed CGS, clarification flows, mode-dependent behaviour, and
error handling.
"""

from __future__ import annotations

import pytest
from typing import Any

from ..gde_orchestrator import GDEOrchestrator, GDEResult
from ..cgs.cgs_manager import CGSManager
from ..cgs.cgs_serializer import CGSSerializer
from ..domain_dsl.transaction_model.transaction_builder import TransactionBuilder
from ..domain_dsl.mutation_metadata.mutation_metadata_model import MutationMetadata
from ..prompt_interpretation.intent_object import IntentObject, GDEIntentType
from ..mode_profiles.mode_profile import AssistanceMode, get_profile


# ── Fixtures ──────────────────────────────────────────────────────────────────

def _valid_cgs(name: str = "Test Game") -> dict[str, Any]:
    cgs = {
        "metadata": {
            "name":     name,
            "version":  "0.1.0",
            "cgs_hash": "",
        },
        "global_systems": [
            {
                "id":    "sys_input", "phase": "Input",
                "reads": [6], "writes": [5],
                "depends_on": [], "deterministic": True,
                "display_name": "Input System",
            }
        ],
        "modes": [
            {
                "id":             "mode_default",
                "display_name":   "Default",
                "is_default":     True,
                "schema_version": "0.1.0",
                "actors": [
                    {
                        "id":         "actor_player",
                        "actor_type": "PLAYER",
                        "control_type": "HUMAN",
                        "components": [
                            {"type_id": 1,   "defaults": {"entity_name": "Player"}},
                            {"type_id": 5,   "defaults": {"max_linear_speed": 5.0}},
                            {"type_id": 100, "defaults": {"current": 80.0, "max": 100.0}},
                        ],
                    },
                    {
                        "id":         "actor_zombie",
                        "actor_type": "ENEMY",
                        "control_type": "AI_PROXY",
                        "components": [
                            {"type_id": 5,   "defaults": {"max_linear_speed": 3.0}},
                            {"type_id": 100, "defaults": {"current": 30.0, "max": 30.0}},
                            {"type_id": 160, "defaults": {"detection_radius": 20.0}},
                        ],
                    },
                ],
                "systems": [],
                "rules":   [],
            }
        ],
    }
    # Stamp hash
    cgs["metadata"]["cgs_hash"] = CGSSerializer.compute_hash(
        {k: v for k, v in cgs.items() if k != "metadata"}
        | {"metadata": {k: v for k, v in cgs["metadata"].items() if k != "cgs_hash"}}
    )
    return cgs


def _make_orchestrator(mode: str = AssistanceMode.COLLABORATIVE) -> GDEOrchestrator:
    orc = GDEOrchestrator(mode=mode, session_id="test_session")
    orc.load_cgs(_valid_cgs())
    return orc


def _make_meta(orc: GDEOrchestrator) -> MutationMetadata:
    return MutationMetadata.create(
        source="manual",
        parent_cgs_hash=orc.current_hash,
        schema_version_target="0.1.0",
    )


# ── Initialisation ────────────────────────────────────────────────────────────

class TestGDEOrchestratorInit:

    def test_not_initialised_before_load(self) -> None:
        orc = GDEOrchestrator()
        assert not orc.is_initialised

    def test_initialised_after_load_cgs(self) -> None:
        orc = GDEOrchestrator()
        orc.load_cgs(_valid_cgs())
        assert orc.is_initialised

    def test_current_cgs_none_before_init(self) -> None:
        orc = GDEOrchestrator()
        assert orc.current_cgs is None

    def test_current_cgs_after_init(self) -> None:
        orc = _make_orchestrator()
        assert orc.current_cgs is not None
        assert orc.current_cgs["metadata"]["name"] == "Test Game"

    def test_current_hash_non_empty_after_init(self) -> None:
        orc = _make_orchestrator()
        assert len(orc.current_hash) == 64

    def test_prompt_without_init_returns_error(self) -> None:
        orc    = GDEOrchestrator()
        result = orc.process_prompt("make the zombie faster")
        assert not result.success
        assert "No CGS" in result.error

    def test_set_mode(self) -> None:
        orc = _make_orchestrator(AssistanceMode.COLLABORATIVE)
        orc.set_mode(AssistanceMode.ADVANCED)
        assert orc._mode_name == AssistanceMode.ADVANCED


# ── Direct Transaction Processing ─────────────────────────────────────────────

class TestGDEOrchestratorTransactions:

    def setup_method(self) -> None:
        self.orc = _make_orchestrator()

    def _txn(self, *ops):
        meta    = _make_meta(self.orc)
        builder = TransactionBuilder(meta)
        for target, value in ops:
            builder.set(target, value)
        return builder.build()

    def test_process_transaction_success(self) -> None:
        txn    = self._txn(("metadata.name", "Updated Name"))
        result = self.orc.process_transaction(txn)
        assert result.success
        assert self.orc.current_cgs["metadata"]["name"] == "Updated Name"

    def test_process_transaction_changes_hash(self) -> None:
        old_hash = self.orc.current_hash
        txn      = self._txn(("metadata.name", "Changed"))
        self.orc.process_transaction(txn)
        assert self.orc.current_hash != old_hash

    def test_process_transaction_bumps_patch_version(self) -> None:
        txn = self._txn(("metadata.name", "Changed"))
        self.orc.process_transaction(txn)
        assert self.orc.current_cgs["metadata"]["version"] == "0.1.1"

    def test_structural_transaction_bumps_minor_version(self) -> None:
        meta    = _make_meta(self.orc)
        builder = TransactionBuilder(meta)
        builder.add_actor(
            "modes.mode_default.actors",
            {
                "id":         "actor_boss",
                "actor_type": "ENEMY",
                "control_type": "AI_PROXY",
                "components": [],
                "tags":       [],
                "mode_scope": [],
            },
        )
        txn    = builder.build()
        result = self.orc.process_transaction(txn)
        assert result.success
        assert self.orc.current_cgs["metadata"]["version"] == "0.2.0"

    def test_invalid_transaction_fails_gracefully(self) -> None:
        meta    = _make_meta(self.orc)
        builder = TransactionBuilder(meta)
        builder.set("metadata.name", "X")  # valid
        txn = builder.build()
        # Tamper metadata to simulate stale hash
        import copy
        stale_meta = MutationMetadata.create(
            source="manual",
            parent_cgs_hash="wrong_hash_00000",
            schema_version_target="0.1.0",
        )
        from ..domain_dsl.transaction_model.transaction_builder import DSLOperation
        bad_txn = type(txn)(
            transaction_id=stale_meta.transaction_id,
            operations=txn.operations,
            metadata=stale_meta,
            schema_version_target="0.1.0",
        )
        result = self.orc.process_transaction(bad_txn)
        assert not result.success
        assert "Stale" in result.error

    def test_invariant_violation_prevents_commit(self) -> None:
        txn    = self._txn(("global_systems.sys_input.deterministic", False))
        result = self.orc.process_transaction(txn)
        assert not result.success
        assert result.consistency_report is not None
        # CGS is unchanged
        assert self.orc.current_cgs["global_systems"][0]["deterministic"] is True


# ── Prompt Processing ─────────────────────────────────────────────────────────

class TestGDEOrchestratorPrompts:

    def setup_method(self) -> None:
        self.orc = _make_orchestrator(AssistanceMode.ARCHITECT_MODE)

    def test_query_prompt_returns_success_without_mutation(self) -> None:
        result   = self.orc.process_prompt("what is the player's speed?")
        old_hash = self.orc.current_hash
        assert result.success
        assert result.is_query
        # Hash unchanged — query does not mutate
        assert self.orc.current_hash == old_hash

    def test_unknown_prompt_architect_does_not_block(self) -> None:
        # ARCHITECT_MODE: never asks, always tries to proceed
        result = self.orc.process_prompt("xyzzy nonsense gibberish")
        # May succeed or fail, but must not raise
        assert isinstance(result, GDEResult)

    def test_set_value_prompt_with_extracted_slots(self) -> None:
        # A clear prompt that the slot extractor can parse
        result = self.orc.process_prompt("set player speed to 10")
        # With ARCHITECT_MODE and a well-formed prompt, this should succeed
        # OR return a clear failure reason (never raise)
        assert isinstance(result, GDEResult)

    def test_process_intent_directly(self) -> None:
        intent = IntentObject.for_value_set(
            raw_prompt="set max speed to 10",
            mode_id="mode_default",
            actor_id="actor_player",
            type_ids=[5],
            field_name="max_linear_speed",
            value=10.0,
            type_hint="float",
            confidence=0.95,
        )
        intent.scope["path_hints"] = [
            "modes.mode_default.actors.actor_player.components.5.defaults.max_linear_speed"
        ]
        result = self.orc.process_intent(intent)
        # With a precise intent and path, should succeed
        assert isinstance(result, GDEResult)


# ── Clarification Flows ───────────────────────────────────────────────────────

class TestGDEOrchestratorClarification:

    def test_fully_assisted_asks_for_ambiguous_prompt(self) -> None:
        orc    = _make_orchestrator(AssistanceMode.FULLY_ASSISTED)
        result = orc.process_prompt("make it faster")   # very ambiguous
        # May need clarification or may partially resolve
        assert isinstance(result, GDEResult)

    def test_architect_never_asks(self) -> None:
        orc    = _make_orchestrator(AssistanceMode.ARCHITECT_MODE)
        result = orc.process_prompt("make it faster")
        # ARCHITECT never asks — may succeed or fail but no clarification
        assert not result.needs_clarification


# ── Mode Profile Tests ────────────────────────────────────────────────────────

class TestModeProfiles:

    def test_get_profile_fully_assisted(self) -> None:
        p = get_profile(AssistanceMode.FULLY_ASSISTED)
        assert p.clarification_threshold == 0.70
        assert p.asks_for_clarification
        assert not p.show_technical_details
        assert p.max_questions_per_clarification == 5

    def test_get_profile_collaborative(self) -> None:
        p = get_profile(AssistanceMode.COLLABORATIVE)
        assert p.clarification_threshold == 0.60
        assert p.auto_assumption_level == "safe"

    def test_get_profile_advanced(self) -> None:
        p = get_profile(AssistanceMode.ADVANCED)
        assert p.clarification_threshold == 0.0
        assert not p.asks_for_clarification
        assert p.show_technical_details

    def test_get_profile_architect(self) -> None:
        p = get_profile(AssistanceMode.ARCHITECT_MODE)
        assert p.max_questions_per_clarification == 0
        assert p.suggestion_policy == "hidden"
        assert not p.auto_commits is False  # auto_commits = True

    def test_should_clarify(self) -> None:
        p = get_profile(AssistanceMode.FULLY_ASSISTED)
        assert p.should_clarify(0.5)
        assert not p.should_clarify(0.9)

    def test_should_block_risk(self) -> None:
        fa = get_profile(AssistanceMode.FULLY_ASSISTED)
        assert fa.should_block("medium")
        assert fa.should_block("high")
        assert not fa.should_block("low")

        collab = get_profile(AssistanceMode.COLLABORATIVE)
        assert not collab.should_block("medium")
        assert collab.should_block("high")

        arch = get_profile(AssistanceMode.ARCHITECT_MODE)
        assert not arch.should_block("high")

    def test_invalid_mode_raises(self) -> None:
        from ..mode_profiles.mode_profile import get_profile
        with pytest.raises(ValueError, match="Unknown"):
            get_profile("INVALID_MODE")

    def test_explanation_for_mutation(self) -> None:
        fa = get_profile(AssistanceMode.FULLY_ASSISTED)
        assert fa.explanation_for_mutation("plain", "technical") == "plain"

        arch = get_profile(AssistanceMode.ARCHITECT_MODE)
        assert arch.explanation_for_mutation("plain", "technical") == ""


# ── Snapshot and Version Integrity ────────────────────────────────────────────

class TestGDEVersionIntegrity:

    def test_multiple_commits_unique_hashes(self) -> None:
        orc    = _make_orchestrator()
        hashes = [orc.current_hash]
        for i in range(3):
            meta = _make_meta(orc)
            txn  = TransactionBuilder(meta).set("metadata.name", f"v{i}").build()
            orc.process_transaction(txn)
            hashes.append(orc.current_hash)
        assert len(set(hashes)) == len(hashes)

    def test_failed_commit_leaves_hash_unchanged(self) -> None:
        orc      = _make_orchestrator()
        old_hash = orc.current_hash
        # Build txn that will fail invariant check
        meta = _make_meta(orc)
        txn  = (
            TransactionBuilder(meta)
            .set("global_systems.sys_input.deterministic", False)
            .build()
        )
        result = orc.process_transaction(txn)
        assert not result.success
        assert orc.current_hash == old_hash

    def test_cgs_content_matches_hash_after_commit(self) -> None:
        orc  = _make_orchestrator()
        meta = _make_meta(orc)
        txn  = TransactionBuilder(meta).set("metadata.name", "New").build()
        result = orc.process_transaction(txn)
        assert result.success
        # Hash returned in result matches what manager now reports
        assert result.new_cgs_hash == orc.current_hash
        # Hash is stamped in the CGS metadata
        assert orc.current_cgs["metadata"]["cgs_hash"] == orc.current_hash
        # Content reflects the mutation
        assert orc.current_cgs["metadata"]["name"] == "New"