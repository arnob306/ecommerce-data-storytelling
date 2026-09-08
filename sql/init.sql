CREATE TABLE IF NOT EXISTS raw_transactions (
    id                SERIAL PRIMARY KEY,
    invoice_no        VARCHAR(20)     NOT NULL,
    stock_code        VARCHAR(20)     NOT NULL,
    description       TEXT,
    quantity          INTEGER         NOT NULL,
    invoice_date      TIMESTAMP       NOT NULL,
    unit_price        NUMERIC(10, 4)  NOT NULL,
    customer_id       VARCHAR(20),        
    country           VARCHAR(100)    NOT NULL,
    loaded_at         TIMESTAMP       NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_raw_transactions_invoice_date ON raw_transactions (invoice_date);
CREATE INDEX IF NOT EXISTS idx_raw_transactions_customer_id  ON raw_transactions (customer_id);
CREATE INDEX IF NOT EXISTS idx_raw_transactions_country      ON raw_transactions (country);
CREATE INDEX IF NOT EXISTS idx_raw_transactions_stock_code   ON raw_transactions (stock_code);

CREATE TABLE IF NOT EXISTS kpi_results (
    id              SERIAL PRIMARY KEY,
    kpi_name        VARCHAR(100)    NOT NULL,
    week_date       DATE            NOT NULL,
    value           NUMERIC(20, 6)  NOT NULL,
    category        VARCHAR(50),        
    cadence         VARCHAR(20),        
    computed_at     TIMESTAMP       NOT NULL DEFAULT NOW(),
    UNIQUE (kpi_name, week_date)
);

CREATE INDEX IF NOT EXISTS idx_kpi_results_kpi_name  ON kpi_results (kpi_name);
CREATE INDEX IF NOT EXISTS idx_kpi_results_week_date ON kpi_results (week_date);

CREATE TABLE IF NOT EXISTS anomalies (
    id                  SERIAL PRIMARY KEY,
    kpi_name            VARCHAR(100)    NOT NULL,
    anomaly_date        DATE            NOT NULL,
    severity            VARCHAR(20)     NOT NULL,   
    confidence          NUMERIC(5, 4)   NOT NULL,   
    actual_value        NUMERIC(20, 6),
    expected_value      NUMERIC(20, 6),
    deviation_pct       NUMERIC(10, 4),
    direction           VARCHAR(10),                
    detection_methods   TEXT[],                     
    detected_at         TIMESTAMP       NOT NULL DEFAULT NOW(),
    UNIQUE (kpi_name, anomaly_date)
);

CREATE INDEX IF NOT EXISTS idx_anomalies_kpi_name     ON anomalies (kpi_name);
CREATE INDEX IF NOT EXISTS idx_anomalies_anomaly_date ON anomalies (anomaly_date);
CREATE INDEX IF NOT EXISTS idx_anomalies_severity     ON anomalies (severity);

CREATE TABLE IF NOT EXISTS root_causes (
    id                  SERIAL PRIMARY KEY,
    anomaly_id          INTEGER         REFERENCES anomalies (id) ON DELETE CASCADE,
    kpi_name            VARCHAR(100)    NOT NULL,
    anomaly_date        DATE            NOT NULL,
    status              VARCHAR(30)     NOT NULL,   
    dimension           VARCHAR(50),                
    segment_value       TEXT,                       
    contribution_pct    NUMERIC(10, 4),
    segment_rank        INTEGER,
    analysed_at         TIMESTAMP       NOT NULL DEFAULT NOW(),
    UNIQUE (anomaly_id, segment_rank)
);

CREATE INDEX IF NOT EXISTS idx_root_causes_anomaly_id   ON root_causes (anomaly_id);
CREATE INDEX IF NOT EXISTS idx_root_causes_kpi_name     ON root_causes (kpi_name);
CREATE INDEX IF NOT EXISTS idx_root_causes_anomaly_date ON root_causes (anomaly_date);

CREATE TABLE IF NOT EXISTS llm_calls (
    id                  SERIAL PRIMARY KEY,
    called_at           TIMESTAMP       NOT NULL,
    model               VARCHAR(100)    NOT NULL,
    prompt_version      VARCHAR(20)     NOT NULL,
    kpi_name            VARCHAR(100),
    anomaly_date        DATE,
    input_tokens        INTEGER,
    output_tokens       INTEGER,
    estimated_cost_usd  NUMERIC(12, 8),
    latency_ms          INTEGER,
    success             BOOLEAN         NOT NULL DEFAULT TRUE,
    quality_flags       TEXT[],                     
    loaded_at           TIMESTAMP       NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_llm_calls_called_at      ON llm_calls (called_at);
CREATE INDEX IF NOT EXISTS idx_llm_calls_prompt_version ON llm_calls (prompt_version);
CREATE INDEX IF NOT EXISTS idx_llm_calls_kpi_name       ON llm_calls (kpi_name);

CREATE TABLE IF NOT EXISTS narratives (
    id                  SERIAL PRIMARY KEY,
    kpi_name            VARCHAR(100)    NOT NULL,
    anomaly_date        DATE            NOT NULL,
    narrative_type      VARCHAR(20)     NOT NULL,   
    prompt_version      VARCHAR(20)     NOT NULL,
    narrative_text      TEXT            NOT NULL,
    retrieved_context   JSONB,                      
    generated_at        TIMESTAMP       NOT NULL DEFAULT NOW(),
    UNIQUE (kpi_name, anomaly_date, narrative_type)
);

CREATE INDEX IF NOT EXISTS idx_narratives_kpi_name    ON narratives (kpi_name);
CREATE INDEX IF NOT EXISTS idx_narratives_anomaly_date ON narratives (anomaly_date);

CREATE OR REPLACE VIEW vw_kpi_with_anomaly_flag AS
SELECT
    k.kpi_name,
    k.week_date,
    k.value,
    k.category,
    CASE WHEN a.id IS NOT NULL THEN TRUE ELSE FALSE END AS is_anomaly,
    a.severity,
    a.confidence,
    a.deviation_pct,
    a.direction
FROM kpi_results k
LEFT JOIN anomalies a
    ON k.kpi_name = a.kpi_name
    AND k.week_date = a.anomaly_date;


CREATE OR REPLACE VIEW vw_llm_monitoring_summary AS
SELECT
    prompt_version,
    COUNT(*)                                    AS total_calls,
    SUM(CASE WHEN success THEN 1 ELSE 0 END)   AS successful_calls,
    ROUND(AVG(latency_ms))                      AS avg_latency_ms,
    SUM(estimated_cost_usd)                     AS total_cost_usd,
    AVG(input_tokens)                           AS avg_input_tokens,
    AVG(output_tokens)                          AS avg_output_tokens,
    COUNT(CASE WHEN array_length(quality_flags, 1) > 0 THEN 1 END) AS calls_with_violations
FROM llm_calls
GROUP BY prompt_version
ORDER BY prompt_version;

CREATE OR REPLACE VIEW vw_anomaly_clusters AS
SELECT
    anomaly_date,
    COUNT(*)                        AS kpi_count,
    ARRAY_AGG(kpi_name)             AS kpis_affected,
    MAX(severity)                   AS max_severity,
    ROUND(AVG(confidence)::NUMERIC, 4) AS avg_confidence
FROM anomalies
GROUP BY anomaly_date
HAVING COUNT(*) > 1
ORDER BY anomaly_date;