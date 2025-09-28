import json
import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


@dataclass
class ValidationResult:
    """Represents the result of a single validation test."""

    test_name: str
    passed: bool
    score: float  # A score between 0 and 1
    details: dict[str, Any] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    recommendations: list[str] = field(default_factory=list)


@dataclass
class TradeComparison:
    """Holds data for comparing a backtest trade with a live trade."""

    backtest_trade: dict[str, Any]
    live_trade: dict[str, Any]
    time_diff: float  # Time difference in seconds
    price_diff: float  # Price difference
    quantity_diff: float  # Quantity difference
    matched: bool


class ConsistencyTest(ABC):
    """Abstract base class for all consistency tests."""

    @abstractmethod
    def run_test(self, backtest_data: dict, live_data: dict) -> ValidationResult:
        """Runs the consistency test."""
        pass


class SignalConsistencyTest(ConsistencyTest):
    """Tests the consistency of trading signals."""

    def __init__(self, tolerance: float = 0.01):
        self.tolerance = tolerance

    def run_test(self, backtest_data: dict, live_data: dict) -> ValidationResult:
        """Tests the consistency of trading signals between backtest and live data."""
        backtest_signals = backtest_data.get("signals", [])
        live_signals = live_data.get("signals", [])

        if not backtest_signals or not live_signals:
            return ValidationResult(
                test_name="Signal Consistency",
                passed=False,
                score=0.0,
                details={"error": "Missing signal data"},
                warnings=["Cannot perform signal consistency test due to missing data"],
            )

        # Convert to DataFrame for easier analysis
        bt_df = pd.DataFrame(backtest_signals)
        live_df = pd.DataFrame(live_signals)

        # Align signals by time
        bt_df["timestamp"] = pd.to_datetime(bt_df["timestamp"])
        live_df["timestamp"] = pd.to_datetime(live_df["timestamp"])

        # Find overlapping time period
        start_time = max(bt_df["timestamp"].min(), live_df["timestamp"].min())
        end_time = min(bt_df["timestamp"].max(), live_df["timestamp"].max())

        bt_period = bt_df[
            (bt_df["timestamp"] >= start_time) & (bt_df["timestamp"] <= end_time)
        ]
        live_period = live_df[
            (live_df["timestamp"] >= start_time) & (live_df["timestamp"] <= end_time)
        ]

        if len(bt_period) == 0 or len(live_period) == 0:
            return ValidationResult(
                test_name="Signal Consistency",
                passed=False,
                score=0.0,
                details={"error": "No overlapping time period"},
                warnings=[
                    "Backtest and live data do not have overlapping time periods"
                ],
            )

        # Calculate signal match rate
        matched_signals = 0
        total_signals = 0
        signal_differences = []

        for _, bt_signal in bt_period.iterrows():
            # Find the closest timestamp in live data
            time_diffs = abs(live_period["timestamp"] - bt_signal["timestamp"])
            closest_idx = time_diffs.idxmin()

            if time_diffs[closest_idx] <= timedelta(minutes=5):  # 5-minute tolerance
                live_signal = live_period.loc[closest_idx]

                # Compare signal values
                bt_value = bt_signal.get("signal", 0)
                live_value = live_signal.get("signal", 0)

                diff = abs(bt_value - live_value)
                signal_differences.append(diff)

                if diff <= self.tolerance:
                    matched_signals += 1

                total_signals += 1

        if total_signals == 0:
            match_rate = 0.0
        else:
            match_rate = matched_signals / total_signals

        avg_difference = (
            np.mean(signal_differences) if signal_differences else float("inf")
        )
        max_difference = (
            np.max(signal_differences) if signal_differences else float("inf")
        )

        passed = match_rate >= 0.8 and avg_difference <= self.tolerance

        details = {
            "match_rate": match_rate,
            "total_compared": total_signals,
            "matched_signals": matched_signals,
            "avg_difference": avg_difference,
            "max_difference": max_difference,
            "tolerance": self.tolerance,
        }

        warnings = []
        recommendations = []

        if match_rate < 0.8:
            warnings.append(f"Low signal match rate: {match_rate:.2%}")
            recommendations.append("Check if strategy parameters are consistent.")

        if avg_difference > self.tolerance:
            warnings.append(
                f"Average signal difference exceeds tolerance: {avg_difference:.4f}"
            )
            recommendations.append(
                "Check consistency of data sources and calculation logic."
            )

        return ValidationResult(
            test_name="Signal Consistency",
            passed=passed,
            score=match_rate,
            details=details,
            warnings=warnings,
            recommendations=recommendations,
        )


