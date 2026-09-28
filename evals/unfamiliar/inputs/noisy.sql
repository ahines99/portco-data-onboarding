CREATE SCHEMA raw;
CREATE TABLE raw.customer (customer_id VARCHAR, customer_name VARCHAR);
INSERT INTO raw.customer SELECT 'C-' || i, 'Synthetic ' || i FROM range(1,9) t(i);
CREATE TABLE raw.vendor (vendor_id VARCHAR, vendor_name VARCHAR);
INSERT INTO raw.vendor SELECT 'C-' || i, 'Supplier ' || i FROM range(1,9) t(i);
CREATE TABLE raw.invoice (invoice_id VARCHAR, customer_id VARCHAR, invoice_date DATE, total_amount DECIMAL(12,2), currency VARCHAR);
INSERT INTO raw.invoice SELECT 'I-' || i, CASE WHEN i=10 THEN 'C-99' ELSE 'C-' || (1+i%8) END, DATE '2025-04-01', 50.25*i, 'USD' FROM range(1,11) t(i);
