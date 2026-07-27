# XACE Unity Adapter

Install with XACE Builder's Project > Adapter tab. The files should land in:

`Assets/XACE`

After Unity recompiles:

1. Open `Tools > XACE > Create Runtime Object`.
2. Select the created `XACE Runtime` GameObject.
3. Start `xace_runtime` for the active XACE project.
4. Press Play in Unity.

The generated runtime object contains:

- `XaceTransport`
- `XaceInputCollector`
- `XaceDeltaApplicator`
- `XaceConsoleWidget`

Unity editor compile validation is still required before this adapter can be marked launch-ready.
