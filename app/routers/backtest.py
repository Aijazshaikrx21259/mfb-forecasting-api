"""Backtest management endpoints."""

from __future__ import annotations

import logging
from datetime import date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

import asyncpg
from fastapi import APIRouter, Depends, HTTPException, Path, Query, status
from pydantic import BaseModel, ConfigDict, Field

from app.config import get_settings
from app.db import get_db_connection
from app.security import verify_api_key


DEFAULT_HORIZONS = (1, 2, 3, 4)
MAX_PAGE_SIZE = 200


def _decimal_to_float(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, Decimal):
        return float(value)
    return float(value)


class BacktestRunResponse(BaseModel):
    run_id: UUID
    horizons: list[int]
    step_size: int
    n_windows: int | None = None
    items_enqueued: int | None = Field(
        default=None, description="Number of item/horizon combinations queued for backtesting."
    )
    windows_enqueued: int | None = Field(
        default=None, description="Number of forecast windows generated for processing."
    )
    message: str | None = None


class BacktestOverallSummary(BaseModel):
    horizon_months: int = Field(..., description="Forecast horizon in months.")
    items_evaluated: int
    pct_items_mape_lt_30: float | None = Field(
        default=None, description="Percentage of items with MAPE below 30%."
    )
    pct_items_beating_sn: float | None = Field(
        default=None, description="Percentage of items outperforming the seasonal naive benchmark.")
    mean_mape: float | None = None
    mean_rmse: float | None = None
    run_id: UUID
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class BacktestItemSummary(BaseModel):
    item_id: str
    model_name: str
    horizon_months: int
    n_windows: int
    n_windows_mape_den: int | None
    mape: float | None
    rmse: float | None
    beats_benchmark: bool
    run_id: UUID
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class BacktestItemSummaryPage(BaseModel):
    items: list[BacktestItemSummary]
    total_count: int
    page: int
    page_size: int
    run_id: UUID | None = Field(
        default=None, description="Backtest run identifier supplying these metrics."
    )


class BacktestWindowError(BaseModel):
    item_id: str
    origin_month: date
    horizon_months: int
    model_name: str
    y_true: float
    y_pred: float
    err: float
    abs_pct_err: float | None
    run_id: UUID
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class BacktestItemDetailResponse(BaseModel):
    item_id: str
    summaries: list[BacktestItemSummary]
    windows: list[BacktestWindowError]
    run_id: UUID


class BacktestBenchmarkResponse(BaseModel):
    name: str
    seasonality: int
    description: str


class ModelMethodInfo(BaseModel):
    """Information about a forecasting method used for an item."""
    item_id: str
    champion_method: str
    horizon_months: int
    last_trained_at: datetime | None = None
    mape: float | None = None
    rmse: float | None = None
    beats_benchmark: bool
    run_id: UUID
    
    model_config = ConfigDict(from_attributes=True)


class ModelTransparencyResponse(BaseModel):
    """Aggregated model transparency information."""
    total_items: int
    method_distribution: dict[str, int]  # method_name -> count
    items: list[ModelMethodInfo]
    run_id: UUID


class PerformanceTrendPoint(BaseModel):
    """Performance metric at a specific point in time."""
    run_id: UUID
    created_at: datetime
    horizon_months: int
    mean_mape: float | None
    mean_rmse: float | None
    items_evaluated: int
    pct_items_beating_sn: float | None


class PerformanceSummaryResponse(BaseModel):
    """Comprehensive performance summary with trends."""
    current_run: BacktestOverallSummary | None
    historical_trend: list[PerformanceTrendPoint]
    method_performance: dict[str, dict[str, float | int]]  # method -> {avg_mape, avg_rmse, count}
    accuracy_distribution: dict[str, int]  # MAPE ranges -> count
    total_runs: int


router = APIRouter(
    prefix="/api/backtest",
    tags=["backtest"],
    dependencies=[Depends(verify_api_key)],
)

logger = logging.getLogger(__name__)


def _normalise_horizons(values: list[int] | None) -> list[int]:
    if not values:
        return list(DEFAULT_HORIZONS)
    normalised = sorted({value for value in values if value > 0})
    if not normalised:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="At least one positive horizon must be provided.",
        )
    return normalised


