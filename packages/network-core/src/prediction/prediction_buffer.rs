use std::collections::BTreeMap;

use crate::{NetworkError, Tick};

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct PredictionBufferStats {
    pub len: usize,
    pub capacity: usize,
    pub oldest_tick: Option<Tick>,
    pub latest_tick: Option<Tick>,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum PredictionInsertResult<T> {
    Inserted,
    Replaced { previous: T },
    Pruned { pruned_ticks: Vec<Tick> },
}

#[derive(Debug, Clone)]
pub struct PredictionBuffer<T> {
    capacity: usize,
    entries: BTreeMap<Tick, T>,
}

impl<T: Clone> PredictionBuffer<T> {
    pub fn new(capacity: usize) -> Self {
        Self {
            capacity: capacity.max(1),
            entries: BTreeMap::new(),
        }
    }

    pub fn insert(&mut self, tick: Tick, value: T) {
        let _ = self.insert_result(tick, value);
    }

    pub fn insert_result(
        &mut self,
        tick: Tick,
        value: T,
    ) -> Result<PredictionInsertResult<T>, NetworkError> {
        let previous = self.entries.insert(tick, value);
        let mut pruned_ticks = Vec::new();
        while self.entries.len() > self.capacity {
            let Some(oldest) = self.entries.keys().next().copied() else {
                break;
            };
            if oldest == tick && self.entries.len() == 1 {
                break;
            }
            self.entries.remove(&oldest);
            pruned_ticks.push(oldest);
        }

        if !pruned_ticks.is_empty() {
            return Ok(PredictionInsertResult::Pruned { pruned_ticks });
        }
        if let Some(previous) = previous {
            return Ok(PredictionInsertResult::Replaced { previous });
        }
        Ok(PredictionInsertResult::Inserted)
    }

    pub fn get(&self, tick: Tick) -> Option<&T> {
        self.entries.get(&tick)
    }

    pub fn require(&self, tick: Tick) -> Result<&T, NetworkError> {
        self.entries.get(&tick).ok_or_else(|| {
            NetworkError::InvalidOperation(format!("prediction for tick {tick} not found"))
        })
    }

    pub fn latest(&self) -> Option<(Tick, &T)> {
        self.entries
            .iter()
            .next_back()
            .map(|(&tick, value)| (tick, value))
    }

    pub fn oldest(&self) -> Option<(Tick, &T)> {
        self.entries
            .iter()
            .next()
            .map(|(&tick, value)| (tick, value))
    }

    pub fn floor(&self, tick: Tick) -> Option<(Tick, &T)> {
        self.entries
            .range(..=tick)
            .next_back()
            .map(|(&tick, value)| (tick, value))
    }

    pub fn ceil(&self, tick: Tick) -> Option<(Tick, &T)> {
        self.entries
            .range(tick..)
            .next()
            .map(|(&tick, value)| (tick, value))
    }

    pub fn range(&self, from_tick: Tick, to_tick: Tick) -> Vec<(Tick, T)> {
        if from_tick > to_tick {
            return Vec::new();
        }
        self.entries
            .range(from_tick..=to_tick)
            .map(|(&tick, value)| (tick, value.clone()))
            .collect()
    }

    pub fn prune_before(&mut self, tick: Tick) -> Vec<Tick> {
        let to_remove = self
            .entries
            .range(..tick)
            .map(|(&entry_tick, _)| entry_tick)
            .collect::<Vec<_>>();
        for entry_tick in &to_remove {
            self.entries.remove(entry_tick);
        }
        to_remove
    }

    pub fn drain_after(&mut self, tick: Tick) -> Vec<(Tick, T)> {
        let to_remove = self
            .entries
            .range((tick.saturating_add(1))..)
            .map(|(&entry_tick, _)| entry_tick)
            .collect::<Vec<_>>();
        let mut drained = Vec::new();
        for entry_tick in to_remove {
            if let Some(value) = self.entries.remove(&entry_tick) {
                drained.push((entry_tick, value));
            }
        }
        drained
    }

    pub fn clear(&mut self) {
        self.entries.clear();
    }

    pub fn ticks(&self) -> Vec<Tick> {
        self.entries.keys().copied().collect()
    }

    pub fn values(&self) -> impl Iterator<Item = &T> {
        self.entries.values()
    }

    pub fn len(&self) -> usize {
        self.entries.len()
    }

    pub fn is_empty(&self) -> bool {
        self.entries.is_empty()
    }

    pub fn capacity(&self) -> usize {
        self.capacity
    }

    pub fn stats(&self) -> PredictionBufferStats {
        PredictionBufferStats {
            len: self.entries.len(),
            capacity: self.capacity,
            oldest_tick: self.entries.keys().next().copied(),
            latest_tick: self.entries.keys().next_back().copied(),
        }
    }
}
