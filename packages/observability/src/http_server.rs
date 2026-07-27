/*!
# http_server.rs — Minimal HTTP Server

Serves two endpoints with zero external HTTP library dependencies:

| Path       | Content-Type             | Body                          |
|------------|--------------------------|-------------------------------|
| GET /health | application/json        | HealthStatus JSON             |
| GET /metrics| text/plain; version=0.0.4| Prometheus text format        |
| GET /        | text/plain              | "XACE Runtime OK"             |
| Any other   | text/plain              | 404 Not Found                 |

## Design

Uses `std::net::TcpListener` with a simple request line parser.
No HTTP library. No async. One thread per connection (connections are
short-lived — load balancers ping /health and disconnect).

Thread model: One background thread accepts connections in a loop.
Each accepted connection is handled synchronously (read → respond → close).
Long-lived streaming connections are not supported — this is a health probe,
not an API server.

## Configuration

Port is configurable in `runtime_config.yaml`:
```yaml
observability:
  health_port: 9090
```

Default: 9090. Set to 0 to disable.
*/

use std::io::{BufRead, BufReader, Write};
use std::net::{TcpListener, TcpStream};
use std::thread;
use std::time::Duration;

use crate::health_check::HealthWriter;
use crate::metrics::METRICS;

// ── Public API ────────────────────────────────────────────────────────────────

/// Starts the background HTTP server thread.
/// Returns immediately. The thread runs for the process lifetime.
/// Call once during process startup.
pub fn start_background(port: u16, health: HealthWriter) {
    if port == 0 {
        return; // explicitly disabled
    }

    thread::Builder::new()
        .name("xace-http-obs".to_string())
        .spawn(move || {
            run_server(port, health);
        })
        .expect("failed to spawn xace-http-obs thread");
}

// ── Server Loop ───────────────────────────────────────────────────────────────

fn run_server(port: u16, health: HealthWriter) {
    let addr = format!("0.0.0.0:{}", port);
    let listener = match TcpListener::bind(&addr) {
        Ok(l) => l,
        Err(e) => {
            eprintln!("[xace-obs] Failed to bind HTTP server on {}: {}", addr, e);
            return;
        }
    };

    // Prevent the accept loop from blocking shutdown
    let _ = listener.set_nonblocking(false);

    for stream in listener.incoming() {
        match stream {
            Ok(stream) => {
                let health_ref = health.clone();
                // Each connection handled synchronously in same thread.
                // Health probes are quick; no need for per-connection threads.
                handle_connection(stream, &health_ref);
            }
            Err(_) => {
                thread::sleep(Duration::from_millis(10));
            }
        }
    }
}

// ── Connection Handler ────────────────────────────────────────────────────────

fn handle_connection(mut stream: TcpStream, health: &HealthWriter) {
    let _ = stream.set_read_timeout(Some(Duration::from_secs(5)));
    let _ = stream.set_write_timeout(Some(Duration::from_secs(5)));

    let request_line = {
        let mut reader = BufReader::new(&stream);
        let mut line = String::new();
        if reader.read_line(&mut line).is_err() {
            return;
        }
        // Drain remaining headers (must consume to avoid RST)
        for _ in 0..100 {
            let mut header = String::new();
            if reader.read_line(&mut header).is_err() {
                break;
            }
            if header.trim().is_empty() {
                break;
            }
        }
        line
    };

    let (method, path) = parse_request_line(&request_line);
    if method != "GET" {
        respond(&mut stream, 405, "text/plain", "Method Not Allowed");
        return;
    }

    match path {
        "/health" | "/health/" => {
            let status = health.snapshot();
            let http_code = if status.is_healthy() { 200 } else { 503 };
            respond(
                &mut stream,
                http_code,
                "application/json",
                &status.to_json(),
            );
        }
        "/metrics" | "/metrics/" => {
            let text = METRICS.encode_text();
            respond(
                &mut stream,
                200,
                "text/plain; version=0.0.4; charset=utf-8",
                &text,
            );
        }
        "/" => {
            respond(&mut stream, 200, "text/plain", "XACE Runtime OK\n");
        }
        _ => {
            respond(
                &mut stream,
                404,
                "text/plain",
                "Not Found. Available: /health /metrics\n",
            );
        }
    }
}

fn respond(stream: &mut TcpStream, code: u16, content_type: &str, body: &str) {
    let reason = match code {
        200 => "OK",
        404 => "Not Found",
        405 => "Method Not Allowed",
        503 => "Service Unavailable",
        _ => "Unknown",
    };
    let response = format!(
        "HTTP/1.1 {} {}\r\n\
         Content-Type: {}\r\n\
         Content-Length: {}\r\n\
         Connection: close\r\n\
         Cache-Control: no-cache\r\n\
         \r\n\
         {}",
        code,
        reason,
        content_type,
        body.len(),
        body,
    );
    let _ = stream.write_all(response.as_bytes());
}

fn parse_request_line(line: &str) -> (&str, &str) {
    let mut parts = line.split_whitespace();
    let method = parts.next().unwrap_or("GET");
    let path = parts.next().unwrap_or("/");
    // Strip query string
    let path = path.split('?').next().unwrap_or(path);
    (method, path)
}
