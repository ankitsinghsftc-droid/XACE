//! # Event Bus Module
//! Deterministic deferred event dispatch.

pub mod event_bus;
pub mod event_dispatcher;
pub mod event_subscription_registry;

#[cfg(test)]
mod tests;

pub use event_bus::EventBus;
pub use event_dispatcher::EventDispatcher;
pub use event_subscription_registry::EventSubscriptionRegistry;
