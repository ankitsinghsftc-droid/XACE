mod session;
fn main() {
    let args:Vec<String>=std::env::args().collect();
    if args.get(1).map(String::as_str)==Some("--echo-session") {
        if args.len()!=4 {eprintln!("usage: --echo-session CGS EXECUTION_PLAN");std::process::exit(2);}
        if let Err(error)=session::run(std::path::Path::new(&args[2]),std::path::Path::new(&args[3]),std::io::stdin().lock(),std::io::stdout().lock()){eprintln!("{error}");std::process::exit(1);}
        return;
    }
    xace_runtime_core::runtime_cli::main_with_ruleset_policy(Some(|registry| {
        registry.register(Box::new(xace_nec011_echo::EchoSystem))
            .map_err(|e| anyhow::anyhow!("echo registration: {:?}", e))?;
        Ok(())
    }), vec![xace_nec011_echo::CONFIG]);
}
