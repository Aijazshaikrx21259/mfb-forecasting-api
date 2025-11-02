"""Forecast champion selection and inference endpoints."""

from __future__ import annotations

import logging
from datetime import date, datetime
from typing import Any
from uuid import UUID

import asyncpg
from fastapi import APIRouter, Depends, HTTPException, Path, Query, status
from pydantic import BaseModel, Field

from app.db import get_db_connection
from app.security import verify_api_key
from app.services import (
    DataUnavailableError,
    ForecastingService,
    ForecastingServiceError,
    MissingDependencyError,
)

logger = logging.getLogger(__name__)


DEFAULT_HORIZONS = (1, 2, 3, 4)


class ForecastPrepResponse(BaseModel):
    items_processed: int = Field(..., description="Total items processed for classification.")
    intermittent_items: int = Field(..., description="Items falling into intermittent/lumpy demand classes.")
    obsolescence_candidates: int = Field(..., description="Items flagged for obsolescence gating.")


class TrainSelectResponse(BaseModel):
    run_id: UUID
    horizons: list[int]
    items_evaluated: int
    items_with_champion: int
    items_beating_baseline: int
    champion_counts: dict[str, int]
    message: str | None = None


class ForecastGenerationResponse(BaseModel):
    run_id: UUID
    horizons: list[int]
    items_forecasted: int
    forecast_rows: int
    forecast_months: int
    message: str | None = None


class ChampionSummary(BaseModel):
    horizon: int
    method: str
    mape: float | None = None
    rmse: float | None = None
    beats_baseline: bool
    needs_review: bool


class ForecastPoint(BaseModel):
    horizon: int
    period_start_date: date
    method: str
    p50: float | None
    p10: float | None
    p90: float | None


class ItemForecastResponse(BaseModel):
    item_id: str
    run_id: UUID
    champions: list[ChampionSummary]
    forecasts: list[ForecastPoint]


class PlanItem(BaseModel):
    item_id: str
    period_start_date: date
    method: str
    p50: float | None
    p10: float | None
    p90: float | None


class PlanResponse(BaseModel):
    run_id: UUID
    horizon: int
    items: list[PlanItem]


class RunMetadataResponse(BaseModel):
    run_id: UUID
    horizons: list[int]
    status: str
    items_evaluated: int | None = None
    items_with_champion: int | None = None
    items_beating_baseline: int | None = None
    items_forecasted: int | None = None
    champion_counts: dict[str, int] | None = None
    created_at: datetime
    updated_at: datetime
    forecast_generated_at: datetime | None = None


router = APIRouter(
    prefix="/api/forecast",
    tags=["forecast"],
    dependencies=[Depends(verify_api_key)],
)


def _decimal_to_float(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    return float(value)


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


def _map_service_error(exc: ForecastingServiceError) -> HTTPException:
    if isinstance(exc, (MissingDependencyError, DataUnavailableError)):
        return HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc))
    return HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc))


async def _resolve_run_id(
    connection: asyncpg.Connection,
    provided: UUID | None,
) -> UUID:
    if provided is not None:
        return provided

    try:
        run_id = await connection.fetchval(
            """
            SELECT run_id
            FROM analytics.forecast_run
            ORDER BY created_at DESC
            LIMIT 1
            """
        )
    except asyncpg.exceptions.UndefinedTableError as exc:  # pragma: no cover - depends on DB
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="analytics.forecast_run table is not available; apply the forecasting migration stub.",
        ) from exc

    if run_id is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No forecasting run has been recorded yet.",
        )

    return run_id


@router.post("/prep/build-item-month", response_model=ForecastPrepResponse)
async def build_item_month_features(
    connection: asyncpg.Connection = Depends(get_db_connection),
) -> ForecastPrepResponse:
    """Compute ADI/CV² classifications and obsolescence gates for each item."""

    service = ForecastingService(connection)
    try:
        summary = await service.prepare_item_features()
    except ForecastingServiceError as exc:
        raise _map_service_error(exc) from exc

    return ForecastPrepResponse(**summary)


