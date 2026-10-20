fn main() {
    xace_runtime_core::runtime_cli::main_with_ruleset_policy(Some(|registry| {
        registry.register(Box::new(xace_nec011_echo::EchoSystem))
            .map_err(|e| anyhow::anyhow!("echo registration: {:?}", e))?;
        Ok(())
    }), vec![xace_nec011_echo::CONFIG]);
}
