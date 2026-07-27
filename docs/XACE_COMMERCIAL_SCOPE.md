# XACE Commercial Scope Record

Record ID: XACE-COMMERCIAL-SCOPE-2026-06-14
Scope status: Frozen for commercial-readiness execution
Signed by: Codex acting as principal architect and release manager for this execution batch
Sign-off date: 2026-06-14

This record freezes the commercial launch model that future readiness work must
target. It does not claim XACE is commercially ready today. Any public claim,
UI wording, CI gate, certification command, release checklist, billing work, or
support workflow that conflicts with this record must be changed or explicitly
approved through a later signed scope revision.

## Product Identity

XACE is deterministic gameplay infrastructure and an AI-assisted
gameplay-authoring platform. AI and humans may propose gameplay systems and
changes; XACE must compile, simulate, validate, replay, roll back, certify, and
mirror supported gameplay into game engines before a capability is advertised.

XACE must not be positioned as a full game engine, a finished-game exporter, an
automatic existing-game converter, or a literal "any game from prompt" product.

## Launch Model

The commercial target is local-first. Builder, runtime, CGS files, SGC plans,
proof artifacts, adapters, save data, logs, and project state run and persist on
the user's machine by default.

Hosted XACE services are not required for the first commercial release. If any
hosted service is added later, it must be opt-in, documented, covered by privacy
and incident-response gates, and disabled without breaking local project access.

## Prompt And Provider Model

Prompting is BYOK or local-model first. Local Ollama-style providers may run
without hosted keys. Hosted providers require user-supplied keys, exact model
selection, health proof for the selected provider/model/base URL/key fingerprint,
redacted telemetry, cost visibility, and explicit user action before use.

Launch-candidate provider families are local Ollama-compatible providers,
OpenAI-compatible providers, Anthropic, and Google Gemini. Exact model IDs are
not frozen in this document; they must be proven by benchmark and health-report
artifacts before automatic routing may choose them.

## Supported Engine Targets

The commercial target includes adapter packages for Godot, Unity, and Unreal.
Commercial claims for an engine are allowed only after installed-editor
validation passes for that engine/version/OS combination and a compatibility
matrix records the result.

Engines remain responsible for rendering, native content pipelines, native
physics scenes, platform packaging, store submission, and engine-native build
settings. XACE owns the portable gameplay core, deterministic runtime, schema
contracts, proof artifacts, adapter protocol, and supported semantic bindings.

## Multiplayer Scope

The planning target for launch multiplayer is host-authoritative gameplay driven
by an authoritative XACE runtime. Dedicated server, peer-to-peer, MMO-scale,
rollback fighting-game, and arbitrary topology claims are out of scope until
the multiplayer topology task chooses and proves them.

No commercial multiplayer claim is allowed until topology, lobby, version
checks, desync detection, rollback, resync, adapter integration, malicious-input
limits, and network chaos proof all pass.

## Paid Tiers And Entitlements

The source repository remains under its current workspace license unless a later
legal decision changes it. Commercial value should be packaged around signed
builds, adapters, support, update channels, verified compatibility, and optional
commercial services rather than hiding local project access behind hosted
runtime dependencies.

Initial paid-tier planning is:

- Community: local source or self-serve builds, no paid support SLA.
- Pro: signed desktop builds, signed adapter packages, stable updates, and
  self-serve support diagnostics.
- Team or Studio: team onboarding, compatibility guidance, priority support,
  and commercial support workflow after security and support gates pass.

Billing, entitlement, activation, trials, and offline grace are not implemented
by this task. They must be built only if later commercial-operations tasks keep
this tier model or replace it with a signed revision.

## License Terms

The current repository workspace license is MIT. Generated game projects and
user-owned project assets remain owned by the user unless a later commercial
license says otherwise. Third-party licenses, adapter package licenses,
generated-code terms, provider terms, and bundled asset terms must be audited
before public commercial release.

## Update Channels

The required release channels are:

- Dev: local development builds, not user-facing promises.
- Beta: signed pre-release builds with explicit known-risk wording.
- Stable: signed release builds allowed only after commercial-launch gates pass.

Any updater must support rollback, version compatibility checks, release notes,
adapter package compatibility, and blocked updates when project migration is not
safe.

## Support Workflow

Support must be based on reproducible diagnostics rather than informal logs.
The commercial support workflow requires redacted support bundles, issue
templates, severity levels, response expectations, incident escalation,
customer communication, and documented recovery steps.

No paid support SLA may be advertised until support diagnostics, privacy,
security, and incident-response gates pass.

## Privacy And Telemetry

Analytics, crash reporting, provider telemetry export, and support bundle upload
are opt-in only. Local logs and proof artifacts may be generated for the user,
but they must be inspectable and redacted before sharing.

XACE must not send project content, prompts, provider keys, proof artifacts, or
crash data to any XACE-hosted service by default.

## Release Gates

Private alpha, public beta, and commercial launch remain blocked until their
signed gate checklists pass. Every public product claim must map to a
reproducible proof artifact. A task is not complete merely because code exists;
completion requires tests, proof artifacts, reproducible commands, documentation,
and sign-off.

## Scope Change Rule

Changing local-first status, supported engine targets, provider families,
commercial tier assumptions, licensing assumptions, update channels, telemetry
defaults, or support workflow requires a new signed scope record with a new
record ID.
