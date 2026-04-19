//! # Rule Definition
//!
//! Defines a game rule in the CGS. A RuleDefinition is a condition→effect
//! declaration that encodes game logic at the schema level without writing
//! code. Rules are evaluated by the RuleSystem each tick.
//!
//! ## What a Rule Is
//! A rule is a declarative if-then statement over component data:
//! IF [condition expression] THEN [effect expression]
//!
//! Examples:
//! - IF entity.health <= 0 THEN entity.state = DestroyRequested
//! - IF entity.lifetime >= max_lifetime THEN emit(LifetimeExpired)
//! - IF player.score >= 100 THEN game.phase = Victory
//!
//! ## What Rules Are Not
//! Rules are not Turing-complete programs. They are declarative
//! constraints evaluated in a fixed order each tick. Complex logic
//! belongs in systems — rules handle simple condition→effect pairs.
//!
//! ## Rule Grammar
//! Condition and effect expressions are strings in the XACE Rule Grammar.
//! The GDE's rule_expression_parser.py validates them against the
//! component vocabulary before allowing CGS commit.
//! The RuleSystem evaluates them at runtime via a simple interpreter.
//!
//! ## Priority and Ordering
//! Rules are sorted by priority descending, then by ID ascending (D11).
//! Higher priority rules are evaluated first each tick.
//! Rules with the same priority are evaluated in alphabetical ID order.
//! This guarantees deterministic evaluation order across all runs.
//!
//! ## Mode Scope
//! Rules are declared inside a GameMode and only apply in that mode.
//! Global rules that apply across all modes are declared in
//! CanonicalGameSchema.global_systems (as a RuleSystem with embedded rules).

use serde::{Deserialize, Serialize};

// ── Rule Condition ────────────────────────────────────────────────────────────

/// A condition expression in the XACE Rule Grammar.
///
/// Evaluated each tick by the RuleSystem. Returns true or false.
/// If true, the associated effect expression is applied via Mutation Gate.
///
/// ## Expression Syntax (subset)
/// Simple comparisons:
///   "entity.COMP_HEALTH_V1.current <= 0"
///   "entity.COMP_GAMESTATE_V1.score >= 1000"
///
/// Logical operators:
///   "entity.COMP_HEALTH_V1.current <= 0 AND entity.COMP_IDENTITY_V1.faction == 'player'"
///
/// Tag checks:
///   "entity.has_tag('enemy') AND entity.COMP_HEALTH_V1.current <= 0"
///
/// The GDE validates the expression against the component vocabulary
/// before allowing the rule to enter the CGS.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct RuleCondition {
    /// The raw condition expression string in XACE Rule Grammar.
    /// Validated by GDE rule_expression_parser before CGS commit.
    pub expression: String,

    /// Human-readable description of what this condition checks.
    /// Used by Design Mentor and builder UI rule browser.
    pub description: String,
}

impl RuleCondition {
    pub fn new(
        expression: impl Into<String>,
        description: impl Into<String>,
    ) -> Self {
        Self {
            expression: expression.into(),
            description: description.into(),
        }
    }

    /// Returns true if the condition expression is non-empty.
    pub fn is_defined(&self) -> bool {
        !self.expression.is_empty()
    }
}

// ── Rule Effect ───────────────────────────────────────────────────────────────

/// An effect expression applied when the condition is true.
///
/// Effects are submitted as mutations via the Mutation Gate — never
/// applied directly. This preserves the mutation pipeline integrity (I2)
/// and ensures all state changes are deterministic and auditable.
///
/// ## Expression Syntax (subset)
/// Component field mutation:
///   "SET entity.COMP_HEALTH_V1.current = 0"
///   "SET game.COMP_GAMESTATE_V1.current_phase = GameOver"
///
/// Entity state change:
///   "SET entity.state = DestroyRequested"
///
/// Event emission:
///   "EMIT EntityDied { source: entity.id }"
///
/// Score increment:
///   "ADD game.COMP_GAMESTATE_V1.score += 10"
///
/// All effects are converted to DSLOperations by the RuleSystem
/// and submitted via the Mutation Gate at phase end.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct RuleEffect {
    /// The raw effect expression string in XACE Rule Grammar.
    /// Validated by GDE rule_expression_validator before CGS commit.
    pub expression: String,

    /// Human-readable description of what this effect does.
    pub description: String,
}

