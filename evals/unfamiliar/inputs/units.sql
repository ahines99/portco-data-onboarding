CREATE SCHEMA raw;
CREATE TABLE raw.invoice (invoice_id VARCHAR, customer_id VARCHAR, invoice_date DATE, total_amount DECIMAL(12,2), currency VARCHAR);
INSERT INTO raw.invoice VALUES ('I-1','C-1','2025-01-01',101.25,'USD'),('I-2','C-2','2025-01-02',208.75,'USD'),('I-3','C-3','2025-01-03',399.50,'USD');
CREATE TABLE raw.invoice_line (invoice_line_id VARCHAR, invoice_id VARCHAR, amount_cents BIGINT, amount DECIMAL(12,2), quantity INTEGER);
INSERT INTO raw.invoice_line VALUES ('L-1','I-1',10125,101.25,1),('L-2','I-2',20875,208.75,1),('L-3','I-3',39950,399.50,1);
CREATE TABLE raw.opportunity (opportunity_id VARCHAR, rev DECIMAL(12,2), stage VARCHAR, close_date DATE);
INSERT INTO raw.opportunity VALUES ('O-1',101.25,'Qualified','2025-06-01'),('O-2',208.75,'Lost','2025-06-02'),('O-3',399.50,'Proposal','2025-06-03');
