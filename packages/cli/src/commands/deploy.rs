// ============================================================================
// packages/cli/src/commands/deploy.rs
// ============================================================================
 
#[derive(clap::Args, Clone)]
pub struct DeployArgs {
    /// Distribution target
    #[arg(long, value_parser = ["standalone", "steam", "itch", "custom"])]
    pub target: String,
 
    /// Game project directory
    #[arg(long, default_value = ".")]
    pub game: PathBuf,
 
    /// Path to built artifact (from `xace build`)
    #[arg(long)]
    pub artifact: Option<PathBuf>,
}
 
pub fn run(args: DeployArgs, ctx: &Context) -> Result<i32, CliError> {
    let _ = (args, ctx);   // suppress unused warnings on stub
    Err(CliError::not_implemented(
        "xace deploy",
        "Phase 17+ — deployment targets (standalone, Steam, itch.io) \
         require the Phase 17 standalone compiler and distribution pipeline. \
         Configure your deploy target in deploy_config.yaml when the feature ships.",
    ))
}
 
// Bring Instant into scope for test.rs functions
use std::time::Instant;
 
// Re-import needed types for build.rs functions
use crate::config::GameConfig;
 