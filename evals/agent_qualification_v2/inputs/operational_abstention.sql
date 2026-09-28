CREATE SCHEMA raw;
-- These are application usage counters, not billing customers, financial accounts, or sales records.
CREATE TABLE raw.accounts (event_token VARCHAR PRIMARY KEY, rack_label VARCHAR, amount BIGINT, currency VARCHAR, status VARCHAR);
-- currency is an arbitrary software rollout label; amount is event count.
INSERT INTO raw.accounts VALUES ('EV-1','rack-red',100,'blue','ready'),('EV-2','rack-blue',150,'green','ready'),('EV-3','rack-green',70,'blue','held');
CREATE TABLE raw.turnover (cycle_token VARCHAR PRIMARY KEY, revenue BIGINT, booked BIGINT, period VARCHAR);
-- revenue and booked are legacy counter labels with no monetary semantics.
INSERT INTO raw.turnover VALUES ('CY-1',18,2,'overnight'),('CY-2',22,3,'daylight'),('CY-3',10,1,'overnight');
