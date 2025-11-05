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
from app.services.forecasting import SEGMENT_DEMAND_CLASSES

logger = logging.getLogger(__name__)

DEFAULT_PIPELINE_HORIZONS: tuple[int, ...] = (1, 2, 3, 4)


async def run_forecast_pipeline(
    horizons: Sequence[int] = DEFAULT_PIPELINE_HORIZONS,
    segment: str | None = None,
) -> str:
    """Execute the full forecasting pipeline and return the run identifier."""

    pool = await get_db_pool()
    run_id: str | None = None
    segment_label = (segment or "all").lower()
    include_classes = SEGMENT_DEMAND_CLASSES.get(segment_label)

    async with pool.acquire() as connection:
        service = ForecastingService(connection)

        logger.info(
            "[pipeline] Preparing item features for %s segment...",
            segment_label,
        )
        await service.prepare_item_features()

        logger.info(
            "[pipeline] Training and selecting champions for horizons %s (segment=%s)",
            horizons,
            segment_label,
        )
        run_id, evaluation = await service.train_and_select(
            list(horizons),
            step_size=1,
            n_windows=None,
            include_classes=include_classes,
            segment=segment_label,
        )

        logger.info(
            "[pipeline] Champion selection complete: run_id=%s items=%s (segment=%s)",
            run_id,
            evaluation.items_with_champion,
            segment_label,
        )

        logger.info("[pipeline] Generating forecasts for run %s (segment=%s)", run_id, segment_label)
        await service.generate_forecasts(run_id, list(horizons))

    if run_id is None:
        raise RuntimeError("Forecast pipeline completed without a run identifier.")

    logger.info("[pipeline] Forecast pipeline finished run %s (segment=%s)", run_id, segment_label)
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
        stable_interval_minutes: int | None = None,
        volatile_interval_minutes: int | None = None,
    ) -> None:
        self.enabled = enabled
        base_interval = max(1, int(interval_minutes) * 60)
        self.interval_seconds = base_interval
        self.initial_delay_seconds = max(0, int(initial_delay_seconds))
        self.horizons = tuple(sorted({int(h) for h in horizons if h > 0})) or DEFAULT_PIPELINE_HORIZONS
        self._lock = asyncio.Lock()
        self._stop_event = asyncio.Event()
        self._tasks: list[asyncio.Task[None]] = []

        self._segments: list[tuple[str, int]] = []
        if stable_interval_minutes:
            self._segments.append(("stable", max(1, int(stable_interval_minutes) * 60)))
        if volatile_interval_minutes:
            self._segments.append(("volatile", max(1, int(volatile_interval_minutes) * 60)))
        if not self._segments:
            self._segments.append(("all", base_interval))

    async def start(self) -> None:
        if not self.enabled:
            logger.info("[pipeline] Automatic pipeline runs disabled by configuration.")
            return

        if self._tasks:
            return

        logger.info(
            "[pipeline] Starting scheduler: segments=%s initial_delay=%ss horizons=%s",
            ", ".join(f"{segment}@{interval}s" for segment, interval in self._segments),
            self.initial_delay_seconds,
            self.horizons,
        )
        self._stop_event.clear()
        for segment, interval in self._segments:
            task = asyncio.create_task(self._run_loop(segment, interval))
            self._tasks.append(task)

    async def stop(self) -> None:
        if not self._tasks:
            return

        logger.info("[pipeline] Stopping scheduler")
        self._stop_event.set()
        for task in self._tasks:
            task.cancel()
        for task in self._tasks:
            try:
                await task
            except asyncio.CancelledError:
                continue
        self._tasks.clear()

    async def run_once(self, segment: str | None = None) -> None:
        if not self.enabled:
            logger.info("[pipeline] Skipping manual run; scheduler disabled.")
            return

        async with self._lock:
            target_segment = segment or self._segments[0][0]
            await self._run_pipeline_guarded(target_segment)

    async def _run_loop(self, segment: str, interval_seconds: int) -> None:
        try:
            initial_delay = self.initial_delay_seconds
            if segment == "stable":
                initial_delay += interval_seconds // 2

            if initial_delay > 0:
                try:
                    await asyncio.wait_for(self._stop_event.wait(), timeout=initial_delay)
                    if self._stop_event.is_set():
                        return
                except asyncio.TimeoutError:
                    pass

            while not self._stop_event.is_set():
                async with self._lock:
                    await self._run_pipeline_guarded(segment)

                try:
                    await asyncio.wait_for(
                        self._stop_event.wait(),
                        timeout=interval_seconds,
                    )
                except asyncio.TimeoutError:
                    continue
        except asyncio.CancelledError:
            raise
        except Exception:  # pragma: no cover - defensive logging
            logger.exception("[pipeline] Scheduler encountered an unexpected error")

    async def _run_pipeline_guarded(self, segment: str) -> None:
        try:
            run_id = await run_forecast_pipeline(self.horizons, segment=segment)
            logger.info("[pipeline] Automated run complete (segment=%s run_id=%s)", segment, run_id)
        except (MissingDependencyError, DataUnavailableError) as exc:
            logger.warning(
                "[pipeline] Pipeline run skipped due to missing dependency/data: %s",
                exc,
            )
        except ForecastingServiceError as exc:
            logger.exception("[pipeline] Forecasting service error: %s", exc)
        except Exception:  # pragma: no cover - defensive logging
            logger.exception("[pipeline] Unexpected failure during pipeline execution")
