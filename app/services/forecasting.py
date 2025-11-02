"""Domain utilities for the forecasting champion-selection pipeline."""

from __future__ import annotations

import asyncio
import json
import logging
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import date
from statistics import mean, median
from uuid import UUID, uuid4
from typing import Any, Iterable, Sequence

import asyncpg
import numpy as np
import pandas as pd

from app.config import get_settings

logger = logging.getLogger(__name__)


EPSILON = 1e-9
SEASON_LENGTH = 12
TIE_TOLERANCE = 1.0  # percentage points of MAPE considered indistinguishable
TSB_ALPHA_D = 0.15
TSB_ALPHA_P = 0.1
PREDICTION_INTERVAL_LEVEL = 80

DEMAND_CLASS_LABELS = ("SMOOTH", "ERRATIC", "INTERMITTENT", "LUMPY")


class ForecastingServiceError(RuntimeError):
    """Raised when the forecasting service cannot complete the requested task."""


class MissingDependencyError(ForecastingServiceError):
    """Raised when optional runtime dependencies are unavailable."""


class DataUnavailableError(ForecastingServiceError):
    """Raised when the required warehouse tables are missing or empty."""


@dataclass(slots=True)
class ItemClassificationResult:
    item_id: str
    demand_class: str
    adi: float | None
    cv2: float | None
    obsolescence_flag: bool


@dataclass(slots=True)
class MethodMetricRow:
    item_id: str
    method: str
    horizon: int
    mape: float | None
    rmse: float | None
    beats_baseline: bool
    fold_count: int
    mape_denominator: int


@dataclass(slots=True)
class ChampionRow:
    item_id: str
    horizon: int
    method: str
    mape: float | None
    rmse: float | None
    beats_baseline: bool
    needs_review: bool
    demand_class: str
    obsolescence_flag: bool


@dataclass(slots=True)
class EvaluationBundle:
    metrics: list[MethodMetricRow]
    champions: list[ChampionRow]
    items_evaluated: int
    items_with_champion: int
    items_beating_baseline: int
    champion_counts: Counter[str]


def _ensure_statsforecast() -> tuple[Any, ...]:
    try:
        from statsforecast import StatsForecast
        from statsforecast.models import ETS, CrostonSBA, SeasonalNaive, TSB
    except ImportError as exc:  # pragma: no cover - optional dependency
        raise MissingDependencyError(
            "statsforecast is required for champion selection. Install dependencies with "
            "`pip install -r requirements.txt`."
        ) from exc

    return StatsForecast, ETS, CrostonSBA, SeasonalNaive, TSB


def _nan_to_none(value: float | None) -> float | None:
    if value is None:
        return None
    if isinstance(value, float) and (np.isnan(value) or np.isinf(value)):
        return None
    return value


def _locate_interval_column(columns: Iterable[str], base: str, side: str, level: int) -> str | None:
    """Return the column name that matches a StatsForecast interval output."""

    candidates = [
        f"{base}-{side}-{level}",
        f"{base}_{side}_{level}",
        f"{base.lower()}-{side}-{level}",
        f"{base.lower()}_{side}_{level}",
    ]

    column_set = set(columns)
    for candidate in candidates:
        if candidate in column_set:
            return candidate

    target = f"{base}-{side}-{level}".replace("_", "-").lower()
    for column in columns:
        normalized = column.replace("_", "-").lower()
        if normalized == target:
            return column

    return None


def _zero_run_lengths(values: Sequence[float]) -> list[int]:
    runs: list[int] = []
    current = 0
    for value in values:
        if abs(value) <= EPSILON:
            current += 1
        else:
            if current:
                runs.append(current)
            current = 0
    if current:
        runs.append(current)
    return runs