impl RuleEffect {
    pub fn new(
        expression: impl Into<String>,
        description: impl Into<String>,
    ) -> Self {
        Self {
            expression: expression.into(),
            description: description.into(),
        }
    }

    /// Returns true if the effect expression is non-empty.
    pub fn is_defined(&self) -> bool {
        !self.expression.is_empty()
    }
}

// ── Rule Scope ────────────────────────────────────────────────────────────────

/// Which entities this rule applies to each tick.
///
/// The RuleSystem uses this to filter the entity set before
/// evaluating the condition. Narrowing scope reduces CPU cost —
/// a rule scoped to "enemy" entities skips all player entities.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub enum RuleScope {
    /// Apply to all entities that match the condition.
    /// Most general — evaluated against every active entity each tick.
    AllEntities,

    /// Apply only to entities with a specific tag.
    /// Example: Tagged("enemy") — only evaluates enemy entities.
    Tagged(String),

    /// Apply only to entities of a specific actor type ID.
    /// Example: ActorType("actor_player") — only player entities.
    ActorType(String),

    /// Apply only to a specific entity by ID.
    /// Used for singleton rules (game controller, world entity).
    /// u64 is the EntityID of the specific entity.
    SpecificEntity(u64),

    /// Apply to entities that have all listed component type IDs.
    /// The RuleSystem only evaluates entities with all these components.
    HasComponents(Vec<u32>),
}

impl Default for RuleScope {
    fn default() -> Self {
        RuleScope::AllEntities
    }
}

impl std::fmt::Display for RuleScope {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            RuleScope::AllEntities => write!(f, "AllEntities"),
            RuleScope::Tagged(tag) => write!(f, "Tagged({})", tag),
            RuleScope::ActorType(t) => write!(f, "ActorType({})", t),
            RuleScope::SpecificEntity(id) => write!(f, "SpecificEntity({})", id),
            RuleScope::HasComponents(ids) => write!(f, "HasComponents({:?})", ids),
        }
    }
}

// ── Rule Definition ───────────────────────────────────────────────────────────

/// A declarative condition→effect game rule defined in the CGS.
///
/// Rules encode game logic at the schema level — no Rust code required.
/// The GDE validates rule expressions. The RuleSystem evaluates them.
/// All effects are applied via the Mutation Gate (I2, I9).
///
/// ## Evaluation Order (D11)
/// Rules are evaluated in strictly deterministic order each tick:
/// 1. Sort by priority DESCENDING (higher priority first)
/// 2. Within same priority, sort by ID ASCENDING (alphabetical)
/// 3. Within each rule, evaluate condition then apply effect
///
/// ## One-Shot vs Continuous
/// `is_one_shot = false` (default): rule evaluates every tick while active.
/// `is_one_shot = true`: rule fires once when condition first becomes true,
/// then sets is_active=false. Useful for "game over on first death" logic.
///
/// ## Active State
/// `is_active = false` means the RuleSystem skips this rule entirely.
/// Rules can be activated/deactivated via schema mutations from the GDE.
/// All rules start active by default.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct RuleDefinition {
    /// Unique identifier for this rule within its GameMode.
    /// Used by SGC, GDE, and Design Mentor to reference rules.
    /// Examples: "rule_death_on_zero_health", "rule_win_on_score_1000"
    pub id: String,

    /// Human-readable name shown in builder UI.
    pub display_name: String,

    /// The condition that triggers this rule's effect.
    pub condition: RuleCondition,

    /// The effect applied when condition is true.
    pub effect: RuleEffect,

    /// Which entities this rule is evaluated against each tick.
    pub scope: RuleScope,

    /// Evaluation priority. Higher = evaluated first.
    /// Rules with same priority are ordered by ID ascending (D11).
    /// Default is 0. Use positive values for high-priority rules,
    /// negative for low-priority cleanup rules.
    pub priority: i32,

    /// Whether this rule is currently active.
    /// Inactive rules are skipped by the RuleSystem entirely.
    pub is_active: bool,

    /// Whether this rule fires only once then deactivates.
    /// One-shot rules set is_active=false after first successful evaluation.
    pub is_one_shot: bool,

    /// Human-readable description of what this rule does.
    /// Used by Design Mentor, builder UI, and NLTL translation layer.
    pub description: String,
}

