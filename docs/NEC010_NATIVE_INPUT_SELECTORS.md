# NEC-010 authored input selector contract

`native_input_bindings` is an optional CGS authoring contract with schema
`xace.native_input_bindings.v1` and an explicit `bindings` list. Each binding has
`binding_id`, `mode_id`, `world_object_id`, `input_profile_id`, `action_id`, and
`native_actions` (engine name to saved native action name).

The World object must exist and its actor must have COMP_INPUT_V1 with HUMAN
control and the same input_profile_id. The canonical profile must declare the
selected action under xace.input_profile.v1. One engine selector per World object
is admitted; ambiguous declarations fail closed. This matches the current
single input.action metadata field, not a complete multi-action controller.

Reconciliation requires explicit enrollment on both sides. The atomic
set_native_input operation checks the prior binding digest and changes only an
already declared engine action name. It cannot change the controller, canonical
profile/action, World identity, or other engines. Native writers independently
require that the selected action exists in the saved native input configuration.
Both configuration drift and approval drift are checked before publication.

An authored selector is not executable input routing. Native input event
semantics, packet fields, axis/button fidelity, actual gameplay input and cooked
readiness remain separate NEC-011/012 gates. No gameplay or runtime activation is
claimed by these persistence proofs. Empty Godot fixture action event arrays are
intentional authoring fixtures, not playable input certification. Unreal selector
support is implemented but native verification is still pending at this checkpoint. No automatic enrollment or unapproved apply is
introduced.

Proofs use the production review/approve/apply host, paired-save verification,
then cold no-op checks in both directions. See the NEC-010 evidence receipts.
