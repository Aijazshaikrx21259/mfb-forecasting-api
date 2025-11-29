-- Alert system schema for in-app notifications
-- Replaces email notification system (US #11, #17)

CREATE SCHEMA IF NOT EXISTS alerts;

-- Alert types and priorities
CREATE TYPE alerts.alert_type AS ENUM (
    'FORECAST_READY',           -- New forecast run completed
    'HIGH_DEMAND_SPIKE',        -- Significant demand increase detected
    'LOW_DEMAND_DROP',          -- Significant demand decrease detected
    'STOCKOUT_RISK',            -- Item at risk of stockout
    'HIGH_PRIORITY_ITEMS',      -- Weekly digest of top priority items
    'MODEL_PERFORMANCE_ALERT',  -- Model accuracy degradation
    'DATA_QUALITY_ISSUE',       -- Data quality problems detected
    'PIPELINE_FAILURE',         -- Pipeline execution failed
    'SYSTEM_MAINTENANCE'        -- System maintenance notification
);

CREATE TYPE alerts.alert_priority AS ENUM (
    'LOW',
    'MEDIUM',
    'HIGH',
    'CRITICAL'
);

CREATE TYPE alerts.alert_status AS ENUM (
    'UNREAD',
    'READ',
    'DISMISSED',
    'ARCHIVED'
);

-- Main alerts table
CREATE TABLE IF NOT EXISTS alerts.user_alerts (
    alert_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id TEXT NOT NULL,  -- Clerk user ID or email
    alert_type alerts.alert_type NOT NULL,
    priority alerts.alert_priority NOT NULL DEFAULT 'MEDIUM',
    status alerts.alert_status NOT NULL DEFAULT 'UNREAD',
    
    title TEXT NOT NULL,
    message TEXT NOT NULL,
    metadata JSONB,  -- Additional context (item_ids, run_id, etc.)
    
    action_url TEXT,  -- Deep link to relevant page
    action_label TEXT,  -- Button text (e.g., "View Items", "Review Forecast")
    
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    read_at TIMESTAMPTZ,
    dismissed_at TIMESTAMPTZ,
    expires_at TIMESTAMPTZ,  -- Auto-archive after this date
    
    CONSTRAINT valid_read_timestamp CHECK (read_at IS NULL OR read_at >= created_at),
    CONSTRAINT valid_dismissed_timestamp CHECK (dismissed_at IS NULL OR dismissed_at >= created_at)
);

-- Alert preferences per user
CREATE TABLE IF NOT EXISTS alerts.user_preferences (
    user_id TEXT PRIMARY KEY,
    
    -- Enable/disable alert types
    enabled_alert_types alerts.alert_type[] NOT NULL DEFAULT ARRAY[
        'FORECAST_READY',
        'HIGH_DEMAND_SPIKE',
        'STOCKOUT_RISK',
        'HIGH_PRIORITY_ITEMS'
    ]::alerts.alert_type[],
    
    -- Minimum priority to show
    min_priority alerts.alert_priority NOT NULL DEFAULT 'MEDIUM',
    
    -- Digest preferences
    weekly_digest_enabled BOOLEAN NOT NULL DEFAULT TRUE,
    weekly_digest_day INTEGER NOT NULL DEFAULT 1,  -- 1=Monday, 7=Sunday
    
    -- Notification settings
    in_app_enabled BOOLEAN NOT NULL DEFAULT TRUE,
    
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Alert templates for consistent messaging
CREATE TABLE IF NOT EXISTS alerts.alert_templates (
    template_id TEXT PRIMARY KEY,
    alert_type alerts.alert_type NOT NULL,
    priority alerts.alert_priority NOT NULL,
    
    title_template TEXT NOT NULL,  -- Supports {{variable}} placeholders
    message_template TEXT NOT NULL,
    action_label TEXT,
    
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Indexes for performance
CREATE INDEX idx_user_alerts_user_status ON alerts.user_alerts(user_id, status) WHERE status IN ('UNREAD', 'READ');
CREATE INDEX idx_user_alerts_created_at ON alerts.user_alerts(created_at DESC);
CREATE INDEX idx_user_alerts_priority ON alerts.user_alerts(priority) WHERE status = 'UNREAD';
CREATE INDEX idx_user_alerts_type ON alerts.user_alerts(alert_type);
CREATE INDEX idx_user_alerts_expires ON alerts.user_alerts(expires_at) WHERE expires_at IS NOT NULL AND status != 'ARCHIVED';

-- Insert default templates
INSERT INTO alerts.alert_templates (template_id, alert_type, priority, title_template, message_template, action_label) VALUES
('forecast_ready', 'FORECAST_READY', 'MEDIUM', 
 'New Forecast Available', 
 'Forecast run {{run_id}} completed successfully. {{items_count}} items forecasted for horizons {{horizons}}.', 
 'View Forecast'),

('high_demand_spike', 'HIGH_DEMAND_SPIKE', 'HIGH', 
 'Demand Spike Detected', 
 '{{items_count}} items show significant demand increase (>{{threshold}}%). Review purchase plan to avoid stockouts.', 
 'Review Items'),

('stockout_risk', 'STOCKOUT_RISK', 'CRITICAL', 
 'Stockout Risk Alert', 
 '{{items_count}} items at risk of stockout next month. Immediate action recommended.', 
 'View At-Risk Items'),

('weekly_digest', 'HIGH_PRIORITY_ITEMS', 'MEDIUM', 
 'Weekly Purchase Planning Digest', 
 'Top {{items_count}} priority items for next month. Total suggested quantity: {{total_qty}} units.', 
 'View Purchase Plan'),

('model_performance', 'MODEL_PERFORMANCE_ALERT', 'HIGH', 
 'Model Performance Degradation', 
 'Forecast accuracy declined by {{mape_change}}% for {{items_count}} items. Model retraining recommended.', 
 'View Performance'),

('data_quality', 'DATA_QUALITY_ISSUE', 'HIGH', 
 'Data Quality Issues Detected', 
 '{{issues_count}} data quality issues found: {{issue_types}}. Review before next forecast run.', 
 'View Issues'),

('pipeline_failure', 'PIPELINE_FAILURE', 'CRITICAL', 
 'Forecast Pipeline Failed', 
 'Pipeline run failed at {{stage}} stage. Error: {{error_message}}', 
 'View Logs')
ON CONFLICT (template_id) DO NOTHING;

-- Function to auto-archive expired alerts
CREATE OR REPLACE FUNCTION alerts.archive_expired_alerts()
RETURNS INTEGER AS $$
DECLARE
    archived_count INTEGER;
BEGIN
    UPDATE alerts.user_alerts
    SET status = 'ARCHIVED'
    WHERE expires_at IS NOT NULL
      AND expires_at < NOW()
      AND status != 'ARCHIVED';
    
    GET DIAGNOSTICS archived_count = ROW_COUNT;
    RETURN archived_count;
END;
$$ LANGUAGE plpgsql;

-- Function to create alert from template
CREATE OR REPLACE FUNCTION alerts.create_alert_from_template(
    p_user_id TEXT,
    p_template_id TEXT,
    p_variables JSONB DEFAULT '{}'::JSONB,
    p_action_url TEXT DEFAULT NULL,
    p_expires_hours INTEGER DEFAULT 168  -- 7 days default
)
RETURNS UUID AS $$
DECLARE
    v_alert_id UUID;
    v_template RECORD;
    v_title TEXT;
    v_message TEXT;
    v_key TEXT;
    v_value TEXT;
BEGIN
    -- Get template
    SELECT * INTO v_template
    FROM alerts.alert_templates
    WHERE template_id = p_template_id;
    
    IF NOT FOUND THEN
        RAISE EXCEPTION 'Template % not found', p_template_id;
    END IF;
    
    -- Replace variables in title and message
    v_title := v_template.title_template;
    v_message := v_template.message_template;
    
    FOR v_key, v_value IN SELECT * FROM jsonb_each_text(p_variables)
    LOOP
        v_title := REPLACE(v_title, '{{' || v_key || '}}', v_value);
        v_message := REPLACE(v_message, '{{' || v_key || '}}', v_value);
    END LOOP;
    
    -- Create alert
    INSERT INTO alerts.user_alerts (
        user_id, alert_type, priority, title, message, metadata, action_url, action_label, expires_at
    ) VALUES (
        p_user_id,
        v_template.alert_type,
        v_template.priority,
        v_title,
        v_message,
        p_variables,
        p_action_url,
        v_template.action_label,
        CASE WHEN p_expires_hours IS NOT NULL THEN NOW() + (p_expires_hours || ' hours')::INTERVAL ELSE NULL END
    )
    RETURNING alert_id INTO v_alert_id;
    
    RETURN v_alert_id;
END;
$$ LANGUAGE plpgsql;

COMMENT ON SCHEMA alerts IS 'In-app alert and notification system';
COMMENT ON TABLE alerts.user_alerts IS 'User notifications and alerts';
COMMENT ON TABLE alerts.user_preferences IS 'Per-user alert preferences';
COMMENT ON TABLE alerts.alert_templates IS 'Reusable alert message templates';