def _obsolescence_flag(demand: Sequence[float]) -> bool:
    if not demand:
        return False

    recent_window = 12
    baseline_window = 24

    zero_runs = _zero_run_lengths(demand)
    if len(demand) >= recent_window * 2 and zero_runs:
        recent_segment = demand[-recent_window:]
        historical_segment = demand[:-recent_window]
        recent_runs = _zero_run_lengths(recent_segment)
        historic_runs = _zero_run_lengths(historical_segment)
        if recent_runs and historic_runs:
            if median(recent_runs) >= median(historic_runs) + 2:
                return True

    indicator = np.array([1 if value > EPSILON else 0 for value in demand], dtype=float)
    if len(indicator) >= recent_window + baseline_window:
        recent = indicator[-recent_window:]
        baseline = indicator[-(recent_window + baseline_window):-recent_window]
        baseline_prob = baseline.mean() if baseline.size else None
        recent_prob = recent.mean() if recent.size else None
        if baseline_prob and recent_prob is not None and baseline_prob > 0:
            drop = baseline_prob - recent_prob
            if drop >= 0.4 * baseline_prob:
                return True

    alpha = 0.3
    ewma = []
    prev = indicator[0]
    ewma.append(prev)
    for value in indicator[1:]:
        prev = alpha * value + (1 - alpha) * prev
        ewma.append(prev)
    if len(ewma) >= 12:
        trailing = ewma[-6:]
        prior = ewma[-12:-6]
        if prior and trailing and mean(trailing) < mean(prior) - 0.05:
            return True

    return False


def _classify_item(item_id: str, demands: Sequence[float]) -> ItemClassificationResult:
    total_periods = len(demands)
    non_zero = [value for value in demands if value > EPSILON]

    if total_periods == 0:
        return ItemClassificationResult(
            item_id=item_id,
            demand_class="NO_HISTORY",
            adi=None,
            cv2=None,
            obsolescence_flag=False,
        )

    if not non_zero:
        return ItemClassificationResult(
            item_id=item_id,
            demand_class="OBSOLETE",
            adi=float("inf"),
            cv2=None,
            obsolescence_flag=True,
        )

    adi = total_periods / max(1, len(non_zero))
    if len(non_zero) > 1:
        nz_array = np.array(non_zero, dtype=float)
        nz_mean = nz_array.mean()
        if nz_mean > EPSILON:
            cv2 = float(np.var(nz_array, ddof=1) / (nz_mean**2))
        else:
            cv2 = None
    else:
        cv2 = None

    if adi < 1.32:
        demand_class = "SMOOTH" if (cv2 or 0) < 0.49 else "ERRATIC"
    else:
        demand_class = "INTERMITTENT" if (cv2 or 0) < 0.49 else "LUMPY"

    obs_flag = _obsolescence_flag(demands)

    return ItemClassificationResult(
        item_id=item_id,
        demand_class=demand_class,
        adi=_nan_to_none(float(adi)),
        cv2=_nan_to_none(float(cv2) if cv2 is not None else None),
        obsolescence_flag=obs_flag,
    )


def _classify_series(df: pd.DataFrame) -> list[ItemClassificationResult]:
    results: list[ItemClassificationResult] = []
    for item_id, group in df.groupby("item_id"):
        demands = group["demand"].tolist()
        result = _classify_item(str(item_id), demands)
        results.append(result)
    return results


def _candidate_methods(demand_class: str, obsolescence_flag: bool) -> list[str]:
    if obsolescence_flag:
        return ["CrostonSBA", "TSB"]
    if demand_class in {"INTERMITTENT", "LUMPY"}:
        return ["CrostonSBA", "ETS"]
    return ["ETS"]


def _simpler_preference(demand_class: str) -> list[str]:
    if demand_class in {"INTERMITTENT", "LUMPY"}:
        return ["CrostonSBA", "ETS", "TSB"]
    return ["ETS", "CrostonSBA", "TSB"]