@router.post("/train-select", response_model=TrainSelectResponse, status_code=status.HTTP_202_ACCEPTED)
async def train_and_select_champions(
    horizons: list[int] = Query(default=list(DEFAULT_HORIZONS), alias="h"),
    step_size: int = Query(default=1, ge=1, le=12),
    n_windows: int | None = Query(default=None, ge=1),
    connection: asyncpg.Connection = Depends(get_db_connection),
) -> TrainSelectResponse:
    """Run rolling-origin CV and store champion selections for each item/horizon."""

    distinct_horizons = _normalise_horizons(horizons)
    service = ForecastingService(connection)

    try:
        run_id, evaluation = await service.train_and_select(distinct_horizons, step_size, n_windows)
    except ForecastingServiceError as exc:
        raise _map_service_error(exc) from exc

    response = TrainSelectResponse(
        run_id=run_id,
        horizons=distinct_horizons,
        items_evaluated=evaluation.items_evaluated,
        items_with_champion=evaluation.items_with_champion,
        items_beating_baseline=evaluation.items_beating_baseline,
        champion_counts=dict(evaluation.champion_counts),
        message="Champion selection completed.",
    )
    return response


@router.post("/forecast", response_model=ForecastGenerationResponse)
async def generate_forecasts(
    horizons: list[int] = Query(default=list(DEFAULT_HORIZONS), alias="h"),
    run_id: UUID | None = Query(default=None),
    connection: asyncpg.Connection = Depends(get_db_connection),
) -> ForecastGenerationResponse:
    """Fit the chosen champion models on full history and write forecasts."""

    distinct_horizons = _normalise_horizons(horizons)
    resolved_run_id = await _resolve_run_id(connection, run_id)

    service = ForecastingService(connection)
    try:
        summary = await service.generate_forecasts(resolved_run_id, distinct_horizons)
    except ForecastingServiceError as exc:
        raise _map_service_error(exc) from exc

    return ForecastGenerationResponse(
        run_id=resolved_run_id,
        horizons=distinct_horizons,
        items_forecasted=summary["items_forecasted"],
        forecast_rows=summary["forecast_rows"],
        forecast_months=summary["forecast_months"],
        message="Forecast generation completed.",
    )


@router.get("/forecasts/items/{item_id}", response_model=ItemForecastResponse)
async def read_item_forecast(
    item_id: str = Path(..., description="Item identifier."),
    horizons: list[int] | None = Query(default=None, alias="h"),
    run_id: UUID | None = Query(default=None),
    connection: asyncpg.Connection = Depends(get_db_connection),
) -> ItemForecastResponse:
    """Return the champion summary and forecast rows for a specific item."""

    resolved_run_id = await _resolve_run_id(connection, run_id)
    horizon_filter = _normalise_horizons(horizons) if horizons else None

    try:
        champion_rows = await connection.fetch(
            """
            SELECT horizon, champion_method, mape, rmse, beats_baseline, needs_review
            FROM analytics.item_champion
            WHERE run_id = $1
              AND item_id = $2
              AND ($3::int[] IS NULL OR horizon = ANY($3::int[]))
            ORDER BY horizon
            """,
            resolved_run_id,
            item_id,
            horizon_filter,
        )
    except asyncpg.exceptions.UndefinedTableError as exc:  # pragma: no cover - depends on DB
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="analytics.item_champion table is unavailable; apply the forecasting migration stub.",
        ) from exc

    if not champion_rows:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No champion selection found for the requested item/run.",
        )

    try:
        forecast_rows = await connection.fetch(
            """
            SELECT horizon_months, period_start_date, method, p50, p10, p90
            FROM analytics.forecast_item_month
            WHERE run_id = $1
              AND item_id = $2
              AND ($3::int[] IS NULL OR horizon_months = ANY($3::int[]))
            ORDER BY horizon_months, period_start_date
            """,
            resolved_run_id,
            item_id,
            horizon_filter,
        )
    except asyncpg.exceptions.UndefinedTableError as exc:  # pragma: no cover - depends on DB
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="analytics.forecast_item_month table is unavailable; apply the forecasting migration stub.",
        ) from exc

    champions = [
        ChampionSummary(
            horizon=row["horizon"],
            method=row["champion_method"],
            mape=_decimal_to_float(row.get("mape")),
            rmse=_decimal_to_float(row.get("rmse")),
            beats_baseline=bool(row.get("beats_baseline")),
            needs_review=bool(row.get("needs_review")),
        )
        for row in champion_rows
    ]

    forecasts = [
        ForecastPoint(
            horizon=row["horizon_months"],
            period_start_date=row["period_start_date"],
            method=row["method"],
            p50=_decimal_to_float(row.get("p50")),
            p10=_decimal_to_float(row.get("p10")),
            p90=_decimal_to_float(row.get("p90")),
        )
        for row in forecast_rows
    ]

    return ItemForecastResponse(
        item_id=item_id,
        run_id=resolved_run_id,
        champions=champions,
        forecasts=forecasts,
    )


