# XACE Unreal Adapter

Install with XACE Builder's Project > Adapter tab. The files should land in:

`Plugins/XACE`

After Unreal detects the plugin:

1. Enable the `XACE Adapter` plugin if Unreal asks.
2. Rebuild or reopen the Unreal project.
3. Create an Actor and add these components:
   - `XaceTransportComponent`
   - `XaceInputCollectorComponent`
   - `XaceDeltaApplicatorComponent`
4. Start `xace_runtime` for the active XACE project.
5. Press Play in Unreal.

Validation status: the plugin source has passed Unreal 5.7 BuildPlugin no-host runtime builds for Win64 Development and Shipping. A live editor/play smoke is still the next validation step.
