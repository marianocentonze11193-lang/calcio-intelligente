import importlib.util
import math
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
SCRIPT = ROOT / "scripts" / "backtest_walk_forward.py"
SPEC = importlib.util.spec_from_file_location("backtest_walk_forward", SCRIPT)
backtest = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(backtest)


class OutcomeCalibrationTests(unittest.TestCase):
    def test_calibration_is_reported_separately_for_1_x_2(self):
        rows = [
            {"outcome": "1", "model_probabilities": {"home_win": 70, "draw": 20, "away_win": 10}},
            {"outcome": "X", "model_probabilities": {"home_win": 20, "draw": 60, "away_win": 20}},
            {"outcome": "2", "model_probabilities": {"home_win": 10, "draw": 20, "away_win": 70}},
        ]
        result = backtest.outcome_calibration_summary(rows)
        self.assertEqual(set(result), {"1", "X", "2"})
        self.assertEqual([result[k]["matches"] for k in ("1", "X", "2")], [3, 3, 3])
        self.assertTrue(all(result[k]["brier_score"] is not None for k in result))
        self.assertTrue(all(result[k]["log_loss"] is not None for k in result))

    def test_empty_input_returns_empty_metrics_without_crashing(self):
        result = backtest.outcome_calibration_summary([])
        self.assertEqual([result[k]["matches"] for k in ("1", "X", "2")], [0, 0, 0])
        self.assertTrue(all(result[k]["brier_score"] is None for k in result))
        self.assertTrue(all(result[k]["log_loss"] is None for k in result))

    def test_invalid_and_non_finite_probabilities_are_ignored(self):
        rows = [
            {"outcome": "1", "model_probabilities": {"home_win": 120, "draw": 0, "away_win": 0}},
            {"outcome": "X", "model_probabilities": {"home_win": float("nan"), "draw": 50, "away_win": 50}},
            {"outcome": "2", "model_probabilities": {"home_win": 20, "draw": 30, "away_win": 50}},
        ]
        result = backtest.outcome_calibration_summary(rows)
        self.assertEqual(result["1"]["matches"], 1)
        self.assertEqual(result["X"]["matches"], 1)
        self.assertTrue(math.isfinite(result["X"]["brier_score"]))

    def test_perfectly_confident_wrong_prediction_has_finite_log_loss(self):
        rows = [{"outcome": "2", "model_probabilities": {"home_win": 100, "draw": 0, "away_win": 0}}]
        result = backtest.outcome_calibration_summary(rows)
        self.assertTrue(math.isfinite(result["2"]["log_loss"]))
        self.assertGreater(result["2"]["log_loss"], 30)


if __name__ == "__main__":
    unittest.main()