async def _resolve_latest_run_id(
    connection: asyncpg.Connection,
    table_name: str,
    provided: UUID | None,
    allow_missing: bool = False,
) -> UUID | None:
    if provided is not None:
        return provided

    query = f"""
        SELECT run_id
        FROM {table_name}
        ORDER BY created_at DESC
        LIMIT 1
    """
    try:
        run_id = await connection.fetchval(query)
    except asyncpg.exceptions.UndefinedTableError as exc:  # pragma: no cover - depends on DB
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Backtest table '{table_name}' is not available in the database.",
        ) from exc

    if run_id is None:
        if allow_missing:
            return None
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No backtest run has been recorded yet.",
        )

    return run_id


@router.post("/run", response_model=BacktestRunResponse, status_code=status.HTTP_202_ACCEPTED)
async def trigger_backtest_run(
    horizons: list[int] = Query(
        default=list(DEFAULT_HORIZONS),
        alias="h",
        description="One or more forecast horizons (months ahead).",
    ),
    step_size: int = Query(
        default=1,
        ge=1,
        le=12,
        description="Number of months to move the forecast origin between windows.",
    ),
    n_windows: int | None = Query(
        default=None,
        ge=1,
        description="Optional explicit number of rolling windows to evaluate.",
    ),
    connection: asyncpg.Connection = Depends(get_db_connection),
) -> BacktestRunResponse:
    """Enqueue a rolling-origin backtest run."""

    distinct_horizons = _normalise_horizons(horizons)

    try:
        record = await connection.fetchrow(
            "SELECT * FROM core.enqueue_backtest_run($1::int[], $2::int, $3::int)",
            distinct_horizons,
            step_size,
            n_windows,
        )
    except asyncpg.exceptions.UndefinedFunctionError as exc:  # pragma: no cover - depends on DB
        settings = get_settings()
        env_name = settings.environment.lower()
        if env_name in {"local", "development", "dev"}:
            run_id = uuid4()
            logger.warning(
                "Stub backtest run created because core.enqueue_backtest_run is missing; "
                "returning synthetic run_id %s.",
                run_id,
            )
            return BacktestRunResponse(
                run_id=run_id,
                horizons=distinct_horizons,
                step_size=step_size,
                n_windows=n_windows,
                items_enqueued=0,
                windows_enqueued=0,
                message=(
                    "Backtest run acknowledged in stub mode; install core.enqueue_backtest_run "
                    "to trigger the real pipeline."
                ),
            )

        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=(
                "Database routine core.enqueue_backtest_run(int[], int, int) is missing. "
                "Install the ingestion pipeline or upgrade the database schema to enable backtesting."
            ),
        ) from exc
    except asyncpg.PostgresError as exc:  # pragma: no cover - depends on DB
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Unable to enqueue backtest run; see server logs for details.",
        ) from exc

    if record is None:
        run_id = uuid4()
        return BacktestRunResponse(
            run_id=run_id,
            horizons=distinct_horizons,
            step_size=step_size,
            n_windows=n_windows,
            message=(
                "Backtest run acknowledged but the database did not return a run identifier. "
                "Verify the enqueue routine to receive structured responses."
            ),
        )

    payload = dict(record)
    run_id = payload.get("run_id")
    if run_id is None:
        run_id = uuid4()

    return BacktestRunResponse(
        run_id=run_id,
        horizons=distinct_horizons,
        step_size=step_size,
        n_windows=n_windows,
        items_enqueued=payload.get("items_enqueued"),
        windows_enqueued=payload.get("windows_enqueued"),
    )


