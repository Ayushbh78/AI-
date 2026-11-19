-- Optional: the app creates these automatically on first start. Run in Supabase -> SQL Editor if you prefer.
CREATE TABLE IF NOT EXISTS courses   (id TEXT PRIMARY KEY, data JSONB NOT NULL, created TEXT NOT NULL DEFAULT '');
CREATE TABLE IF NOT EXISTS materials (course_id TEXT PRIMARY KEY, data JSONB NOT NULL);
CREATE TABLE IF NOT EXISTS users     (username TEXT PRIMARY KEY, data JSONB NOT NULL);
CREATE TABLE IF NOT EXISTS app_secrets (name TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS docs      (kind TEXT NOT NULL, key TEXT NOT NULL, data JSONB NOT NULL, PRIMARY KEY (kind, key));
-- Block Supabase's public REST API from these tables; the app connects directly as the database owner.
ALTER TABLE courses     ENABLE ROW LEVEL SECURITY;
ALTER TABLE materials   ENABLE ROW LEVEL SECURITY;
ALTER TABLE users       ENABLE ROW LEVEL SECURITY;
ALTER TABLE app_secrets ENABLE ROW LEVEL SECURITY;
ALTER TABLE docs        ENABLE ROW LEVEL SECURITY;

-- Faster 'my courses' pages: the courses of one person are found through this index.
CREATE INDEX IF NOT EXISTS courses_owner_idx ON courses ((data->>'owner'));