def _compute_metrics(cv_frame: pd.DataFrame, horizons: Sequence[int]) -> dict[str, dict[int, MethodMetricRow]]:
    metrics: dict[str, dict[int, MethodMetricRow]] = defaultdict(dict)

    if cv_frame.empty:
        return metrics

    metric_groups = cv_frame.groupby(["model", "h"], sort=False)

    for (model_name, horizon), rows in metric_groups:
        if horizon not in horizons:
            continue
        y_true = rows["y"].to_numpy(dtype=float)
        y_hat = rows["y_hat"].to_numpy(dtype=float)
        errors = y_hat - y_true
        rmse = float(np.sqrt(np.mean(np.square(errors)))) if len(errors) else None

        mask = np.abs(y_true) > EPSILON
        mape = None
        if mask.any():
            mape = float(np.mean(np.abs((y_true[mask] - y_hat[mask]) / y_true[mask])) * 100)

        metrics[model_name][int(horizon)] = MethodMetricRow(
            item_id="",
            method=str(model_name),
            horizon=int(horizon),
            mape=_nan_to_none(mape),
            rmse=_nan_to_none(rmse),
            beats_baseline=False,
            fold_count=len(rows),
            mape_denominator=int(mask.sum()),
        )

    return metrics


def _select_champion(
    item_id: str,
    demand_class: str,
    obsolescence_flag: bool,
    candidate_metrics: dict[str, dict[int, MethodMetricRow]],
    baseline_metrics: dict[int, MethodMetricRow],
    horizons: Sequence[int],
) -> tuple[list[ChampionRow], list[MethodMetricRow], Counter[str], int]:
    champions: list[ChampionRow] = []
    metrics_output: list[MethodMetricRow] = []
    champion_counter: Counter[str] = Counter()
    all_guardrails_met = True

    preference_order = _simpler_preference(demand_class)

    for horizon in horizons:
        horizon_candidates: list[MethodMetricRow] = []
        for method, horizon_map in candidate_metrics.items():
            metric = horizon_map.get(horizon)
            if metric is None:
                continue
            horizon_candidates.append(
                MethodMetricRow(
                    item_id=item_id,
                    method=method,
                    horizon=horizon,
                    mape=metric.mape,
                    rmse=metric.rmse,
                    beats_baseline=False,
                    fold_count=metric.fold_count,
                    mape_denominator=metric.mape_denominator,
                )
            )

        if not horizon_candidates:
            all_guardrails_met = False
            continue

        metrics_output.extend(horizon_candidates)

        best_metric = min(
            horizon_candidates,
            key=lambda metric: (
                metric.mape if metric.mape is not None else float("inf"),
                metric.rmse if metric.rmse is not None else float("inf"),
            ),
        )

        for metric in horizon_candidates:
            if metric is best_metric:
                continue
            if best_metric.mape is None or metric.mape is None:
                continue
            if abs(best_metric.mape - metric.mape) <= TIE_TOLERANCE:

                def _preference_rank(name: str) -> int:
                    try:
                        return preference_order.index(name)
                    except ValueError:
                        return len(preference_order)

                if _preference_rank(metric.method) < _preference_rank(best_metric.method):
                    best_metric = metric

        baseline = baseline_metrics.get(horizon)
        beats_baseline = False
        needs_review = False
        if baseline is not None:
            metrics_output.append(
                MethodMetricRow(
                    item_id=item_id,
                    method=baseline.method,
                    horizon=horizon,
                    mape=baseline.mape,
                    rmse=baseline.rmse,
                    beats_baseline=False,
                    fold_count=baseline.fold_count,
                    mape_denominator=baseline.mape_denominator,
                )
            )
            if best_metric.mape is not None and baseline.mape is not None:
                beats_baseline = best_metric.mape + 1e-6 < baseline.mape
            elif best_metric.rmse is not None and baseline.rmse is not None:
                beats_baseline = best_metric.rmse + 1e-6 < baseline.rmse
            needs_review = not beats_baseline
        else:
            needs_review = True
            all_guardrails_met = False

        if not beats_baseline:
            all_guardrails_met = False
        best_metric.beats_baseline = beats_baseline

        champions.append(
            ChampionRow(
                item_id=item_id,
                horizon=horizon,
                method=best_metric.method,
                mape=best_metric.mape,
                rmse=best_metric.rmse,
                beats_baseline=beats_baseline,
                needs_review=needs_review,
                demand_class=demand_class,
                obsolescence_flag=obsolescence_flag,
            )
        )
        champion_counter[best_metric.method] += 1

    guardrail_flag = 1 if champions and all_guardrails_met else 0

    return champions, metrics_output, champion_counter, guardrail_flag


