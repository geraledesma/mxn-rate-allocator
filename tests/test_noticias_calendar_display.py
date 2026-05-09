"""Display rules for tier vigencia vs. change-batch registro calendar dates."""

from __future__ import annotations

from datetime import date, datetime, timezone

import pytest


@pytest.fixture(scope="module")
def cal_mod():
    import streamlit_app as sa

    return sa


def test_vigencia_uses_utc_calendar_not_cdmx_eve(cal_mod):
    """UTC midnight 7 May must not become evening 6 May / calendar 30 Apr bug."""
    d = datetime(2026, 5, 7, 0, 0, tzinfo=timezone.utc)
    assert cal_mod._vigencia_effective_calendar_date(d) == date(2026, 5, 7)


def test_vigencia_naive_reads_wall_components(cal_mod):
    d = datetime(2026, 5, 1, 23, 0, 0)  # naive
    assert cal_mod._vigencia_effective_calendar_date(d) == date(2026, 5, 1)

