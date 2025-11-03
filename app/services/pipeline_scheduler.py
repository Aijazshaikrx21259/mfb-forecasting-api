"""Automated forecasting pipeline runner."""

from __future__ import annotations

import asyncio
import logging
from typing import Sequence

from app.db import get_db_pool
from app.services import (
    ForecastingService,
    ForecastingServiceError,
    MissingDependencyError,
    DataUnavailableError,
)

logger = logging.getLogger(__name__)

DEFAULT_PIPELINE_HORIZONS: tuple[int, ...] = (1, 2, 3, 4)


async def run_forecast_pipeline(
    horizons: Sequence[int] = DEFAULT_PIPELINE_HORIZONS,
) -> str:
    """Execute the full forecasting pipeline and return the run identifier."""

    pool = await get_db_pool()
    run_id: str | None = None

    async with pool.acquire() as connection:
        service = ForecastingService(connection)

        logger.info("[pipeline] Preparing item features for forecasting...")
        await service.prepare_item_features()

        logger.info("[pipeline] Training and selecting champions for horizons %s", horizons)
        run_id, evaluation = await service.train_and_select(list(horizons), step_size=1, n_windows=None)

        logger.info(
            "[pipeline] Champion selection complete: run_id=%s items=%s",
            run_id,
            evaluation.items_with_champion,
        )

        logger.info("[pipeline] Generating forecasts for run %s", run_id)
        await service.generate_forecasts(run_id, list(horizons))

    if run_id is None:
        raise RuntimeError("Forecast pipeline completed without a run identifier.")

    logger.info("[pipeline] Forecast pipeline finished run %s", run_id)
    return str(run_id)


class ForecastPipelineScheduler:
    """Background scheduler that periodically runs the forecasting pipeline."""

    def __init__(
        self,
        *,
        enabled: bool,
        interval_minutes: int,
        initial_delay_seconds: int,
        horizons: Sequence[int] = DEFAULT_PIPELINE_HORIZONS,
    ) -> None:
        self.enabled = enabled
        self.interval_seconds = max(1, int(interval_minutes) * 60)
        self.initial_delay_seconds = max(0, int(initial_delay_seconds))
        self.horizons = tuple(sorted({int(h) for h in horizons if h > 0})) or DEFAULT_PIPELINE_HORIZONS
        self._task: asyncio.Task[None] | None = None
        self._lock = asyncio.Lock()
        self._stop_event = asyncio.Event()

    async def start(self) -> None:
        if not self.enabled:
            logger.info("[pipeline] Automatic pipeline runs disabled by configuration.")
            return

        if self._task is not None:
            return

        logger.info(
            "[pipeline] Starting scheduler: interval=%ss initial_delay=%ss horizons=%s",
            self.interval_seconds,
            self.initial_delay_seconds,
            self.horizons,
        )
        self._stop_event.clear()
        self._task = asyncio.create_task(self._run_loop())

    async def stop(self) -> None:
        if self._task is None:
            return

        logger.info("[pipeline] Stopping scheduler")
        self._stop_event.set()
        self._task.cancel()
        try:
            await self._task
        except asyncio.CancelledError:
            pass
        finally:
            self._task = None

    async def run_once(self) -> None:
        if not self.enabled:
            logger.info("[pipeline] Skipping manual run; scheduler disabled.")
            return

        async with self._lock:
            await self._run_pipeline_guarded()

    async def _run_loop(self) -> None:
        try:
            if self.initial_delay_seconds > 0:
                try:
                    await asyncio.wait_for(self._stop_event.wait(), timeout=self.initial_delay_seconds)
                    if self._stop_event.is_set():
                        return
                except asyncio.TimeoutError:
                    pass

            while not self._stop_event.is_set():
                async with self._lock:
                    await self._run_pipeline_guarded()

                try:
                    await asyncio.wait_for(
                        self._stop_event.wait(),
                        timeout=self.interval_seconds,
                    )
                except asyncio.TimeoutError:
                    continue
        except asyncio.CancelledError:
            raise
        except Exception:  # pragma: no cover - defensive logging
            logger.exception("[pipeline] Scheduler encountered an unexpected error")

    async def _run_pipeline_guarded(self) -> None:
        try:
            run_id = await run_forecast_pipeline(self.horizons)
            logger.info("[pipeline] Automated run complete (run_id=%s)", run_id)
        except (MissingDependencyError, DataUnavailableError) as exc:
            logger.warning(
                "[pipeline] Pipeline run skipped due to missing dependency/data: %s",
                exc,
            )
        except ForecastingServiceError as exc:
            logger.exception("[pipeline] Forecasting service error: %s", exc)
        except Exception:  # pragma: no cover - defensive logging
            logger.exception("[pipeline] Unexpected failure during pipeline execution")
