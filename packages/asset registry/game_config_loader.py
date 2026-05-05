"""
game_config_loader.py — Loads game_config.yaml and declares DCL domain usage.

MASTER_PLAN Phase 7.4: "game_config_loader.py — loads game_config.yaml
domain declarations"

## What game_config.yaml Contains
Every XACE game project has a game_config.yaml at its root that declares:
  - Which DCL domain packages this game uses
  - The game's world_id and schema version
  - Asset registry configuration (naming conventions, auto-register rules)
  - Engine adapter target (Unity, Godot, Unreal)
  - Build targets and export settings

## DCL Domain Loading (CLAUDE.md Audit 1)
CLAUDE.md: "dcl_registry.py — CompositeComponentRegistry: core + domains +
GCL assembled at game load" and "game_config_loader.py — loads game_config.yaml
domain declarations"

The game_config.yaml `domains` key controls which DCL packages are loaded:
```yaml
domains:
  - combat
  - character
  - physics
  - world
```

Only declared domains are available in this game's CompositeComponentRegistry.
GDE validation, Schema Factory, and PIL all use the composite registry.
A system referencing COMP_HEALTH_V1 without `combat` in the domains list
will fail validation.

## Asset Registry Configuration
game_config.yaml also controls asset registry behaviour:
```yaml
asset_registry:
  auto_register: true          # Auto-create PLACEHOLDER refs on entity creation
  naming_convention: default   # Use AssetNamingPolicy.generate()
  placeholder_threshold_hours: 24  # Warn after N hours with no link
```

## Error Handling
Missing or malformed game_config.yaml raises GameConfigError.
Unknown domain names raise GameConfigError (must match DCL package names).
All validation errors are collected before raising — not fail-fast per field.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

try:
    import yaml
    _YAML_AVAILABLE = True
except ImportError:
    _YAML_AVAILABLE = False


# ── Known DCL Domain Names ────────────────────────────────────────────────────

# From MASTER_PLAN Phase 1.10 — all valid DCL domain package names.
KNOWN_DCL_DOMAINS: frozenset[str] = frozenset({
    "combat",
    "character",
    "physics",
    "ai",
    "stealth",
    "rpg",
    "world",
    "interaction",
    "camera",
    "audio",
    "network",
    "ui",
    "persistence",
})

# Known engine adapter targets
KNOWN_ENGINE_TARGETS: frozenset[str] = frozenset({
    "unity",
    "unreal",
    "godot",
    "custom",
})


# ── Game Config Error ─────────────────────────────────────────────────────────

class GameConfigError(Exception):
    """Raised when game_config.yaml is missing, malformed, or invalid."""
    pass


# ── Asset Registry Config ─────────────────────────────────────────────────────

@dataclass
class AssetRegistryConfig:
    """Asset registry settings from game_config.yaml."""
    auto_register: bool = True
    naming_convention: str = "default"
    placeholder_threshold_hours: float = 24.0
    max_suggestions_in_ui: int = 20
    warn_on_missing: bool = True

    @classmethod
    def from_dict(cls, data: dict) -> "AssetRegistryConfig":
        return cls(
            auto_register=bool(data.get("auto_register", True)),
            naming_convention=str(data.get("naming_convention", "default")),
            placeholder_threshold_hours=float(
                data.get("placeholder_threshold_hours", 24.0)
            ),
            max_suggestions_in_ui=int(data.get("max_suggestions_in_ui", 20)),
            warn_on_missing=bool(data.get("warn_on_missing", True)),
        )

    def to_dict(self) -> dict:
        return {
            "auto_register": self.auto_register,
            "naming_convention": self.naming_convention,
            "placeholder_threshold_hours": self.placeholder_threshold_hours,
            "max_suggestions_in_ui": self.max_suggestions_in_ui,
            "warn_on_missing": self.warn_on_missing,
        }


# ── Game Config ───────────────────────────────────────────────────────────────

@dataclass
class GameConfig:
    """
    Parsed and validated game_config.yaml for one XACE project.

    Returned by GameConfigLoader.load(). Used by:
      - dcl_loader.py to load the declared DCL domains
      - AssetRegistryManager for auto-registration configuration
      - ProtocolHandshake for world_id and schema_version validation
    """
    # Project identity
    world_id: str
    game_name: str
    schema_version: str = "0.1.0"

    # DCL domains declared for this game
    domains: list[str] = field(default_factory=list)

    # Engine adapter target
    engine_target: str = "unity"

    # Asset registry configuration
    asset_registry: AssetRegistryConfig = field(
        default_factory=AssetRegistryConfig
    )

    # GCL (game component library) folder path relative to project root
    gcl_path: str = "gcl"

    # Additional metadata (version, author, etc.)
    metadata: dict = field(default_factory=dict)

    # ── Convenience ───────────────────────────────────────────────────────

    @property
    def has_combat(self) -> bool:
        return "combat" in self.domains

    @property
    def has_audio(self) -> bool:
        return "audio" in self.domains

    @property
    def has_network(self) -> bool:
        return "network" in self.domains

    @property
    def has_rpg(self) -> bool:
        return "rpg" in self.domains

    @property
    def has_ai(self) -> bool:
        return "ai" in self.domains

    def has_domain(self, domain: str) -> bool:
        return domain in self.domains

    def to_dict(self) -> dict:
        return {
            "world_id": self.world_id,
            "game_name": self.game_name,
            "schema_version": self.schema_version,
            "domains": sorted(self.domains),
            "engine_target": self.engine_target,
            "asset_registry": self.asset_registry.to_dict(),
            "gcl_path": self.gcl_path,
            "metadata": self.metadata,
        }


# ── Game Config Loader ────────────────────────────────────────────────────────

class GameConfigLoader:
    """
    Loads, validates, and parses game_config.yaml from a project directory.

    ## Usage
    ```python
    loader = GameConfigLoader()
    config = loader.load("/path/to/my_game/")
    print(config.domains)   # ["combat", "character", "world"]
    print(config.world_id)  # "my_game_session"
    ```
    """

    CONFIG_FILENAME = "game_config.yaml"

    def __init__(self) -> None:
        self._last_loaded_path: Optional[Path] = None

    # ── Primary API ───────────────────────────────────────────────────────

    def load(self, project_root: str) -> GameConfig:
        """
        Loads and validates game_config.yaml from the project root directory.

        Args:
            project_root: Path to the XACE game project directory.

        Returns:
            Parsed and validated GameConfig.

        Raises:
            GameConfigError if the file is missing, unreadable, or invalid.
        """
        config_path = Path(project_root) / self.CONFIG_FILENAME

        if not config_path.exists():
            raise GameConfigError(
                f"game_config.yaml not found at '{config_path}'. "
                "Every XACE project must have a game_config.yaml at its root. "
                "Run 'xace init' to create one."
            )

        raw_data = self._read_yaml(config_path)
        self._last_loaded_path = config_path
        return self._parse_and_validate(raw_data, config_path)

    def load_from_dict(self, data: dict) -> GameConfig:
        """
        Parses a GameConfig from an already-loaded dict.
        Used in tests and when YAML is loaded externally.
        """
        return self._parse_and_validate(data, path=None)

    def load_from_yaml_string(self, yaml_string: str) -> GameConfig:
        """
        Parses a GameConfig from a YAML string.
        Used in tests.
        """
        if not _YAML_AVAILABLE:
            raise GameConfigError(
                "PyYAML is not installed. Install it with: pip install pyyaml"
            )
        try:
            data = yaml.safe_load(yaml_string)
        except yaml.YAMLError as e:
            raise GameConfigError(f"Invalid YAML: {e}") from e
        return self._parse_and_validate(data, path=None)

    # ── Validation ────────────────────────────────────────────────────────

    def validate_domains(self, domains: list[str]) -> list[str]:
        """
        Validates that all domain names are known DCL packages.
        Returns a list of validation error strings (empty if all valid).
        """
        errors = []
        for domain in domains:
            if domain not in KNOWN_DCL_DOMAINS:
                errors.append(
                    f"Unknown DCL domain: '{domain}'. "
                    f"Valid domains: {sorted(KNOWN_DCL_DOMAINS)}"
                )
        return errors

    # ── Internal ──────────────────────────────────────────────────────────

    def _read_yaml(self, config_path: Path) -> dict:
        """Reads and parses the YAML file."""
        if not _YAML_AVAILABLE:
            raise GameConfigError(
                "PyYAML is not installed. Install it with: pip install pyyaml\n"
                "Or use GameConfigLoader.load_from_dict() for testing."
            )
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f)
        except OSError as e:
            raise GameConfigError(
                f"Could not read game_config.yaml at '{config_path}': {e}"
            ) from e
        except yaml.YAMLError as e:
            raise GameConfigError(
                f"Invalid YAML in game_config.yaml at '{config_path}': {e}"
            ) from e

        if not isinstance(data, dict):
            raise GameConfigError(
                f"game_config.yaml at '{config_path}' must be a YAML mapping, "
                f"not {type(data).__name__}"
            )
        return data

    def _parse_and_validate(
        self,
        data: dict,
        path: Optional[Path],
    ) -> GameConfig:
        """
        Parses raw YAML dict into a GameConfig and validates all fields.
        Collects all errors before raising — not fail-fast.
        """
        errors: list[str] = []
        location = str(path) if path else "provided config"

        # ── Required fields ────────────────────────────────────────────────
        world_id = data.get("world_id", "").strip()
        if not world_id:
            errors.append("'world_id' is required and must not be empty")

        game_name = data.get("game_name", "").strip()
        if not game_name:
            errors.append("'game_name' is required and must not be empty")

        # ── Domains ────────────────────────────────────────────────────────
        raw_domains = data.get("domains", [])
        if not isinstance(raw_domains, list):
            errors.append("'domains' must be a list of DCL domain names")
            raw_domains = []

        domains = [str(d).strip().lower() for d in raw_domains]
        domain_errors = self.validate_domains(domains)
        errors.extend(domain_errors)

        # ── Engine target ──────────────────────────────────────────────────
        engine_target = str(data.get("engine_target", "unity")).lower()
        if engine_target not in KNOWN_ENGINE_TARGETS:
            errors.append(
                f"Unknown engine_target: '{engine_target}'. "
                f"Valid targets: {sorted(KNOWN_ENGINE_TARGETS)}"
            )

        # ── Schema version ─────────────────────────────────────────────────
        schema_version = str(data.get("schema_version", "0.1.0")).strip()
        if not schema_version:
            errors.append("'schema_version' must not be empty")

        # ── Raise all errors together ──────────────────────────────────────
        if errors:
            error_list = "\n".join(f"  - {e}" for e in errors)
            raise GameConfigError(
                f"game_config.yaml validation failed ({location}):\n{error_list}"
            )

        # ── Asset registry config ──────────────────────────────────────────
        asset_reg_data = data.get("asset_registry", {})
        asset_registry_config = (
            AssetRegistryConfig.from_dict(asset_reg_data)
            if isinstance(asset_reg_data, dict)
            else AssetRegistryConfig()
        )

        return GameConfig(
            world_id=world_id,
            game_name=game_name,
            schema_version=schema_version,
            domains=domains,
            engine_target=engine_target,
            asset_registry=asset_registry_config,
            gcl_path=str(data.get("gcl_path", "gcl")),
            metadata={
                k: v for k, v in data.items()
                if k not in {
                    "world_id", "game_name", "schema_version", "domains",
                    "engine_target", "asset_registry", "gcl_path",
                }
            },
        )