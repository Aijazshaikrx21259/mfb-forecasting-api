"""Service for managing forecast adjustments."""

from datetime import date, datetime
from typing import Any
from uuid import UUID

import asyncpg

from app.models.adjustments import (
    AdjustmentCreate,
    AdjustmentResponse,
    AdjustmentUpdate,
    AdjustmentReview,
    AdjustmentStatus,
    AdjustmentHistoryEntry,
    AdjustmentTemplate,
)


class AdjustmentService:
    """Service for forecast adjustment operations."""

    def __init__(self, connection: asyncpg.Connection):
        """Initialize adjustment service with database connection."""
        self.conn = connection

    async def create_adjustment(self, adjustment: AdjustmentCreate) -> AdjustmentResponse:
        """Create a new forecast adjustment."""
        row = await self.conn.fetchrow(
            """
            INSERT INTO adjustments.forecast_adjustments (
                item_id, run_id, horizon, period_start_date,
                original_p50, original_p10, original_p90, original_method,
                adjusted_p50, adjusted_p10, adjusted_p90,
                adjustment_reason, notes, confidence_level, adjusted_by
            ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14, $15)
            RETURNING *
            """,
            adjustment.item_id,
            adjustment.run_id,
            adjustment.horizon,
            adjustment.period_start_date,
            adjustment.original_p50,
            adjustment.original_p10,
            adjustment.original_p90,
            adjustment.original_method,
            adjustment.adjusted_p50,
            adjustment.adjusted_p10,
            adjustment.adjusted_p90,
            adjustment.adjustment_reason,
            adjustment.notes,
            adjustment.confidence_level,
            adjustment.adjusted_by,
        )

        return self._row_to_adjustment(row)

    async def get_adjustment(self, adjustment_id: UUID) -> AdjustmentResponse | None:
        """Get a specific adjustment by ID."""
        row = await self.conn.fetchrow(
            """
            SELECT * FROM adjustments.forecast_adjustments
            WHERE adjustment_id = $1
            """,
            adjustment_id,
        )

        return self._row_to_adjustment(row) if row else None

    async def list_adjustments(
        self,
        item_id: str | None = None,
        run_id: UUID | None = None,
        status: AdjustmentStatus | None = None,
        adjusted_by: str | None = None,
        period_start_date: date | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[AdjustmentResponse], int]:
        """List adjustments with filters."""
        conditions = []
        params: list[Any] = []
        param_idx = 1

        if item_id:
            conditions.append(f"item_id = ${param_idx}")
            params.append(item_id)
            param_idx += 1

        if run_id:
            conditions.append(f"run_id = ${param_idx}")
            params.append(run_id)
            param_idx += 1

        if status:
            conditions.append(f"status = ${param_idx}")
            params.append(status.value)
            param_idx += 1

        if adjusted_by:
            conditions.append(f"adjusted_by = ${param_idx}")
            params.append(adjusted_by)
            param_idx += 1

        if period_start_date:
            conditions.append(f"period_start_date = ${param_idx}")
            params.append(period_start_date)
            param_idx += 1

        where_clause = " AND ".join(conditions) if conditions else "TRUE"

        # Get total count
        total = await self.conn.fetchval(
            f"SELECT COUNT(*) FROM adjustments.forecast_adjustments WHERE {where_clause}",
            *params,
        )

        # Get paginated results
        params.extend([limit, offset])
        rows = await self.conn.fetch(
            f"""
            SELECT * FROM adjustments.forecast_adjustments
            WHERE {where_clause}
            ORDER BY created_at DESC
            LIMIT ${param_idx} OFFSET ${param_idx + 1}
            """,
            *params,
        )

        adjustments = [self._row_to_adjustment(row) for row in rows]
        return adjustments, total

    async def update_adjustment(
        self, adjustment_id: UUID, update: AdjustmentUpdate
    ) -> AdjustmentResponse | None:
        """Update an adjustment."""
        updates = []
        params: list[Any] = []
        param_idx = 1

        if update.adjusted_p50 is not None:
            updates.append(f"adjusted_p50 = ${param_idx}")
            params.append(update.adjusted_p50)
            param_idx += 1

        if update.adjusted_p10 is not None:
            updates.append(f"adjusted_p10 = ${param_idx}")
            params.append(update.adjusted_p10)
            param_idx += 1

        if update.adjusted_p90 is not None:
            updates.append(f"adjusted_p90 = ${param_idx}")
            params.append(update.adjusted_p90)
            param_idx += 1

        if update.adjustment_reason is not None:
            updates.append(f"adjustment_reason = ${param_idx}")
            params.append(update.adjustment_reason)
            param_idx += 1

        if update.notes is not None:
            updates.append(f"notes = ${param_idx}")
            params.append(update.notes)
            param_idx += 1

        if update.confidence_level is not None:
            updates.append(f"confidence_level = ${param_idx}")
            params.append(update.confidence_level)
            param_idx += 1

        if not updates:
            return await self.get_adjustment(adjustment_id)

        updates.append("updated_at = NOW()")
        params.append(adjustment_id)

        row = await self.conn.fetchrow(
            f"""
            UPDATE adjustments.forecast_adjustments
            SET {', '.join(updates)}
            WHERE adjustment_id = ${param_idx}
            RETURNING *
            """,
            *params,
        )

        return self._row_to_adjustment(row) if row else None

    async def review_adjustment(
        self, adjustment_id: UUID, review: AdjustmentReview
    ) -> AdjustmentResponse | None:
        """Review an adjustment (approve or reject)."""
        row = await self.conn.fetchrow(
            """
            UPDATE adjustments.forecast_adjustments
            SET status = $1,
                reviewed_by = $2,
                reviewed_at = NOW(),
                review_notes = $3,
                updated_at = NOW()
            WHERE adjustment_id = $4
            RETURNING *
            """,
            review.status.value,
            review.reviewed_by,
            review.review_notes,
            adjustment_id,
        )

        return self._row_to_adjustment(row) if row else None

    async def delete_adjustment(self, adjustment_id: UUID) -> bool:
        """Delete an adjustment."""
        result = await self.conn.execute(
            """
            DELETE FROM adjustments.forecast_adjustments
            WHERE adjustment_id = $1
            """,
            adjustment_id,
        )
        return result.split()[-1] == "1"

    async def get_adjustment_history(
        self, adjustment_id: UUID
    ) -> list[AdjustmentHistoryEntry]:
        """Get history of changes for an adjustment."""
        rows = await self.conn.fetch(
            """
            SELECT * FROM adjustments.adjustment_history
            WHERE adjustment_id = $1
            ORDER BY changed_at DESC
            """,
            adjustment_id,
        )

        return [self._row_to_history(row) for row in rows]

    async def get_active_adjustment(
        self, item_id: str, period_start_date: date, run_id: UUID | None = None
    ) -> AdjustmentResponse | None:
        """Get the active (approved) adjustment for an item/period."""
        row = await self.conn.fetchrow(
            """
            SELECT * FROM adjustments.get_active_adjustment($1, $2, $3)
            """,
            item_id,
            period_start_date,
            run_id,
        )

        if not row:
            return None

        # Fetch full adjustment details
        return await self.get_adjustment(row["adjustment_id"])

    async def list_templates(self) -> list[AdjustmentTemplate]:
        """List all adjustment templates."""
        rows = await self.conn.fetch(
            """
            SELECT * FROM adjustments.adjustment_templates
            ORDER BY template_name
            """
        )

        return [self._row_to_template(row) for row in rows]

    async def get_template(self, template_id: str) -> AdjustmentTemplate | None:
        """Get a specific adjustment template."""
        row = await self.conn.fetchrow(
            """
            SELECT * FROM adjustments.adjustment_templates
            WHERE template_id = $1
            """,
            template_id,
        )

        return self._row_to_template(row) if row else None

    async def apply_template(
        self,
        template_id: str,
        item_id: str,
        run_id: UUID,
        horizon: int,
        period_start_date: date,
        original_p50: float,
        adjusted_by: str,
    ) -> AdjustmentResponse:
        """Apply a template to create an adjustment."""
        template = await self.get_template(template_id)
        if not template:
            raise ValueError(f"Template {template_id} not found")

        # Calculate adjusted value based on template
        if template.adjustment_type == "PERCENTAGE":
            adjusted_p50 = original_p50 * (1 + (template.adjustment_value or 0) / 100)
        elif template.adjustment_type == "ABSOLUTE":
            adjusted_p50 = template.adjustment_value or 0
        else:
            adjusted_p50 = original_p50  # Default to original

        adjustment = AdjustmentCreate(
            item_id=item_id,
            run_id=run_id,
            horizon=horizon,
            period_start_date=period_start_date,
            original_p50=original_p50,
            adjusted_p50=max(0, adjusted_p50),  # Ensure non-negative
            adjustment_reason=template.default_reason or "Applied template",
            confidence_level=template.default_confidence,
            adjusted_by=adjusted_by,
        )

        return await self.create_adjustment(adjustment)

    def _row_to_adjustment(self, row: asyncpg.Record) -> AdjustmentResponse:
        """Convert database row to AdjustmentResponse."""
        return AdjustmentResponse(
            adjustment_id=row["adjustment_id"],
            item_id=row["item_id"],
            run_id=row["run_id"],
            horizon=row["horizon"],
            period_start_date=row["period_start_date"],
            original_p50=row["original_p50"],
            original_p10=row["original_p10"],
            original_p90=row["original_p90"],
            original_method=row["original_method"],
            adjusted_p50=row["adjusted_p50"],
            adjusted_p10=row["adjusted_p10"],
            adjusted_p90=row["adjusted_p90"],
            adjustment_reason=row["adjustment_reason"],
            notes=row["notes"],
            confidence_level=row["confidence_level"],
            adjusted_by=row["adjusted_by"],
            adjusted_at=row["adjusted_at"],
            status=AdjustmentStatus(row["status"]),
            reviewed_by=row["reviewed_by"],
            reviewed_at=row["reviewed_at"],
            review_notes=row["review_notes"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    def _row_to_history(self, row: asyncpg.Record) -> AdjustmentHistoryEntry:
        """Convert database row to AdjustmentHistoryEntry."""
        return AdjustmentHistoryEntry(
            history_id=row["history_id"],
            adjustment_id=row["adjustment_id"],
            field_name=row["field_name"],
            old_value=row["old_value"],
            new_value=row["new_value"],
            changed_by=row["changed_by"],
            changed_at=row["changed_at"],
            change_reason=row["change_reason"],
        )

    def _row_to_template(self, row: asyncpg.Record) -> AdjustmentTemplate:
        """Convert database row to AdjustmentTemplate."""
        return AdjustmentTemplate(
            template_id=row["template_id"],
            template_name=row["template_name"],
            description=row["description"],
            adjustment_type=row["adjustment_type"],
            adjustment_value=row["adjustment_value"],
            adjustment_formula=row["adjustment_formula"],
            default_reason=row["default_reason"],
            default_confidence=row["default_confidence"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )
