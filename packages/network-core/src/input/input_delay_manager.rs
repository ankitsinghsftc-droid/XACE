use std::collections::{BTreeMap, VecDeque};

use crate::PeerId;

const DEFAULT_SAMPLE_WINDOW: usize = 64;

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct LatencySample {
    pub rtt_ms: u32,
    pub jitter_ms: u32,
    pub packet_loss_ppm: u32,
}

impl LatencySample {
    pub fn new(rtt_ms: u32) -> Self {
        Self {
            rtt_ms,
            jitter_ms: 0,
            packet_loss_ppm: 0,
        }
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct DelayRecommendation {
    pub delay_ticks: u32,
    pub worst_peer: Option<PeerId>,
    pub max_rtt_ms: u32,
    pub max_jitter_ms: u32,
    pub max_packet_loss_ppm: u32,
}

#[derive(Debug, Clone)]
pub struct InputDelayConfig {
    pub tick_rate_hz: u32,
    pub min_delay_ticks: u32,
    pub max_delay_ticks: u32,
    pub safety_ticks: u32,
    pub sample_window: usize,
    pub jitter_weight_numerator: u32,
    pub packet_loss_extra_tick_threshold_ppm: u32,
}

impl Default for InputDelayConfig {
    fn default() -> Self {
        Self {
            tick_rate_hz: 60,
            min_delay_ticks: 0,
            max_delay_ticks: 12,
            safety_ticks: 1,
            sample_window: DEFAULT_SAMPLE_WINDOW,
            jitter_weight_numerator: 1,
            packet_loss_extra_tick_threshold_ppm: 10_000,
        }
    }
}

#[derive(Debug, Clone, Default)]
struct PeerLatencyWindow {
    samples: VecDeque<LatencySample>,
}

impl PeerLatencyWindow {
    fn push(&mut self, sample: LatencySample, max_len: usize) {
        self.samples.push_back(sample);
        while self.samples.len() > max_len {
            self.samples.pop_front();
        }
    }

    fn percentile_rtt(&self, percentile_value: u32) -> u32 {
        percentile_from_sorted(
            sorted_values(self.samples.iter().map(|s| s.rtt_ms)),
            percentile_value,
        )
    }

    fn max_jitter(&self) -> u32 {
        self.samples
            .iter()
            .map(|sample| sample.jitter_ms)
            .max()
            .unwrap_or(0)
    }

    fn max_packet_loss(&self) -> u32 {
        self.samples
            .iter()
            .map(|sample| sample.packet_loss_ppm)
            .max()
            .unwrap_or(0)
    }
}

#[derive(Debug, Clone)]
pub struct InputDelayManager {
    config: InputDelayConfig,
    tick_ms: u32,
    samples: BTreeMap<PeerId, PeerLatencyWindow>,
    last_recommendation: DelayRecommendation,
}

impl InputDelayManager {
    pub fn new(tick_rate_hz: u32, safety_ticks: u32) -> Self {
        Self::with_config(InputDelayConfig {
            tick_rate_hz,
            safety_ticks,
            ..InputDelayConfig::default()
        })
    }

    pub fn with_config(config: InputDelayConfig) -> Self {
        let tick_ms = (1000_u32.div_ceil(config.tick_rate_hz.max(1))).max(1);
        let min_delay = config.min_delay_ticks.min(config.max_delay_ticks);
        Self {
            config,
            tick_ms,
            samples: BTreeMap::new(),
            last_recommendation: DelayRecommendation {
                delay_ticks: min_delay,
                worst_peer: None,
                max_rtt_ms: 0,
                max_jitter_ms: 0,
                max_packet_loss_ppm: 0,
            },
        }
    }

    pub fn record_latency(&mut self, peer_id: PeerId, latency_ms: u32) {
        self.record_sample(peer_id, LatencySample::new(latency_ms));
    }

    pub fn record_sample(&mut self, peer_id: PeerId, sample: LatencySample) {
        self.samples
            .entry(peer_id)
            .or_default()
            .push(sample, self.config.sample_window.max(1));
        self.last_recommendation = self.compute_recommendation();
    }

    pub fn remove_peer(&mut self, peer_id: PeerId) {
        self.samples.remove(&peer_id);
        self.last_recommendation = self.compute_recommendation();
    }

    pub fn recommended_delay_ticks(&self) -> u32 {
        self.last_recommendation.delay_ticks
    }

    pub fn recommendation(&self) -> DelayRecommendation {
        self.last_recommendation
    }

    pub fn peer_count(&self) -> usize {
        self.samples.len()
    }

    pub fn tick_ms(&self) -> u32 {
        self.tick_ms
    }

    fn compute_recommendation(&self) -> DelayRecommendation {
        let mut worst_peer = None;
        let mut max_budget_ms = 0u32;
        let mut max_rtt_ms = 0u32;
        let mut max_jitter_ms = 0u32;
        let mut max_packet_loss_ppm = 0u32;

        for (&peer_id, window) in &self.samples {
            let rtt = window.percentile_rtt(95);
            let jitter = window.max_jitter();
            let loss = window.max_packet_loss();
            let one_way = rtt.div_ceil(2);
            let jitter_budget = jitter.saturating_mul(self.config.jitter_weight_numerator);
            let loss_budget = if loss >= self.config.packet_loss_extra_tick_threshold_ppm {
                self.tick_ms
            } else {
                0
            };
            let budget = one_way
                .saturating_add(jitter_budget)
                .saturating_add(loss_budget);

            if budget > max_budget_ms {
                max_budget_ms = budget;
                worst_peer = Some(peer_id);
            }
            max_rtt_ms = max_rtt_ms.max(rtt);
            max_jitter_ms = max_jitter_ms.max(jitter);
            max_packet_loss_ppm = max_packet_loss_ppm.max(loss);
        }

        let mut delay_ticks = max_budget_ms
            .div_ceil(self.tick_ms)
            .saturating_add(self.config.safety_ticks);
        delay_ticks = delay_ticks.clamp(
            self.config.min_delay_ticks.min(self.config.max_delay_ticks),
            self.config.max_delay_ticks,
        );

        DelayRecommendation {
            delay_ticks,
            worst_peer,
            max_rtt_ms,
            max_jitter_ms,
            max_packet_loss_ppm,
        }
    }
}

fn sorted_values(values: impl Iterator<Item = u32>) -> Vec<u32> {
    let mut values: Vec<_> = values.collect();
    values.sort_unstable();
    values
}

fn percentile_from_sorted(values: Vec<u32>, percentile_value: u32) -> u32 {
    if values.is_empty() {
        return 0;
    }
    let percentile_value = percentile_value.min(100);
    let index = ((values.len() as u32 - 1) * percentile_value).div_ceil(100) as usize;
    values[index.min(values.len() - 1)]
}
