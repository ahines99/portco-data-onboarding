CREATE SCHEMA raw;
CREATE TABLE raw.posting_rubric (account_code VARCHAR PRIMARY KEY, account_name VARCHAR, account_type VARCHAR);
INSERT INTO raw.posting_rubric VALUES ('410','Synthetic service revenue','revenue'),('510','Synthetic direct costs','cogs'),('110','Synthetic cash','asset');
-- Books are GL journal lines. net_movement has undocumented sign convention and must not substitute for either debit or credit.
CREATE TABLE raw.daybook (journal_id VARCHAR, line_number INTEGER, account_code VARCHAR, posting_date DATE, debit_amount DECIMAL(12,2), credit_amount DECIMAL(12,2), net_movement DECIMAL(12,2), PRIMARY KEY(journal_id,line_number));
INSERT INTO raw.daybook VALUES ('J1',1,'410','2025-05-01',0,120,120),('J1',2,'110','2025-05-01',120,0,-120),('J2',1,'510','2025-05-02',45,0,45),('J2',2,'110','2025-05-02',0,45,-45);
