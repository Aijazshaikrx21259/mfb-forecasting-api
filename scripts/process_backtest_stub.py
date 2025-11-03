"""Process stub backtest jobs for local development.

This helper populates the analytics backtest summary tables when using the
`migration/sql/local_backtest_stub.sql` scaffold. It is intended only for local
workflows.

Usage:
    docker compose exec web python scripts/process_backtest_stub.py [--run-id UUID]
"""

from __future__ import annotations

import argparse
import asyncio
import os
from typing import Iterable

import asyncpg

PLACEHOLDER_N_WINDOWS = 12
PLACEHOLDER_MAPE_BASE = 18.0
PLACEHOLDER_RMSE_BASE = 9.0


async def _connect() -> asyncpg.Connection:
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        raise SystemExit("DATABASE_URL must be set in the environment")
    return await asyncpg.connect(database_url)


def _fake_metrics(horizon: int) -> tuple[float, float, bool]:
    h = max(horizon, 1)
    mape = PLACEHOLDER_MAPE_BASE + 2.5 * (h - 1)
    rmse = PLACEHOLDER_RMSE_BASE + 1.5 * (h - 1)
    beats = h <= 3
    return mape, rmse, beats


async def _resolve_run_id(conn: asyncpg.Connection, run_id: str | None) -> str | None:
    if run_id:
        return run_id
    row = await conn.fetchrow(
        """
        SELECT run_id
        FROM core.backtest_run_queue
        WHERE status IN ('PENDING', 'RUNNING')
        ORDER BY enqueued_at DESC
        LIMIT 1
        """
    )
    return str(row["run_id"]) if row else None


async def _load_pending_jobs(
    conn: asyncpg.Connection, run_id: str
) -> Iterable[asyncpg.Record]:
    return await conn.fetch(
        """
        SELECT item_id, horizon
        FROM core.backtest_job_queue
        WHERE run_id = $1 AND status = 'PENDING'
        ORDER BY item_id, horizon
        """,
        run_id,
    )


async def _upsert_item_summary(
    conn: asyncpg.Connection,
    run_id: str,
    item_id: str,
    horizon: int,
) -> None:
    mape, rmse, beats = _fake_metrics(horizon)
    await conn.execute(
        """
        INSERT INTO analytics.backtest_item_summary (
            run_id, item_id, model_name, horizon_months,
            n_windows, n_windows_mape_den, mape, rmse, beats_benchmark
        )
        VALUES ($1, $2, 'TSB', $3, $4, $4, $5, $6, $7)
        ON CONFLICT (run_id, item_id, model_name, horizon_months)
        DO UPDATE SET
            n_windows = EXCLUDED.n_windows,
            n_windows_mape_den = EXCLUDED.n_windows_mape_den,
            mape = EXCLUDED.mape,
            rmse = EXCLUDED.rmse,
            beats_benchmark = EXCLUDED.beats_benchmark,
            created_at = now()
        """,
        run_id,
        item_id,
        horizon,
        PLACEHOLDER_N_WINDOWS,
        mape,
        rmse,
        beats,
    )


async def _mark_job_complete(
    conn: asyncpg.Connection, run_id: str, item_id: str, horizon: int
) -> None:
    await conn.execute(
        """
        UPDATE core.backtest_job_queue
        SET status = 'COMPLETE', finished_at = now()
        WHERE run_id = $1 AND item_id = $2 AND horizon = $3
        """,
        run_id,
        item_id,
        horizon,
    )


async def _write_overall_summary(conn: asyncpg.Connection, run_id: str) -> None:
    await conn.execute(
        """
        INSERT INTO analytics.backtest_overall_summary (
            run_id,
            horizon_months,
            items_evaluated,
            pct_items_mape_lt_30,
            pct_items_beating_sn,
            mean_mape,
            mean_rmse
        )
        SELECT
            $1,
            horizon_months,
            COUNT(*) AS items_evaluated,
            100.0,
            100.0,
            AVG(mape)::numeric,
            AVG(rmse)::numeric
        FROM analytics.backtest_item_summary
        WHERE run_id = $1
        GROUP BY horizon_months
        ON CONFLICT (run_id, horizon_months) DO UPDATE SET
            items_evaluated = EXCLUDED.items_evaluated,
            pct_items_mape_lt_30 = EXCLUDED.pct_items_mape_lt_30,
            pct_items_beating_sn = EXCLUDED.pct_items_beating_sn,
            mean_mape = EXCLUDED.mean_mape,
            mean_rmse = EXCLUDED.mean_rmse,
            created_at = now()
        """,
        run_id,
    )


async def _complete_run(conn: asyncpg.Connection, run_id: str) -> None:
    await conn.execute(
        """
        UPDATE core.backtest_run_queue
        SET status = 'COMPLETE', finished_at = now()
        WHERE run_id = $1
        """,
        run_id,
    )


async def process_backtest_stub(run_id: str | None) -> None:
    conn = await _connect()
    try:
        resolved = await _resolve_run_id(conn, run_id)
        if not resolved:
            print("No pending backtest runs to process.")
            return

        jobs = await _load_pending_jobs(conn, resolved)
        if not jobs:
            print(f"Run {resolved} has no pending jobs.")
            await _complete_run(conn, resolved)
            return

        for job in jobs:
            item_id = job["item_id"]
            horizon = int(job["horizon"])
            await _upsert_item_summary(conn, resolved, item_id, horizon)
            await _mark_job_complete(conn, resolved, item_id, horizon)

        await _write_overall_summary(conn, resolved)
        await _complete_run(conn, resolved)
        print(f"Backtest summary populated for run {resolved}.")
    finally:
        await conn.close()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Populate stub backtest metrics.")
    parser.add_argument(
        "--run-id",
        dest="run_id",
        help="Specific backtest run identifier. Defaults to the latest pending run.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    asyncio.run(process_backtest_stub(args.run_id))


if __name__ == "__main__":
    main()
