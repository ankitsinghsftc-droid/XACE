use serde::{Deserialize, Serialize};

#[derive(Debug, Clone, Copy, PartialEq, Eq, PartialOrd, Ord, Serialize, Deserialize)]
pub enum ConnectionState {
    Connecting,
    Handshaking,
    Syncing,
    Live,
    Desynced,
    Reconnecting,
    Disconnected,
}

impl ConnectionState {
    pub fn can_simulate(self) -> bool {
        matches!(self, Self::Live)
    }

    pub fn is_terminal(self) -> bool {
        matches!(self, Self::Disconnected)
    }

    pub fn can_transition_to(self, next: Self) -> bool {
        use ConnectionState::*;
        if self == next {
            return true;
        }
        matches!(
            (self, next),
            (Connecting, Handshaking)
                | (Connecting, Disconnected)
                | (Handshaking, Syncing)
                | (Handshaking, Disconnected)
                | (Syncing, Live)
                | (Syncing, Desynced)
                | (Syncing, Disconnected)
                | (Live, Desynced)
                | (Live, Reconnecting)
                | (Live, Disconnected)
                | (Desynced, Syncing)
                | (Desynced, Reconnecting)
                | (Desynced, Disconnected)
                | (Reconnecting, Handshaking)
                | (Reconnecting, Syncing)
                | (Reconnecting, Live)
                | (Reconnecting, Disconnected)
        )
    }
}
