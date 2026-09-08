-- Runs once, only when the pgdata volume is first initialised.
-- If you add this file to an existing volume it will NOT run; either
--   docker compose down -v && docker compose up -d db      (destroys dev data)
-- or
--   docker compose exec db createdb -U app taskmanager_test
CREATE DATABASE taskmanager_test OWNER app;