@router.get("/summary", response_model=list[BacktestOverallSummary])
async def read_backtest_summary(
    horizons: list[int] | None = Query(
        default=None,
        alias="h",
        description="Filter results to these forecast horizons.",
    ),
    run_id: UUID | None = Query(
        default=None,
        description="Specific backtest run identifier. Defaults to the most recent run.",
    ),
    connection: asyncpg.Connection = Depends(get_db_connection),
) -> list[BacktestOverallSummary]:
    """Return overall backtest metrics for the requested run."""

    resolved_run_id = await _resolve_latest_run_id(
        connection,
        "analytics.backtest_overall_summary",
        run_id,
        allow_missing=True,
    )

    if resolved_run_id is None:
        return []

    try:
        records = await connection.fetch(
            """
            SELECT *
            FROM analytics.backtest_overall_summary
            WHERE run_id = $1
            ORDER BY horizon_months
            """,
            resolved_run_id,
        )
    except asyncpg.exceptions.UndefinedTableError as exc:  # pragma: no cover - depends on DB
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Backtest overall summary table is not available in the database.",
        ) from exc

    if not records:
        return []

    horizon_filter = set(_normalise_horizons(horizons) if horizons else [])

    response: list[BacktestOverallSummary] = []
    for record in records:
        horizon = record["horizon_months"]
        if horizon_filter and horizon not in horizon_filter:
            continue

        response.append(
            BacktestOverallSummary(
                horizon_months=horizon,
                items_evaluated=record.get("items_evaluated", 0),
                pct_items_mape_lt_30=_decimal_to_float(record.get("pct_items_mape_lt_30")),
                pct_items_beating_sn=_decimal_to_float(record.get("pct_items_beating_sn")),
                mean_mape=_decimal_to_float(record.get("mean_mape")),
                mean_rmse=_decimal_to_float(record.get("mean_rmse")),
                run_id=record["run_id"],
                created_at=record["created_at"],
            )
        )

    if horizon_filter and not response:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No summary metrics found for the requested horizons.",
        )

    return response


@router.get("/items", response_model=BacktestItemSummaryPage)
async def list_backtest_items(
    horizons: list[int] | None = Query(
        default=None,
        alias="h",
        description="Optional list of forecast horizons to include.",
    ),
    beats_benchmark: bool | None = Query(
        default=None, description="Filter by whether the model beats the seasonal naive benchmark."
    ),
    model_name: str | None = Query(
        default=None, description="Filter by model name (case-insensitive exact match)."
    ),
    item_id: str | None = Query(
        default=None, description="Limit results to a specific item identifier."
    ),
    order_by: str = Query(
        default="mape",
        description="Sort key: mape, rmse, item_id, model_name, or beats_benchmark.",
    ),
    descending: bool = Query(
        default=False, description="Return results in descending order.",
    ),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=MAX_PAGE_SIZE),
    run_id: UUID | None = Query(
        default=None, description="Specific backtest run identifier. Defaults to latest run."
    ),
    connection: asyncpg.Connection = Depends(get_db_connection),
) -> BacktestItemSummaryPage:
    """Paginate backtest metrics per item and model."""

    resolved_run_id = await _resolve_latest_run_id(
        connection,
        "analytics.backtest_item_summary",
        run_id,
        allow_missing=True,
    )

    if resolved_run_id is None:
        return BacktestItemSummaryPage(
            items=[],
            total_count=0,
            page=page,
            page_size=page_size,
            run_id=None,
        )

    order_fields = {
        "mape": "mape",
        "rmse": "rmse",
        "item_id": "item_id",
        "model_name": "model_name",
        "beats_benchmark": "beats_benchmark",
    }
    order_field = order_fields.get(order_by.lower())
    if order_field is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Unsupported order_by value. Choose from mape, rmse, item_id, model_name, beats_benchmark.",
        )

    horizon_filter = _normalise_horizons(horizons) if horizons else None
    order_direction = "DESC" if descending else "ASC"
    offset = (page - 1) * page_size

    query = f"""
        SELECT *,
               COUNT(*) OVER() AS total_count
        FROM analytics.backtest_item_summary
        WHERE run_id = $1
          AND ($2::int[] IS NULL OR horizon_months = ANY($2::int[]))
          AND ($3::boolean IS NULL OR beats_benchmark = $3)
          AND ($4::text IS NULL OR UPPER(model_name) = UPPER($4))
          AND ($5::text IS NULL OR item_id = $5)
        ORDER BY {order_field} {order_direction}, item_id ASC
        LIMIT $6 OFFSET $7
    """

    try:
        records = await connection.fetch(
            query,
            resolved_run_id,
            horizon_filter,
            beats_benchmark,
            model_name,
            item_id,
            page_size,
            offset,
        )
    except asyncpg.exceptions.UndefinedTableError as exc:  # pragma: no cover - depends on DB
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Backtest item summary table is not available in the database.",
        ) from exc

    if not records:
        return BacktestItemSummaryPage(
            items=[],
            total_count=0,
            page=page,
            page_size=page_size,
            run_id=resolved_run_id,
        )

    total_count = records[0].get("total_count", 0)

    items = [
        BacktestItemSummary(
            item_id=record["item_id"],
            model_name=record["model_name"],
            horizon_months=record["horizon_months"],
            n_windows=record.get("n_windows", 0),
            n_windows_mape_den=record.get("n_windows_mape_den"),
            mape=_decimal_to_float(record.get("mape")),
            rmse=_decimal_to_float(record.get("rmse")),
            beats_benchmark=record.get("beats_benchmark", False),
            run_id=record["run_id"],
            created_at=record["created_at"],
        )
        for record in records
    ]

    return BacktestItemSummaryPage(
        items=items,
        total_count=int(total_count),
        page=page,
        page_size=page_size,
        run_id=resolved_run_id,
    )


