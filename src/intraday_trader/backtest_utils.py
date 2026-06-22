import logging

import pandas as pd

# --- Logging Setup ---
logger = logging.getLogger(__name__)  # Create logger for this module
# --- End Logging Setup ---


# --- Helper function to safely get analysis results ---
def safe_get_analysis(analyzer):
    """
    Safely retrieves analysis results from an analyzer.
    This wrapper prevents exceptions that occur during the analysis retrieval
    process from crashing the program.
    """
    if analyzer is None:
        return {}
    try:
        return analyzer.get_analysis() or {}
    except Exception as e:
        logger.warning(f"{analyzer.__class__.__name__}.get_analysis() failed: {e}")
        return {}


# --- Helper function to analyze optimization results ---
def analyze_optimization_results(optimized_results, param_names, initial_cash: float):
    """
    Analyzes Backtrader optimization results and returns a pandas DataFrame.

    Args:
        optimized_results (list): The optimization results from cerebro.run().
        param_names (list): A list of strings containing the names of the
                            parameters being optimized in the strategy.

    Returns:
        pandas.DataFrame: A DataFrame containing the parameters and
                          performance metrics for each optimization run.
    """
    results_list = []
    if not optimized_results:
        logger.warning("Optimization returned no results.")
        return pd.DataFrame(results_list)

    for run_results in optimized_results:
        # Added a check to skip any None or empty result sets.
        if run_results is None or not run_results:
            logger.warning(
                "Skipping an empty or None result set from an optimization run."
            )
            error_row = dict.fromkeys(param_names, "ErrorRun")
            error_row.update(
                {
                    "Final Value": None,
                    "Total Trades": 0,
                    "Win Rate (%)": 0,
                    "Total Net PnL": 0,
                    "Sharpe Ratio": None,
                    "Max Drawdown (%)": None,
                    "Annualized Return (%)": None,
                    "Error": "Empty or None run result",
                }
            )
            results_list.append(error_row)
            continue  # Proceed to the next run_results

        # The inner list typically contains only one strategy instance.
        for strategy_instance in run_results:
            # Check if the strategy instance itself is None.
            if strategy_instance is None:
                logger.warning("Skipping a None strategy instance within a run result.")
                # Use default values, as parameter retrieval would fail.
                error_row = dict.fromkeys(param_names, "ErrorRun")
                error_row.update(
                    {
                        "Final Value": None,
                        "Total Trades": 0,
                        "Win Rate (%)": 0,
                        "Total Net PnL": 0,
                        "Sharpe Ratio": None,
                        "Max Drawdown (%)": None,
                        "Annualized Return (%)": None,
                        "Error": "None strategy instance",
                    }
                )
                results_list.append(error_row)
                continue  # Proceed to the next strategy_instance

            # --- Attempt to retrieve parameters ---
            try:
                params = strategy_instance.params
                param_values = {name: getattr(params, name) for name in param_names}
            except Exception as param_e:
                logger.error(
                    f"Could not retrieve parameters from strategy_instance: {param_e}"
                )
                param_values = dict.fromkeys(param_names, "ParamError")

            try:
                # Check if the strategy_instance has an 'analyzers' attribute.
                if not hasattr(strategy_instance, "analyzers"):
                    logger.warning(
                        "Strategy instance is missing the 'analyzers' attribute."
                    )
                    raise AttributeError("Strategy instance missing analyzers")

                trade_analyzer = strategy_instance.analyzers.getbyname("tradeanalyzer")
                sharpe_analyzer = strategy_instance.analyzers.getbyname("sharpe")
                drawdown_analyzer = strategy_instance.analyzers.getbyname("drawdown")
                returns_analyzer = strategy_instance.analyzers.getbyname("returns")

                # Use the safe helper function to get analysis results.
                trade_analysis = safe_get_analysis(trade_analyzer)
                sharpe_ratio = safe_get_analysis(sharpe_analyzer)
                drawdown = safe_get_analysis(drawdown_analyzer)
                returns = safe_get_analysis(returns_analyzer)

                total_trades = trade_analysis.get("total", {}).get("total", 0)
                won_trades = trade_analysis.get("won", {}).get("total", 0)
                win_rate = (won_trades / total_trades * 100) if total_trades > 0 else 0
                total_pnl = trade_analysis.get("pnl", {}).get("net", {}).get("total", 0)

                # Check if the 'broker' attribute exists.
                if hasattr(strategy_instance, "broker") and strategy_instance.broker:
                    final_value = strategy_instance.broker.getvalue()
                else:
                    logger.warning(
                        "Strategy instance missing 'broker' attribute. Calculating Final Value from PnL."
                    )
                    # 从已经计算出的交易分析器中获取总净盈亏
                    total_pnl = (
                        trade_analysis.get("pnl", {}).get("net", {}).get("total", 0)
                    )
                    # 手动计算最终市值
                    final_value = initial_cash + total_pnl

                result_row = {
                    **param_values,
                    "Final Value": final_value,
                    "Total Trades": total_trades,
                    "Win Rate (%)": win_rate,
                    "Total Net PnL": total_pnl,
                    "Sharpe Ratio": sharpe_ratio.get("sharperatio", None),
                    "Max Drawdown (%)": drawdown.get("max", {}).get("drawdown", None),
                    "Annualized Return (%)": returns.get("rnorm100", None),
                }
                results_list.append(result_row)

            except AttributeError as e:
                logger.error(
                    f"Error extracting analyzer data (AttributeError) for parameters: "
                    f"{param_values}. Error: {e}"
                )
                result_row = {
                    **param_values,
                    "Final Value": None,
                    "Total Trades": 0,
                    "Win Rate (%)": 0,
                    "Total Net PnL": 0,
                    "Sharpe Ratio": None,
                    "Max Drawdown (%)": None,
                    "Annualized Return (%)": None,
                    "Error": f"AttributeError: {e}",
                }
                results_list.append(result_row)

            except Exception as e:
                # Log a more detailed error, including the parameters.
                logger.error(
                    f"Error extracting analyzer data for parameters: {param_values}. "
                    f"Type: {type(e).__name__}, Error: {e}",
                    exc_info=True,
                )  # exc_info=True includes the full traceback in the log.
                result_row = {
                    **param_values,
                    "Final Value": None,
                    "Total Trades": 0,
                    "Win Rate (%)": 0,
                    "Total Net PnL": 0,
                    "Sharpe Ratio": None,
                    "Max Drawdown (%)": None,
                    "Annualized Return (%)": None,
                    "Error": f"{type(e).__name__}: {e}",
                }
                results_list.append(result_row)

    return pd.DataFrame(results_list)
