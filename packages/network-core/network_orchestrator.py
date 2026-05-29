"""High-level Python network lifecycle orchestration for XACE.

The Rust network-core crate owns deterministic simulation primitives. This
module is the Python-side coordinator used by tooling and builder/runtime glue
to reason about network lifecycle, mode transitions, peer readiness, and tick
advancement without opening sockets itself.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from time import monotonic
from typing import Dict, Iterable, Optional, Set

try:
    from .network_mode import NetworkMode
except ImportError:  # pragma: no cover - supports direct script-path imports.
    from network_mode import NetworkMode


class NetworkLifecycleState(str, Enum):
    CREATED = "created"
    CONFIGURED = "configured"
    STARTING = "starting"
    LIVE = "live"
    PAUSED = "paused"
    RESYNCING = "resyncing"
    STOPPING = "stopping"
    STOPPED = "stopped"
    FAILED = "failed"

    @property
    def is_terminal(self) -> bool:
        return self in {self.STOPPED, self.FAILED}


@dataclass(frozen=True)
class NetworkPeer:
    peer_id: int
    display_name: str = ""
    engine_name: str = ""
    adapter_version: str = ""
    joined_tick: int = 0
    last_seen_tick: int = 0
    live: bool = False

    def validate(self) -> None:
        if self.peer_id <= 0:
            raise ValueError("peer_id must be greater than zero")
        if self.joined_tick < 0 or self.last_seen_tick < 0:
            raise ValueError("peer ticks must be non-negative")


@dataclass(frozen=True)
class NetworkOrchestratorConfig:
    mode: NetworkMode = NetworkMode.OFFLINE
    max_peers: int = 64
    heartbeat_timeout_ticks: int = 180
    allow_late_join: bool = True
    require_all_live_peers: bool = True
    local_peer_id: Optional[int] = None
    server_peer_id: Optional[int] = None

    def validate(self) -> None:
        if self.max_peers < 0:
            raise ValueError("max_peers must be non-negative")
        if self.mode.is_multiplayer and self.max_peers == 0:
            raise ValueError("multiplayer modes require max_peers > 0")
        if self.heartbeat_timeout_ticks <= 0:
            raise ValueError("heartbeat_timeout_ticks must be greater than zero")
        for label, peer_id in (
            ("local_peer_id", self.local_peer_id),
            ("server_peer_id", self.server_peer_id),
        ):
            if peer_id is not None and peer_id <= 0:
                raise ValueError(f"{label} must be greater than zero")
        if self.mode.needs_upstream_server and self.server_peer_id is None:
            raise ValueError("client mode requires server_peer_id")


@dataclass(frozen=True)
class NetworkStatus:
    mode: NetworkMode
    state: NetworkLifecycleState
    tick: int
    peer_count: int
    live_peer_count: int
    required_input_peers: tuple[int, ...]
    paused_reason: Optional[str]
    failed_reason: Optional[str]


@dataclass
class NetworkOrchestrator:
    config: NetworkOrchestratorConfig = field(default_factory=NetworkOrchestratorConfig)
    state: NetworkLifecycleState = NetworkLifecycleState.CREATED
    tick: int = 0
    peers: Dict[int, NetworkPeer] = field(default_factory=dict)
    paused_reason: Optional[str] = None
    failed_reason: Optional[str] = None
    started_monotonic: Optional[float] = None

    def __post_init__(self) -> None:
        self.config.validate()
        if self.config.local_peer_id is not None and self.config.local_peer_id not in self.peers:
            self.peers[self.config.local_peer_id] = NetworkPeer(
                peer_id=self.config.local_peer_id,
                display_name="local",
                joined_tick=self.tick,
                last_seen_tick=self.tick,
                live=self.config.mode is NetworkMode.OFFLINE,
            )

    @classmethod
    def for_mode(cls, mode: NetworkMode | str, **kwargs: object) -> "NetworkOrchestrator":
        parsed_mode = NetworkMode.parse(mode)
        return cls(NetworkOrchestratorConfig(mode=parsed_mode, **kwargs))

    def configure(self, config: NetworkOrchestratorConfig) -> None:
        self._require_state({NetworkLifecycleState.CREATED, NetworkLifecycleState.CONFIGURED})
        config.validate()
        self.config = config
        self.state = NetworkLifecycleState.CONFIGURED

    def start(self) -> None:
        self._require_state({NetworkLifecycleState.CREATED, NetworkLifecycleState.CONFIGURED})
        self.state = NetworkLifecycleState.STARTING
        self.started_monotonic = monotonic()
        if self.config.mode is NetworkMode.OFFLINE:
            self.state = NetworkLifecycleState.LIVE
        elif not self.config.mode.accepts_remote_peers and self.config.mode is not NetworkMode.CLIENT:
            raise RuntimeError(f"mode {self.config.mode.value} cannot start network service")

    def mark_live(self) -> None:
        self._require_state({NetworkLifecycleState.STARTING, NetworkLifecycleState.RESYNCING})
        self.state = NetworkLifecycleState.LIVE
        self.paused_reason = None

    def pause(self, reason: str) -> None:
        self._require_state({NetworkLifecycleState.STARTING, NetworkLifecycleState.LIVE})
        self.state = NetworkLifecycleState.PAUSED
        self.paused_reason = reason or "paused"

    def resume(self) -> None:
        self._require_state({NetworkLifecycleState.PAUSED})
        self.state = NetworkLifecycleState.LIVE
        self.paused_reason = None

    def enter_resync(self, reason: str = "resync") -> None:
        self._require_state({NetworkLifecycleState.LIVE, NetworkLifecycleState.PAUSED})
        self.state = NetworkLifecycleState.RESYNCING
        self.paused_reason = reason

    def stop(self) -> None:
        if self.state.is_terminal:
            return
        self.state = NetworkLifecycleState.STOPPING
        self.peers.clear()
        self.state = NetworkLifecycleState.STOPPED

    def fail(self, reason: str) -> None:
        self.failed_reason = reason or "network orchestrator failed"
        self.state = NetworkLifecycleState.FAILED

    def transition_mode(self, mode: NetworkMode | str) -> None:
        self._require_state({NetworkLifecycleState.CREATED, NetworkLifecycleState.CONFIGURED})
        next_mode = NetworkMode.parse(mode)
        if not self.config.mode.compatible_with(next_mode):
            raise ValueError(
                f"cannot transition configured mode {self.config.mode.value} to {next_mode.value}"
            )
        self.config = NetworkOrchestratorConfig(
            mode=next_mode,
            max_peers=self.config.max_peers,
            heartbeat_timeout_ticks=self.config.heartbeat_timeout_ticks,
            allow_late_join=self.config.allow_late_join,
            require_all_live_peers=self.config.require_all_live_peers,
            local_peer_id=self.config.local_peer_id,
            server_peer_id=self.config.server_peer_id,
        )
        self.config.validate()
        self.state = NetworkLifecycleState.CONFIGURED

    def add_peer(
        self,
        peer_id: int,
        *,
        display_name: str = "",
        engine_name: str = "",
        adapter_version: str = "",
    ) -> NetworkPeer:
        if self.config.mode is NetworkMode.OFFLINE:
            raise RuntimeError("offline mode does not accept remote peers")
        if not self.config.allow_late_join and self.state is NetworkLifecycleState.LIVE:
            raise RuntimeError("late joins are disabled for this session")
        if len(self.peers) >= self.config.max_peers:
            raise RuntimeError(f"peer limit reached: {self.config.max_peers}")
        if peer_id in self.peers:
            raise ValueError(f"peer {peer_id} already exists")

        peer = NetworkPeer(
            peer_id=peer_id,
            display_name=display_name or f"peer_{peer_id}",
            engine_name=engine_name,
            adapter_version=adapter_version,
            joined_tick=self.tick,
            last_seen_tick=self.tick,
        )
        peer.validate()
        self.peers[peer_id] = peer
        return peer

    def remove_peer(self, peer_id: int) -> NetworkPeer:
        try:
            return self.peers.pop(peer_id)
        except KeyError as exc:
            raise KeyError(f"unknown peer {peer_id}") from exc

    def mark_peer_live(self, peer_id: int) -> None:
        peer = self._peer(peer_id)
        self.peers[peer_id] = NetworkPeer(
            peer_id=peer.peer_id,
            display_name=peer.display_name,
            engine_name=peer.engine_name,
            adapter_version=peer.adapter_version,
            joined_tick=peer.joined_tick,
            last_seen_tick=self.tick,
            live=True,
        )

    def observe_heartbeat(self, peer_id: int) -> None:
        peer = self._peer(peer_id)
        self.peers[peer_id] = NetworkPeer(
            peer_id=peer.peer_id,
            display_name=peer.display_name,
            engine_name=peer.engine_name,
            adapter_version=peer.adapter_version,
            joined_tick=peer.joined_tick,
            last_seen_tick=self.tick,
            live=peer.live,
        )

    def advance_tick(self, count: int = 1) -> int:
        if count <= 0:
            raise ValueError("tick count must be greater than zero")
        if self.state not in {NetworkLifecycleState.LIVE, NetworkLifecycleState.RESYNCING}:
            raise RuntimeError(f"cannot advance tick while state is {self.state.value}")
        self.tick += count
        return self.tick

    def timed_out_peers(self) -> tuple[int, ...]:
        return tuple(
            peer.peer_id
            for peer in self.peers.values()
            if peer.live
            and self.tick - peer.last_seen_tick > self.config.heartbeat_timeout_ticks
        )

    def required_input_peers(self) -> tuple[int, ...]:
        if not self.config.mode.requires_lockstep:
            return ()
        if not self.config.require_all_live_peers and self.config.mode is NetworkMode.CLIENT:
            return tuple(
                peer_id
                for peer_id in (self.config.server_peer_id,)
                if peer_id is not None and peer_id in self.peers
            )
        return tuple(sorted(peer.peer_id for peer in self.peers.values() if peer.live))

    def status(self) -> NetworkStatus:
        live_peers = [peer for peer in self.peers.values() if peer.live]
        return NetworkStatus(
            mode=self.config.mode,
            state=self.state,
            tick=self.tick,
            peer_count=len(self.peers),
            live_peer_count=len(live_peers),
            required_input_peers=self.required_input_peers(),
            paused_reason=self.paused_reason,
            failed_reason=self.failed_reason,
        )

    def sync_required_peers(self, peer_ids: Iterable[int]) -> None:
        desired: Set[int] = set(peer_ids)
        for peer_id in desired:
            if peer_id <= 0:
                raise ValueError("peer ids must be greater than zero")
            if peer_id not in self.peers:
                self.add_peer(peer_id)
        for peer_id in list(self.peers):
            if peer_id not in desired and peer_id != self.config.local_peer_id:
                self.remove_peer(peer_id)

    def _peer(self, peer_id: int) -> NetworkPeer:
        try:
            return self.peers[peer_id]
        except KeyError as exc:
            raise KeyError(f"unknown peer {peer_id}") from exc

    def _require_state(self, allowed: Set[NetworkLifecycleState]) -> None:
        if self.state not in allowed:
            allowed_values = ", ".join(sorted(state.value for state in allowed))
            raise RuntimeError(
                f"invalid network lifecycle state {self.state.value}; expected one of: {allowed_values}"
            )
