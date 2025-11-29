-- Forecast adjustments schema for manual overrides (US #18)
-- Allows users to adjust forecasted quantities and add notes

CREATE SCHEMA IF NOT EXISTS adjustments;

-- Adjustment status
CREATE TYPE adjustments.adjustment_status AS ENUM (
    'PENDING',      -- Awaiting review
    'APPROVED',     -- Approved and active
    'REJECTED',     -- Rejected, not applied
    'SUPERSEDED'    -- Replaced by newer adjustment
);

-- Main adjustments table
CREATE TABLE IF NOT EXISTS adjustments.forecast_adjustments (
    adjustment_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    
    -- What is being adjusted
    item_id TEXT NOT NULL,
    run_id UUID NOT NULL,
    horizon INT NOT NULL CHECK (horizon >= 1 AND horizon <= 12),
    period_start_date DATE NOT NULL,
    
    -- Original forecast values
    original_p50 NUMERIC(12, 2),
    original_p10 NUMERIC(12, 2),
    original_p90 NUMERIC(12, 2),
    original_method TEXT,
    
    -- Adjusted values
    adjusted_p50 NUMERIC(12, 2) NOT NULL,
    adjusted_p10 NUMERIC(12, 2),
    adjusted_p90 NUMERIC(12, 2),
    
    -- Adjustment metadata
    adjustment_reason TEXT NOT NULL,
    notes TEXT,
    confidence_level INT CHECK (confidence_level >= 1 AND confidence_level <= 5),  -- 1=Low, 5=High
    
    -- Who and when
    adjusted_by TEXT NOT NULL,  -- User ID or email
    adjusted_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    
    -- Approval workflow
    status adjustments.adjustment_status NOT NULL DEFAULT 'PENDING',
    reviewed_by TEXT,
    reviewed_at TIMESTAMPTZ,
    review_notes TEXT,
    
    -- Audit trail
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    
    -- Constraints
    CONSTRAINT valid_adjustment CHECK (adjusted_p50 >= 0),
    CONSTRAINT valid_confidence_bounds CHECK (
        (adjusted_p10 IS NULL AND adjusted_p90 IS NULL) OR
        (adjusted_p10 <= adjusted_p50 AND adjusted_p50 <= adjusted_p90)
    ),
    CONSTRAINT valid_review_timestamp CHECK (
        reviewed_at IS NULL OR reviewed_at >= adjusted_at
    )
);

-- Adjustment history for audit trail
CREATE TABLE IF NOT EXISTS adjustments.adjustment_history (
    history_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    adjustment_id UUID NOT NULL REFERENCES adjustments.forecast_adjustments(adjustment_id) ON DELETE CASCADE,
    
    -- What changed
    field_name TEXT NOT NULL,
    old_value TEXT,
    new_value TEXT,
    
    -- Who and when
    changed_by TEXT NOT NULL,
    changed_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    change_reason TEXT
);

-- Adjustment templates for common scenarios
CREATE TABLE IF NOT EXISTS adjustments.adjustment_templates (
    template_id TEXT PRIMARY KEY,
    template_name TEXT NOT NULL,
    description TEXT,
    
    -- Template logic
    adjustment_type TEXT NOT NULL,  -- 'PERCENTAGE', 'ABSOLUTE', 'FORMULA'
    adjustment_value NUMERIC(12, 2),
    adjustment_formula TEXT,
    
    -- Default values
    default_reason TEXT,
    default_confidence INT CHECK (default_confidence >= 1 AND default_confidence <= 5),
    
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Indexes for performance
CREATE INDEX idx_adjustments_item_date ON adjustments.forecast_adjustments(item_id, period_start_date);
CREATE INDEX idx_adjustments_run ON adjustments.forecast_adjustments(run_id);
CREATE INDEX idx_adjustments_status ON adjustments.forecast_adjustments(status) WHERE status IN ('PENDING', 'APPROVED');
CREATE INDEX idx_adjustments_user ON adjustments.forecast_adjustments(adjusted_by);
CREATE INDEX idx_adjustments_created ON adjustments.forecast_adjustments(created_at DESC);
CREATE INDEX idx_adjustment_history_adj_id ON adjustments.adjustment_history(adjustment_id);

-- Function to get active adjustment for an item/period
CREATE OR REPLACE FUNCTION adjustments.get_active_adjustment(
    p_item_id TEXT,
    p_period_start_date DATE,
    p_run_id UUID DEFAULT NULL
)
RETURNS TABLE (
    adjustment_id UUID,
    adjusted_p50 NUMERIC,
    adjusted_p10 NUMERIC,
    adjusted_p90 NUMERIC,
    adjustment_reason TEXT,
    adjusted_by TEXT,
    adjusted_at TIMESTAMPTZ
) AS $$
BEGIN
    RETURN QUERY
    SELECT 
        fa.adjustment_id,
        fa.adjusted_p50,
        fa.adjusted_p10,
        fa.adjusted_p90,
        fa.adjustment_reason,
        fa.adjusted_by,
        fa.adjusted_at
    FROM adjustments.forecast_adjustments fa
    WHERE fa.item_id = p_item_id
      AND fa.period_start_date = p_period_start_date
      AND fa.status = 'APPROVED'
      AND (p_run_id IS NULL OR fa.run_id = p_run_id)
    ORDER BY fa.adjusted_at DESC
    LIMIT 1;
END;
$$ LANGUAGE plpgsql;

-- Function to supersede old adjustments when new one is approved
CREATE OR REPLACE FUNCTION adjustments.supersede_old_adjustments()
RETURNS TRIGGER AS $$
BEGIN
    IF NEW.status = 'APPROVED' AND OLD.status != 'APPROVED' THEN
        -- Mark other approved adjustments for same item/period as superseded
        UPDATE adjustments.forecast_adjustments
        SET status = 'SUPERSEDED',
            updated_at = NOW()
        WHERE item_id = NEW.item_id
          AND period_start_date = NEW.period_start_date
          AND adjustment_id != NEW.adjustment_id
          AND status = 'APPROVED';
    END IF;
    
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- Trigger to auto-supersede old adjustments
CREATE TRIGGER trigger_supersede_adjustments
    AFTER UPDATE ON adjustments.forecast_adjustments
    FOR EACH ROW
    WHEN (NEW.status = 'APPROVED' AND OLD.status != 'APPROVED')
    EXECUTE FUNCTION adjustments.supersede_old_adjustments();

-- Function to log adjustment changes to history
CREATE OR REPLACE FUNCTION adjustments.log_adjustment_change()
RETURNS TRIGGER AS $$
BEGIN
    -- Log status changes
    IF OLD.status IS DISTINCT FROM NEW.status THEN
        INSERT INTO adjustments.adjustment_history (
            adjustment_id, field_name, old_value, new_value, changed_by, change_reason
        ) VALUES (
            NEW.adjustment_id, 'status', OLD.status::TEXT, NEW.status::TEXT, 
            COALESCE(NEW.reviewed_by, NEW.adjusted_by), NEW.review_notes
        );
    END IF;
    
    -- Log value changes
    IF OLD.adjusted_p50 IS DISTINCT FROM NEW.adjusted_p50 THEN
        INSERT INTO adjustments.adjustment_history (
            adjustment_id, field_name, old_value, new_value, changed_by
        ) VALUES (
            NEW.adjustment_id, 'adjusted_p50', OLD.adjusted_p50::TEXT, NEW.adjusted_p50::TEXT, NEW.adjusted_by
        );
    END IF;
    
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- Trigger to log changes
CREATE TRIGGER trigger_log_adjustment_changes
    AFTER UPDATE ON adjustments.forecast_adjustments
    FOR EACH ROW
    EXECUTE FUNCTION adjustments.log_adjustment_change();

-- Insert common adjustment templates
INSERT INTO adjustments.adjustment_templates (template_id, template_name, description, adjustment_type, adjustment_value, default_reason, default_confidence) VALUES
('increase_10pct', 'Increase by 10%', 'Increase forecast by 10% for promotional events', 'PERCENTAGE', 10, 'Promotional event expected', 4),
('increase_20pct', 'Increase by 20%', 'Increase forecast by 20% for major events', 'PERCENTAGE', 20, 'Major event or holiday', 4),
('decrease_10pct', 'Decrease by 10%', 'Decrease forecast by 10% for reduced demand', 'PERCENTAGE', -10, 'Expected demand reduction', 3),
('decrease_20pct', 'Decrease by 20%', 'Decrease forecast by 20% for significant reduction', 'PERCENTAGE', -20, 'Significant demand reduction expected', 3),
('set_zero', 'Set to Zero', 'Set forecast to zero (discontinued item)', 'ABSOLUTE', 0, 'Item discontinued or out of stock', 5),
('double', 'Double Forecast', 'Double the forecasted quantity', 'PERCENTAGE', 100, 'Exceptional demand expected', 3)
ON CONFLICT (template_id) DO NOTHING;

COMMENT ON SCHEMA adjustments IS 'Manual forecast adjustments and overrides';
COMMENT ON TABLE adjustments.forecast_adjustments IS 'User-submitted forecast adjustments with approval workflow';
COMMENT ON TABLE adjustments.adjustment_history IS 'Audit trail of adjustment changes';
COMMENT ON TABLE adjustments.adjustment_templates IS 'Reusable adjustment templates for common scenarios';
