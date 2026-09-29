//! Example host composition: removable gameplay stays outside runtime core.
fn main() {
    xace_runtime_core::runtime_cli::main_with_host_systems(Some(|registry| {
        registry.register(Box::new(xace_reference_mechanic::ReferenceSystem))
            .map_err(|err| anyhow::anyhow!("host registration: {:?}", err))?;
        Ok(())
    }));
}
