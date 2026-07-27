"""
audio_manifest.py — Audio-specific asset tracking and metadata.

A specialised manifest layer for audio assets (AUDIO_CLIP and AUDIO_MUSIC)
that tracks additional metadata the main AssetManifest does not carry:
  - Duration estimates (for sequence planning and budget warnings)
  - Looping configuration
  - 3D vs 2D spatialization
  - Volume and pitch defaults
  - Music track sequencing (for COMP_MUSIC_STATE_V1)

## Why Separate From AssetManifest
The main AssetManifest is a generic registry of all asset types.
Audio has enough domain-specific metadata to justify a dedicated layer.
The PIL performance risk guard queries audio duration estimates when
evaluating mutations that involve many audio emitters.

## Relationship to AssetManifest
AudioManifest does NOT store AssetReference objects — it only stores
asset_ids and their audio metadata. The full reference (status, resolved_path)
lives in AssetManifest. AudioManifest is an overlay.

## COMP_AUDIO_EMITTER_V1 Integration
When COMP_AUDIO_EMITTER_V1 is created for an entity, the auto-registration
flow creates an AUDIO_CLIP AssetReference in the main manifest AND registers
the audio metadata in AudioManifest with sensible defaults.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

from asset_type_enum import AssetType


# ── Audio Spatialization ──────────────────────────────────────────────────────

class AudioSpatialization(str, Enum):
    """Whether the audio plays in 3D space or flat (2D/UI)."""
    SPATIAL_3D = "SPATIAL_3D"   # Positional audio — volume attenuates with distance
    FLAT_2D    = "FLAT_2D"      # Non-positional — UI sounds, music, global ambience


# ── Audio Metadata ────────────────────────────────────────────────────────────

@dataclass
class AudioMetadata:
    """
    Audio-specific metadata for one AUDIO_CLIP or AUDIO_MUSIC asset.

    All values are designer-set estimates used for sequencing and budget
    warnings. The engine is the authoritative source of actual duration
    (from AssetResolutionUpdate feedback), which updates duration_seconds
    when available.
    """
    asset_id: str
    asset_type: AssetType       # Must be AUDIO_CLIP or AUDIO_MUSIC

    # Duration estimate in seconds (0.0 = unknown until engine resolves)
    duration_seconds: float = 0.0

    # Whether this clip loops by default
    loops: bool = False

    # 3D positional or flat 2D
    spatialization: AudioSpatialization = AudioSpatialization.SPATIAL_3D

    # Default volume (0.0 silent, 1.0 full)
    default_volume: float = 1.0

    # Default pitch multiplier (1.0 = normal)
    default_pitch: float = 1.0

    # For AUDIO_MUSIC: tracks that should play before/after this one
    previous_track_id: Optional[str] = None
    next_track_id: Optional[str] = None

    # Tags for filtering (e.g. "combat", "ambient", "ui", "voice")
    tags: list[str] = field(default_factory=list)

    # Human-readable label for the builder UI
    display_name: str = ""

    def __post_init__(self) -> None:
        if self.asset_type not in (AssetType.AUDIO_CLIP, AssetType.AUDIO_MUSIC):
            raise ValueError(
                f"AudioMetadata: asset_type must be AUDIO_CLIP or AUDIO_MUSIC, "
                f"got {self.asset_type.value} for '{self.asset_id}'"
            )
        if not (0.0 <= self.default_volume <= 1.0):
            raise ValueError(
                f"AudioMetadata '{self.asset_id}': default_volume must be in [0.0, 1.0], "
                f"got {self.default_volume}"
            )
        if self.default_pitch <= 0.0:
            raise ValueError(
                f"AudioMetadata '{self.asset_id}': default_pitch must be > 0.0, "
                f"got {self.default_pitch}"
            )
        if not self.display_name:
            self.display_name = self.asset_id.replace("_", " ").title()

    @property
    def is_music(self) -> bool:
        return self.asset_type == AssetType.AUDIO_MUSIC

    @property
    def is_sfx(self) -> bool:
        return self.asset_type == AssetType.AUDIO_CLIP

    @property
    def is_looping(self) -> bool:
        return self.loops

    @property
    def duration_known(self) -> bool:
        return self.duration_seconds > 0.0

    def to_dict(self) -> dict:
        return {
            "asset_id": self.asset_id,
            "asset_type": self.asset_type.value,
            "duration_seconds": self.duration_seconds,
            "loops": self.loops,
            "spatialization": self.spatialization.value,
            "default_volume": self.default_volume,
            "default_pitch": self.default_pitch,
            "previous_track_id": self.previous_track_id,
            "next_track_id": self.next_track_id,
            "tags": sorted(self.tags),
            "display_name": self.display_name,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "AudioMetadata":
        return cls(
            asset_id=data["asset_id"],
            asset_type=AssetType.from_string(data["asset_type"]),
            duration_seconds=float(data.get("duration_seconds", 0.0)),
            loops=bool(data.get("loops", False)),
            spatialization=AudioSpatialization(
                data.get("spatialization", "SPATIAL_3D")
            ),
            default_volume=float(data.get("default_volume", 1.0)),
            default_pitch=float(data.get("default_pitch", 1.0)),
            previous_track_id=data.get("previous_track_id"),
            next_track_id=data.get("next_track_id"),
            tags=data.get("tags", []),
            display_name=data.get("display_name", ""),
        )


# ── Audio Budget Summary ──────────────────────────────────────────────────────

@dataclass
class AudioBudgetSummary:
    """
    Aggregate audio statistics for the PIL performance risk guard.
    Returned by AudioManifest.compute_budget_summary().
    """
    total_sfx_clips: int
    total_music_tracks: int
    sfx_with_known_duration: int
    total_sfx_duration_seconds: float
    music_with_known_duration: int
    total_music_duration_seconds: float
    looping_sfx_count: int
    spatial_3d_count: int
    flat_2d_count: int

    def to_dict(self) -> dict:
        return {
            "total_sfx_clips": self.total_sfx_clips,
            "total_music_tracks": self.total_music_tracks,
            "sfx_with_known_duration": self.sfx_with_known_duration,
            "total_sfx_duration_seconds": self.total_sfx_duration_seconds,
            "music_with_known_duration": self.music_with_known_duration,
            "total_music_duration_seconds": self.total_music_duration_seconds,
            "looping_sfx_count": self.looping_sfx_count,
            "spatial_3d_count": self.spatial_3d_count,
            "flat_2d_count": self.flat_2d_count,
        }


# ── Audio Manifest ────────────────────────────────────────────────────────────

class AudioManifest:
    """
    Specialised overlay registry for AUDIO_CLIP and AUDIO_MUSIC assets.

    Stores audio-domain metadata on top of the main AssetManifest.
    Keyed by asset_id — same key space as AssetManifest.
    """

    def __init__(self) -> None:
        # Primary store: asset_id → AudioMetadata
        self._metadata: dict[str, AudioMetadata] = {}

        # Secondary index: tag → set[asset_id] for filtered queries
        self._by_tag: dict[str, set[str]] = {}

        # Secondary index: AssetType → set[asset_id]
        self._by_type: dict[AssetType, set[str]] = {
            AssetType.AUDIO_CLIP:  set(),
            AssetType.AUDIO_MUSIC: set(),
        }

    # ── Registration ──────────────────────────────────────────────────────

    def register(self, metadata: AudioMetadata) -> None:
        """
        Registers audio metadata for an asset_id.
        Raises ValueError if asset_id is already registered.
        """
        if metadata.asset_id in self._metadata:
            raise ValueError(
                f"AudioManifest.register(): '{metadata.asset_id}' already registered. "
                "Use update_duration() to update duration after engine resolution."
            )
        self._metadata[metadata.asset_id] = metadata
        self._by_type[metadata.asset_type].add(metadata.asset_id)
        for tag in metadata.tags:
            self._by_tag.setdefault(tag, set()).add(metadata.asset_id)

    def register_sfx(
        self,
        asset_id: str,
        loops: bool = False,
        spatial: bool = True,
        volume: float = 1.0,
        tags: Optional[list[str]] = None,
    ) -> AudioMetadata:
        """
        Convenience factory for registering an AUDIO_CLIP with defaults.
        Returns the created AudioMetadata.
        """
        meta = AudioMetadata(
            asset_id=asset_id,
            asset_type=AssetType.AUDIO_CLIP,
            loops=loops,
            spatialization=(
                AudioSpatialization.SPATIAL_3D
                if spatial else AudioSpatialization.FLAT_2D
            ),
            default_volume=volume,
            tags=tags or [],
        )
        self.register(meta)
        return meta

    def register_music(
        self,
        asset_id: str,
        loops: bool = True,
        volume: float = 0.8,
        tags: Optional[list[str]] = None,
    ) -> AudioMetadata:
        """
        Convenience factory for registering an AUDIO_MUSIC track.
        Music is always FLAT_2D and loops by default.
        """
        meta = AudioMetadata(
            asset_id=asset_id,
            asset_type=AssetType.AUDIO_MUSIC,
            loops=loops,
            spatialization=AudioSpatialization.FLAT_2D,
            default_volume=volume,
            tags=tags or [],
        )
        self.register(meta)
        return meta

    # ── Updates ───────────────────────────────────────────────────────────

    def update_duration(self, asset_id: str, duration_seconds: float) -> bool:
        """
        Updates the duration of an audio asset after the engine resolves it.
        Called by engine_sync_receiver when AssetResolutionUpdate arrives
        with duration data from the engine.
        Returns True if found and updated, False if not registered.
        """
        meta = self._metadata.get(asset_id)
        if meta is None:
            return False
        if duration_seconds < 0.0:
            raise ValueError(
                f"AudioManifest.update_duration(): duration must be >= 0.0 "
                f"for '{asset_id}', got {duration_seconds}"
            )
        meta.duration_seconds = duration_seconds
        return True

    def link_music_sequence(
        self,
        asset_id: str,
        previous_track_id: Optional[str] = None,
        next_track_id: Optional[str] = None,
    ) -> None:
        """
        Sets the music sequence links for a track.
        Used to build a music playlist for COMP_MUSIC_STATE_V1.
        """
        meta = self._metadata.get(asset_id)
        if meta is None:
            raise KeyError(f"AudioManifest: '{asset_id}' not registered")
        if not meta.is_music:
            raise ValueError(
                f"AudioManifest.link_music_sequence(): '{asset_id}' is not AUDIO_MUSIC"
            )
        meta.previous_track_id = previous_track_id
        meta.next_track_id = next_track_id

    # ── Queries ───────────────────────────────────────────────────────────

    def get(self, asset_id: str) -> Optional[AudioMetadata]:
        """Returns AudioMetadata for the given asset_id, or None."""
        return self._metadata.get(asset_id)

    def get_all_sfx(self) -> list[AudioMetadata]:
        """Returns all AUDIO_CLIP metadata, sorted by asset_id (D11)."""
        ids = sorted(self._by_type[AssetType.AUDIO_CLIP])
        return [self._metadata[i] for i in ids]

    def get_all_music(self) -> list[AudioMetadata]:
        """Returns all AUDIO_MUSIC metadata, sorted by asset_id (D11)."""
        ids = sorted(self._by_type[AssetType.AUDIO_MUSIC])
        return [self._metadata[i] for i in ids]

    def get_by_tag(self, tag: str) -> list[AudioMetadata]:
        """Returns all audio assets with the given tag, sorted by asset_id."""
        ids = sorted(self._by_tag.get(tag, set()))
        return [self._metadata[i] for i in ids if i in self._metadata]

    def get_music_sequence(self, start_asset_id: str) -> list[AudioMetadata]:
        """
        Returns the full music sequence starting from the given track,
        following next_track_id links until a loop or dead end.
        """
        sequence = []
        visited = set()
        current_id: Optional[str] = start_asset_id

        while current_id and current_id not in visited:
            meta = self._metadata.get(current_id)
            if meta is None or not meta.is_music:
                break
            sequence.append(meta)
            visited.add(current_id)
            current_id = meta.next_track_id

        return sequence

    def contains(self, asset_id: str) -> bool:
        return asset_id in self._metadata

    def total_count(self) -> int:
        return len(self._metadata)

    def sfx_count(self) -> int:
        return len(self._by_type[AssetType.AUDIO_CLIP])

    def music_count(self) -> int:
        return len(self._by_type[AssetType.AUDIO_MUSIC])

    # ── Budget Summary ────────────────────────────────────────────────────

    def compute_budget_summary(self) -> AudioBudgetSummary:
        """
        Returns aggregate audio statistics for the PIL performance risk guard.
        """
        sfx_all = self.get_all_sfx()
        music_all = self.get_all_music()

        sfx_with_dur = [m for m in sfx_all if m.duration_known]
        music_with_dur = [m for m in music_all if m.duration_known]
        all_meta = list(self._metadata.values())

        return AudioBudgetSummary(
            total_sfx_clips=len(sfx_all),
            total_music_tracks=len(music_all),
            sfx_with_known_duration=len(sfx_with_dur),
            total_sfx_duration_seconds=sum(m.duration_seconds for m in sfx_with_dur),
            music_with_known_duration=len(music_with_dur),
            total_music_duration_seconds=sum(m.duration_seconds for m in music_with_dur),
            looping_sfx_count=sum(1 for m in sfx_all if m.loops),
            spatial_3d_count=sum(
                1 for m in all_meta
                if m.spatialization == AudioSpatialization.SPATIAL_3D
            ),
            flat_2d_count=sum(
                1 for m in all_meta
                if m.spatialization == AudioSpatialization.FLAT_2D
            ),
        )

    # ── Serialization ─────────────────────────────────────────────────────

    def to_dict(self) -> dict:
        return {
            "metadata": [
                meta.to_dict()
                for meta in sorted(
                    self._metadata.values(), key=lambda m: m.asset_id
                )
            ]
        }

    @classmethod
    def from_dict(cls, data: dict) -> "AudioManifest":
        manifest = cls()
        for meta_data in data.get("metadata", []):
            try:
                meta = AudioMetadata.from_dict(meta_data)
                manifest._metadata[meta.asset_id] = meta
                manifest._by_type[meta.asset_type].add(meta.asset_id)
                for tag in meta.tags:
                    manifest._by_tag.setdefault(tag, set()).add(meta.asset_id)
            except (ValueError, KeyError):
                continue  # Skip malformed entries on load
        return manifest

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent)

    @classmethod
    def from_json(cls, json_str: str) -> "AudioManifest":
        return cls.from_dict(json.loads(json_str))

    def __len__(self) -> int:
        return len(self._metadata)

    def __repr__(self) -> str:
        return (
            f"AudioManifest("
            f"sfx={self.sfx_count()}, "
            f"music={self.music_count()})"
        )