"""Data quality management endpoints."""

from __future__ import annotations

import re
from datetime import datetime
from enum import Enum
from typing import Any
from uuid import UUID

import asyncpg
from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict, field_validator

from app.db import get_db_connection
from app.security import verify_api_key


class FlagType(str, Enum):
    ANOMALY = "ANOMALY"
    STOCKOUT = "STOCKOUT"
    BAD_DATA = "BAD_DATA"
    MANUAL_EXCLUDE = "MANUAL_EXCLUDE"


class MonthFlagCreate(BaseModel):
    month_key: str
    agency_internal_id: str | None = None
    item_id: str | None = None
    flag_type: FlagType
    flag_reason: str | None = None
    expires_at_utc: datetime | None = None

    model_config = ConfigDict(str_strip_whitespace=True)

    @field_validator("month_key")
    @classmethod
    def validate_month_key(cls, value: str) -> str:
        if not re.fullmatch(r"\d{4}-\d{2}", value):
            msg = "month_key must follow YYYY-MM format"
            raise ValueError(msg)
        return value


class MonthFlagResponse(BaseModel):
    flag_id: UUID
    month_key: str
    agency_internal_id: str | None
    item_id: str | None
    flag_type: FlagType
    flag_level: str
    flag_reason: str | None
    flagged_by: str
    flagged_at_utc: datetime
    expires_at_utc: datetime | None
    is_active: bool
    detected_issue_id: UUID | None


class DeactivateRequest(BaseModel):
    flag_id: UUID


class CandidateResponse(BaseModel):
    candidate_id: UUID
    month_key: str
    agency_internal_id: str | None
    item_id: str | None
    flag_type: FlagType
    flag_level: str
    flag_reason: str | None
    detected_rule: str | None
    detected_score: float | None
    detected_at_utc: datetime


router = APIRouter(
    prefix="/api/data-quality",
    tags=["data-quality"],
    dependencies=[Depends(verify_api_key)],
)


def _determine_flag_level(agency_internal_id: str | None, item_id: str | None) -> str:
    if agency_internal_id and item_id:
        return "AGENCY_ITEM"
    if agency_internal_id:
        return "AGENCY"
    if item_id:
        return "ITEM"
    return "GLOBAL"


async def _fetch_flag_record(record: asyncpg.Record | None) -> MonthFlagResponse:
    if record is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Flag not found")
    payload: dict[str, Any] = dict(record)
    return MonthFlagResponse(**payload)


@router.post("/flags", response_model=MonthFlagResponse, status_code=status.HTTP_201_CREATED)
async def create_month_flag(
    request: MonthFlagCreate,
    connection: asyncpg.Connection = Depends(get_db_connection),
) -> MonthFlagResponse:
    """Create or update a manual month quality flag."""

    flag_level = _determine_flag_level(request.agency_internal_id, request.item_id)

    appended_reason = request.flag_reason.strip() if request.flag_reason else "Manual exclusion"
    system_row = await connection.fetchrow(
        """
        SELECT flag_id, flag_reason
        FROM analytics.month_quality_flag
        WHERE month_key = $1
          AND COALESCE(agency_internal_id, '') = COALESCE($2, '')
          AND COALESCE(item_id, '') = COALESCE($3, '')
          AND flagged_by = 'SYSTEM'
          AND is_active = TRUE
        ORDER BY flagged_at_utc DESC
        LIMIT 1
        """,
        request.month_key,
        request.agency_internal_id,
        request.item_id,
    )

    if system_row and system_row.get("flag_reason"):
        appended_reason = f"{appended_reason} | system: {system_row['flag_reason']}"

    if system_row:
        await connection.execute(
            "UPDATE analytics.month_quality_flag SET is_active = FALSE WHERE flag_id = $1",
            system_row["flag_id"],
        )

    record = await connection.fetchrow(
        """
        INSERT INTO analytics.month_quality_flag (
            month_key,
            agency_internal_id,
            item_id,
            flag_type,
            flag_level,
            flag_reason,
            flagged_by,
            flagged_at_utc,
            expires_at_utc,
            is_active
        )
        VALUES ($1, $2, $3, $4, $5, $6, 'USER', now(), $7, TRUE)
        ON CONFLICT (scope_key) DO UPDATE
        SET
            flag_type = EXCLUDED.flag_type,
            flag_level = EXCLUDED.flag_level,
            flag_reason = EXCLUDED.flag_reason,
            flagged_at_utc = now(),
            expires_at_utc = EXCLUDED.expires_at_utc,
            is_active = TRUE,
            flagged_by = 'USER'
        RETURNING *
        """,
        request.month_key,
        request.agency_internal_id,
        request.item_id,
        request.flag_type.value,
        flag_level,
        appended_reason,
        request.expires_at_utc,
    )

    return await _fetch_flag_record(record)


@router.get("/flags", response_model=list[MonthFlagResponse])
async def list_month_flags(
    month_key: str | None = Query(default=None, description="Filter by month key (YYYY-MM)."),
    agency_internal_id: str | None = Query(default=None, description="Filter by agency identifier."),
    item_id: str | None = Query(default=None, description="Filter by item identifier."),
    include_inactive: bool = Query(default=False, description="Include inactive flags."),
    connection: asyncpg.Connection = Depends(get_db_connection),
) -> list[MonthFlagResponse]:
    """Return matching quality flags."""

    records = await connection.fetch(
        """
        SELECT *
        FROM analytics.month_quality_flag
        WHERE ($1::text IS NULL OR month_key = $1)
          AND ($2::text IS NULL OR agency_internal_id = $2)
          AND ($3::text IS NULL OR item_id = $3)
          AND ($4::boolean OR is_active = TRUE)
        ORDER BY month_key DESC, flagged_at_utc DESC
        """,
        month_key,
        agency_internal_id,
        item_id,
        include_inactive,
    )

    return [MonthFlagResponse(**dict(record)) for record in records]


@router.post("/flags/deactivate", response_model=MonthFlagResponse)
async def deactivate_flag(
    request: DeactivateRequest,
    connection: asyncpg.Connection = Depends(get_db_connection),
) -> MonthFlagResponse:
    """Deactivate a specific flag by identifier."""

    record = await connection.fetchrow(
        """
        UPDATE analytics.month_quality_flag
        SET is_active = FALSE, flagged_at_utc = now()
        WHERE flag_id = $1
        RETURNING *
        """,
        request.flag_id,
    )

    return await _fetch_flag_record(record)


@router.get("/candidates", response_model=list[CandidateResponse])
async def list_anomaly_candidates(
    month_key: str | None = Query(default=None, description="Filter anomaly candidates by month key."),
    connection: asyncpg.Connection = Depends(get_db_connection),
) -> list[CandidateResponse]:
    """Expose system-generated anomaly candidates for review."""

    records = await connection.fetch(
        """
        SELECT *
        FROM analytics.system_anomaly_candidates
        WHERE ($1::text IS NULL OR month_key = $1)
        ORDER BY detected_at_utc DESC
        """,
        month_key,
    )

    result: list[CandidateResponse] = []
    for record in records:
        payload: dict[str, Any] = dict(record)
        if payload.get("detected_score") is not None:
            payload["detected_score"] = float(payload["detected_score"])
        result.append(CandidateResponse(**payload))
    return result


