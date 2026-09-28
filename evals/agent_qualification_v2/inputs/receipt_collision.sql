CREATE SCHEMA raw;
CREATE TABLE raw.billing_documents (invoice_id VARCHAR PRIMARY KEY, customer_id VARCHAR, invoice_date DATE, total_amount DECIMAL(12,2), currency VARCHAR);
INSERT INTO raw.billing_documents VALUES ('001','C-1','2025-04-01',100,'USD'),('002','C-2','2025-04-02',200,'USD'),('003','C-3','2025-04-03',300,'USD');
-- Teller slips are cash receipts. batch_slot is a local ingestion sequence, not an invoice reference.
CREATE TABLE raw.teller_slips (payment_id VARCHAR PRIMARY KEY, invoice_id VARCHAR, paid_at TIMESTAMP, amount DECIMAL(12,2), method VARCHAR, batch_slot VARCHAR);
INSERT INTO raw.teller_slips VALUES ('T-1','002','2025-04-05 10:00:00',100,'bank','001'),('T-2','002','2025-04-06 10:00:00',100,'bank','002'),('T-3','003','2025-04-07 10:00:00',300,'wire','003');
-- invoice_id below is a legacy misnomer for an ingest packet id, coincidentally overlapping all invoices.
CREATE TABLE raw.ingest_packets (invoice_id VARCHAR PRIMARY KEY, payload_bytes BIGINT, retry_count INTEGER);
INSERT INTO raw.ingest_packets VALUES ('001',1000,0),('002',2000,1),('003',3000,0);
