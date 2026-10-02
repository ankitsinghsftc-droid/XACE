use anyhow::{Context, Result};
#[tokio::main]
async fn main() -> Result<()> {
    let args: Vec<String> = std::env::args().collect();
    anyhow::ensure!(
        args.len() == 4,
        "Usage: xace-session-relay BIND CERT.der KEY.der (XACE_RELAY_OPERATOR_TOKEN required)"
    );
    let listener = tokio::net::TcpListener::bind(&args[1]).await?;
    let credential =
        std::env::var("XACE_RELAY_OPERATOR_TOKEN").context("Missing operator credential")?;
    println!("XACE relay listening on {}", listener.local_addr()?);
    xace_session_relay::server::serve(
        listener,
        std::fs::read(&args[2])?,
        std::fs::read(&args[3])?,
        credential,
    )
    .await
}
