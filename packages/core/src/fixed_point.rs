//! Deterministic fixed-point numeric primitives for authoritative state.
//!
//! `Fixed64` stores values as signed micro-units (`1.0 == 1_000_000`).
//! Authoritative gameplay state should store this type, integer ticks, or
//! domain-specific integer counters instead of `f32`/`f64`.

use serde::{Deserialize, Serialize};

pub const FIXED64_SCALE: i64 = 1_000_000;

#[derive(Debug, Clone, Copy, PartialEq, Eq, PartialOrd, Ord, Hash, Serialize, Deserialize)]
#[serde(transparent)]
pub struct Fixed64 {
    raw: i64,
}

impl Fixed64 {
    pub const ZERO: Self = Self::from_raw(0);
    pub const ONE: Self = Self::from_units(1);
    pub const MAX: Self = Self::from_raw(i64::MAX);
    pub const MIN: Self = Self::from_raw(i64::MIN);

    pub const fn from_raw(raw: i64) -> Self {
        Self { raw }
    }

    pub const fn from_units(units: i64) -> Self {
        Self {
            raw: units * FIXED64_SCALE,
        }
    }

    pub const fn from_millis(millis: i64) -> Self {
        Self {
            raw: millis * 1_000,
        }
    }

    pub const fn from_micros(micros: i64) -> Self {
        Self { raw: micros }
    }

    pub fn from_ratio(numerator: i64, denominator: i64) -> Option<Self> {
        if denominator == 0 {
            return None;
        }
        let raw = (numerator as i128)
            .checked_mul(FIXED64_SCALE as i128)?
            .checked_div(denominator as i128)?;
        Some(Self::from_i128_saturating(raw))
    }

    pub fn from_u64_ratio(numerator: u64, denominator: u64) -> Option<Self> {
        if denominator == 0 {
            return None;
        }
        let raw = (numerator as i128)
            .checked_mul(FIXED64_SCALE as i128)?
            .checked_div(denominator as i128)?;
        Some(Self::from_i128_saturating(raw))
    }

    pub fn raw(self) -> i64 {
        self.raw
    }

    pub fn is_zero(self) -> bool {
        self.raw == 0
    }

    pub fn abs(self) -> Self {
        Self::from_raw(self.raw.saturating_abs())
    }

    pub fn saturating_add(self, rhs: Self) -> Self {
        Self::from_raw(self.raw.saturating_add(rhs.raw))
    }

    pub fn saturating_sub(self, rhs: Self) -> Self {
        Self::from_raw(self.raw.saturating_sub(rhs.raw))
    }

    pub fn saturating_mul(self, rhs: Self) -> Self {
        let raw = (self.raw as i128 * rhs.raw as i128) / FIXED64_SCALE as i128;
        Self::from_i128_saturating(raw)
    }

    pub fn checked_div(self, rhs: Self) -> Option<Self> {
        if rhs.raw == 0 {
            return None;
        }
        let raw = (self.raw as i128)
            .checked_mul(FIXED64_SCALE as i128)?
            .checked_div(rhs.raw as i128)?;
        Some(Self::from_i128_saturating(raw))
    }

    pub fn sqrt(self) -> Self {
        if self.raw <= 0 {
            return Self::ZERO;
        }
        let scaled = self.raw as u128 * FIXED64_SCALE as u128;
        Self::from_raw(integer_sqrt(scaled).min(i64::MAX as u128) as i64)
    }

    pub fn to_decimal_string(self) -> String {
        let sign = if self.raw < 0 { "-" } else { "" };
        let abs = self.raw.saturating_abs();
        let units = abs / FIXED64_SCALE;
        let micros = abs % FIXED64_SCALE;
        if micros == 0 {
            return format!("{sign}{units}");
        }
        let mut fraction = format!("{micros:06}");
        while fraction.ends_with('0') {
            fraction.pop();
        }
        format!("{sign}{units}.{fraction}")
    }

    fn from_i128_saturating(value: i128) -> Self {
        if value > i64::MAX as i128 {
            Self::MAX
        } else if value < i64::MIN as i128 {
            Self::MIN
        } else {
            Self::from_raw(value as i64)
        }
    }
}

impl Default for Fixed64 {
    fn default() -> Self {
        Self::ZERO
    }
}

impl std::fmt::Display for Fixed64 {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(&self.to_decimal_string())
    }
}

impl std::ops::Add for Fixed64 {
    type Output = Fixed64;

    fn add(self, rhs: Self) -> Self::Output {
        self.saturating_add(rhs)
    }
}

impl std::ops::Sub for Fixed64 {
    type Output = Fixed64;

    fn sub(self, rhs: Self) -> Self::Output {
        self.saturating_sub(rhs)
    }
}

impl std::ops::Mul for Fixed64 {
    type Output = Fixed64;

    fn mul(self, rhs: Self) -> Self::Output {
        self.saturating_mul(rhs)
    }
}

impl std::ops::Neg for Fixed64 {
    type Output = Fixed64;

    fn neg(self) -> Self::Output {
        Self::from_raw(self.raw.saturating_neg())
    }
}

impl From<i64> for Fixed64 {
    fn from(value: i64) -> Self {
        Self::from_units(value)
    }
}

fn integer_sqrt(value: u128) -> u128 {
    if value < 2 {
        return value;
    }
    let mut x0 = value / 2;
    let mut x1 = (x0 + value / x0) / 2;
    while x1 < x0 {
        x0 = x1;
        x1 = (x0 + value / x0) / 2;
    }
    x0
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn fixed64_uses_micro_unit_scale() {
        assert_eq!(Fixed64::ONE.raw(), 1_000_000);
        assert_eq!(Fixed64::from_millis(1500).to_decimal_string(), "1.5");
    }

    #[test]
    fn fixed64_mul_div_and_sqrt_are_integer_deterministic() {
        let three = Fixed64::from_units(3);
        let four = Fixed64::from_units(4);
        let twenty_five = three * three + four * four;

        assert_eq!(twenty_five, Fixed64::from_units(25));
        assert_eq!(twenty_five.sqrt(), Fixed64::from_units(5));
        assert_eq!(
            Fixed64::from_units(10).checked_div(Fixed64::from_units(4)),
            Some(Fixed64::from_millis(2500))
        );
        assert_eq!(
            Fixed64::from_u64_ratio(5, 2),
            Some(Fixed64::from_millis(2500))
        );
    }

    #[test]
    fn fixed64_serializes_as_scaled_integer() {
        let encoded = serde_json::to_string(&Fixed64::from_millis(1250)).unwrap();
        assert_eq!(encoded, "1250000");
        let decoded: Fixed64 = serde_json::from_str(&encoded).unwrap();
        assert_eq!(decoded.to_decimal_string(), "1.25");
    }
}
