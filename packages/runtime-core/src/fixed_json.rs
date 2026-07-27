//! Fixed-point JSON helpers for authoritative runtime component payloads.

use serde_json::{Number, Value};
use xace_core::fixed_point::{Fixed64, FIXED64_SCALE};

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum IntegerEncoding {
    RawMicroUnits,
    WholeUnits,
}

pub fn fixed_tick_delta_60hz() -> Fixed64 {
    Fixed64::from_u64_ratio(1, 60).unwrap_or_else(|| Fixed64::from_raw(16_666))
}

pub fn fixed_from_json(value: &Value, integer_encoding: IntegerEncoding) -> Option<Fixed64> {
    match value {
        Value::Number(number) => parse_fixed_literal(&number.to_string(), integer_encoding),
        Value::String(text) => parse_fixed_literal(text, integer_encoding),
        _ => None,
    }
}

pub fn fixed_field(
    value: &Value,
    names: &[&str],
    integer_encoding: IntegerEncoding,
) -> Option<Fixed64> {
    names
        .iter()
        .find_map(|name| fixed_from_json(value.get(*name)?, integer_encoding))
}

pub fn fixed_value(value: Fixed64) -> Value {
    Value::Number(Number::from(value.raw()))
}

pub fn set_fixed_field(value: &mut Value, field: &str, number: Fixed64) {
    if !value.is_object() {
        *value = Value::Object(Default::default());
    }
    if let Some(object) = value.as_object_mut() {
        object.insert(field.to_string(), fixed_value(number));
    }
}

pub fn u64_field(value: &Value, names: &[&str]) -> Option<u64> {
    names.iter().find_map(|name| {
        let value = value.get(*name)?;
        match value {
            Value::Number(number) => parse_u64_literal(&number.to_string()),
            Value::String(text) => parse_u64_literal(text),
            _ => None,
        }
    })
}

pub fn fixed_to_u64_units(value: Fixed64) -> Option<u64> {
    let raw = value.raw();
    if raw < 0 || raw % FIXED64_SCALE != 0 {
        return None;
    }
    Some((raw / FIXED64_SCALE) as u64)
}

pub fn fixed_from_units_u64(units: u64) -> Fixed64 {
    let raw = (units as i128) * (FIXED64_SCALE as i128);
    fixed_from_i128_saturating(raw)
}

pub fn parse_fixed_literal(text: &str, integer_encoding: IntegerEncoding) -> Option<Fixed64> {
    let text = text.trim();
    if text.is_empty() || text.contains('e') || text.contains('E') {
        return None;
    }

    let (negative, unsigned) = match text.as_bytes().first().copied() {
        Some(b'-') => (true, &text[1..]),
        Some(b'+') => (false, &text[1..]),
        _ => (false, text),
    };
    if unsigned.is_empty() {
        return None;
    }

    let mut pieces = unsigned.split('.');
    let units_text = pieces.next().unwrap_or_default();
    let fraction_text = pieces.next();
    if pieces.next().is_some() {
        return None;
    }

    if let Some(fraction_text) = fraction_text {
        parse_decimal_units(units_text, fraction_text, negative)
    } else {
        let raw = units_text.parse::<i128>().ok()?;
        let raw = match integer_encoding {
            IntegerEncoding::RawMicroUnits => raw,
            IntegerEncoding::WholeUnits => raw.checked_mul(FIXED64_SCALE as i128)?,
        };
        Some(fixed_from_i128_saturating(if negative {
            -raw
        } else {
            raw
        }))
    }
}

fn parse_decimal_units(units_text: &str, fraction_text: &str, negative: bool) -> Option<Fixed64> {
    if fraction_text.len() > 6
        || !fraction_text.bytes().all(|byte| byte.is_ascii_digit())
        || !units_text.bytes().all(|byte| byte.is_ascii_digit())
    {
        return None;
    }
    let units = if units_text.is_empty() {
        0
    } else {
        units_text.parse::<i128>().ok()?
    };
    let mut fraction = fraction_text.to_string();
    while fraction.len() < 6 {
        fraction.push('0');
    }
    let micros = if fraction.is_empty() {
        0
    } else {
        fraction.parse::<i128>().ok()?
    };
    let raw = units
        .checked_mul(FIXED64_SCALE as i128)?
        .checked_add(micros)?;
    Some(fixed_from_i128_saturating(if negative {
        -raw
    } else {
        raw
    }))
}

fn parse_u64_literal(text: &str) -> Option<u64> {
    let text = text.trim();
    if text.is_empty() || text.starts_with('-') || text.contains('e') || text.contains('E') {
        return None;
    }
    let (units_text, fraction_text) = match text.split_once('.') {
        Some((units, fraction)) => (units, Some(fraction)),
        None => (text, None),
    };
    if !units_text.bytes().all(|byte| byte.is_ascii_digit()) {
        return None;
    }
    if let Some(fraction) = fraction_text {
        if !fraction.bytes().all(|byte| byte == b'0') {
            return None;
        }
    }
    units_text.parse::<u64>().ok()
}

fn fixed_from_i128_saturating(value: i128) -> Fixed64 {
    if value > i64::MAX as i128 {
        Fixed64::MAX
    } else if value < i64::MIN as i128 {
        Fixed64::MIN
    } else {
        Fixed64::from_raw(value as i64)
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    #[test]
    fn parses_component_raw_integers_and_legacy_decimals() {
        let legacy_decimal = serde_json::from_str::<Value>("1.5").unwrap();
        assert_eq!(
            fixed_from_json(&json!(1_500_000), IntegerEncoding::RawMicroUnits),
            Some(Fixed64::from_millis(1500))
        );
        assert_eq!(
            fixed_from_json(&legacy_decimal, IntegerEncoding::RawMicroUnits),
            Some(Fixed64::from_millis(1500))
        );
    }

    #[test]
    fn parses_executor_whole_unit_integers() {
        assert_eq!(
            fixed_from_json(&json!(2), IntegerEncoding::WholeUnits),
            Some(Fixed64::from_units(2))
        );
    }

    #[test]
    fn serializes_fixed_as_raw_integer_json() {
        assert_eq!(fixed_value(Fixed64::from_millis(1250)), json!(1_250_000));
    }
}