@router.get("/items/{item_id}", response_model=BacktestItemDetailResponse)
async def read_backtest_item_detail(
    item_id: str = Path(..., description="Item identifier."),
    horizons: list[int] | None = Query(
        default=None,
        alias="h",
        description="Optional list of horizons to include.",
    ),
    model_name: str | None = Query(
        default=None, description="Filter to a single model name (case-insensitive)."
    ),
    run_id: UUID | None = Query(
        default=None, description="Specific backtest run identifier. Defaults to most recent run."
    ),
    connection: asyncpg.Connection = Depends(get_db_connection),
) -> BacktestItemDetailResponse:
    """Return summary and per-window errors for a specific item."""

    resolved_run_id = await _resolve_latest_run_id(connection, "analytics.backtest_item_summary", run_id)
    horizon_filter = _normalise_horizons(horizons) if horizons else None

    try:
        summary_rows = await connection.fetch(
            """
            SELECT *
            FROM analytics.backtest_item_summary
            WHERE run_id = $1
              AND item_id = $2
              AND ($3::int[] IS NULL OR horizon_months = ANY($3::int[]))
              AND ($4::text IS NULL OR UPPER(model_name) = UPPER($4))
            ORDER BY horizon_months, model_name
            """,
            resolved_run_id,
            item_id,
            horizon_filter,
            model_name,
        )
    except asyncpg.exceptions.UndefinedTableError as exc:  # pragma: no cover - depends on DB
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Backtest item summary table is not available in the database.",
        ) from exc

    if not summary_rows:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No backtest metrics found for the requested item.",
        )

    try:
        window_rows = await connection.fetch(
            """
            SELECT *
            FROM core.backtest_window_errors
            WHERE run_id = $1
              AND item_id = $2
              AND ($3::int[] IS NULL OR horizon_months = ANY($3::int[]))
              AND ($4::text IS NULL OR UPPER(model_name) = UPPER($4))
            ORDER BY origin_month, horizon_months, model_name
            """,
            resolved_run_id,
            item_id,
            horizon_filter,
            model_name,
        )
    except asyncpg.exceptions.UndefinedTableError as exc:  # pragma: no cover - depends on DB
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Backtest window-error table is not available in the database.",
        ) from exc

    summaries = [
        BacktestItemSummary(
            item_id=row["item_id"],
            model_name=row["model_name"],
            horizon_months=row["horizon_months"],
            n_windows=row.get("n_windows", 0),
            n_windows_mape_den=row.get("n_windows_mape_den"),
            mape=_decimal_to_float(row.get("mape")),
            rmse=_decimal_to_float(row.get("rmse")),
            beats_benchmark=row.get("beats_benchmark", False),
            run_id=row["run_id"],
            created_at=row["created_at"],
        )
        for row in summary_rows
    ]

    windows = [
        BacktestWindowError(
            item_id=row["item_id"],
            origin_month=row["origin_month"],
            horizon_months=row["horizon_months"],
            model_name=row["model_name"],
            y_true=_decimal_to_float(row.get("y_true")) or 0.0,
            y_pred=_decimal_to_float(row.get("y_pred")) or 0.0,
            err=_decimal_to_float(row.get("err")) or 0.0,
            abs_pct_err=_decimal_to_float(row.get("abs_pct_err")),
            run_id=row["run_id"],
            created_at=row["created_at"],
        )
        for row in window_rows
    ]

    return BacktestItemDetailResponse(
        item_id=item_id,
        summaries=summaries,
        windows=windows,
        run_id=resolved_run_id,
    )


