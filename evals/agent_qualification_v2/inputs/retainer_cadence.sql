CREATE SCHEMA raw;
-- Retainers are recurring subscription lines, with a monthly amount in cents.
CREATE TABLE raw.retainer_roll (subscription_id VARCHAR PRIMARY KEY, customer_id VARCHAR, plan_code VARCHAR, monthly_amount_cents BIGINT, currency VARCHAR, start_date DATE, end_date DATE, status VARCHAR, annual_quote DECIMAL(12,2), rate_unit VARCHAR);
-- annual_quote mixes per-seat quotes and whole-contract estimates; no mapping to MRR is supportable.
INSERT INTO raw.retainer_roll VALUES ('R-1','Q-1','CORE',12000,'USD','2025-01-01',NULL,'active',1440,'per-seat'),('R-2','Q-2','PLUS',9900,'USD','2025-01-15',NULL,'active',5000,'whole-contract'),('R-3','Q-3','CORE',5000,'EUR','2025-02-01','2025-03-01','ended',600,'unknown');
