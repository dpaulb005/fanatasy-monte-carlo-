"""Tests for sync orchestration, era capabilities, and politeness."""

from __future__ import annotations

import pytest

from league.ingestion.politeness import Politeness
from league.ingestion.ports import SeasonRef, capabilities_for_year
from league.ingestion.runner import run_sync
from league.ingestion.synthetic import generate_season
from league.ingestion.synthetic_source import SyntheticSource
from league.models import Season, SyncLog


class _CountingSource:
    """A source that records which years were actually fetched."""

    def __init__(self, years: list[int]) -> None:
        self._years = years
        self.fetched: list[int] = []

    def available_years(self) -> list[int]:
        return list(self._years)

    def fetch_season(self, ref: SeasonRef):
        self.fetched.append(ref.year)
        return generate_season(ref.year)


def test_capabilities_era_boundaries() -> None:
    old = capabilities_for_year(2016)
    assert old.endpoint == "history"
    assert not old.box_scores and not old.activity

    y2018 = capabilities_for_year(2018)
    assert y2018.endpoint == "current"
    assert not y2018.box_scores  # detailed weekly starts 2019

    modern = capabilities_for_year(2021)
    assert modern.endpoint == "current"
    assert modern.box_scores and modern.activity and modern.transactions


@pytest.mark.django_db
def test_run_sync_persists_and_logs() -> None:
    source = _CountingSource([2022, 2023])
    sync = run_sync(source, league_id=999999, years=[2022, 2023])

    assert sync.status == SyncLog.Status.SUCCESS
    assert Season.objects.filter(is_complete=True).count() == 2
    assert source.fetched == [2022, 2023]
    assert sync.row_counts["seasons"] == 2


@pytest.mark.django_db
def test_run_sync_skips_completed_seasons() -> None:
    source = _CountingSource([2022, 2023])
    run_sync(source, league_id=999999, years=[2022, 2023])

    # Second run: both already complete -> skipped, none re-fetched.
    source2 = _CountingSource([2022, 2023])
    sync = run_sync(source2, league_id=999999, years=[2022, 2023])
    assert source2.fetched == []
    assert sync.row_counts["skipped"] == 2


@pytest.mark.django_db
def test_run_sync_force_refetches() -> None:
    run_sync(_CountingSource([2022]), league_id=999999, years=[2022])
    source = _CountingSource([2022])
    run_sync(source, league_id=999999, years=[2022], force=True)
    assert source.fetched == [2022]


@pytest.mark.django_db
def test_run_sync_records_failure() -> None:
    class _Boom:
        def available_years(self) -> list[int]:
            return [2022]

        def fetch_season(self, ref: SeasonRef):
            raise RuntimeError("espn exploded")

    with pytest.raises(RuntimeError):
        run_sync(_Boom(), league_id=999999, years=[2022])
    assert SyncLog.objects.filter(status=SyncLog.Status.FAILED).exists()


def test_synthetic_source_available_years() -> None:
    assert SyntheticSource([2020, 2019]).available_years() == [2019, 2020]


def test_politeness_retries_then_succeeds() -> None:
    calls = {"n": 0}
    slept: list[float] = []

    def flaky() -> str:
        calls["n"] += 1
        if calls["n"] < 3:
            raise ConnectionError("transient")
        return "ok"

    politeness = Politeness(base_delay=0.01, max_retries=3, sleep=slept.append)
    assert politeness.call(flaky) == "ok"
    assert calls["n"] == 3
    assert len(slept) == 2  # two backoff sleeps before the third success


def test_politeness_gives_up_after_max_retries() -> None:
    def always_fail() -> str:
        raise ConnectionError("down")

    politeness = Politeness(base_delay=0.0, max_retries=2, sleep=lambda _s: None)
    with pytest.raises(ConnectionError):
        politeness.call(always_fail)


def test_espn_source_allows_public_league_without_cookies() -> None:
    from league.ingestion.espn_source import EspnApiSource

    # No cookies is valid (public league); construction must not raise.
    src = EspnApiSource(league_id=123, years=[2025])
    assert src.available_years() == [2025]


def test_espn_source_rejects_half_credentials() -> None:
    import pytest

    from league.ingestion.espn_source import EspnApiSource

    with pytest.raises(ValueError, match="BOTH"):
        EspnApiSource(league_id=123, espn_s2="abc", swid="")
