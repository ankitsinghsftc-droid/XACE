/*!
# config.rs — Game Configuration

Reads and validates `game_config.yaml` from a game project directory.

## Expected Format

```yaml
# game_config.yaml — XACE game project configuration

name: "My Game"
version: "0.1.0"
schema_version: "0.1.0"

# Which engine adapters to generate build artifacts for
target_engines:
  - unity        # generates Unity C# adapter
  - godot        # generates GDNative adapter

# DCL domain packages enabled for this game
domains:
  - combat
  - character
  - physics

# LLM inference configuration
llm:
  default_provider: anthropic    # anthropic | deepseek | zai | local
  tier_s_enabled: true           # route trivial SETs to deterministic path
  local_models:
    - llama3.1:70b

# Engine adapter network configuration
adapters:
  mode: tcp          # tcp | shm | ffi
  tcp_host: "127.0.0.1"
  tcp_port: 7878

# Build output
build:
  output_dir: "./dist"
  artifact_name: ""              # empty = uses `name` field
```
*/

use std::path::{Path, PathBuf};

use serde::{Deserialize, Serialize};

use crate::error::CliError;

// ── Config Structs ────────────────────────────────────────────────────────────

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct GameConfig {
    pub name: String,
    #[serde(default = "default_version")]
    pub version: String,
    #[serde(default = "default_version")]
    pub schema_version: String,
    #[serde(default)]
    pub target_engines: Vec<TargetEngine>,
    #[serde(default)]
    pub domains: Vec<String>,
    #[serde(default)]
    pub llm: LlmConfig,
    #[serde(default)]
    pub adapters: AdapterConfig,
    #[serde(default)]
    pub build: BuildConfig,

    /// Path to the game project directory (populated at load time, not in YAML)
    #[serde(skip)]
    pub game_dir: PathBuf,
}

impl GameConfig {
    /// Loads and validates game_config.yaml from a game project directory.
    pub fn load(game_dir: impl AsRef<Path>) -> Result<Self, CliError> {
        let dir = game_dir.as_ref().to_path_buf();
        let path = dir.join("game_config.yaml");

        if !path.exists() {
            return Err(CliError::ConfigError {
                path: path.clone(),
                reason: format!(
                    "File not found. Create a game_config.yaml in '{}'. \
                     Run `xace init` (coming soon) or copy from examples/.",
                    dir.display()
                ),
            });
        }

        let raw = std::fs::read_to_string(&path).map_err(|e| CliError::Io {
            path: Some(path.clone()),
            source: e,
        })?;

        let mut config: Self = serde_yaml::from_str(&raw).map_err(|e| CliError::ConfigError {
            path: path.clone(),
            reason: format!("YAML parse error: {}", e),
        })?;

        config.game_dir = dir;
        config.validate(&path)?;
        Ok(config)
    }

    fn validate(&self, path: &Path) -> Result<(), CliError> {
        if self.name.is_empty() {
            return Err(CliError::ConfigError {
                path: path.to_path_buf(),
                reason: "`name` is required and must not be empty.".to_string(),
            });
        }
        if self.target_engines.is_empty() {
            return Err(CliError::ConfigError {
                path: path.to_path_buf(),
                reason: "`target_engines` must list at least one engine \
                         (unity | godot | unreal | standalone)."
                    .to_string(),
            });
        }
        Ok(())
    }

    /// Returns the output directory for build artifacts.
    pub fn output_dir(&self) -> PathBuf {
        let dir = PathBuf::from(&self.build.output_dir);
        if dir.is_relative() {
            self.game_dir.join(dir)
        } else {
            dir
        }
    }

    /// Returns the artifact name (defaults to game name, snake_cased).
    pub fn artifact_name(&self) -> String {
        if !self.build.artifact_name.is_empty() {
            self.build.artifact_name.clone()
        } else {
            self.name
                .to_lowercase()
                .replace(' ', "_")
                .chars()
                .filter(|c| c.is_alphanumeric() || *c == '_' || *c == '-')
                .collect()
        }
    }

    pub fn python_package_dir(&self) -> PathBuf {
        // Assume xace packages are siblings of the CLI binary's package
        // In a real installation this would be a configured path
        PathBuf::from(env!("CARGO_MANIFEST_DIR"))
            .parent()
            .unwrap_or_else(|| Path::new("."))
            .to_path_buf()
    }
}

// ── Sub-configs ───────────────────────────────────────────────────────────────

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "snake_case")]
pub enum TargetEngine {
    Unity,
    Godot,
    Unreal,
    Standalone,
}

impl std::fmt::Display for TargetEngine {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            Self::Unity => write!(f, "unity"),
            Self::Godot => write!(f, "godot"),
            Self::Unreal => write!(f, "unreal"),
            Self::Standalone => write!(f, "standalone"),
        }
    }
}

impl std::str::FromStr for TargetEngine {
    type Err = String;
    fn from_str(s: &str) -> Result<Self, Self::Err> {
        match s.to_lowercase().as_str() {
            "unity" => Ok(Self::Unity),
            "godot" => Ok(Self::Godot),
            "unreal" => Ok(Self::Unreal),
            "standalone" => Ok(Self::Standalone),
            other => Err(format!(
                "unknown engine '{}'. Valid: unity, godot, unreal, standalone",
                other
            )),
        }
    }
}

#[derive(Debug, Clone, Serialize, Deserialize, Default)]
pub struct LlmConfig {
    #[serde(default = "default_provider")]
    pub default_provider: String,
    #[serde(default = "bool_true")]
    pub tier_s_enabled: bool,
    #[serde(default)]
    pub local_models: Vec<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct AdapterConfig {
    #[serde(default = "default_adapter_mode")]
    pub mode: String,
    #[serde(default = "default_tcp_host")]
    pub tcp_host: String,
    #[serde(default = "default_tcp_port")]
    pub tcp_port: u16,
}

impl Default for AdapterConfig {
    fn default() -> Self {
        Self {
            mode: "tcp".to_string(),
            tcp_host: "127.0.0.1".to_string(),
            tcp_port: 7878,
        }
    }
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct BuildConfig {
    #[serde(default = "default_output_dir")]
    pub output_dir: String,
    #[serde(default)]
    pub artifact_name: String,
}

impl Default for BuildConfig {
    fn default() -> Self {
        Self {
            output_dir: "./dist".to_string(),
            artifact_name: String::new(),
        }
    }
}

// ── Defaults ──────────────────────────────────────────────────────────────────

fn default_version() -> String {
    "0.1.0".to_string()
}
fn default_provider() -> String {
    "anthropic".to_string()
}
fn default_adapter_mode() -> String {
    "tcp".to_string()
}
fn default_tcp_host() -> String {
    "127.0.0.1".to_string()
}
fn default_tcp_port() -> u16 {
    7878
}
fn default_output_dir() -> String {
    "./dist".to_string()
}
fn bool_true() -> bool {
    true
}
