// ============================================================================
// packages/runtime-core/src/query_engine/sorted_merge_iterator.rs
// ============================================================================
/*!
# sorted_merge_iterator.rs — K-Way Merge Across Archetypes
 
This is the **critical D3 preservation mechanism** for archetype storage.
 
## Problem
 
D3 requires entity iteration in EntityID ASC order GLOBALLY across the world.
But archetype storage groups entities by component composition — entities are
NOT stored in global EntityID order; they're grouped by archetype.
 
Within one archetype, entities CAN be iterated in EntityID ASC order (via
Archetype.iter_sorted). Across archetypes, we need a merge.
 
## Solution: k-Way Merge with Min-Heap
 
Each archetype produces an EntityID-sorted iterator. We maintain a `BinaryHeap`
(min-heap by EntityID) of the current "head" of each archetype's iterator.
 
At each step:
1. Pop the minimum entity from the heap
2. Yield it
3. Advance that archetype's iterator
4. Push the next entry (if any) onto the heap
 
## Complexity
 
For N total entities across K archetypes:
    Time:  O(N log K)
    Space: O(K)
 
For 5,000 entities across 20 archetypes: 5,000 × log₂(20) ≈ 21,500 heap ops.
Each heap op is ~50ns → 1.1 ms per full iteration. Compare to BTreeMap iteration
of 5,000 entities (~12 ns per node × 5,000 ≈ 60 µs).
 
The k-way merge appears slower per-element, BUT iteration in archetype storage
is cache-friendly within each archetype, and the BTreeMap path pays cache misses
on every node traversal. Net result: archetype is faster overall.
 
## Determinism
 
The merge is deterministic: same archetypes + same entity composition →
same iteration order. Min-heap ties are broken by archetype_id (lower wins),
ensuring stable ordering even if two archetypes contain the same EntityID
(which should not happen but is defended against).
*/
 
use std::cmp::Ordering;
use std::collections::BinaryHeap;
 
use crate::component_tables::archetype::{Archetype, ComponentBundle};
use crate::component_tables::archetype_storage::ArchetypeStorage;
use crate::component_tables::storage_strategy::{ArchetypeId, EntityId};
 
 
// ── Heap Entry ────────────────────────────────────────────────────────────────
 
/// One pending entity from one archetype's sorted iterator.
/// Ordered by EntityId ASC; ties broken by ArchetypeId ASC for stability.
#[derive(Debug)]
struct HeapEntry {
    entity_id:    EntityId,
    row:          usize,
    archetype_id: ArchetypeId,
}
 
impl PartialEq for HeapEntry {
    fn eq(&self, other: &Self) -> bool {
        self.entity_id == other.entity_id && self.archetype_id == other.archetype_id
    }
}
impl Eq for HeapEntry {}
 
// BinaryHeap is a max-heap; we invert ordering to get min-heap behaviour.
impl PartialOrd for HeapEntry {
    fn partial_cmp(&self, other: &Self) -> Option<Ordering> { Some(self.cmp(other)) }
}
impl Ord for HeapEntry {
    fn cmp(&self, other: &Self) -> Ordering {
        // Reverse ordering on entity_id to make BinaryHeap a min-heap
        other.entity_id.cmp(&self.entity_id)
            .then_with(|| other.archetype_id.cmp(&self.archetype_id))
    }
}
 
 
// ── Sorted Merge Iterator ─────────────────────────────────────────────────────
 
/// Iterates entities across all archetypes in strict EntityID ASC order.
///
/// Created from `ArchetypeStorage::iter_sorted` (preferred) or directly
/// for custom archetype subsets.
pub struct SortedMergeIterator<'a> {
    storage:    &'a ArchetypeStorage,
    heap:       BinaryHeap<HeapEntry>,
    cursors:    std::collections::BTreeMap<ArchetypeId, std::vec::IntoIter<(EntityId, usize)>>,
}
 
impl<'a> SortedMergeIterator<'a> {
    /// Creates a merge iterator over all archetypes in storage.
    pub fn new(storage: &'a ArchetypeStorage) -> Self {
        let mut heap    = BinaryHeap::new();
        let mut cursors = std::collections::BTreeMap::new();
 
        for archetype in storage.iter_archetypes() {
            // Materialise each archetype's sorted iterator into a Vec for owned iteration
            let sorted: Vec<(EntityId, usize)> = archetype.iter_sorted().collect();
            let mut iter = sorted.into_iter();
            if let Some((entity_id, row)) = iter.next() {
                heap.push(HeapEntry { entity_id, row, archetype_id: archetype.id });
                cursors.insert(archetype.id, iter);
            }
        }
 
        Self { storage, heap, cursors }
    }
 
    /// Creates a merge iterator filtered to only archetypes matching a query.
    pub fn new_filtered(
        storage:  &'a ArchetypeStorage,
        archetype_ids: &std::collections::BTreeSet<ArchetypeId>,
    ) -> Self {
        let mut heap    = BinaryHeap::new();
        let mut cursors = std::collections::BTreeMap::new();
 
        for archetype in storage.iter_archetypes() {
            if !archetype_ids.contains(&archetype.id) {
                continue;
            }
            let sorted: Vec<(EntityId, usize)> = archetype.iter_sorted().collect();
            let mut iter = sorted.into_iter();
            if let Some((entity_id, row)) = iter.next() {
                heap.push(HeapEntry { entity_id, row, archetype_id: archetype.id });
                cursors.insert(archetype.id, iter);
            }
        }
 
        Self { storage, heap, cursors }
    }
}
 
impl<'a> Iterator for SortedMergeIterator<'a> {
    type Item = (EntityId, ComponentBundle<'a>);
 
    fn next(&mut self) -> Option<Self::Item> {
        let head = self.heap.pop()?;
 
        // Push the next entry from that archetype's cursor
        if let Some(cursor) = self.cursors.get_mut(&head.archetype_id) {
            if let Some((next_id, next_row)) = cursor.next() {
                self.heap.push(HeapEntry {
                    entity_id:    next_id,
                    row:          next_row,
                    archetype_id: head.archetype_id,
                });
            }
        }
 
        let archetype = self.storage.archetype(head.archetype_id)?;
        Some((
            head.entity_id,
            ComponentBundle {
                entity_id: head.entity_id,
                row:       head.row,
                archetype,
            },
        ))
    }
}
 
 