def _evaluate_items(
    series_df: pd.DataFrame,
    classifications: dict[str, ItemClassificationResult],
    horizons: Sequence[int],
    step_size: int,
    n_windows: int | None,
) -> EvaluationBundle:
    StatsForecast, ETS, CrostonSBA, SeasonalNaive, TSB = _ensure_statsforecast()

    metrics: list[MethodMetricRow] = []
    champions: list[ChampionRow] = []
    champion_counter: Counter[str] = Counter()
    items_with_champion = 0
    items_beating_baseline = 0

    max_horizon = max(horizons)

    for item_id, group in series_df.groupby("item_id"):
        demand_series = group.sort_values("period_start_date")
        if len(demand_series) < max(3, max_horizon + 1):
            logger.warning("Skipping item %s due to insufficient history", item_id)
            continue

        classification = classifications.get(str(item_id))
        if classification is None:
            # Compute on the fly if prep step was skipped.
            classification = _classify_item(str(item_id), demand_series["demand"].tolist())

        candidate_names = _candidate_methods(classification.demand_class, classification.obsolescence_flag)

        model_instances: list[Any] = []
        for name in candidate_names:
            if name == "ETS":
                model_instances.append(ETS(season_length=SEASON_LENGTH))
            elif name == "CrostonSBA":
                model_instances.append(CrostonSBA())
            elif name == "TSB":
                model_instances.append(TSB(alpha_d=TSB_ALPHA_D, alpha_p=TSB_ALPHA_P))

        baseline_model = SeasonalNaive(season_length=SEASON_LENGTH)
        models_for_cv = model_instances + [baseline_model]

        df = pd.DataFrame(
            {
                "unique_id": str(item_id),
                "ds": pd.to_datetime(demand_series["period_start_date"]),
                "y": demand_series["demand"].astype(float),
            }
        )

        try:
            sf = StatsForecast(models=models_for_cv, freq="MS", n_jobs=1)
            cross_validation_kwargs: dict[str, Any] = {
                "df": df,
                "step_size": step_size,
            }
            if n_windows is not None:
                cross_validation_kwargs["n_windows"] = n_windows

            cv_frame = sf.cross_validation(h=max_horizon, **cross_validation_kwargs)
            cv_frame = cv_frame.reset_index()
        except Exception as exc:  # pragma: no cover - upstream library behaviour
            logger.exception("StatsForecast CV failed for item %s: %s", item_id, exc)
            continue

        model_columns = [
            column
            for column in cv_frame.columns
            if column not in {"unique_id", "ds", "cutoff", "y"}
        ]
        if not model_columns:
            logger.warning("Skipping item %s: cross-validation returned no model columns", item_id)
            continue

        cv_long = cv_frame.melt(
            id_vars=["unique_id", "ds", "cutoff", "y"],
            value_vars=model_columns,
            var_name="model",
            value_name="y_hat",
        )

        cv_long["h"] = (
            (cv_long["ds"].dt.year - cv_long["cutoff"].dt.year) * 12
            + (cv_long["ds"].dt.month - cv_long["cutoff"].dt.month)
        )
        cv_long = cv_long[cv_long["h"] > 0]

        metric_map = _compute_metrics(cv_long, horizons)

        candidate_metric_map = {
            name: horizon_map
            for name, horizon_map in metric_map.items()
            if name in candidate_names
        }
        if not candidate_metric_map:
            continue

        horizon_champions, horizon_metrics, champion_counts, guardrail_hits = _select_champion(
            item_id=str(item_id),
            demand_class=classification.demand_class,
            obsolescence_flag=classification.obsolescence_flag,
            candidate_metrics=candidate_metric_map,
            baseline_metrics=metric_map.get("SeasonalNaive", {}),
            horizons=horizons,
        )

        if horizon_champions:
            champions.extend(horizon_champions)
            items_with_champion += 1
            items_beating_baseline += guardrail_hits
        metrics.extend(horizon_metrics)
        champion_counter.update(champion_counts)

    items_evaluated = series_df["item_id"].nunique()

    return EvaluationBundle(
        metrics=metrics,
        champions=champions,
        items_evaluated=items_evaluated,
        items_with_champion=items_with_champion,
        items_beating_baseline=items_beating_baseline,
        champion_counts=champion_counter,
    )


