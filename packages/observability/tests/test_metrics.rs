/ ============================================================================
// packages/observability/tests/test_metrics.rs
// ============================================================================
 
#[cfg(test)]
mod test_metrics {
    use xace_observability::metrics::{Counter, Gauge, Histogram, METRICS};
 
    // ── Counter ───────────────────────────────────────────────────────────────
 
    #[test]
    fn counter_starts_at_zero() {
        let c = Counter::new("test_counter", "help");
        assert_eq!(c.get(), 0);
    }
 
    #[test]
    fn counter_add_accumulates() {
        let c = Counter::new("c1", "");
        c.add(5);
        c.add(3);
        assert_eq!(c.get(), 8);
    }
 
    #[test]
    fn counter_inc_adds_one() {
        let c = Counter::new("c2", "");
        c.inc();
        c.inc();
        assert_eq!(c.get(), 2);
    }
 
    #[test]
    fn counter_encode_contains_name() {
        let c = Counter::new("my_counter", "My help text");
        c.add(42);
        let encoded = c.encode();
        assert!(encoded.contains("my_counter"));
        assert!(encoded.contains("My help text"));
        assert!(encoded.contains("42"));
    }
 
    #[test]
    fn counter_thread_safe_concurrent_increments() {
        use std::sync::Arc;
        let c = Arc::new(Counter::new("concurrent", ""));
        let handles: Vec<_> = (0..10).map(|_| {
            let c2 = c.clone();
            std::thread::spawn(move || { for _ in 0..100 { c2.add(1); } })
        }).collect();
        for h in handles { h.join().unwrap(); }
        assert_eq!(c.get(), 1000);
    }
 
    // ── Gauge ─────────────────────────────────────────────────────────────────
 
    #[test]
    fn gauge_set_and_get() {
        let g = Gauge::new("g1", "");
        g.set(3.14);
        assert!((g.get() - 3.14).abs() < 1e-10);
    }
 
    #[test]
    fn gauge_add_accumulates() {
        let g = Gauge::new("g2", "");
        g.set(10.0);
        g.add(5.0);
        assert!((g.get() - 15.0).abs() < 1e-10);
    }
 
    #[test]
    fn gauge_can_decrease() {
        let g = Gauge::new("g3", "");
        g.set(10.0);
        g.add(-3.0);
        assert!((g.get() - 7.0).abs() < 1e-10);
    }
 
    #[test]
    fn gauge_encode_contains_value() {
        let g = Gauge::new("my_gauge", "gauge help");
        g.set(99.5);
        let encoded = g.encode();
        assert!(encoded.contains("my_gauge"));
        assert!(encoded.contains("99.5"));
    }
 
    // ── Histogram ─────────────────────────────────────────────────────────────
 
    #[test]
    fn histogram_records_samples() {
        let h = Histogram::new("h1", "");
        for i in 1..=100 {
            h.record(i as f64);
        }
        assert_eq!(h.count(), 100);
    }
 
    #[test]
    fn histogram_p50_is_median() {
        let h = Histogram::new("h2", "");
        for i in 1..=100 {
            h.record(i as f64);
        }
        let p50 = h.percentile(50.0).unwrap();
        // Median of 1..=100 is around 50
        assert!(p50 >= 49.0 && p50 <= 51.0, "p50={}", p50);
    }
 
    #[test]
    fn histogram_p99_is_high() {
        let h = Histogram::new("h3", "");
        for i in 1..=100 {
            h.record(i as f64);
        }
        let p99 = h.percentile(99.0).unwrap();
        assert!(p99 >= 98.0);
    }
 
    #[test]
    fn histogram_mean_is_correct() {
        let h = Histogram::new("h4", "");
        h.record(1.0);
        h.record(3.0);
        let mean = h.mean().unwrap();
        assert!((mean - 2.0).abs() < 1e-10);
    }
 
    #[test]
    fn histogram_encode_contains_p50_p95_p99() {
        let h = Histogram::new("tick_ms", "tick help");
        for i in 0..100 { h.record(i as f64); }
        let encoded = h.encode();
        assert!(encoded.contains("tick_ms_p50"));
        assert!(encoded.contains("tick_ms_p95"));
        assert!(encoded.contains("tick_ms_p99"));
        assert!(encoded.contains("tick_ms_count"));
    }
 
    #[test]
    fn histogram_none_when_empty() {
        let h = Histogram::new("empty", "");
        assert!(h.percentile(50.0).is_none());
        assert!(h.mean().is_none());
    }
 
    // ── Global METRICS ────────────────────────────────────────────────────────
 
    #[test]
    fn global_metrics_counter_accessible() {
        METRICS.counter("entity_count").add(10);
        assert!(METRICS.counter("entity_count").get() >= 10);
    }
 
    #[test]
    fn global_metrics_encode_text_non_empty() {
        METRICS.counter("test_metric_001").add(1);
        let text = METRICS.encode_text();
        assert!(!text.is_empty());
    }
 
    #[test]
    fn global_metrics_lazy_create_new_counter() {
        let name = "dynamic_counter_xyz";
        METRICS.counter(name).add(5);
        assert_eq!(METRICS.counter(name).get(), 5);
    }
}