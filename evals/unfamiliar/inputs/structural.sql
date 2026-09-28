CREATE SCHEMA raw;
CREATE TABLE raw.r17 (invoice_id VARCHAR, customer_id VARCHAR, invoice_date DATE, due_date DATE, total_amount DECIMAL(12,2), currency VARCHAR, batch_marker VARCHAR);
INSERT INTO raw.r17 SELECT 'B-' || i, 'P-' || (i % 4), DATE '2025-01-01' + CAST(i AS INTEGER), DATE '2025-02-01' + CAST(i AS INTEGER), 125.50 + i, 'USD', 'X' FROM range(1,13) t(i);
CREATE TABLE raw.r29 (customer_id VARCHAR, customer_name VARCHAR, currency VARCHAR);
INSERT INTO raw.r29 VALUES ('P-0','Synthetic A','USD'),('P-1','Synthetic B','USD'),('P-2','Synthetic C','USD'),('P-3','Synthetic D','USD');
