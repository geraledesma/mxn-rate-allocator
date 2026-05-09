"""Unit tests for globally sorted tier-rate change detection."""

from __future__ import annotations

from datetime import datetime, timezone

from rate_allocator.persistence.history import TierRateChangeEvent


def test_tier_changes_sorted_global_newest_first() -> None:
    """Exercise the same comparator used after aggregating rows (vigencia desc)."""
    from rate_allocator.persistence import history as history_mod

    key = history_mod._event_sort_key

    newer = TierRateChangeEvent(
        effective_from=datetime(2026, 5, 10, tzinfo=timezone.utc),
        applied_at=datetime(2026, 5, 11, tzinfo=timezone.utc),
        institution_name="Z",
        institution_key="zz",
        tier_index=1,
        old_rate=0.10,
        new_rate=0.09,
        source="",
        note=None,
    )
    older = TierRateChangeEvent(
        effective_from=datetime(2026, 3, 1, tzinfo=timezone.utc),
        applied_at=datetime(2026, 3, 5, tzinfo=timezone.utc),
        institution_name="A",
        institution_key="aa",
        tier_index=2,
        old_rate=0.07,
        new_rate=0.08,
        source="",
        note=None,
    )
    naive_ok = TierRateChangeEvent(
        effective_from=datetime(2026, 4, 1),
        applied_at=datetime(2026, 4, 2),
        institution_name="M",
        institution_key="mm",
        tier_index=0,
        old_rate=0.06,
        new_rate=0.07,
        source="",
        note=None,
    )

    merged = sorted([older, naive_ok, newer], key=key)
    assert merged[0] is newer
    assert merged[1] is naive_ok
    assert merged[2] is older
