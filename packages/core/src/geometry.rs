//! Version 1 portable geometry query contracts. Coordinates are Fixed64 micro-units.
use crate::entity_id::EntityID;
use crate::fixed_point::Fixed64;
use serde::{Deserialize, Serialize};

pub const GEOMETRY_QUERY_VERSION: u32 = 1;
pub const MAX_DISPLACEMENT_RAW: i64 = 16_000_000;

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Aabb {
    pub center: [Fixed64; 3],
    pub half_extents: [Fixed64; 3],
}

/// Axis ordering for equal contacts: X, Y, Z; negative before positive.
#[derive(Debug, Clone, Copy, PartialEq, Eq, PartialOrd, Ord, Serialize, Deserialize)]
pub enum AxisNormal {
    NegativeX,
    PositiveX,
    NegativeY,
    PositiveY,
    NegativeZ,
    PositiveZ,
}
impl AxisNormal {
    pub fn axis(self) -> usize {
        self as usize / 2
    }
    pub fn sign(self) -> i64 {
        if self as usize % 2 == 0 {
            -1
        } else {
            1
        }
    }
    pub fn from_axis(axis: usize, positive: bool) -> Option<Self> {
        [
            Self::NegativeX,
            Self::PositiveX,
            Self::NegativeY,
            Self::PositiveY,
            Self::NegativeZ,
            Self::PositiveZ,
        ]
        .get(axis.checked_mul(2)? + usize::from(positive))
        .copied()
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
pub enum GeometrySelection {
    Solids,
    Triggers,
    All,
}
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct GeometryFilter {
    pub selection: GeometrySelection,
    pub layer_mask: u32,
    pub exclude: Option<EntityID>,
}
impl Default for GeometryFilter {
    fn default() -> Self {
        Self {
            selection: GeometrySelection::Solids,
            layer_mask: u32::MAX,
            exclude: None,
        }
    }
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub enum GeometryQueryV1 {
    Sweep {
        bounds: Aabb,
        displacement: [Fixed64; 3],
        filter: GeometryFilter,
    },
    Overlap {
        bounds: Aabb,
        filter: GeometryFilter,
    },
    /// NegativeY is a ground probe; +/-X and +/-Z are side probes.
    Probe {
        bounds: Aabb,
        direction: AxisNormal,
        distance: Fixed64,
        filter: GeometryFilter,
    },
    /// Explicit candidate entities permit semantic targeting without hidden component reads.
    Nearest {
        origin: [Fixed64; 3],
        max_distance: Fixed64,
        candidates: Vec<EntityID>,
    },
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct GeometryContact {
    pub entity_id: EntityID,
    pub object_id: Option<crate::wire::session_contract::ContractId>,
    /// Exact reduced fraction in [0,1], positive denominator. Never rounded for ordering.
    pub time_numerator: u64,
    pub time_denominator: u64,
    pub normal: AxisNormal,
    pub initial_overlap: bool,
    /// Displacement to this contact, rounded toward the start in each axis.
    pub travel: [Fixed64; 3],
}
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct GeometryTarget {
    pub entity_id: EntityID,
    pub object_id: Option<crate::wire::session_contract::ContractId>,
    /// Raw micro-unit squared distance; intentionally wider than Fixed64.
    pub distance_squared: u128,
}
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub enum GeometryResultV1 {
    Contacts(Vec<GeometryContact>),
    Overlaps(Vec<EntityID>),
    Nearest(Option<GeometryTarget>),
}