class ExecutionConsistencyTest(ConsistencyTest):
    """Tests the consistency of trade execution."""

    def __init__(self, time_tolerance: int = 300, price_tolerance: float = 0.001):
        self.time_tolerance = time_tolerance  # seconds
        self.price_tolerance = price_tolerance  # price percentage

    def run_test(self, backtest_data: dict, live_data: dict) -> ValidationResult:
        """Tests the consistency of trade execution between backtest and live data."""
        backtest_trades = backtest_data.get("trades", [])
        live_trades = live_data.get("trades", [])

        if not backtest_trades or not live_trades:
            return ValidationResult(
                test_name="Execution Consistency",
                passed=False,
                score=0.0,
                details={"error": "Missing trade data"},
                warnings=[
                    "Cannot perform execution consistency test due to missing data"
                ],
            )

        # Match trades
        trade_comparisons = self._match_trades(backtest_trades, live_trades)

        if not trade_comparisons:
            return ValidationResult(
                test_name="Execution Consistency",
                passed=False,
                score=0.0,
                details={"error": "Could not match any trades"},
                warnings=["No matches found between backtest and live trades"],
            )

        # Analyze match results
        matched_count = sum(1 for comp in trade_comparisons if comp.matched)
        total_count = len(trade_comparisons)
        match_rate = matched_count / total_count if total_count > 0 else 0

        # Calculate execution quality metrics
        time_diffs = [comp.time_diff for comp in trade_comparisons if comp.matched]
        price_diffs = [
            abs(comp.price_diff) for comp in trade_comparisons if comp.matched
        ]
        quantity_diffs = [
            abs(comp.quantity_diff) for comp in trade_comparisons if comp.matched
        ]

        avg_time_diff = np.mean(time_diffs) if time_diffs else float("inf")
        avg_price_diff = np.mean(price_diffs) if price_diffs else float("inf")
        avg_quantity_diff = np.mean(quantity_diffs) if quantity_diffs else float("inf")

        max_time_diff = np.max(time_diffs) if time_diffs else float("inf")
        max_price_diff = np.max(price_diffs) if price_diffs else float("inf")

        # Calculate score
        time_score = max(0, 1 - avg_time_diff / self.time_tolerance)
        price_score = max(0, 1 - avg_price_diff / self.price_tolerance)
        overall_score = (match_rate + time_score + price_score) / 3

        passed = (
            match_rate >= 0.8
            and avg_time_diff <= self.time_tolerance
            and avg_price_diff <= self.price_tolerance
        )

        details = {
            "match_rate": match_rate,
            "matched_trades": matched_count,
            "total_trades": total_count,
            "avg_time_diff_seconds": avg_time_diff,
            "avg_price_diff": avg_price_diff,
            "avg_quantity_diff": avg_quantity_diff,
            "max_time_diff_seconds": max_time_diff,
            "max_price_diff": max_price_diff,
            "time_tolerance": self.time_tolerance,
            "price_tolerance": self.price_tolerance,
        }

        warnings = []
        recommendations = []

        if match_rate < 0.8:
            warnings.append(f"Low trade match rate: {match_rate:.2%}")
            recommendations.append("Check trade logic and trigger conditions.")

        if avg_time_diff > self.time_tolerance:
            warnings.append(
                f"Average execution time difference is too high: {avg_time_diff:.1f}s"
            )
            recommendations.append("Optimize trade execution speed.")

        if avg_price_diff > self.price_tolerance:
            warnings.append(
                f"Average price difference is too high: {avg_price_diff:.4f}"
            )
            recommendations.append("Check slippage control and order types.")

        return ValidationResult(
            test_name="Execution Consistency",
            passed=passed,
            score=overall_score,
            details=details,
            warnings=warnings,
            recommendations=recommendations,
        )

    def _match_trades(
        self, backtest_trades: list[dict], live_trades: list[dict]
    ) -> list[TradeComparison]:
        """Matches backtest and live trades."""
        comparisons = []

        for bt_trade in backtest_trades:
            bt_time = pd.to_datetime(bt_trade["timestamp"])
            bt_symbol = bt_trade.get("symbol", "")
            bt_side = bt_trade.get("side", "")

            best_match = None
            min_time_diff = float("inf")

            for live_trade in live_trades:
                live_time = pd.to_datetime(live_trade["timestamp"])
                live_symbol = live_trade.get("symbol", "")
                live_side = live_trade.get("side", "")

                # Check basic matching conditions
                if bt_symbol == live_symbol and bt_side == live_side:
                    time_diff = abs((live_time - bt_time).total_seconds())

                    if time_diff < min_time_diff and time_diff <= self.time_tolerance:
                        min_time_diff = time_diff
                        best_match = live_trade

            if best_match:
                price_diff = best_match.get("price", 0) - bt_trade.get("price", 0)
                quantity_diff = best_match.get("quantity", 0) - bt_trade.get(
                    "quantity", 0
                )

                matched = min_time_diff <= self.time_tolerance and abs(
                    price_diff
                ) <= self.price_tolerance * bt_trade.get("price", 1)

                comparison = TradeComparison(
                    backtest_trade=bt_trade,
                    live_trade=best_match,
                    time_diff=min_time_diff,
                    price_diff=price_diff,
                    quantity_diff=quantity_diff,
                    matched=matched,
                )

                comparisons.append(comparison)

        return comparisons


