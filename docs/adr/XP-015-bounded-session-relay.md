# XP-015 — Bounded TLS session relay

Decision: implement a separate transport service and native Player transport library. The creator's existing runtime remains the only authority. World Contract, CGS, SGC, gameplay systems, mutation gates, session identity and input/baseline protocols are unchanged. Package and game are transport services, not gameplay categories.

`packages/session-relay/src/lib.rs` defines strict versioned envelopes (`xace.relay.request.v1`, `xace.relay.response.v1`), `Request`, `Response`, `Service`, `Route`, `Config` and certificate-verified `Client`. `server.rs` owns bounded sessions, grants, leases and tunnel pairing. `client.rs` owns outbound host and guest bridges; `main.rs` is the operator's relay executable. The launcher remains the trusted local process owner.

Trust and authentication:

- TLS 1.3 verifies the server hostname and its chain against an explicitly provisioned CA. There is no insecure verifier or certificate supplied by an invite. The trusted local `xace.relay.config.v1` file selects the endpoint and CA. At most eight DNS addresses are raced within the connection deadline so a broken IPv6 route cannot serially delay a reachable IPv4 endpoint.
- Register requires an operator-issued hosting credential. Registration returns a fresh opaque host capability and session UUID. Only that host capability can publish invites, poll its incoming channels, attach a channel or end the session. Credentials are never logged.
- `xace.invite.v2` adds a typed relay route to the existing descriptor-pinned invitation. Exchange consumes the relay invite once and returns a session lease. The original XP-014 package token still enforces verified acquisition followed by one-time gameplay ticket redemption. Failed relay publication does not reserve a gameplay slot.
- Leases authorize only package/game connections for their session. Pairing uses another one-use channel capability plus host authorization. Clients cannot supply an arbitrary target address or reach runtime control, Builder, a shell or an executable-download endpoint. Host bridges map the two services to fixed loopback endpoints.
- Encryption terminates at the trusted relay. This is not end-to-end encryption against the relay operator. The operator must protect its server key and provisioning credentials. No social accounts, matchmaking or AI-provider credentials are introduced.

The certificate-verification configuration follows the [rustls client configuration API](https://docs.rs/rustls/0.23.40/rustls/client/struct.ClientConfig.html); asynchronous TLS uses [tokio-rustls](https://docs.rs/tokio-rustls/0.26.4/tokio_rustls/). Cargo.lock pins the implementation tested here.

Bounds for this initial deployment profile:

- 16 sessions per service; 128 simultaneously handled TLS connections including pending handshakes; 3 invite/lease slots per session plus the local creator.
- 600-second invitation lifetime; 7200-second session/lease lifetime. A missing host heartbeat expires the relay session after ten seconds, with a one-second cleanup sweep.
- Two concurrent tunnels per lease; eight pending pairings per session; four-second pairing wait; 8 KiB typed control frames; five-second TLS/connect/control/read/write/flush deadlines.
- Two fixed 16 KiB forwarding buffers per paired tunnel. No unbounded payload queue. Aggregate payload limits are 8 MiB per wall-clock second and 2 GiB per session, summed across directions and peers. Exceeding either closes the affected tunnel; it does not allocate a backlog. TLS/control overhead is outside these payload counters and remains constrained by the connection/frame bounds. These bounds are not a claim of general Internet DDoS resistance.
- Fifteen seconds without bytes in either forwarding direction closes an idle tunnel. XP-014's file size, inventory, hash, acquisition-time and leased-cache bounds still apply.

Lifecycle:

Host and guest create outbound TLS connections only; creators expose no listener to the Internet. Guest listeners bind loopback for the installed Player. Dropping either bridge cancels its tasks and sockets; end removes relay state, and a host crash is bounded by heartbeat expiry. Leases expire with the session; an abandoned redeemed invitation does not become reusable. Lost exchange/redemption responses fail closed and may require a new invite/session.

Brief link interruption can reconnect using the same relay lease and XP-013's rotating gameplay credential. A new verified baseline is required before input membership returns. Host control polling retries bounded interruptions and exposes connected/reconnecting/lost status. Relay restart loses in-memory leases: this profile visibly interrupts remote play and requires ending/restarting the hosted session. It does not recover by creating a second authority or silently downgrading to private plaintext transport. Local host play can continue while remote peers are fenced.

The relay has no persistence, replication, automatic certificate renewal or availability SLA. Host polling and complete baseline projection remain bounded initial-profile choices; high-latency catch-up, restrictive-network reachability and public capacity must be measured during the pending two-network acceptance. These limits do not redefine generic world semantics or privilege the reference mechanic.