class ForecastingService:
    """High-level orchestration helper for champion selection and forecasting."""

    def __init__(self, connection: asyncpg.Connection):
        self.connection = connection

    async def _fetch_series(self, item_ids: Sequence[str] | None = None) -> pd.DataFrame:
        filters = ""
        params: list[Any] = []
        if item_ids:
            filters = "WHERE item_id = ANY($1::text[])"
            params.append(list(item_ids))

        query = f"""
            SELECT item_id, period_start_date, demand
            FROM core.item_month_demand
            {filters}
            ORDER BY item_id, period_start_date
        """

        try:
            records = await self.connection.fetch(query, *params)
        except asyncpg.exceptions.UndefinedTableError as exc:  # pragma: no cover - depends on DB
            raise DataUnavailableError(
                "core.item_month_demand table is unavailable. Apply the analytics build or "
                "load the dev stub migration (migration/sql/local_forecast_stub.sql)."
            ) from exc

        if not records:
            raise DataUnavailableError(
                "core.item_month_demand contained no rows; provide history before running the pipeline."
            )

        frame = pd.DataFrame([dict(record) for record in records])
        frame["item_id"] = frame["item_id"].astype(str)
        frame["period_start_date"] = pd.to_datetime(frame["period_start_date"])
        frame["demand"] = frame["demand"].astype(float)
        return frame

    async def prepare_item_features(self) -> dict[str, Any]:
        frame = await self._fetch_series()
        classifications = await asyncio.to_thread(_classify_series, frame)

        await self._persist_classifications(classifications)

        intermittent_count = sum(
            1 for result in classifications if result.demand_class in {"INTERMITTENT", "LUMPY"}
        )
        obsolescence_count = sum(result.obsolescence_flag for result in classifications)

        return {
            "items_processed": len(classifications),
            "intermittent_items": intermittent_count,
            "obsolescence_candidates": obsolescence_count,
        }

    async def train_and_select(
        self,
        horizons: Sequence[int],
        step_size: int,
        n_windows: int | None,
    ) -> tuple[UUID, EvaluationBundle]:
        frame = await self._fetch_series()
        classifications = await self._load_classifications()

        evaluation = await asyncio.to_thread(
            _evaluate_items,
            frame,
            classifications,
            horizons,
            step_size,
            n_windows,
        )

        run_id = uuid4()

        await self._persist_backtest_metrics(run_id, evaluation.metrics)
        await self._persist_champions(run_id, evaluation.champions)
        await self._record_run(run_id, horizons, evaluation)

        return run_id, evaluation

    async def generate_forecasts(
        self,
        run_id: UUID,
        horizons: Sequence[int],
    ) -> dict[str, Any]:
        champions = await self._load_champions(run_id)
        if not champions:
            raise ForecastingServiceError(
                f"No champions found for run {run_id}. Execute train-select before forecasting."
            )

        item_ids = sorted({row.item_id for row in champions})
        frame = await self._fetch_series(item_ids=item_ids)

        forecast_rows = await asyncio.to_thread(
            self._build_forecasts,
            frame,
            champions,
            horizons,
        )

        await self._persist_forecasts(run_id, forecast_rows)
        await self._update_run_forecast_metadata(run_id, forecast_rows)

        unique_periods = {row[1] for row in forecast_rows}

        return {
            "items_forecasted": len(item_ids),
            "forecast_rows": len(forecast_rows),
            "forecast_months": len(unique_periods),
        }

    async def _persist_classifications(self, classifications: Iterable[ItemClassificationResult]) -> None:
        rows = [
            (
                result.item_id,
                result.demand_class,
                result.adi,
                result.cv2,
                result.obsolescence_flag,
            )
            for result in classifications
        ]

        if not rows:
            return

        query = """
            INSERT INTO analytics.item_classification (item_id, demand_class, adi, cv2, obsolescence_flag, updated_at)
            VALUES ($1, $2, $3, $4, $5, now())
            ON CONFLICT (item_id) DO UPDATE
            SET demand_class = EXCLUDED.demand_class,
                adi = EXCLUDED.adi,
                cv2 = EXCLUDED.cv2,
                obsolescence_flag = EXCLUDED.obsolescence_flag,
                updated_at = now()
        """

        try:
            await self.connection.executemany(query, rows)
        except asyncpg.PostgresError as exc:  # pragma: no cover - depends on DB
            raise ForecastingServiceError("Failed to persist item classifications.") from exc

    async def _persist_backtest_metrics(self, run_id: UUID, metrics: Iterable[MethodMetricRow]) -> None:
        rows = [
            (
                run_id,
                metric.item_id,
                metric.horizon,
                metric.method,
                metric.mape,
                metric.rmse,
                metric.beats_baseline,
                metric.fold_count,
                metric.mape_denominator,
            )
            for metric in metrics
        ]

        if not rows:
            return

        query = """
            INSERT INTO analytics.backtest_metrics (
                run_id,
                item_id,
                horizon,
                method,
                mape,
                rmse,
                beats_baseline,
                fold_count,
                mape_denominator_count,
                decided_at
            )
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, now())
        """

        try:
            await self.connection.executemany(query, rows)
        except asyncpg.PostgresError as exc:  # pragma: no cover - depends on DB
            raise ForecastingServiceError("Failed to persist backtest metrics.") from exc

    async def _persist_champions(self, run_id: UUID, champions: Iterable[ChampionRow]) -> None:
        rows = [
            (
                run_id,
                row.item_id,
                row.horizon,
                row.method,
                row.mape,
                row.rmse,
                row.beats_baseline,
                row.needs_review,
                row.demand_class,
                row.obsolescence_flag,
            )
            for row in champions
        ]

        if not rows:
            return

        query = """
            INSERT INTO analytics.item_champion (
                run_id,
                item_id,
                horizon,
                champion_method,
                mape,
                rmse,
                beats_baseline,
                needs_review,
                demand_class,
                obsolescence_flag,
                decided_at
            )
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, now())
        """

        try:
            await self.connection.executemany(query, rows)
        except asyncpg.PostgresError as exc:  # pragma: no cover - depends on DB
            raise ForecastingServiceError("Failed to persist champion selections.") from exc

    async def _record_run(self, run_id: UUID, horizons: Sequence[int], evaluation: EvaluationBundle) -> None:
        query = """
            INSERT INTO analytics.forecast_run (
                run_id,
                horizons,
                status,
                items_evaluated,
                items_with_champion,
                items_beating_baseline,
                champion_counts,
                created_at,
                updated_at
            )
            VALUES ($1, $2, 'TRAINED', $3, $4, $5, $6::jsonb, now(), now())
        """

        champion_counts = {method: count for method, count in evaluation.champion_counts.items()}
        champion_counts_json = json.dumps(champion_counts)

        try:
            await self.connection.execute(
                query,
                run_id,
                list(sorted(horizons)),
                evaluation.items_evaluated,
                evaluation.items_with_champion,
                evaluation.items_beating_baseline,
                champion_counts_json,
            )
        except asyncpg.PostgresError as exc:  # pragma: no cover - depends on DB
            raise ForecastingServiceError("Failed to record forecast run metadata.") from exc

    async def _load_classifications(self) -> dict[str, ItemClassificationResult]:
        try:
            records = await self.connection.fetch(
                """
                SELECT item_id, demand_class, adi, cv2, obsolescence_flag
                FROM analytics.item_classification
                """
            )
        except asyncpg.exceptions.UndefinedTableError:
            return {}

        classifications: dict[str, ItemClassificationResult] = {}
        for record in records:
            classifications[str(record["item_id"])] = ItemClassificationResult(
                item_id=str(record["item_id"]),
                demand_class=str(record["demand_class"]),
                adi=_nan_to_none(float(record["adi"])) if record["adi"] is not None else None,
                cv2=_nan_to_none(float(record["cv2"])) if record["cv2"] is not None else None,
                obsolescence_flag=bool(record["obsolescence_flag"]),
            )
        return classifications

    async def _load_champions(self, run_id: UUID) -> list[ChampionRow]:
        try:
            records = await self.connection.fetch(
                """
                SELECT item_id, horizon, champion_method, mape, rmse, beats_baseline, needs_review, demand_class, obsolescence_flag
                FROM analytics.item_champion
                WHERE run_id = $1
                ORDER BY item_id, horizon
                """,
                run_id,
            )
        except asyncpg.exceptions.UndefinedTableError as exc:  # pragma: no cover - depends on DB
            raise ForecastingServiceError(
                "analytics.item_champion table is missing; run the forecasting stub migration."
            ) from exc

        champions: list[ChampionRow] = []
        for record in records:
            demand_class = record["demand_class"]
            demand_class_str = str(demand_class) if demand_class is not None else "UNKNOWN"
            champions.append(
                ChampionRow(
                    item_id=str(record["item_id"]),
                    horizon=int(record["horizon"]),
                    method=str(record["champion_method"]),
                    mape=_nan_to_none(float(record["mape"])) if record["mape"] is not None else None,
                    rmse=_nan_to_none(float(record["rmse"])) if record["rmse"] is not None else None,
                    beats_baseline=bool(record["beats_baseline"]),
                    needs_review=bool(record["needs_review"]),
                    demand_class=demand_class_str,
                    obsolescence_flag=bool(record["obsolescence_flag"]),
                )
            )
        return champions

    def _build_forecasts(
        self,
        frame: pd.DataFrame,
        champions: Sequence[ChampionRow],
        horizons: Sequence[int],
    ) -> list[tuple[str, date, int, str, float | None, float | None, float | None]]:
        StatsForecast, ETS, CrostonSBA, SeasonalNaive, TSB = _ensure_statsforecast()

        grouped_series = {
            item_id: group.sort_values("period_start_date")
            for item_id, group in frame.groupby("item_id")
        }

        champion_map: dict[str, dict[int, ChampionRow]] = defaultdict(dict)
        for row in champions:
            champion_map[row.item_id][row.horizon] = row

        target_horizons = set(horizons)
        forecast_rows: list[tuple[str, date, int, str, float | None, float | None, float | None]] = []

        for item_id, horizon_map in champion_map.items():
            if item_id not in grouped_series:
                logger.warning("Skipping forecast for %s: history missing", item_id)
                continue

            series = grouped_series[item_id]

            by_method: dict[str, list[int]] = defaultdict(list)
            for horizon, champion in horizon_map.items():
                if horizon not in target_horizons:
                    continue
                by_method[champion.method].append(horizon)

            for method, method_horizons in by_method.items():
                max_h = max(method_horizons)

                if method == "ETS":
                    model = ETS(season_length=SEASON_LENGTH)
                elif method == "CrostonSBA":
                    model = CrostonSBA()
                elif method == "TSB":
                    from statsforecast.utils import ConformalIntervals

                    conformal = ConformalIntervals(n_windows=5, h=max_h)
                    model = TSB(
                        alpha_d=TSB_ALPHA_D,
                        alpha_p=TSB_ALPHA_P,
                        prediction_intervals=conformal,
                    )
                else:
                    logger.warning("Unknown champion method %s for %s", method, item_id)
                    continue

                df = pd.DataFrame(
                    {
                        "unique_id": [item_id] * len(series),
                        "ds": pd.to_datetime(series["period_start_date"]),
                        "y": series["demand"].astype(float),
                    }
                )

                try:
                    sf = StatsForecast(models=[model], freq="MS", n_jobs=1)
                    forecast_df = sf.forecast(df=df, h=max_h, level=[PREDICTION_INTERVAL_LEVEL])
                except Exception as exc:  # pragma: no cover - upstream behaviour
                    logger.exception("Forecast generation failed for %s (%s): %s", item_id, method, exc)
                    continue

                if forecast_df.empty:
                    continue

                mean_col = method
                lower_col = _locate_interval_column(
                    forecast_df.columns, mean_col, "lo", PREDICTION_INTERVAL_LEVEL
                )
                upper_col = _locate_interval_column(
                    forecast_df.columns, mean_col, "hi", PREDICTION_INTERVAL_LEVEL
                )

                forecast_df = forecast_df.sort_values("ds").reset_index(drop=True)

                for idx, row in forecast_df.iterrows():
                    horizon = idx + 1
                    if horizon not in method_horizons:
                        continue
                    champion = horizon_map[horizon]
                    period_date = pd.Timestamp(row["ds"]).to_pydatetime().date()
                    p50 = _nan_to_none(float(row.get(mean_col))) if mean_col in row else None
                    p10 = _nan_to_none(float(row.get(lower_col))) if lower_col and lower_col in row else None
                    p90 = _nan_to_none(float(row.get(upper_col))) if upper_col and upper_col in row else None
                    forecast_rows.append(
                        (
                            item_id,
                            period_date,
                            horizon,
                            champion.method,
                            p50,
                            p10,
                            p90,
                        )
                    )

        return forecast_rows

    async def _persist_forecasts(
        self,
        run_id: UUID,
        forecast_rows: Iterable[tuple[str, date, int, str, float | None, float | None, float | None]],
    ) -> None:
        rows = [
            (
                run_id,
                item_id,
                period_start,
                horizon,
                method,
                p50,
                p10,
                p90,
            )
            for item_id, period_start, horizon, method, p50, p10, p90 in forecast_rows
        ]

        if not rows:
            return

        delete_query = "DELETE FROM analytics.forecast_item_month WHERE run_id = $1"
        insert_query = """
            INSERT INTO analytics.forecast_item_month (
                run_id,
                item_id,
                period_start_date,
                horizon_months,
                method,
                p50,
                p10,
                p90,
                created_at
            )
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, now())
        """

        try:
            await self.connection.execute(delete_query, run_id)
            await self.connection.executemany(insert_query, rows)
        except asyncpg.PostgresError as exc:  # pragma: no cover - depends on DB
            raise ForecastingServiceError("Failed to persist forecast rows.") from exc

    async def _update_run_forecast_metadata(
        self,
        run_id: UUID,
        forecast_rows: Sequence[tuple[Any, ...]],
    ) -> None:
        distinct_items = len({row[0] for row in forecast_rows})
        query = """
            UPDATE analytics.forecast_run
            SET status = 'FORECASTED',
                items_forecasted = $2,
                forecast_generated_at = now(),
                updated_at = now()
            WHERE run_id = $1
        """

        try:
            await self.connection.execute(query, run_id, distinct_items)
        except asyncpg.PostgresError as exc:  # pragma: no cover - depends on DB
            raise ForecastingServiceError("Failed to update forecast run metadata.") from exc


__all__ = ["ForecastingService", "ForecastingServiceError", "MissingDependencyError", "DataUnavailableError"]