class PerformanceConsistencyTest(ConsistencyTest):
    """Tests the consistency of performance metrics."""

    def __init__(self, return_tolerance: float = 0.05, sharpe_tolerance: float = 0.2):
        self.return_tolerance = return_tolerance
        self.sharpe_tolerance = sharpe_tolerance

    def run_test(self, backtest_data: dict, live_data: dict) -> ValidationResult:
        """Tests the consistency of performance metrics."""
        bt_performance = backtest_data.get("performance", {})
        live_performance = live_data.get("performance", {})

        if not bt_performance or not live_performance:
            return ValidationResult(
                test_name="Performance Consistency",
                passed=False,
                score=0.0,
                details={"error": "Missing performance data"},
                warnings=["Cannot perform performance consistency test"],
            )

        # Compare key performance indicators
        metrics_comparison = {}

        # Compare total return
        bt_return = bt_performance.get("total_return", 0)
        live_return = live_performance.get("total_return", 0)
        return_diff = abs(bt_return - live_return)

        metrics_comparison["total_return"] = {
            "backtest": bt_return,
            "live": live_return,
            "difference": return_diff,
            "relative_diff": (
                return_diff / abs(bt_return) if bt_return != 0 else float("inf")
            ),
            "within_tolerance": return_diff <= self.return_tolerance,
        }

        # Compare Sharpe ratio
        bt_sharpe = bt_performance.get("sharpe_ratio", 0)
        live_sharpe = live_performance.get("sharpe_ratio", 0)
        sharpe_diff = abs(bt_sharpe - live_sharpe)

        metrics_comparison["sharpe_ratio"] = {
            "backtest": bt_sharpe,
            "live": live_sharpe,
            "difference": sharpe_diff,
            "relative_diff": (
                sharpe_diff / abs(bt_sharpe) if bt_sharpe != 0 else float("inf")
            ),
            "within_tolerance": sharpe_diff <= self.sharpe_tolerance,
        }

        # Compare max drawdown
        bt_drawdown = bt_performance.get("max_drawdown", 0)
        live_drawdown = live_performance.get("max_drawdown", 0)
        drawdown_diff = abs(bt_drawdown - live_drawdown)

        metrics_comparison["max_drawdown"] = {
            "backtest": bt_drawdown,
            "live": live_drawdown,
            "difference": drawdown_diff,
            "relative_diff": (
                drawdown_diff / abs(bt_drawdown) if bt_drawdown != 0 else float("inf")
            ),
            "within_tolerance": drawdown_diff <= 0.05,  # 5% tolerance
        }

        # Compare win rate
        bt_winrate = bt_performance.get("win_rate", 0)
        live_winrate = live_performance.get("win_rate", 0)
        winrate_diff = abs(bt_winrate - live_winrate)

        metrics_comparison["win_rate"] = {
            "backtest": bt_winrate,
            "live": live_winrate,
            "difference": winrate_diff,
            "relative_diff": (
                winrate_diff / abs(bt_winrate) if bt_winrate != 0 else float("inf")
            ),
            "within_tolerance": winrate_diff <= 0.1,  # 10% tolerance
        }

        # Calculate overall consistency score
        consistent_metrics = sum(
            1 for metric in metrics_comparison.values() if metric["within_tolerance"]
        )
        total_metrics = len(metrics_comparison)
        consistency_score = consistent_metrics / total_metrics

        passed = consistency_score >= 0.75  # At least 75% of metrics must be consistent

        warnings = []
        recommendations = []

        for metric_name, metric_data in metrics_comparison.items():
            if not metric_data["within_tolerance"]:
                warnings.append(
                    f"{metric_name} difference is too high: {metric_data['difference']:.4f}"
                )

                if metric_name == "total_return":
                    recommendations.append(
                        "Check transaction costs and slippage settings."
                    )
                elif metric_name == "sharpe_ratio":
                    recommendations.append("Check risk management and position sizing.")
                elif metric_name == "max_drawdown":
                    recommendations.append(
                        "Check implementation of stop-loss strategy."
                    )
                elif metric_name == "win_rate":
                    recommendations.append(
                        "Check signal filtering and execution logic."
                    )

        return ValidationResult(
            test_name="Performance Consistency",
            passed=passed,
            score=consistency_score,
            details={
                "metrics_comparison": metrics_comparison,
                "consistent_metrics": consistent_metrics,
                "total_metrics": total_metrics,
                "consistency_score": consistency_score,
            },
            warnings=warnings,
            recommendations=recommendations,
        )


