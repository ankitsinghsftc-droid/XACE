//! Canonical, engine-neutral semantic input action registry.

pub const MOVE: &str = "Move";
pub const JUMP: &str = "Jump";
pub const CROUCH: &str = "Crouch";
pub const DASH: &str = "Dash";
pub const ATTACK: &str = "Attack";
pub const INTERACT: &str = "Interact";
pub const PICKUP: &str = "Pickup";

#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash)]
pub enum SemanticInputKind {
    Axis2D,
    Button,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct SemanticInputDefinition {
    pub name: &'static str,
    pub kind: SemanticInputKind,
    pub summary: &'static str,
    pub replay_relevant: bool,
    pub network_synchronised: bool,
}

const fn input(
    name: &'static str,
    kind: SemanticInputKind,
    summary: &'static str,
) -> SemanticInputDefinition {
    SemanticInputDefinition {
        name,
        kind,
        summary,
        replay_relevant: true,
        network_synchronised: true,
    }
}

pub const BUILTIN_SEMANTIC_INPUTS: &[SemanticInputDefinition] = &[
    input(
        MOVE,
        SemanticInputKind::Axis2D,
        "Two-axis locomotion intent.",
    ),
    input(JUMP, SemanticInputKind::Button, "Jump press/hold intent."),
    input(CROUCH, SemanticInputKind::Button, "Crouch hold intent."),
    input(
        DASH,
        SemanticInputKind::Button,
        "Sprint or dash modifier intent.",
    ),
    input(
        ATTACK,
        SemanticInputKind::Button,
        "Primary combat action intent.",
    ),
    input(
        INTERACT,
        SemanticInputKind::Button,
        "General interaction intent.",
    ),
    input(
        PICKUP,
        SemanticInputKind::Button,
        "Inventory pickup intent.",
    ),
];

pub fn get_semantic_input(name: &str) -> Option<&'static SemanticInputDefinition> {
    BUILTIN_SEMANTIC_INPUTS
        .iter()
        .find(|item| item.name == name)
}

pub fn is_registered_semantic_input(name: &str) -> bool {
    get_semantic_input(name).is_some()
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::collections::BTreeSet;

    #[test]
    fn names_are_unique_and_portable() {
        let mut names = BTreeSet::new();
        for item in BUILTIN_SEMANTIC_INPUTS {
            assert!(names.insert(item.name));
            assert!(item.name.bytes().all(|byte| byte.is_ascii_alphanumeric()));
        }
    }

    #[test]
    fn platformer_actions_are_replayable_and_network_synchronised() {
        for name in [MOVE, JUMP] {
            let item = get_semantic_input(name).unwrap();
            assert!(item.replay_relevant);
            assert!(item.network_synchronised);
        }
    }
}
