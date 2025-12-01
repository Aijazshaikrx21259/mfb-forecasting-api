"""Alert service for managing user notifications."""

from datetime import datetime, timedelta
from typing import Any
from uuid import UUID

import asyncpg

from app.models.alerts import (
    AlertCreate,
    AlertPriority,
    AlertResponse,
    AlertStatus,
    AlertType,
    AlertPreferencesResponse,
    AlertPreferencesUpdate,
)


class AlertService:
    """Service for alert operations."""

    def __init__(self, connection: asyncpg.Connection):
        """Initialize alert service with database connection."""
        self.conn = connection

    async def create_alert(self, alert: AlertCreate) -> AlertResponse:
        """Create a new alert for a user."""
        expires_at = None
        if alert.expires_hours:
            expires_at = datetime.utcnow() + timedelta(hours=alert.expires_hours)

        row = await self.conn.fetchrow(
            """
            INSERT INTO alerts.user_alerts (
                user_id, alert_type, priority, title, message,
                metadata, action_url, action_label, expires_at
            ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
            RETURNING *
            """,
            alert.user_id,
            alert.alert_type.value,
            alert.priority.value,
            alert.title,
            alert.message,
            alert.metadata,
            alert.action_url,
            alert.action_label,
            expires_at,
        )

        return self._row_to_alert(row)

    async def create_alert_from_template(
        self,
        user_id: str,
        template_id: str,
        variables: dict[str, Any],
        action_url: str | None = None,
        expires_hours: int = 168,
    ) -> AlertResponse:
        """Create an alert using a template."""
        alert_id = await self.conn.fetchval(
            """
            SELECT alerts.create_alert_from_template($1, $2, $3, $4, $5)
            """,
            user_id,
            template_id,
            variables,
            action_url,
            expires_hours,
        )

        row = await self.conn.fetchrow(
            """
            SELECT * FROM alerts.user_alerts WHERE alert_id = $1
            """,
            alert_id,
        )

        return self._row_to_alert(row)

    async def get_alert(self, alert_id: UUID, user_id: str) -> AlertResponse | None:
        """Get a specific alert by ID."""
        row = await self.conn.fetchrow(
            """
            SELECT * FROM alerts.user_alerts
            WHERE alert_id = $1 AND user_id = $2
            """,
            alert_id,
            user_id,
        )

        return self._row_to_alert(row) if row else None

    async def list_alerts(
        self,
        user_id: str,
        status: AlertStatus | None = None,
        alert_type: AlertType | None = None,
        priority: AlertPriority | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[AlertResponse], int]:
        """List alerts for a user with filters."""
        conditions = ["user_id = $1"]
        params: list[Any] = [user_id]
        param_idx = 2

        if status:
            conditions.append(f"status = ${param_idx}")
            params.append(status.value)
            param_idx += 1

        if alert_type:
            conditions.append(f"alert_type = ${param_idx}")
            params.append(alert_type.value)
            param_idx += 1

        if priority:
            conditions.append(f"priority = ${param_idx}")
            params.append(priority.value)
            param_idx += 1

        where_clause = " AND ".join(conditions)

        # Get total count
        total = await self.conn.fetchval(
            f"SELECT COUNT(*) FROM alerts.user_alerts WHERE {where_clause}",
            *params,
        )

        # Get paginated results
        params.extend([limit, offset])
        rows = await self.conn.fetch(
            f"""
            SELECT * FROM alerts.user_alerts
            WHERE {where_clause}
            ORDER BY created_at DESC
            LIMIT ${param_idx} OFFSET ${param_idx + 1}
            """,
            *params,
        )

        alerts = [self._row_to_alert(row) for row in rows]
        return alerts, total

    async def update_alert_status(
        self, alert_id: UUID, user_id: str, status: AlertStatus
    ) -> AlertResponse | None:
        """Update alert status."""
        now = datetime.utcnow()
        read_at = now if status == AlertStatus.READ else None
        dismissed_at = now if status == AlertStatus.DISMISSED else None

        row = await self.conn.fetchrow(
            """
            UPDATE alerts.user_alerts
            SET status = $1,
                read_at = COALESCE(read_at, $2),
                dismissed_at = $3
            WHERE alert_id = $4 AND user_id = $5
            RETURNING *
            """,
            status.value,
            read_at,
            dismissed_at,
            alert_id,
            user_id,
        )

        return self._row_to_alert(row) if row else None

    async def mark_all_as_read(self, user_id: str) -> int:
        """Mark all unread alerts as read for a user."""
        result = await self.conn.execute(
            """
            UPDATE alerts.user_alerts
            SET status = 'READ', read_at = NOW()
            WHERE user_id = $1 AND status = 'UNREAD'
            """,
            user_id,
        )
        # Extract count from result string like "UPDATE 5"
        return int(result.split()[-1]) if result else 0

    async def delete_alert(self, alert_id: UUID, user_id: str) -> bool:
        """Delete an alert."""
        result = await self.conn.execute(
            """
            DELETE FROM alerts.user_alerts
            WHERE alert_id = $1 AND user_id = $2
            """,
            alert_id,
            user_id,
        )
        return result.split()[-1] == "1"

    async def get_unread_count(self, user_id: str) -> int:
        """Get count of unread alerts for a user."""
        return await self.conn.fetchval(
            """
            SELECT COUNT(*) FROM alerts.user_alerts
            WHERE user_id = $1 AND status = 'UNREAD'
            """,
            user_id,
        )

    async def archive_expired_alerts(self) -> int:
        """Archive all expired alerts."""
        return await self.conn.fetchval(
            """
            SELECT alerts.archive_expired_alerts()
            """
        )

    async def get_preferences(self, user_id: str) -> AlertPreferencesResponse | None:
        """Get alert preferences for a user."""
        row = await self.conn.fetchrow(
            """
            SELECT * FROM alerts.user_preferences WHERE user_id = $1
            """,
            user_id,
        )

        if not row:
            return None

        return AlertPreferencesResponse(
            user_id=row["user_id"],
            enabled_alert_types=[AlertType(t) for t in row["enabled_alert_types"]],
            min_priority=AlertPriority(row["min_priority"]),
            weekly_digest_enabled=row["weekly_digest_enabled"],
            weekly_digest_day=row["weekly_digest_day"],
            in_app_enabled=row["in_app_enabled"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    async def update_preferences(
        self, user_id: str, preferences: AlertPreferencesUpdate
    ) -> AlertPreferencesResponse:
        """Update alert preferences for a user."""
        # Build update query dynamically
        updates = []
        params: list[Any] = []
        param_idx = 1

        if preferences.enabled_alert_types is not None:
            updates.append(f"enabled_alert_types = ${param_idx}")
            params.append([t.value for t in preferences.enabled_alert_types])
            param_idx += 1

        if preferences.min_priority is not None:
            updates.append(f"min_priority = ${param_idx}")
            params.append(preferences.min_priority.value)
            param_idx += 1

        if preferences.weekly_digest_enabled is not None:
            updates.append(f"weekly_digest_enabled = ${param_idx}")
            params.append(preferences.weekly_digest_enabled)
            param_idx += 1

        if preferences.weekly_digest_day is not None:
            updates.append(f"weekly_digest_day = ${param_idx}")
            params.append(preferences.weekly_digest_day)
            param_idx += 1

        if preferences.in_app_enabled is not None:
            updates.append(f"in_app_enabled = ${param_idx}")
            params.append(preferences.in_app_enabled)
            param_idx += 1

        if not updates:
            # No updates, just return current preferences
            return await self.get_preferences(user_id)

        updates.append("updated_at = NOW()")
        params.append(user_id)

        row = await self.conn.fetchrow(
            f"""
            INSERT INTO alerts.user_preferences (user_id)
            VALUES (${param_idx})
            ON CONFLICT (user_id) DO UPDATE SET
                {', '.join(updates)}
            RETURNING *
            """,
            *params,
        )

        return AlertPreferencesResponse(
            user_id=row["user_id"],
            enabled_alert_types=[AlertType(t) for t in row["enabled_alert_types"]],
            min_priority=AlertPriority(row["min_priority"]),
            weekly_digest_enabled=row["weekly_digest_enabled"],
            weekly_digest_day=row["weekly_digest_day"],
            in_app_enabled=row["in_app_enabled"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    def _row_to_alert(self, row: asyncpg.Record) -> AlertResponse:
        """Convert database row to AlertResponse."""
        import json
        
        # Parse metadata if it's a JSON string
        metadata = row["metadata"]
        if isinstance(metadata, str):
            try:
                metadata = json.loads(metadata)
            except (json.JSONDecodeError, TypeError):
                metadata = None
        
        return AlertResponse(
            alert_id=row["alert_id"],
            user_id=row["user_id"],
            alert_type=AlertType(row["alert_type"]),
            priority=AlertPriority(row["priority"]),
            status=AlertStatus(row["status"]),
            title=row["title"],
            message=row["message"],
            metadata=metadata,
            action_url=row["action_url"],
            action_label=row["action_label"],
            created_at=row["created_at"],
            read_at=row["read_at"],
            dismissed_at=row["dismissed_at"],
            expires_at=row["expires_at"],
        )
