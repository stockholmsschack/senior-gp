"""Each season's configuration is stored, revised and moved on its own."""

from dataclasses import replace
from datetime import date

import pytest

from senior_gp.configuration import (
    DM, GP, MEMBER_SYSTEM, RILTON, ActiveConfiguration, ConfigurationValidationError, StaleConfigurationError,
    Tournament, by_date_of_play, configuration_path, load_configuration, save_configuration, stored_seasons,
)

COMPO_CUP = Tournament(MEMBER_SYSTEM, "5382", "Compo Cup", GP)
NEXT_SEASON_CUP = Tournament(MEMBER_SYSTEM, "6001", "Höstcupen", GP)


def test_saving_one_season_leaves_another_unchanged(tmp_path):
    save_configuration(tmp_path, ActiveConfiguration(2025, (COMPO_CUP,)))
    stored_2025 = configuration_path(tmp_path, 2025).read_bytes()

    saved = save_configuration(tmp_path, ActiveConfiguration(2026, (NEXT_SEASON_CUP,)))
    save_configuration(tmp_path, replace(saved, tournaments=(replace(NEXT_SEASON_CUP, scoring=DM),)))

    assert configuration_path(tmp_path, 2025).read_bytes() == stored_2025
    assert load_configuration(tmp_path, 2025).revision == 1
    assert load_configuration(tmp_path, 2026).revision == 2
    assert stored_seasons(tmp_path) == (2026, 2025)


def test_each_season_checks_its_own_revision(tmp_path):
    save_configuration(tmp_path, ActiveConfiguration(2025, (COMPO_CUP,)))
    save_configuration(tmp_path, ActiveConfiguration(2025, (COMPO_CUP,), revision=1))

    with pytest.raises(StaleConfigurationError):
        save_configuration(tmp_path, ActiveConfiguration(2026, (NEXT_SEASON_CUP,), revision=2))


def test_a_season_without_a_file_is_reported(tmp_path):
    with pytest.raises(ConfigurationValidationError, match="season 2026 has no configuration yet"):
        load_configuration(tmp_path, 2026)
    assert stored_seasons(tmp_path) == ()


def test_a_file_in_another_seasons_directory_is_refused(tmp_path):
    save_configuration(tmp_path, ActiveConfiguration(2025, (COMPO_CUP,)))
    moved = configuration_path(tmp_path, 2026)
    moved.parent.mkdir(parents=True)
    configuration_path(tmp_path, 2025).rename(moved)

    with pytest.raises(ConfigurationValidationError, match="the file for season 2026 names season 2025"):
        load_configuration(tmp_path, 2026)


def test_a_configuration_from_before_phase_6_moves_to_its_season(tmp_path):
    save_configuration(tmp_path, ActiveConfiguration(2025, (COMPO_CUP,)))
    document = configuration_path(tmp_path, 2025).read_text()
    configuration_path(tmp_path, 2025).unlink()
    (tmp_path / "active-configuration.toml").write_text(document)

    assert load_configuration(tmp_path, 2025) == ActiveConfiguration(2025, (COMPO_CUP,), revision=1)
    assert not (tmp_path / "active-configuration.toml").exists()
    assert configuration_path(tmp_path, 2025).read_text() == document


def test_a_configuration_from_before_phase_6_never_replaces_a_seasons_file(tmp_path):
    save_configuration(tmp_path, ActiveConfiguration(2025, (COMPO_CUP,)))
    stored = configuration_path(tmp_path, 2025).read_bytes()
    (tmp_path / "active-configuration.toml").write_text('revision = 4\nseason = 2025\n')

    with pytest.raises(ConfigurationValidationError, match="already exists"):
        stored_seasons(tmp_path)
    assert configuration_path(tmp_path, 2025).read_bytes() == stored
    assert (tmp_path / "active-configuration.toml").exists()


def test_a_start_date_is_stored_as_a_toml_date(tmp_path):
    dated = replace(COMPO_CUP, start_date=date(2025, 3, 21))
    save_configuration(tmp_path, ActiveConfiguration(2025, (dated,)))

    assert "start_date = 2025-03-21\n" in configuration_path(tmp_path, 2025).read_text()
    assert load_configuration(tmp_path, 2025).tournaments == (dated,)


def test_a_start_date_that_is_not_a_date_is_refused(tmp_path):
    with pytest.raises(ConfigurationValidationError, match="'5382': start_date must be a date"):
        save_configuration(tmp_path, ActiveConfiguration(2025, (replace(COMPO_CUP, start_date="2025-03-21"),)))


def test_tournaments_are_ordered_by_date_of_play_with_undated_ones_last():
    rilton = Tournament(RILTON, "1301930", "Rilton U2200", start_date=date(2025, 12, 27))
    undated = Tournament(MEMBER_SYSTEM, "5400", "Undated")
    early = replace(COMPO_CUP, start_date=date(2025, 3, 21))
    same_day = replace(NEXT_SEASON_CUP, start_date=date(2025, 3, 21))

    assert by_date_of_play((undated, rilton, same_day, early)) == (same_day, early, rilton, undated)
