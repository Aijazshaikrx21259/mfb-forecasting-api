-- Add category support to item tables for US #15

-- Add category column to core.dim_item if it doesn't exist
DO $$ 
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns 
        WHERE table_schema = 'core' 
        AND table_name = 'dim_item' 
        AND column_name = 'category'
    ) THEN
        ALTER TABLE core.dim_item ADD COLUMN category TEXT;
        CREATE INDEX idx_dim_item_category ON core.dim_item(category);
    END IF;
END $$;

-- Update categories from staging data if available
-- Map FBC_Agency_Category_Name to item categories
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.tables 
        WHERE table_schema = 'stg' 
        AND table_name = 'fact_goods_distributed'
    ) THEN
        -- Update categories from staging data
        UPDATE core.dim_item di
        SET category = COALESCE(
            (
                SELECT fbc_agency_category_name
                FROM stg.fact_goods_distributed sgd
                WHERE sgd.item_id = di.item_id
                AND sgd.fbc_agency_category_name IS NOT NULL
                LIMIT 1
            ),
            'Uncategorized'
        )
        WHERE di.category IS NULL;
    END IF;
END $$;

-- If no staging data, create sample categories for demo
DO $$
DECLARE
    item_count INT;
BEGIN
    -- Check if we have items without categories
    SELECT COUNT(*) INTO item_count
    FROM core.dim_item
    WHERE category IS NULL OR category = '';
    
    IF item_count > 0 THEN
        -- Assign sample categories based on item_id patterns
        UPDATE core.dim_item
        SET category = CASE
            WHEN item_id LIKE 'P-9%' THEN 'Produce'
            WHEN item_id LIKE 'P-3%' THEN 'Canned Goods'
            WHEN item_id LIKE 'P-8%' THEN 'Grains'
            WHEN item_id LIKE 'P-6%' THEN 'Dairy'
            WHEN item_id LIKE 'P-5%' THEN 'Protein'
            ELSE 'Other'
        END
        WHERE category IS NULL OR category = '';
    END IF;
END $$;

-- Verify categories
SELECT 
    category,
    COUNT(*) as item_count,
    COUNT(DISTINCT item_id) as unique_items
FROM core.dim_item
WHERE category IS NOT NULL
GROUP BY category
ORDER BY item_count DESC;

COMMENT ON COLUMN core.dim_item.category IS 'Product category (e.g., Produce, Canned Goods, Grains, Dairy)';