impl RuleDefinition {
    /// Creates a new active continuous rule with default priority.
    pub fn new(
        id: impl Into<String>,
        display_name: impl Into<String>,
        condition: RuleCondition,
        effect: RuleEffect,
    ) -> Self {
        Self {
            id: id.into(),
            display_name: display_name.into(),
            condition,
            effect,
            scope: RuleScope::AllEntities,
            priority: 0,
            is_active: true,
            is_one_shot: false,
            description: String::new(),
        }
    }

    /// Creates a one-shot rule that fires once then deactivates.
    pub fn one_shot(
        id: impl Into<String>,
        display_name: impl Into<String>,
        condition: RuleCondition,
        effect: RuleEffect,
    ) -> Self {
        let mut rule = Self::new(id, display_name, condition, effect);
        rule.is_one_shot = true;
        rule
    }

    /// Creates a high-priority rule.
    pub fn with_priority(mut self, priority: i32) -> Self {
        self.priority = priority;
        self
    }

    /// Creates a scoped rule applying only to specific entities.
    pub fn with_scope(mut self, scope: RuleScope) -> Self {
        self.scope = scope;
        self
    }

    /// Creates a rule with a description.
    pub fn with_description(mut self, description: impl Into<String>) -> Self {
        self.description = description.into();
        self
    }

    /// Returns the sort key for deterministic evaluation order (D11).
    /// Sort by (priority DESC, id ASC).
    /// Negate priority so higher priority sorts first in ascending sort.
    pub fn sort_key(&self) -> (i32, &str) {
        (-self.priority, self.id.as_str())
    }

    /// Returns true if this rule is ready to be evaluated.
    /// A rule is ready when it is active and both condition and effect
    /// expressions are defined.
    pub fn is_evaluable(&self) -> bool {
        self.is_active
            && self.condition.is_defined()
            && self.effect.is_defined()
    }

    /// Deactivates this rule.
    /// Called by the RuleSystem after a one-shot rule fires,
    /// or by a GDE mutation disabling a rule.
    pub fn deactivate(&mut self) {
        self.is_active = false;
    }

    /// Validates this rule for internal consistency.
    ///
    /// Checks:
    /// - ID is not empty
    /// - Condition expression is not empty
    /// - Effect expression is not empty
    ///
    /// Full expression grammar validation is performed by
    /// GDE rule_expression_parser and rule_expression_validator (Phase 12).
    pub fn validate(&self) -> Result<(), String> {
        if self.id.is_empty() {
            return Err("RuleDefinition ID must not be empty".into());
        }

        if !self.condition.is_defined() {
            return Err(format!(
                "Rule {} condition expression must not be empty",
                self.id
            ));
        }

        if !self.effect.is_defined() {
            return Err(format!(
                "Rule {} effect expression must not be empty",
                self.id
            ));
        }

        Ok(())
    }
}

// ── Tests ─────────────────────────────────────────────────────────────────────

#[cfg(test)]
mod tests {
    use super::*;

    fn death_rule() -> RuleDefinition {
        RuleDefinition::new(
            "rule_death_on_zero_health",
            "Death on Zero Health",
            RuleCondition::new(
                "entity.COMP_HEALTH_V1.current <= 0",
                "Entity health has reached zero",
            ),
            RuleEffect::new(
                "SET entity.state = DestroyRequested",
                "Mark entity for destruction",
            ),
        )
    }

    fn win_rule() -> RuleDefinition {
        RuleDefinition::new(
            "rule_win_on_score",
            "Win on Score",
            RuleCondition::new(
                "game.COMP_GAMESTATE_V1.score >= 1000",
                "Score has reached 1000",
            ),
            RuleEffect::new(
                "SET game.COMP_GAMESTATE_V1.current_phase = Victory",
                "Trigger victory state",
            ),
        )
        .with_priority(100)
    }