class ConsistencyValidator:
    """Main class for the consistency validator."""

    def __init__(self):
        self.tests: list[ConsistencyTest] = []
        self.validation_history: list[dict] = []

        # Register default tests
        self.register_test(SignalConsistencyTest())
        self.register_test(ExecutionConsistencyTest())
        self.register_test(PerformanceConsistencyTest())

        logger.info("Consistency validator initialized.")

    def register_test(self, test: ConsistencyTest):
        """Registers a test."""
        self.tests.append(test)
        logger.info(f"Registered test: {test.__class__.__name__}")

    def validate_consistency(
        self,
        backtest_data: dict,
        live_data: dict,
        test_names: list[str] | None = None,
    ) -> dict[str, ValidationResult]:
        """Performs consistency validation."""
        logger.info("Starting consistency validation...")

        results = {}

        for test in self.tests:
            test_name = test.__class__.__name__

            # If test names are specified, only run those tests
            if test_names and test_name not in test_names:
                continue

            try:
                result = test.run_test(backtest_data, live_data)
                results[test_name] = result

                logger.info(
                    f"Test completed: {result.test_name} - {'Passed' if result.passed else 'Failed'} (Score: {result.score:.2f})"
                )

            except Exception as e:
                logger.error(f"Test execution failed {test_name}: {e}")
                results[test_name] = ValidationResult(
                    test_name=test_name,
                    passed=False,
                    score=0.0,
                    details={"error": str(e)},
                    warnings=[f"Test execution exception: {e}"],
                )

        # Record validation history
        validation_record = {
            "timestamp": datetime.now(),
            "results": results,
            "overall_score": self._calculate_overall_score(results),
            "passed_tests": sum(1 for r in results.values() if r.passed),
            "total_tests": len(results),
        }

        self.validation_history.append(validation_record)

        logger.info(
            f"Consistency validation finished. Overall score: {validation_record['overall_score']:.2f}"
        )
        return results

    def _calculate_overall_score(self, results: dict[str, ValidationResult]) -> float:
        """Calculates the overall score."""
        if not results:
            return 0.0

        total_score = sum(result.score for result in results.values())
        return total_score / len(results)

    def generate_validation_report(self, results: dict[str, ValidationResult]) -> dict:
        """Generates a validation report."""
        overall_score = self._calculate_overall_score(results)
        passed_tests = sum(1 for r in results.values() if r.passed)
        total_tests = len(results)

        # Collect all warnings and recommendations
        all_warnings = []
        all_recommendations = []

        for result in results.values():
            all_warnings.extend(result.warnings)
            all_recommendations.extend(result.recommendations)

        # Deduplicate
        all_warnings = list(set(all_warnings))
        all_recommendations = list(set(all_recommendations))

        # Determine overall status
        if overall_score >= 0.8 and passed_tests == total_tests:
            status = "Excellent"
        elif overall_score >= 0.6 and passed_tests >= total_tests * 0.75:
            status = "Good"
        elif overall_score >= 0.4:
            status = "Needs Improvement"
        else:
            status = "Serious Issues"

        report = {
            "timestamp": datetime.now(),
            "overall_status": status,
            "overall_score": overall_score,
            "passed_tests": passed_tests,
            "total_tests": total_tests,
            "pass_rate": passed_tests / total_tests if total_tests > 0 else 0,
            "test_results": {
                name: {
                    "passed": result.passed,
                    "score": result.score,
                    "warnings_count": len(result.warnings),
                    "recommendations_count": len(result.recommendations),
                }
                for name, result in results.items()
            },
            "summary_warnings": all_warnings,
            "summary_recommendations": all_recommendations,
            "detailed_results": results,
        }

        return report

    def export_validation_report(
        self, results: dict[str, ValidationResult], file_path: str
    ):
        """Exports the validation report."""
        report = self.generate_validation_report(results)

        # Convert to a serializable format
        serializable_report = self._make_serializable(report)

        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(serializable_report, f, indent=2, ensure_ascii=False, default=str)

        logger.info(f"Validation report exported to: {file_path}")

    def _make_serializable(self, obj):
        """Converts an object to a serializable format."""
        if isinstance(obj, dict):
            return {k: self._make_serializable(v) for k, v in obj.items()}
        elif isinstance(obj, list):
            return [self._make_serializable(item) for item in obj]
        elif isinstance(obj, ValidationResult):
            return {
                "test_name": obj.test_name,
                "passed": obj.passed,
                "score": obj.score,
                "details": obj.details,
                "warnings": obj.warnings,
                "recommendations": obj.recommendations,
            }
        elif isinstance(obj, (datetime, pd.Timestamp)):
            return obj.isoformat()
        elif isinstance(obj, np.ndarray):
            return obj.tolist()
        elif isinstance(obj, (np.integer, np.floating)):
            return obj.item()
        else:
            return obj

    def get_validation_history(self, days: int = 30) -> list[dict]:
        """Gets the validation history."""
        cutoff_date = datetime.now() - timedelta(days=days)
        return [
            record
            for record in self.validation_history
            if record["timestamp"] >= cutoff_date
        ]


