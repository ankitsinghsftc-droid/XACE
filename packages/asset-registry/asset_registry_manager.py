"""
asset_registry_manager.py — Main orchestrator for the XACE Asset Registry (Audit 2).

AssetRegistryManager is the single entry point for all asset registry
operations. It owns and coordinates all sub-components:
  - AssetManifest      — authoritative reference store
  - PlaceholderRegistry — PLACEHOLDER tracking and builder UI
  - AssetLinker        — PLACEHOLDER → LINKED transitions
  - AssetValidator     — I12 enforcement before CGS commit
  - AssetCleanupManager — orphaned reference removal
  - EngineSyncReceiver — bulk engine feedback processing
  - AudioManifest      — audio-specific metadata
  - AssetReportGenerator — builder UI reports

## Session Lifecycle
```
Session starts
  └── AssetRegistryManager.__init__()
        └── All sub-components initialised

Entity defined in GDE
  └── manager.auto_register_entity_assets(actor_definition)
        └── AssetNamingPolicy.generate() per component field
              └── AssetManifest.register(PLACEHOLDER ref)
                    └── PlaceholderRegistry.track()

CGS commit attempted
  └── manager.validate_for_commit()
        └── AssetValidator.validate_no_unresolved()
              └── Err if any UNRESOLVED → commit blocked (I12)

Engine connects (tick 0)
  └── manager.receive_engine_feedback(resolved_assets)
        └── EngineSyncReceiver.receive_initial_sync()
              └── AssetLinker.link_bulk() → PLACEHOLDER → LINKED

Session ends
  └── manager.to_dict() → saved to session file
```

## Thread Safety
AssetRegistryManager is NOT thread-safe. See individual component docs.
All calls must come from the schema pipeline thread (single-threaded) or
at tick boundaries as guaranteed by I13.
"""

from __future__ import annotations

import json
from typing import Optional

from asset_cleanup_manager import AssetCleanupManager
from asset_linker import AssetLinker, LinkResult
from asset_manifest import AssetManifest
from asset_naming_policy import AssetNamingPolicy
from asset_reference import AssetReference
from asset_report import AssetReport, AssetReportGenerator
from asset_status_enum import AssetStatus
from asset_type_enum import AssetType
from asset_validator import AssetValidationReport, AssetValidator
from audio_manifest import AudioManifest, AudioMetadata
from engine_sync_receiver import EngineSyncReceiver, SyncResult
from placeholder_registry import PlaceholderRegistry