@router.get("/benchmark/method", response_model=BacktestBenchmarkResponse)
async def describe_benchmark_method() -> BacktestBenchmarkResponse:
    """Describe the baseline method used for backtest comparisons."""

    return BacktestBenchmarkResponse(
        name="Seasonal Naive",
        seasonality=12,
        description=(
            "Forecasts each month using the actuals from the same month one year prior. "
            "Used as a benchmark to evaluate ETS, Croston-SBA, and TSB models."
        ),
    )


@router.get("/model-transparency", response_model=ModelTransparencyResponse)
async def get_model_transparency(
    horizon: int = Query(default=1, ge=1, description="Forecast horizon to analyze."),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=MAX_PAGE_SIZE),
    run_id: UUID | None = Query(
        default=None, description="Specific backtest run identifier. Defaults to latest run."
    ),
    connection: asyncpg.Connection = Depends(get_db_connection),
) -> ModelTransparencyResponse:
    """
    Return model transparency information showing which forecasting method 
    was selected for each item and when it was last trained.
    
    This endpoint supports US #13: Model Transparency Dashboard.
    """
    
    resolved_run_id = await _resolve_latest_run_id(
        connection,
        "analytics.backtest_item_summary",
        run_id,
        allow_missing=True,
    )
    
    if resolved_run_id is None:
        return ModelTransparencyResponse(
            total_items=0,
            method_distribution={},
            items=[],
            run_id=uuid4(),
        )
    
    offset = (page - 1) * page_size
    
    try:
        # Get items with their champion methods
        records = await connection.fetch(
            """
            SELECT 
                item_id,
                model_name as champion_method,
                horizon_months,
                created_at as last_trained_at,
                mape,
                rmse,
                beats_benchmark,
                run_id,
                COUNT(*) OVER() AS total_count
            FROM analytics.backtest_item_summary
            WHERE run_id = $1
              AND horizon_months = $2
            ORDER BY item_id
            LIMIT $3 OFFSET $4
            """,
            resolved_run_id,
            horizon,
            page_size,
            offset,
        )
        
        # Get method distribution for all items (not just current page)
        distribution_records = await connection.fetch(
            """
            SELECT 
                model_name,
                COUNT(*) as count
            FROM analytics.backtest_item_summary
            WHERE run_id = $1
              AND horizon_months = $2
            GROUP BY model_name
            ORDER BY count DESC
            """,
            resolved_run_id,
            horizon,
        )
        
    except asyncpg.exceptions.UndefinedTableError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Backtest item summary table is not available in the database.",
        ) from exc
    
    if not records:
        return ModelTransparencyResponse(
            total_items=0,
            method_distribution={},
            items=[],
            run_id=resolved_run_id,
        )
    
    total_count = records[0].get("total_count", 0)
    
    # Build method distribution
    method_distribution = {
        record["model_name"]: record["count"]
        for record in distribution_records
    }
    
    # Build items list
    items = [
        ModelMethodInfo(
            item_id=record["item_id"],
            champion_method=record["champion_method"],
            horizon_months=record["horizon_months"],
            last_trained_at=record.get("last_trained_at"),
            mape=_decimal_to_float(record.get("mape")),
            rmse=_decimal_to_float(record.get("rmse")),
            beats_benchmark=record.get("beats_benchmark", False),
            run_id=record["run_id"],
        )
        for record in records
    ]
    
    return ModelTransparencyResponse(
        total_items=int(total_count),
        method_distribution=method_distribution,
        items=items,
        run_id=resolved_run_id,
    )


