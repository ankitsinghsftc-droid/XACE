use std::{
    io::{Read, Write},
    net::{TcpListener, TcpStream},
    time::Duration,
};
use xace_session_relay::{
    client::{GuestBridge, HostBridge},
    now, Config,
};
fn main() -> anyhow::Result<()> {
    let config = Config::from_env()?.unwrap();
    let listener = TcpListener::bind("127.0.0.1:0")?;
    let addr = listener.local_addr()?;
    std::thread::spawn(move || {
        for s in listener.incoming() {
            let mut s = s.unwrap();
            eprintln!("local accepted");
            let mut b = [0; 5];
            s.read_exact(&mut b).unwrap();
            eprintln!("local read");
            s.write_all(&vec![42u8; 200000]).unwrap();
        }
    });
    let host = HostBridge::start(config.clone(), addr, addr)?;
    let route = host.publish(now() + 600)?;
    let guest = GuestBridge::start(config, route)?;
    for i in 0..20 {
        let start = std::time::Instant::now();
        let mut s = TcpStream::connect(guest.package)?;
        s.set_read_timeout(Some(Duration::from_secs(8)))?;
        s.write_all(b"hello")?;
        let mut b = vec![0; 200000];
        let result = s.read_exact(&mut b);
        eprintln!("result {result:?}, host healthy {}", host.healthy());
        result?;
        anyhow::ensure!(b.iter().all(|v| *v == 42), "wrong bytes");
        eprintln!("round {i} {:?}", start.elapsed());
    }
    Ok(())
}
