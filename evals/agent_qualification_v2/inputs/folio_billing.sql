CREATE SCHEMA raw;
-- Payors are billed customers; folios are final customer invoice headers.
CREATE TABLE raw.payor_register (customer_id VARCHAR PRIMARY KEY, trading_style VARCHAR, currency VARCHAR, country VARCHAR);
INSERT INTO raw.payor_register VALUES ('P-A','Synthetic Amber Atelier','USD','US'),('P-B','Synthetic Birch Studio','EUR','IE'),('P-C','Synthetic Cedar Works','USD','US');
CREATE TABLE raw.charge_folios (folio_number VARCHAR PRIMARY KEY, customer_id VARCHAR, invoice_date DATE, due_date DATE, total_amount_cents BIGINT, currency VARCHAR, revenue_hint DECIMAL(12,2));
-- total_amount_cents is explicitly in 1/100 major currency units. revenue_hint is an unqualified estimate, not an invoice total.
INSERT INTO raw.charge_folios VALUES ('F-01','P-A','2025-02-01','2025-03-01',12345,'USD',99),('F-02','P-A','2025-02-02','2025-03-02',4550,'USD',100),('F-03','P-B','2025-02-03','2025-03-03',9000,'EUR',80);