@router.get("/performance-summary", response_model=PerformanceSummaryResponse)
async def get_performance_summary(
    horizon: int = Query(default=1, ge=1, description="Forecast horizon to analyze."),
    limit_runs: int = Query(default=10, ge=1, le=50, description="Number of historical runs to include."),
    connection: asyncpg.Connection = Depends(get_db_connection),
) -> PerformanceSummaryResponse:
    """
    Return comprehensive performance summary with historical trends and method comparison.
    
    This endpoint supports US #14: Forecast Performance Tracking.
    """
    
    try:
        # Get current run summary
        current_run_records = await connection.fetch(
            """
            SELECT *
            FROM analytics.backtest_overall_summary
            WHERE horizon_months = $1
            ORDER BY created_at DESC
            LIMIT 1
            """,
            horizon,
        )
        
        current_run = None
        if current_run_records:
            record = current_run_records[0]
            current_run = BacktestOverallSummary(
                horizon_months=record["horizon_months"],
                items_evaluated=record.get("items_evaluated", 0),
                pct_items_mape_lt_30=_decimal_to_float(record.get("pct_items_mape_lt_30")),
                pct_items_beating_sn=_decimal_to_float(record.get("pct_items_beating_sn")),
                mean_mape=_decimal_to_float(record.get("mean_mape")),
                mean_rmse=_decimal_to_float(record.get("mean_rmse")),
                run_id=record["run_id"],
                created_at=record["created_at"],
            )
        
        # Get historical trend
        trend_records = await connection.fetch(
            """
            SELECT 
                run_id,
                created_at,
                horizon_months,
                mean_mape,
                mean_rmse,
                items_evaluated,
                pct_items_beating_sn
            FROM analytics.backtest_overall_summary
            WHERE horizon_months = $1
            ORDER BY created_at DESC
            LIMIT $2
            """,
            horizon,
            limit_runs,
        )
        
        historical_trend = [
            PerformanceTrendPoint(
                run_id=record["run_id"],
                created_at=record["created_at"],
                horizon_months=record["horizon_months"],
                mean_mape=_decimal_to_float(record.get("mean_mape")),
                mean_rmse=_decimal_to_float(record.get("mean_rmse")),
                items_evaluated=record.get("items_evaluated", 0),
                pct_items_beating_sn=_decimal_to_float(record.get("pct_items_beating_sn")),
            )
            for record in trend_records
        ]
        
        # Get method performance (from latest run)
        if current_run:
            method_records = await connection.fetch(
                """
                SELECT 
                    model_name,
                    AVG(mape) as avg_mape,
                    AVG(rmse) as avg_rmse,
                    COUNT(*) as count
                FROM analytics.backtest_item_summary
                WHERE run_id = $1
                  AND horizon_months = $2
                GROUP BY model_name
                ORDER BY count DESC
                """,
                current_run.run_id,
                horizon,
            )
            
            method_performance = {
                record["model_name"]: {
                    "avg_mape": _decimal_to_float(record.get("avg_mape")) or 0.0,
                    "avg_rmse": _decimal_to_float(record.get("avg_rmse")) or 0.0,
                    "count": record.get("count", 0),
                }
                for record in method_records
            }
        else:
            method_performance = {}
        
        # Get accuracy distribution (MAPE ranges)
        if current_run:
            accuracy_records = await connection.fetch(
                """
                WITH mape_ranges AS (
                    SELECT 
                        CASE 
                            WHEN mape IS NULL THEN 'Unknown'
                            WHEN mape < 10 THEN '0-10%'
                            WHEN mape < 20 THEN '10-20%'
                            WHEN mape < 30 THEN '20-30%'
                            WHEN mape < 50 THEN '30-50%'
                            ELSE '50%+'
                        END as mape_range,
                        CASE 
                            WHEN mape IS NULL THEN 6
                            WHEN mape < 10 THEN 1
                            WHEN mape < 20 THEN 2
                            WHEN mape < 30 THEN 3
                            WHEN mape < 50 THEN 4
                            ELSE 5
                        END as sort_order
                    FROM analytics.backtest_item_summary
                    WHERE run_id = $1
                      AND horizon_months = $2
                )
                SELECT mape_range, COUNT(*) as count
                FROM mape_ranges
                GROUP BY mape_range, sort_order
                ORDER BY sort_order
                """,
                current_run.run_id,
                horizon,
            )
            
            accuracy_distribution = {
                record["mape_range"]: record["count"]
                for record in accuracy_records
            }
        else:
            accuracy_distribution = {}
        
        # Get total number of runs
        total_runs_record = await connection.fetchval(
            """
            SELECT COUNT(DISTINCT run_id)
            FROM analytics.backtest_overall_summary
            WHERE horizon_months = $1
            """,
            horizon,
        )
        
        total_runs = total_runs_record or 0
        
    except asyncpg.exceptions.UndefinedTableError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Backtest summary tables are not available in the database.",
        ) from exc
    
    return PerformanceSummaryResponse(
        current_run=current_run,
        historical_trend=historical_trend,
        method_performance=method_performance,
        accuracy_distribution=accuracy_distribution,
        total_runs=int(total_runs),
    )
