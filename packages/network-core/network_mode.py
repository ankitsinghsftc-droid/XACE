"""Canonical network mode helpers for XACE multiplayer tooling.

This module mirrors the Rust-side NetworkMode enum without requiring Python
callers to import or parse Rust metadata. It is intentionally small and
dependency-free because builder scripts, orchestration glue, and generated
engine adapters may all need to make the same mode decisions.
"""

from __future__ import annotations

from enum import Enum
from typing import Iterable


class NetworkMode(str, Enum):
    """Supported runtime networking modes.

    The string values are stable wire/tooling identifiers. Display names can
    change later; these values should not.
    """

    OFFLINE = "offline"
    HOST = "host"
    CLIENT = "client"
    DEDICATED_SERVER = "dedicated_server"
    PEER_TO_PEER = "peer_to_peer"

    @classmethod
    def parse(cls, value: "NetworkMode | str") -> "NetworkMode":
        if isinstance(value, cls):
            return value

        normalised = str(value).strip().lower().replace("-", "_")
        aliases = {
            "solo": cls.OFFLINE,
            "single_player": cls.OFFLINE,
            "singleplayer": cls.OFFLINE,
            "server": cls.DEDICATED_SERVER,
            "dedicated": cls.DEDICATED_SERVER,
            "listen_server": cls.HOST,
            "p2p": cls.PEER_TO_PEER,
            "peer": cls.PEER_TO_PEER,
        }
        if normalised in aliases:
            return aliases[normalised]

        try:
            return cls(normalised)
        except ValueError as exc:
            valid = ", ".join(mode.value for mode in cls)
            raise ValueError(f"unknown network mode '{value}', expected one of: {valid}") from exc

    @classmethod
    def values(cls) -> tuple[str, ...]:
        return tuple(mode.value for mode in cls)

    @classmethod
    def multiplayer_modes(cls) -> tuple["NetworkMode", ...]:
        return tuple(mode for mode in cls if mode.is_multiplayer)

    @property
    def is_multiplayer(self) -> bool:
        return self is not self.OFFLINE

    @property
    def requires_lockstep(self) -> bool:
        return self is not self.OFFLINE

    @property
    def is_server_authoritative(self) -> bool:
        return self in {self.HOST, self.CLIENT, self.DEDICATED_SERVER}

    @property
    def accepts_remote_peers(self) -> bool:
        return self in {self.HOST, self.DEDICATED_SERVER, self.PEER_TO_PEER}

    @property
    def owns_simulation_clock(self) -> bool:
        return self in {self.OFFLINE, self.HOST, self.DEDICATED_SERVER, self.PEER_TO_PEER}

    @property
    def needs_upstream_server(self) -> bool:
        return self is self.CLIENT

    def compatible_with(self, other: "NetworkMode | str") -> bool:
        other_mode = self.parse(other)
        if self is self.OFFLINE or other_mode is self.OFFLINE:
            return self is other_mode
        if self is self.CLIENT:
            return other_mode in {self.HOST, self.DEDICATED_SERVER}
        if other_mode is self.CLIENT:
            return self in {self.HOST, self.DEDICATED_SERVER}
        if self is self.PEER_TO_PEER or other_mode is self.PEER_TO_PEER:
            return self is other_mode
        return True


def parse_network_modes(values: Iterable["NetworkMode | str"]) -> tuple[NetworkMode, ...]:
    """Parse a deterministic tuple of unique modes preserving input order."""

    seen: set[NetworkMode] = set()
    parsed: list[NetworkMode] = []
    for value in values:
        mode = NetworkMode.parse(value)
        if mode not in seen:
            parsed.append(mode)
            seen.add(mode)
    return tuple(parsed)
