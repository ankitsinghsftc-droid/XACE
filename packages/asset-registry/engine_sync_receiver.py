"""
engine_sync_receiver.py — Receives AssetResolutionUpdate feedback from the engine
and applies bulk PLACEHOLDER → LINKED transitions to the Asset Registry.

## Integration Point
This module bridges the engine feedback pipeline (Phase 7.3) and the Asset
Registry (Phase 7.4). When the engine adapter connects and resolves assets
it was sent as PLACEHOLDERs, it sends AssetResolutionUpdateFeedback containing
all the asset_ids it has now loaded with their resolved paths.

## Feedback Flow (Audit 2 + Audit 6)
```
Engine adapter connects
  └── Receives SnapshotPayload with PLACEHOLDER asset_ids
        └── Engine loads available assets (meshes, audio, etc.)
              └── Sends AssetResolutionUpdateFeedback next tick:
                    { "resolved_assets": { "char_knight_mesh_v1": "/path/mesh.fbx", ... } }
                          └── EngineSyncReceiver.receive_feedback()
                                └── AssetLinker.link_bulk()
                                      └── Manifest: PLACEHOLDER → LINKED
                                            └── PlaceholderRegistry cleaned up
```

## Determinism (I13)
Feedback is always processed at tick boundaries (I13 from Phase 7.3).
The receiver is called from the PhaseOrchestrator after the feedback
buffer is drained — never mid-tick.

## Idempotency
The receiver is idempotent — receiving the same resolved_assets dict
twice produces the same result as receiving it once. The AssetLinker
is safe to call on an already-LINKED asset (it returns a no-op result).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

from asset_linker import AssetLinker, LinkResult
from asset_manifest import AssetManifest


# ── Sync Event ────────────────────────────────────────────────────────────────

@dataclass
class SyncEvent:
    """Record of one AssetResolutionUpdate feedback batch received."""
    tick: int
    generated_frame: int
    total_in_feedback: int
    linked_count: int
    skipped_count: int
    failed_count: int
    warnings: list[str]
    received_at: datetime = field(default_factory=datetime.utcnow)

    def to_dict(self) -> dict:
        return {
            "tick": self.tick,
            "generated_frame": self.generated_frame,
            "total_in_feedback": self.total_in_feedback,
            "linked_count": self.linked_count,
            "skipped_count": self.skipped_count,
            "failed_count": self.failed_count,
            "warnings": self.warnings,
            "received_at": self.received_at.isoformat(),
        }


# ── Sync Result ───────────────────────────────────────────────────────────────

@dataclass
class SyncResult:
    """Result returned from receive_feedback() for caller inspection."""
    tick: int
    link_results: list[LinkResult] = field(default_factory=list)

    @property
    def linked_count(self) -> int:
        return sum(1 for r in self.link_results if r.success)

    @property
    def failed_count(self) -> int:
        return sum(1 for r in self.link_results if not r.success)

    @property
    def warning_count(self) -> int:
        return sum(1 for r in self.link_results if r.has_warning)

    @property
    def warnings(self) -> list[str]:
        return [
            r.extension_warning
            for r in self.link_results
            if r.extension_warning
        ]

    @property
    def failures(self) -> list[str]:
        return [
            f"{r.asset_id}: {r.error}"
            for r in self.link_results
            if not r.success and r.error
        ]

    def summary(self) -> str:
        return (
            f"EngineSyncReceiver tick={self.tick}: "
            f"linked={self.linked_count}, "
            f"failed={self.failed_count}, "
            f"warnings={self.warning_count}"
        )


# ── Engine Sync Receiver ──────────────────────────────────────────────────────

class EngineSyncReceiver:
    """
    Processes AssetResolutionUpdateFeedback from the engine adapter and
    applies bulk PLACEHOLDER → LINKED transitions to the Asset Registry.

    ## Usage
    ```python
    receiver = EngineSyncReceiver(linker, manifest)

    # Called at tick boundary when FEEDBACK message arrives (I13):
    result = receiver.receive_feedback(
        resolved_assets={"character_knight_mesh_v1": "/assets/knight.fbx"},
        tick=42,
        generated_frame=2520,
    )
    print(result.summary())
    ```
    """

    def __init__(self, linker: AssetLinker, manifest: AssetManifest) -> None:
        self._linker = linker
        self._manifest = manifest
        self._sync_history: list[SyncEvent] = []
        self._total_linked: int = 0
        self._total_failed: int = 0

    # ── Primary API ───────────────────────────────────────────────────────

    def receive_feedback(
        self,
        resolved_assets: dict[str, str],
        tick: int,
        generated_frame: int = 0,
    ) -> SyncResult:
        """
        Processes one AssetResolutionUpdateFeedback batch.

        Args:
            resolved_assets: Dict of {asset_id: resolved_engine_path}.
                             Comes directly from AssetResolutionUpdateFeedback.resolved_assets.
            tick: The simulation tick this feedback was processed at (I13).
            generated_frame: The engine frame this feedback was generated in.

        Returns:
            SyncResult with per-asset link outcomes.
        """
        if not resolved_assets:
            return SyncResult(tick=tick)

        # Delegate to AssetLinker for the actual transitions
        link_results = self._linker.link_bulk(
            links=resolved_assets,
            source="engine_feedback",
        )

        result = SyncResult(tick=tick, link_results=link_results)

        # Record the sync event
        event = SyncEvent(
            tick=tick,
            generated_frame=generated_frame,
            total_in_feedback=len(resolved_assets),
            linked_count=result.linked_count,
            skipped_count=0,  # failures are counted separately
            failed_count=result.failed_count,
            warnings=result.warnings,
        )
        self._sync_history.append(event)
        self._total_linked += result.linked_count
        self._total_failed += result.failed_count

        # Log failures (these are unexpected — engine sent a ref we don't know)
        for failure in result.failures:
            print(f"[WARN] EngineSyncReceiver: link failed — {failure}")

        return result

    def receive_feedback_from_payload(
        self,
        payload_dict: dict,
        tick: int,
    ) -> SyncResult:
        """
        Parses and processes an AssetResolutionUpdateFeedback payload dict.

        The payload dict is the deserialized JSON from the wire message:
        ```json
        {
            "resolved_assets": {"char_knight_mesh_v1": "/path/to/knight.fbx"},
            "generated_frame": 2520
        }
        ```

        Args:
            payload_dict: Deserialized AssetResolutionUpdateFeedback JSON.
            tick: Current simulation tick.
        """
        resolved_assets = payload_dict.get("resolved_assets", {})
        generated_frame = payload_dict.get("generated_frame", 0)

        if not isinstance(resolved_assets, dict):
            print(
                f"[WARN] EngineSyncReceiver: 'resolved_assets' is not a dict "
                f"in feedback at tick={tick}"
            )
            return SyncResult(tick=tick)

        return self.receive_feedback(
            resolved_assets=resolved_assets,
            tick=tick,
            generated_frame=generated_frame,
        )

    # ── Bulk Initial Sync ─────────────────────────────────────────────────

    def receive_initial_sync(
        self,
        resolved_assets: dict[str, str],
        tick: int = 0,
    ) -> SyncResult:
        """
        Processes the initial asset resolution batch sent when the engine
        adapter first connects and loads all available assets.

        This is identical to receive_feedback() but labelled separately
        for clarity in sync logs — it represents the full initial state
        sync rather than an incremental update.
        """
        return self.receive_feedback(
            resolved_assets=resolved_assets,
            tick=tick,
            generated_frame=0,
        )

    # ── Inspection ────────────────────────────────────────────────────────

    def sync_history(self) -> list[SyncEvent]:
        """Returns all sync events, newest first."""
        return list(reversed(self._sync_history))

    def total_linked(self) -> int:
        """Total assets successfully linked across all sync events."""
        return self._total_linked

    def total_failed(self) -> int:
        """Total link failures across all sync events."""
        return self._total_failed

    def sync_count(self) -> int:
        """Number of feedback batches processed."""
        return len(self._sync_history)

    def remaining_placeholder_count(self) -> int:
        """
        Number of assets still PLACEHOLDER after all sync events.
        Surfaced in the builder UI as "N assets waiting for engine".
        """
        return self._manifest.count_by_status(
            __import__("asset_status_enum", fromlist=["AssetStatus"]).AssetStatus.PLACEHOLDER
        )

    def __repr__(self) -> str:
        return (
            f"EngineSyncReceiver("
            f"syncs={self.sync_count()}, "
            f"total_linked={self._total_linked}, "
            f"total_failed={self._total_failed})"
        )