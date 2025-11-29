"""Alert generation triggers for various system events."""

import logging
from typing import Any
from uuid import UUID

import asyncpg

from app.services.alert_service import AlertService

logger = logging.getLogger(__name__)


class AlertTriggers:
    """Triggers for generating alerts based on system events."""

    def __init__(self, connection: asyncpg.Connection):
        """Initialize alert triggers with database connection."""
        self.conn = connection
        self.service = AlertService(connection)

    async def trigger_forecast_ready(
        self,
        user_ids: list[str],
        run_id: UUID,
        items_count: int,
        horizons: list[int],
    ) -> int:
        """
        Trigger alerts when a new forecast is ready.
        
        Args:
            user_ids: List of user IDs to notify
            run_id: Forecast run UUID
            items_count: Number of items forecasted
            horizons: List of forecast horizons
            
        Returns:
            Number of alerts created
        """
        created_count = 0
        
        for user_id in user_ids:
            try:
                await self.service.create_alert_from_template(
                    user_id=user_id,
                    template_id="forecast_ready",
                    variables={
                        "run_id": str(run_id),
                        "items_count": str(items_count),
                        "horizons": ", ".join(str(h) for h in horizons),
                    },
                    action_url=f"/items?run_id={run_id}",
                    expires_hours=168,  # 7 days
                )
                created_count += 1
            except Exception as e:
                logger.error(f"Failed to create forecast_ready alert for {user_id}: {e}")
        
        return created_count

    async def trigger_high_demand_spike(
        self,
        user_ids: list[str],
        items: list[dict[str, Any]],
        threshold_pct: float = 50.0,
    ) -> int:
        """
        Trigger alerts for items with significant demand spikes.
        
        Args:
            user_ids: List of user IDs to notify
            items: List of items with demand spikes (item_id, spike_pct)
            threshold_pct: Spike threshold percentage
            
        Returns:
            Number of alerts created
        """
        if not items:
            return 0
        
        created_count = 0
        item_ids = [item["item_id"] for item in items[:10]]  # Top 10
        
        for user_id in user_ids:
            try:
                await self.service.create_alert_from_template(
                    user_id=user_id,
                    template_id="high_demand_spike",
                    variables={
                        "items_count": str(len(items)),
                        "threshold": f"{threshold_pct:.0f}",
                    },
                    action_url=f"/items?item_ids={','.join(item_ids)}",
                    expires_hours=72,  # 3 days
                )
                created_count += 1
            except Exception as e:
                logger.error(f"Failed to create demand_spike alert for {user_id}: {e}")
        
        return created_count

    async def trigger_stockout_risk(
        self,
        user_ids: list[str],
        at_risk_items: list[dict[str, Any]],
    ) -> int:
        """
        Trigger critical alerts for items at risk of stockout.
        
        Args:
            user_ids: List of user IDs to notify
            at_risk_items: List of items at risk (item_id, risk_score)
            
        Returns:
            Number of alerts created
        """
        if not at_risk_items:
            return 0
        
        created_count = 0
        item_ids = [item["item_id"] for item in at_risk_items[:20]]  # Top 20
        
        for user_id in user_ids:
            try:
                await self.service.create_alert_from_template(
                    user_id=user_id,
                    template_id="stockout_risk",
                    variables={
                        "items_count": str(len(at_risk_items)),
                    },
                    action_url=f"/purchase-plan?filter=at_risk&item_ids={','.join(item_ids)}",
                    expires_hours=48,  # 2 days
                )
                created_count += 1
            except Exception as e:
                logger.error(f"Failed to create stockout_risk alert for {user_id}: {e}")
        
        return created_count

    async def trigger_weekly_digest(
        self,
        user_ids: list[str],
        top_items: list[dict[str, Any]],
        total_qty: float,
    ) -> int:
        """
        Trigger weekly digest alerts with top priority items.
        
        Args:
            user_ids: List of user IDs to notify
            top_items: List of top priority items
            total_qty: Total suggested quantity
            
        Returns:
            Number of alerts created
        """
        if not top_items:
            return 0
        
        created_count = 0
        
        for user_id in user_ids:
            try:
                await self.service.create_alert_from_template(
                    user_id=user_id,
                    template_id="weekly_digest",
                    variables={
                        "items_count": str(len(top_items)),
                        "total_qty": f"{total_qty:,.0f}",
                    },
                    action_url="/purchase-plan",
                    expires_hours=168,  # 7 days
                )
                created_count += 1
            except Exception as e:
                logger.error(f"Failed to create weekly_digest alert for {user_id}: {e}")
        
        return created_count

    async def trigger_model_performance_alert(
        self,
        user_ids: list[str],
        items_count: int,
        mape_change: float,
    ) -> int:
        """
        Trigger alerts when model performance degrades.
        
        Args:
            user_ids: List of user IDs to notify
            items_count: Number of items affected
            mape_change: MAPE percentage change
            
        Returns:
            Number of alerts created
        """
        created_count = 0
        
        for user_id in user_ids:
            try:
                await self.service.create_alert_from_template(
                    user_id=user_id,
                    template_id="model_performance",
                    variables={
                        "items_count": str(items_count),
                        "mape_change": f"{mape_change:.1f}",
                    },
                    action_url="/backtest",
                    expires_hours=168,  # 7 days
                )
                created_count += 1
            except Exception as e:
                logger.error(f"Failed to create model_performance alert for {user_id}: {e}")
        
        return created_count

    async def trigger_data_quality_issue(
        self,
        user_ids: list[str],
        issues_count: int,
        issue_types: list[str],
    ) -> int:
        """
        Trigger alerts for data quality issues.
        
        Args:
            user_ids: List of user IDs to notify
            issues_count: Number of issues detected
            issue_types: Types of issues found
            
        Returns:
            Number of alerts created
        """
        created_count = 0
        
        for user_id in user_ids:
            try:
                await self.service.create_alert_from_template(
                    user_id=user_id,
                    template_id="data_quality",
                    variables={
                        "issues_count": str(issues_count),
                        "issue_types": ", ".join(issue_types),
                    },
                    action_url="/data-quality",
                    expires_hours=72,  # 3 days
                )
                created_count += 1
            except Exception as e:
                logger.error(f"Failed to create data_quality alert for {user_id}: {e}")
        
        return created_count

    async def trigger_pipeline_failure(
        self,
        user_ids: list[str],
        stage: str,
        error_message: str,
    ) -> int:
        """
        Trigger critical alerts when pipeline fails.
        
        Args:
            user_ids: List of user IDs to notify
            stage: Pipeline stage that failed
            error_message: Error message
            
        Returns:
            Number of alerts created
        """
        created_count = 0
        
        for user_id in user_ids:
            try:
                await self.service.create_alert_from_template(
                    user_id=user_id,
                    template_id="pipeline_failure",
                    variables={
                        "stage": stage,
                        "error_message": error_message[:200],  # Truncate
                    },
                    action_url="/admin/logs",
                    expires_hours=24,  # 1 day
                )
                created_count += 1
            except Exception as e:
                logger.error(f"Failed to create pipeline_failure alert for {user_id}: {e}")
        
        return created_count

    async def get_active_users(self) -> list[str]:
        """
        Get list of active user IDs who should receive alerts.
        
        Returns:
            List of user IDs with in_app_enabled=true
        """
        rows = await self.conn.fetch(
            """
            SELECT user_id FROM alerts.user_preferences
            WHERE in_app_enabled = true
            """
        )
        
        return [row["user_id"] for row in rows]