    #[test]
    fn new_rule_is_active_by_default() {
        let rule = death_rule();
        assert!(rule.is_active);
        assert!(!rule.is_one_shot);
    }

    #[test]
    fn new_rule_is_evaluable() {
        let rule = death_rule();
        assert!(rule.is_evaluable());
    }

    #[test]
    fn inactive_rule_not_evaluable() {
        let mut rule = death_rule();
        rule.deactivate();
        assert!(!rule.is_evaluable());
    }

    #[test]
    fn one_shot_rule_created_correctly() {
        let rule = RuleDefinition::one_shot(
            "rule_first_kill",
            "First Kill",
            RuleCondition::new("entity.COMP_HEALTH_V1.current <= 0", ""),
            RuleEffect::new("EMIT FirstKill {}", ""),
        );
        assert!(rule.is_one_shot);
        assert!(rule.is_active);
    }

    #[test]
    fn deactivate_sets_inactive() {
        let mut rule = death_rule();
        rule.deactivate();
        assert!(!rule.is_active);
    }

    #[test]
    fn sort_key_higher_priority_sorts_first() {
        let low = death_rule(); // priority 0
        let high = win_rule();  // priority 100
        assert!(high.sort_key() < low.sort_key());
    }

    #[test]
    fn sort_key_same_priority_sorts_by_id() {
        let rule_a = RuleDefinition::new(
            "rule_aaa", "A",
            RuleCondition::new("x > 0", ""),
            RuleEffect::new("SET x = 0", ""),
        );
        let rule_z = RuleDefinition::new(
            "rule_zzz", "Z",
            RuleCondition::new("x > 0", ""),
            RuleEffect::new("SET x = 0", ""),
        );
        assert!(rule_a.sort_key() < rule_z.sort_key());
    }

    #[test]
    fn validate_passes_for_valid_rule() {
        assert!(death_rule().validate().is_ok());
    }

    #[test]
    fn validate_fails_for_empty_id() {
        let rule = RuleDefinition::new(
            "",
            "No ID",
            RuleCondition::new("x > 0", ""),
            RuleEffect::new("SET x = 0", ""),
        );
        assert!(rule.validate().is_err());
    }

    #[test]
    fn validate_fails_for_empty_condition() {
        let rule = RuleDefinition::new(
            "rule_test",
            "Test",
            RuleCondition::new("", ""),
            RuleEffect::new("SET x = 0", ""),
        );
        assert!(rule.validate().is_err());
    }

    #[test]
    fn validate_fails_for_empty_effect() {
        let rule = RuleDefinition::new(
            "rule_test",
            "Test",
            RuleCondition::new("x > 0", ""),
            RuleEffect::new("", ""),
        );
        assert!(rule.validate().is_err());
    }

    #[test]
    fn with_priority_sets_priority() {
        let rule = death_rule().with_priority(50);
        assert_eq!(rule.priority, 50);
    }

    #[test]
    fn with_scope_sets_scope() {
        let rule = death_rule().with_scope(RuleScope::Tagged("enemy".into()));
        assert_eq!(rule.scope, RuleScope::Tagged("enemy".into()));
    }

    #[test]
    fn rule_scope_display() {
        assert_eq!(RuleScope::AllEntities.to_string(), "AllEntities");
        assert_eq!(RuleScope::Tagged("enemy".into()).to_string(), "Tagged(enemy)");
        assert_eq!(RuleScope::SpecificEntity(42).to_string(), "SpecificEntity(42)");
    }

    #[test]
    fn condition_defined_when_nonempty() {
        let c = RuleCondition::new("x > 0", "");
        assert!(c.is_defined());
    }

    #[test]
    fn condition_not_defined_when_empty() {
        let c = RuleCondition::new("", "");
        assert!(!c.is_defined());
    }

    #[test]
    fn high_priority_rule_has_correct_priority() {
        let rule = win_rule();
        assert_eq!(rule.priority, 100);
    }

    #[test]
    fn with_description_sets_description() {
        let rule = death_rule()
            .with_description("Destroys entity when health hits zero");
        assert!(!rule.description.is_empty());
    }
}
