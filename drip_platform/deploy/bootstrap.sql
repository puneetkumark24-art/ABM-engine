-- bootstrap.sql — create the non-superuser runtime role and grant it access.
-- Run by the api entrypoint as the postgres superuser AFTER migrations, so all
-- tables (incl. partitions) already exist. The app connects as app_rw at
-- runtime, which is why RLS actually applies (superusers bypass RLS).

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'app_rw') THEN
    EXECUTE format('CREATE ROLE app_rw LOGIN NOSUPERUSER PASSWORD %L', :'app_pw');
  ELSE
    EXECUTE format('ALTER ROLE app_rw PASSWORD %L', :'app_pw');
  END IF;
END $$;

GRANT USAGE ON SCHEMA public TO app_rw;
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO app_rw;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO app_rw;
GRANT EXECUTE ON ALL FUNCTIONS IN SCHEMA public TO app_rw;

-- future tables/sequences created by later migrations inherit these grants
ALTER DEFAULT PRIVILEGES IN SCHEMA public
  GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO app_rw;
ALTER DEFAULT PRIVILEGES IN SCHEMA public
  GRANT USAGE, SELECT ON SEQUENCES TO app_rw;