if __name__ == "__main__":
    # Create validator
    validator = ConsistencyValidator()

    # Mock data
    backtest_data = {
        "signals": [
            {"timestamp": "2024-01-01 10:00:00", "signal": 1.0},
            {"timestamp": "2024-01-01 11:00:00", "signal": -1.0},
        ],
        "trades": [
            {
                "timestamp": "2024-01-01 10:01:00",
                "symbol": "AAPL",
                "side": "buy",
                "quantity": 100,
                "price": 150.0,
            },
            {
                "timestamp": "2024-01-01 11:01:00",
                "symbol": "AAPL",
                "side": "sell",
                "quantity": 100,
                "price": 151.0,
            },
        ],
        "performance": {
            "total_return": 0.05,
            "sharpe_ratio": 1.2,
            "max_drawdown": -0.02,
            "win_rate": 0.6,
        },
    }

    live_data = {
        "signals": [
            {"timestamp": "2024-01-01 10:00:30", "signal": 0.98},
            {"timestamp": "2024-01-01 11:00:30", "signal": -0.95},
        ],
        "trades": [
            {
                "timestamp": "2024-01-01 10:01:30",
                "symbol": "AAPL",
                "side": "buy",
                "quantity": 100,
                "price": 150.05,
            },
            {
                "timestamp": "2024-01-01 11:01:30",
                "symbol": "AAPL",
                "side": "sell",
                "quantity": 100,
                "price": 150.95,
            },
        ],
        "performance": {
            "total_return": 0.048,
            "sharpe_ratio": 1.15,
            "max_drawdown": -0.025,
            "win_rate": 0.58,
        },
    }

    # Perform validation
    results = validator.validate_consistency(backtest_data, live_data)

    # Generate report
    report = validator.generate_validation_report(results)
    print(json.dumps(report, indent=2, ensure_ascii=False, default=str))

    # Export report
    validator.export_validation_report(results, "validation_report.json")
