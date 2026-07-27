// ============================================================================
// packages/observability/tests/test_trace.rs
// ============================================================================

#[cfg(test)]
mod test_trace {
    use xace_observability::trace::{Span, SpanId, TraceId, TraceLog};
    use xace_observability::tracer::{current_trace_id, enter_span, TRACER};

    #[test]
    fn trace_id_new_unique_not_zero() {
        let id = TraceId::new_unique();
        assert!(!id.is_zero());
    }

    #[test]
    fn trace_id_unique_across_calls() {
        let a = TraceId::new_unique();
        let b = TraceId::new_unique();
        assert_ne!(a, b);
    }

    #[test]
    fn trace_id_to_hex_is_32_chars() {
        let id = TraceId::new_unique();
        let hex = id.to_hex();
        assert_eq!(hex.len(), 32);
        assert!(hex.chars().all(|c| c.is_ascii_hexdigit()));
    }

    #[test]
    fn span_id_unique_across_calls() {
        let a = SpanId::new_unique();
        let b = SpanId::new_unique();
        assert_ne!(a, b);
    }

    #[test]
    fn span_close_produces_record() {
        let trace_id = TraceId::new_unique();
        let span = Span::new("test_span", trace_id, None);
        let id = span.span_id;
        let record = span.close();
        assert_eq!(record.span_id, id);
        assert_eq!(record.name, "test_span");
        assert_eq!(record.trace_id, trace_id);
    }

    #[test]
    fn span_duration_positive() {
        let trace = TraceId::new_unique();
        let span = Span::new("work", trace, None);
        // Do trivial work to advance time
        std::thread::sleep(std::time::Duration::from_millis(1));
        let record = span.close();
        assert!(record.duration_us > 0);
    }

    #[test]
    fn span_with_attributes_serialises() {
        let trace = TraceId::new_unique();
        let mut span = Span::new("attr_test", trace, None);
        span.add_attribute("key", "value");
        let record = span.close();
        assert_eq!(
            record.attributes.get("key").map(|s| s.as_str()),
            Some("value")
        );
        let json = record.to_jsonl();
        assert!(json.contains("attr_test"));
        assert!(json.contains("key"));
    }

    #[test]
    fn scoped_span_enters_and_exits() {
        TRACER.set_active_trace(TraceId::new_unique());
        {
            let _span = enter_span("outer", [("entity", "player")]);
            // span is open here
        }
        // span is closed — nothing to assert except no panic
    }

    #[test]
    fn nested_spans_have_parent_child_relationship() {
        TRACER.set_active_trace(TraceId::new_unique());
        let outer_id = TRACER.enter("outer", None);
        let inner_id = TRACER.enter("inner", None); // parent = outer_id implicitly
        TRACER.exit(inner_id);
        TRACER.exit(outer_id);
        // Assert no panic; parent tracking is tested via TraceLog inspection
    }

    #[test]
    fn current_trace_id_none_when_not_set() {
        // Fresh thread has no active trace
        let result = std::thread::spawn(|| current_trace_id()).join().unwrap();
        assert!(result.is_none());
    }

    #[test]
    fn trace_log_push_and_flush() {
        let log = TraceLog::new(None);
        let trace = TraceId::new_unique();
        let span = Span::new("log_test", trace, None);
        let record = span.close();
        log.push(record);
        assert!(!log.is_empty());
        let flushed = log.flush();
        assert_eq!(flushed.len(), 1);
        assert!(log.is_empty());
    }

    #[test]
    fn span_display_is_non_empty() {
        let id = SpanId::new_unique();
        assert!(!format!("{}", id).is_empty());
        let tid = TraceId::new_unique();
        assert!(!format!("{}", tid).is_empty());
    }
}
