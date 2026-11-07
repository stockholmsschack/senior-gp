"""The default season and the year choices, by the Stockholm date."""

from datetime import UTC, date, datetime, timedelta, timezone

import pytest

from senior_gp.seasons import default_season, is_historical, retained_seasons, season_choices, stockholm_today


@pytest.mark.parametrize("instant, today, season", [
    # 23:30 UTC on 31 December is 00:30 on 1 January in Stockholm (UTC+1).
    (datetime(2025, 12, 31, 22, 30, tzinfo=UTC), date(2025, 12, 31), 2025),
    (datetime(2025, 12, 31, 23, 30, tzinfo=UTC), date(2026, 1, 1), 2025),
    # 22:30 UTC on 31 May is 00:30 on 1 June in Stockholm (UTC+2).
    (datetime(2026, 5, 31, 21, 30, tzinfo=UTC), date(2026, 5, 31), 2025),
    (datetime(2026, 5, 31, 22, 30, tzinfo=UTC), date(2026, 6, 1), 2026),
])
def test_the_default_changes_on_1_june_in_stockholm(instant, today, season):
    assert stockholm_today(lambda: instant) == today
    assert default_season(today) == season


def test_a_clock_in_another_time_zone_gives_the_stockholm_date():
    new_york = timezone(timedelta(hours=-4))

    assert stockholm_today(lambda: datetime(2026, 5, 31, 18, 30, tzinfo=new_york)) == date(2026, 6, 1)


def test_a_clock_without_a_time_zone_is_refused():
    with pytest.raises(ValueError, match="time zone"):
        stockholm_today(lambda: datetime(2026, 6, 1))


@pytest.mark.parametrize("today", [date(2026, 1, 1), date(2026, 5, 31), date(2026, 6, 1), date(2026, 12, 31)])
def test_the_choices_are_this_year_and_last_year_and_in_development_the_year_before(today):
    assert season_choices(today) == (2026, 2025)
    assert season_choices(today, development=True) == (2026, 2025, 2024)
    assert default_season(today) in season_choices(today)


@pytest.mark.parametrize("today", [date(2027, 1, 1), date(2027, 6, 1)])
def test_a_season_older_than_last_year_is_historical(today):
    assert [season for season in (2027, 2026, 2025) if is_historical(season, today)] == [2025]


@pytest.mark.parametrize("today, stored, retained", [
    # Before 2027 has data, 2024 stays as the third stored season.
    (date(2027, 1, 1), {2026, 2025, 2024, 2023}, {2027, 2026, 2025, 2024}),
    (date(2027, 6, 1), {2027, 2026, 2025, 2024}, {2027, 2026, 2025}),
    (date(2027, 6, 1), set(), {2027, 2026, 2025}),
])
def test_cleanup_keeps_three_years_and_three_stored_seasons(today, stored, retained):
    assert retained_seasons(today, stored) == retained