class AssetRegistryManager:
    """
    Single entry point for all XACE Asset Registry operations.

    Instantiated once per session by the GDE / Schema Factory at startup.
    Passed by reference to all sub-systems that need asset resolution.
    """

    def __init__(self, schema_version: str = "0.1.0") -> None:
        self._schema_version = schema_version

        # Core sub-components
        self._manifest          = AssetManifest()
        self._placeholder_reg   = PlaceholderRegistry()
        self._audio_manifest    = AudioManifest()

        # Operation handlers
        self._linker            = AssetLinker(self._manifest, self._placeholder_reg)
        self._validator         = AssetValidator(self._manifest)
        self._cleanup_manager   = AssetCleanupManager(self._manifest, self._placeholder_reg)
        self._engine_receiver   = EngineSyncReceiver(self._linker, self._manifest)
        self._report_generator  = AssetReportGenerator(
            self._manifest, self._placeholder_reg, schema_version
        )

    # ── Auto-Registration (GDE → Registry) ───────────────────────────────

    def auto_register(
        self,
        entity_type: str,
        entity_name: str,
        asset_type: AssetType,
        entity_id: Optional[str] = None,
        version: int = 1,
    ) -> AssetReference:
        """
        Auto-registers one PLACEHOLDER asset reference using the naming policy.

        Called by the GDE when an entity definition is created that
        declares an asset-carrying component (COMP_RENDER_V1, COMP_AUDIO_EMITTER_V1, etc.)

        Returns the created AssetReference.
        Raises ValueError if the asset_id is already registered (use get() to check first).
        """
        asset_id = AssetNamingPolicy.generate(entity_type, entity_name, asset_type, version)

        # Idempotent check — return existing if already registered
        existing = self._manifest.get(asset_id)
        if existing is not None:
            return existing

        ref = AssetReference.make_placeholder(asset_id, asset_type)
        self._manifest.register(ref)
        self._placeholder_reg.track(
            asset_id=asset_id,
            asset_type=asset_type,
            entity_id=entity_id,
            schema_version=self._schema_version,
        )
        return ref

    def auto_register_many(
        self,
        entity_type: str,
        entity_name: str,
        asset_types: list[AssetType],
        entity_id: Optional[str] = None,
    ) -> list[AssetReference]:
        """
        Auto-registers multiple asset types for one entity in one call.
        Returns list of created AssetReferences in the order of asset_types.
        """
        return [
            self.auto_register(entity_type, entity_name, at, entity_id)
            for at in asset_types
        ]

    def register_unresolved(
        self, asset_id: str, asset_type: AssetType
    ) -> AssetReference:
        """
        Registers an UNRESOLVED reference found in the CGS that has no
        manifest entry. This marks the I12 violation for reporting.
        """
        ref = AssetReference.make_unresolved(asset_id, asset_type)
        try:
            self._manifest.register(ref)
        except ValueError:
            pass  # Already registered
        return ref

    # ── Linking ───────────────────────────────────────────────────────────

    def link(
        self,
        asset_id: str,
        resolved_path: str,
        source: str = "manual",
    ) -> LinkResult:
        """Links an asset to a resolved engine path."""
        return self._linker.link(asset_id, resolved_path, source=source)

    def link_bulk(
        self,
        links: dict[str, str],
        source: str = "manual",
    ) -> list[LinkResult]:
        """Links multiple assets. Sorted for determinism (D11)."""
        return self._linker.link_bulk(links, source=source)

    def mark_missing(self, asset_id: str) -> LinkResult:
        """Marks a LINKED asset as MISSING (file deleted or moved)."""
        return self._linker.mark_missing(asset_id)

    # ── Engine Feedback Integration ───────────────────────────────────────

    def receive_engine_feedback(
        self,
        resolved_assets: dict[str, str],
        tick: int,
        generated_frame: int = 0,
    ) -> SyncResult:
        """
        Processes AssetResolutionUpdateFeedback from the engine adapter.
        Called at tick boundaries only (I13).
        """
        return self._engine_receiver.receive_feedback(
            resolved_assets=resolved_assets,
            tick=tick,
            generated_frame=generated_frame,
        )

    def receive_engine_feedback_from_payload(
        self,
        payload_dict: dict,
        tick: int,
    ) -> SyncResult:
        """Parses and processes a raw AssetResolutionUpdateFeedback payload."""
        return self._engine_receiver.receive_feedback_from_payload(payload_dict, tick)

    # ── Validation (I12) ──────────────────────────────────────────────────

    def validate_for_commit(self) -> AssetValidationReport:
        """
        Validates that no UNRESOLVED references exist before CGS commit (I12).
        Called by the GDE before applying any DSLTransaction.
        Returns a report — the caller checks report.blocks_commit.
        """
        return self._validator.validate_no_unresolved()

    def validate_asset_id(
        self,
        asset_id: str,
        expected_type: Optional[AssetType] = None,
        component_path: Optional[str] = None,
    ) -> AssetValidationReport:
        """Validates a single asset_id from the Schema Factory / GDE."""
        return self._validator.validate_asset_id(asset_id, expected_type, component_path)

    def validate_full_manifest(self) -> AssetValidationReport:
        """Validates the entire manifest. Used at session load."""
        return self._validator.validate_manifest()

    # ── Cleanup ───────────────────────────────────────────────────────────

    def cleanup_for_entity(self, entity_id: str) -> int:
        """
        Removes orphaned PLACEHOLDER refs when an entity is deleted.
        Returns count of references removed.
        """
        result = self._cleanup_manager.cleanup_for_entity(entity_id)
        return result.removed_count

    def cleanup_orphaned(self, active_asset_ids: set[str]) -> int:
        """
        Removes PLACEHOLDER refs not in the active CGS asset_id set.
        Returns count removed.
        """
        result = self._cleanup_manager.cleanup_orphaned_placeholders(active_asset_ids)
        return result.removed_count

    # ── Queries ───────────────────────────────────────────────────────────

    def get(self, asset_id: str) -> Optional[AssetReference]:
        """Returns the AssetReference for asset_id, or None."""
        return self._manifest.get(asset_id)

    def contains(self, asset_id: str) -> bool:
        """Returns True if asset_id is registered."""
        return self._manifest.contains(asset_id)

    def get_all_placeholders(self) -> list[AssetReference]:
        """Returns all PLACEHOLDER refs sorted by asset_id (D11)."""
        return self._manifest.get_all_placeholders()

    def get_all_unresolved(self) -> list[AssetReference]:
        """Returns all UNRESOLVED refs (I12 blockers), sorted."""
        return self._manifest.get_all_unresolved()

    def has_unresolved(self) -> bool:
        """Fast check — any UNRESOLVED refs?"""
        return self._manifest.has_unresolved()

    def total_asset_count(self) -> int:
        """Total registered asset references."""
        return self._manifest.total_count()

    def placeholder_count(self) -> int:
        """Count of PLACEHOLDER refs."""
        return self._manifest.count_by_status(AssetStatus.PLACEHOLDER)

    # ── Audio ─────────────────────────────────────────────────────────────

    def register_audio_metadata(self, metadata: AudioMetadata) -> None:
        """Registers audio-specific metadata alongside the main manifest ref."""
        self._audio_manifest.register(metadata)

    def get_audio_metadata(self, asset_id: str) -> Optional[AudioMetadata]:
        """Returns audio metadata for an asset_id, or None."""
        return self._audio_manifest.get(asset_id)

    def update_audio_duration(self, asset_id: str, duration_seconds: float) -> bool:
        """Updates audio duration after engine resolution."""
        return self._audio_manifest.update_audio_duration(asset_id, duration_seconds)

    # ── Reporting ─────────────────────────────────────────────────────────

    def generate_report(self) -> AssetReport:
        """Generates a full AssetReport for the builder UI."""
        return self._report_generator.generate()

    def generate_minimal_report(self) -> dict:
        """Generates a lightweight summary for high-frequency UI refreshes."""
        return self._report_generator.generate_minimal()

    def builder_summary(self) -> str:
        """
        Returns the zero-experience builder UI message.
        CLAUDE.md: "7 assets are placeholders — game runs but looks like grey boxes"
        """
        return self._manifest.compute_metrics().builder_summary

    # ── Direct Sub-Component Access ───────────────────────────────────────

    @property
    def manifest(self) -> AssetManifest:
        return self._manifest

    @property
    def placeholder_registry(self) -> PlaceholderRegistry:
        return self._placeholder_reg

    @property
    def audio_manifest(self) -> AudioManifest:
        return self._audio_manifest

    @property
    def linker(self) -> AssetLinker:
        return self._linker

    @property
    def validator(self) -> AssetValidator:
        return self._validator

    @property
    def engine_receiver(self) -> EngineSyncReceiver:
        return self._engine_receiver

    # ── Serialization ─────────────────────────────────────────────────────

    def to_dict(self) -> dict:
        """Serializes the full registry state for session save."""
        return {
            "schema_version": self._schema_version,
            "manifest": self._manifest.to_dict(),
            "placeholder_registry": self._placeholder_reg.to_dict(),
            "audio_manifest": self._audio_manifest.to_dict(),
        }

    @classmethod
    def from_dict(cls, data: dict) -> "AssetRegistryManager":
        """Restores the full registry state from a saved session dict."""
        schema_version = data.get("schema_version", "0.1.0")
        manager = cls(schema_version=schema_version)

        if "manifest" in data:
            manager._manifest = AssetManifest.from_dict(data["manifest"])
            # Rebuild linker/validator/receiver with restored manifest
            manager._linker = AssetLinker(manager._manifest, manager._placeholder_reg)
            manager._validator = AssetValidator(manager._manifest)
            manager._engine_receiver = EngineSyncReceiver(
                manager._linker, manager._manifest
            )
            manager._report_generator = AssetReportGenerator(
                manager._manifest, manager._placeholder_reg, schema_version
            )

        if "placeholder_registry" in data:
            manager._placeholder_reg = PlaceholderRegistry.from_dict(
                data["placeholder_registry"]
            )

        if "audio_manifest" in data:
            manager._audio_manifest = AudioManifest.from_dict(data["audio_manifest"])

        return manager

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent, default=str)

    @classmethod
    def from_json(cls, json_str: str) -> "AssetRegistryManager":
        return cls.from_dict(json.loads(json_str))

    def __repr__(self) -> str:
        return (
            f"AssetRegistryManager("
            f"total={self.total_asset_count()}, "
            f"placeholder={self.placeholder_count()}, "
            f"unresolved={len(self.get_all_unresolved())}, "
            f"schema='{self._schema_version}')"
        )