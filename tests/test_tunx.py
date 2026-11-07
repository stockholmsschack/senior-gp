"""Check TUNX parsing and the Rilton calculation against the retained XLS exports."""

import json
from pathlib import Path
import struct
import unittest

from senior_gp.rilton_processor.excel_parser import ExcelParser
from senior_gp.rilton_processor.tunx_results import UnsupportedSectionError, section_rows
from senior_gp.tunx import ParseError, parse
from senior_gp.tunx.constants import (
    CONFIG_MARKER, CONFIG_OFFSET_CURRENT_ROUND, CONFIG_OFFSET_TIEBREAKS, PAIRING_RECORD_SIZE, PAIRINGS_MARKER,
)

RILTON = Path(__file__).resolve().parents[1] / "reference-artifacts" / "current-config-2025" / "inputs" / "rilton"
U1800 = RILTON / "rilton_u1800_2025_2026_1301929.TUNX"
U1800_VARIANT = RILTON / "rilton_u1800_2025_2026_1301929-2.TUNX"
U2200 = RILTON / "rilton_u2200_2025_2026_1301930.TUNX"
# Downloaded from chess-results.com on 2026-10-25; the XLS exports are in RILTON
FIXTURES = Path(__file__).resolve().parent / "fixtures" / "rilton"
U1800_2024 = FIXTURES / "rilton_u1800_2024_2025_967028.TUNX"
U2200_2024 = FIXTURES / "rilton_u2200_2024_2025_967027.TUNX"
# An event outside the U1800/U2200 pair, with its chess-results final ranking
CUP_2024 = FIXTURES / "rilton_cup_2024_2025_967022.TUNX"
CUP_2024_RANKING = FIXTURES / "rilton_cup_2024_2025_967022.ranking.json"
NUMERIC_FIELDS = ("Pts", "BH/C1", "BH", "PS")


def rows(path: Path, season: int = 2025) -> list[dict]:
    return section_rows(parse(path.read_bytes()), path.name, season)


def xls_rows(name: str, season: int) -> list[dict]:
    """Return the player rows of a retained XLS export, without its footer."""
    return [row for row in ExcelParser({}, season).read_rows(str(RILTON / name)) if row["SNo."] != ""]


def pairing_offset(content: bytes, record: int) -> int:
    return content.find(PAIRINGS_MARKER.to_bytes(4, "little")) + 4 + record * PAIRING_RECORD_SIZE


def config_offset(content: bytes, field: int) -> int:
    return content.find(CONFIG_MARKER.to_bytes(4, "little")) + 4 + field


def patched(content: bytes, offset: int, value: int) -> bytes:
    """Return the content with one little-endian u16 replaced."""
    return content[:offset] + struct.pack("<H", value) + content[offset + 2:]


class XlsParityTests(unittest.TestCase):
    def test_rounds_split_at_full_player_coverage(self):
        self.assertEqual([len(r.pairings) for r in parse(U1800.read_bytes()).rounds], [48, 47, 47, 48, 48, 48, 48])
        self.assertEqual([len(r.pairings) for r in parse(U2200.read_bytes()).rounds],
                         [73, 74, 74, 74, 74, 74, 74, 76, 77])

    def test_every_player_matches_xls_identity_values_and_order(self):
        compared = 0
        sections = (
            (U1800, "rilton-u1800-2025.xls", 2025), (U2200, "rilton-u2200-2025.xls", 2025),
            (U1800_2024, "rilton-u1800-2024.xls", 2024), (U2200_2024, "rilton-u2200-2024.xls", 2024),
        )
        for tunx, xls, season in sections:
            expected = xls_rows(xls, season)
            actual = rows(tunx, season)
            self.assertEqual(len(actual), len(expected))
            for got, want in zip(actual, expected):
                self.assertEqual((got["SNo."], got["Name"], got["Fide-No."]),
                                 (want["SNo."], want["Name"], want["Fide-No."] or 0), tunx.name)
                self.assertEqual([got[field] for field in NUMERIC_FIELDS],
                                 [want[field] for field in NUMERIC_FIELDS], f"{tunx.name} {got['SNo.']}")
                compared += len(NUMERIC_FIELDS)
        # 238 players in 2025/2026 and 241 in 2024/2025
        self.assertEqual(compared, 1916)

    def test_rilton_cup_matches_its_final_ranking(self):
        expected = json.loads(CUP_2024_RANKING.read_text())
        actual = [[row[column] for column in expected["columns"]] for row in rows(CUP_2024, season=2024)]
        self.assertEqual(len(actual), 115)
        self.assertEqual(actual, expected["rows"])

    def test_both_u1800_variants_give_the_same_rows(self):
        self.assertNotEqual(U1800.read_bytes(), U1800_VARIANT.read_bytes())
        self.assertEqual(rows(U1800), rows(U1800_VARIANT))

    def test_complete_ties_follow_starting_number(self):
        for path, first, second in ((U1800, 7, 74), (U2200, 86, 97)):
            numbers = [row["SNo."] for row in rows(path)]
            position = numbers.index(first)
            self.assertEqual(numbers[position + 1], second, path.name)


class FailureTests(unittest.TestCase):
    def setUp(self):
        self.content = U1800.read_bytes()

    def test_unknown_result_code_names_round_player_and_code(self):
        # Record 0 is round 1: player 48 against player 1
        content = patched(self.content, pairing_offset(self.content, 0) + 4, 7)
        with self.assertRaisesRegex(ParseError, "Round 1, player 48 against player 1: unknown result code 7"):
            parse(content)

    def test_player_twice_in_a_round_is_malformed(self):
        # Record 1 pairs 2 and 49; pairing 2 against 48 repeats player 48 from record 0
        content = patched(self.content, pairing_offset(self.content, 1) + 2, 48)
        with self.assertRaisesRegex(ParseError, "Player 48 appears twice in round 1"):
            parse(content)

    def test_truncated_file_is_malformed(self):
        with self.assertRaisesRegex(ParseError, "Pairings end without an end marker in round 3"):
            parse(self.content[:pairing_offset(self.content, 100)])

    def test_unplayed_round_or_missing_result_is_not_finished(self):
        current_round = patched(self.content, config_offset(self.content, CONFIG_OFFSET_CURRENT_ROUND), 6)
        missing_result = patched(self.content, pairing_offset(self.content, 0) + 4, 0)
        for content in (current_round, missing_result):
            tournament = parse(content)
            self.assertFalse(tournament.finished)
            with self.assertRaisesRegex(ValueError, "has not finished"):
                section_rows(tournament, "U1800", 2025)

    def test_other_tie_breaks_are_unsupported(self):
        content = patched(self.content, config_offset(self.content, CONFIG_OFFSET_TIEBREAKS), 52)
        with self.assertRaisesRegex(UnsupportedSectionError, r"unsupported tie-break settings \[52, 37, 8\]"):
            section_rows(parse(content), "U1800", 2025)

    def test_other_edition_is_unsupported(self):
        with self.assertRaisesRegex(UnsupportedSectionError, "is not the 2024/2025 edition"):
            rows(U1800, season=2024)


if __name__ == "__main__":
    unittest.main()