@router.get("/plan", response_model=PlanResponse)
async def read_default_plan(
    horizon: int = Query(default=1, ge=1, description="Horizon in months to plan for."),
    run_id: UUID | None = Query(default=None),
    connection: asyncpg.Connection = Depends(get_db_connection),
) -> PlanResponse:
    """Return the first-step plan (p50/p10/p90) for each item at the requested horizon."""

    resolved_run_id = await _resolve_run_id(connection, run_id)

    try:
        records = await connection.fetch(
            """
            WITH ranked AS (
                SELECT item_id,
                       period_start_date,
                       method,
                       p50,
                       p10,
                       p90,
                       ROW_NUMBER() OVER (PARTITION BY item_id ORDER BY period_start_date) AS rn
                FROM analytics.forecast_item_month
                WHERE run_id = $1
                  AND horizon_months = $2
            )
            SELECT item_id, period_start_date, method, p50, p10, p90
            FROM ranked
            WHERE rn = 1
            ORDER BY item_id
            """,
            resolved_run_id,
            horizon,
        )
    except asyncpg.exceptions.UndefinedTableError as exc:  # pragma: no cover - depends on DB
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="analytics.forecast_item_month table is unavailable; apply the forecasting migration stub.",
        ) from exc

    items = [
        PlanItem(
            item_id=row["item_id"],
            period_start_date=row["period_start_date"],
            method=row["method"],
            p50=_decimal_to_float(row.get("p50")),
            p10=_decimal_to_float(row.get("p10")),
            p90=_decimal_to_float(row.get("p90")),
        )
        for row in records
    ]

    return PlanResponse(run_id=resolved_run_id, horizon=horizon, items=items)


@router.get("/runs/latest", response_model=RunMetadataResponse)
async def read_latest_run(
    connection: asyncpg.Connection = Depends(get_db_connection),
) -> RunMetadataResponse:
    """Return metadata about the latest forecasting pipeline run."""

    try:
        record = await connection.fetchrow(
            """
            SELECT *
            FROM analytics.forecast_run
            ORDER BY created_at DESC
            LIMIT 1
            """
        )
    except asyncpg.exceptions.UndefinedTableError as exc:  # pragma: no cover - depends on DB
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="analytics.forecast_run table is unavailable; apply the forecasting migration stub.",
        ) from exc

    if record is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No forecasting run has been recorded yet.",
        )

    champion_counts = record.get("champion_counts")
    champion_counts_dict: dict[str, int] | None = None
    if champion_counts:
        if isinstance(champion_counts, dict):
            champion_counts_dict = {str(key): int(value) for key, value in champion_counts.items()}
        else:
            champion_counts_dict = {}

    horizons_value = record.get("horizons") or []

    return RunMetadataResponse(
        run_id=record["run_id"],
        horizons=list(horizons_value),
        status=record.get("status", "UNKNOWN"),
        items_evaluated=record.get("items_evaluated"),
        items_with_champion=record.get("items_with_champion"),
        items_beating_baseline=record.get("items_beating_baseline"),
        items_forecasted=record.get("items_forecasted"),
        champion_counts=champion_counts_dict,
        created_at=record["created_at"],
        updated_at=record["updated_at"],
        forecast_generated_at=record.get("forecast_generated_at"),
    )


