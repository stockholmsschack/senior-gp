"""Check January standard Elo classification at the API boundary."""

from copy import deepcopy
from tempfile import TemporaryDirectory
import unittest

from senior_gp.rating_fetcher.exceptions import ProcessingError
from senior_gp.rating_fetcher.processor import RatingProcessor


class RatingClassificationTests(unittest.TestCase):
    def test_missing_standard_elo_is_class_e(self):
        players = [
            {},
            {"elo": None},
            {"elo": {}},
            {"elo": {"rating": None}},
            {"elo": {"rapidRating": 2400, "blitzRating": 2300}},
        ]
        original = deepcopy(players)
        with TemporaryDirectory() as directory:
            result = RatingProcessor(2025, directory).add_klass_classification(players)
        self.assertEqual([player["klass"] for player in result], ["E"] * 5)
        self.assertEqual(players, original)

    def test_standard_elo_takes_precedence(self):
        with TemporaryDirectory() as directory:
            result = RatingProcessor(2025, directory).add_klass_classification([
                {"elo": {"rating": 1750, "rapidRating": 2400, "blitzRating": 2300}}
            ])
        self.assertEqual(result[0]["klass"], "D")

    def test_malformed_values_still_fail(self):
        with TemporaryDirectory() as directory:
            processor = RatingProcessor(2025, directory)
            for elo in ([], "", 0, {"rating": "unknown"}):
                with self.subTest(elo=elo), self.assertRaises(ProcessingError):
                    processor.add_klass_classification([{"elo": elo}])
