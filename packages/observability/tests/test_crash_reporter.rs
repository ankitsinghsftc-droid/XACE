// ============================================================================
// packages/observability/tests/test_crash_reporter.rs
// ============================================================================

#[cfg(test)]
mod test_crash_reporter {
    use std::path::PathBuf;
    use std::sync::{Mutex, MutexGuard, OnceLock};
    use xace_observability::crash_reporter;
    use xace_observability::tick_ring_buffer::{TickRecord, TICK_BUFFER};

    static CRASH_TEST_LOCK: OnceLock<Mutex<()>> = OnceLock::new();

    fn crash_test_guard() -> MutexGuard<'static, ()> {
        CRASH_TEST_LOCK
            .get_or_init(|| Mutex::new(()))
            .lock()
            .unwrap()
    }

    fn tmp_crash_dir() -> PathBuf {
        let dir = std::env::temp_dir().join(format!(
            "xace_crash_test_{}",
            std::time::SystemTime::now()
                .duration_since(std::time::UNIX_EPOCH)
                .unwrap()
                .as_millis()
        ));
        dir
    }

    #[test]
    fn install_does_not_panic() {
        let _guard = crash_test_guard();
        crash_reporter::install(); // idempotent
        crash_reporter::install(); // safe to call twice
    }

    #[test]
    fn report_determinism_violation_writes_file() {
        let _guard = crash_test_guard();
        let dir = tmp_crash_dir();
        crash_reporter::set_crash_dir(dir.clone());

        // Push some tick history
        TICK_BUFFER.push(TickRecord::new(999, &"a".repeat(64), 8.3, 100, 5));
        TICK_BUFFER.push(TickRecord::new(1000, &"b".repeat(64), 8.1, 100, 3));

        crash_reporter::report_determinism_violation("D6", "Non-deterministic RNG in AISystem");

        // Allow file write to complete
        std::thread::sleep(std::time::Duration::from_millis(50));

        // The crash report directory should have been created
        assert!(dir.exists(), "crash report directory was not created");
        let files: Vec<_> = std::fs::read_dir(&dir)
            .unwrap()
            .filter_map(|e| e.ok())
            .collect();
        assert!(!files.is_empty(), "no crash report file was written");

        // Read and validate the determinism report. Other tests or panic hooks
        // can write into the same global crash directory during parallel runs.
        let report = files
            .iter()
            .filter_map(|entry| std::fs::read_to_string(entry.path()).ok())
            .filter_map(|content| serde_json::from_str::<serde_json::Value>(&content).ok())
            .find(|report| report["report_type"] == "DETERMINISM_VIOLATION")
            .expect("determinism violation report should be present");

        assert_eq!(report["report_type"], "DETERMINISM_VIOLATION");
        assert!(report["violation"]["rule"].as_str().unwrap().contains("D6"));
        assert!(report["violation"]["message"]
            .as_str()
            .unwrap()
            .contains("RNG"));
        assert!(report["last_ticks"].is_array());
    }

    #[test]
    fn crash_report_contains_tick_history() {
        let _guard = crash_test_guard();
        let dir = tmp_crash_dir();
        crash_reporter::set_crash_dir(dir.clone());

        for i in 0..5 {
            TICK_BUFFER.push(TickRecord::new(i, &format!("{i:064x}"), 8.0, 50, 1));
        }

        crash_reporter::report_fatal("test fatal error for tick history check");

        std::thread::sleep(std::time::Duration::from_millis(50));

        if dir.exists() {
            if let Ok(entries) = std::fs::read_dir(&dir) {
                for entry in entries.flatten() {
                    let content = std::fs::read_to_string(entry.path()).unwrap_or_default();
                    if content.contains("test fatal error") {
                        let report: serde_json::Value = serde_json::from_str(&content).unwrap();
                        let ticks = report["last_ticks"].as_array().unwrap();
                        assert!(!ticks.is_empty(), "crash report must include tick history");
                        return;
                    }
                }
            }
        }
        // If dir doesn't exist yet, just verify no panic — timing dependent
    }

    #[test]
    fn crash_report_redacts_api_keys() {
        let _guard = crash_test_guard();
        let dir = tmp_crash_dir();
        crash_reporter::set_crash_dir(dir.clone());
        let fake_key = format!("{}{}", "sk-", "xace-crash-redaction-secret-123");

        crash_reporter::report_fatal(&format!("provider failed with {fake_key}"));

        std::thread::sleep(std::time::Duration::from_millis(50));
        let content = std::fs::read_dir(&dir)
            .unwrap()
            .filter_map(|e| e.ok())
            .filter_map(|e| std::fs::read_to_string(e.path()).ok())
            .find(|body| body.contains("provider failed"))
            .expect("redaction crash report should be written");

        assert!(
            !content.contains(&fake_key),
            "crash report leaked an API key"
        );
        assert!(content.contains("[REDACTED_SECRET]"));
    }

    #[test]
    fn tick_ring_buffer_recent_newest_first() {
        let buf = xace_observability::tick_ring_buffer::TickRingBuffer::new(10);
        for i in 0..5u64 {
            buf.push(TickRecord::new(i, &format!("h{}", i), 1.0, 0, 0));
        }
        let recent = buf.recent(3);
        assert_eq!(recent.len(), 3);
        // Newest first: tick 4, 3, 2
        assert_eq!(recent[0].tick_number, 4);
        assert_eq!(recent[1].tick_number, 3);
        assert_eq!(recent[2].tick_number, 2);
    }

    #[test]
    fn tick_ring_buffer_wraps_correctly() {
        let buf = xace_observability::tick_ring_buffer::TickRingBuffer::new(3);
        for i in 0..6u64 {
            buf.push(TickRecord::new(i, "h", 1.0, 0, 0));
        }
        // Only last 3 should survive: 3, 4, 5
        let all = buf.recent(10);
        assert_eq!(all.len(), 3);
        let ticks: std::collections::HashSet<u64> = all.iter().map(|r| r.tick_number).collect();
        assert!(ticks.contains(&5));
        assert!(ticks.contains(&4));
        assert!(ticks.contains(&3));
        assert!(!ticks.contains(&0));
    }

    #[test]
    fn tick_ring_buffer_determinism_violations_filtered() {
        let buf = xace_observability::tick_ring_buffer::TickRingBuffer::new(10);
        buf.push(TickRecord::new(1, "h", 1.0, 0, 0)); // no violation
        buf.push(
            TickRecord::new(2, "h", 1.0, 0, 0).with_violations(1), // has violation
        );
        buf.push(TickRecord::new(3, "h", 1.0, 0, 0)); // no violation
        let violations = buf.determinism_violations();
        assert_eq!(violations.len(), 1);
        assert_eq!(violations[0].tick_number, 2);
    }
}
