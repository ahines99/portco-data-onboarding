CREATE SCHEMA raw;
-- Engagement roster contains employees; annual_salary_cents is annual base salary in USD cents.
CREATE TABLE raw.engagement_roster (employee_id VARCHAR PRIMARY KEY, full_name VARCHAR, hire_date DATE, termination_date DATE, department VARCHAR, annual_salary_cents BIGINT, compensation DECIMAL(12,2), compensation_basis VARCHAR);
-- compensation mixes weekly allowances and incentive targets and is not annual base salary.
INSERT INTO raw.engagement_roster VALUES ('E-1','Synthetic Person One','2024-01-01',NULL,'Lab',8500000,125,'weekly allowance'),('E-2','Synthetic Person Two','2024-06-01',NULL,'Operations',7200000,10000,'incentive target'),('E-3','Synthetic Person Three','2023-01-01','2025-01-31','Lab',6400000,80,'weekly allowance');
