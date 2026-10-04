-- Least-privilege application role (row-level security applies; no UPDATE/DELETE on ledgers or audit).
CREATE ROLE opspilot_app LOGIN PASSWORD 'opspilot_app' NOSUPERUSER NOBYPASSRLS;
CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS pg_trgm;
