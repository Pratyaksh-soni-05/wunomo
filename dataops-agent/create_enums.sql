DO $$ BEGIN
  CREATE TYPE cicdstatus AS ENUM ('pending','running','passed','failed','skipped');
EXCEPTION WHEN duplicate_object THEN null;
END $$;

DO $$ BEGIN
  CREATE TYPE gatedecision AS ENUM ('auto_approved','pending_approval','approved','rejected');
EXCEPTION WHEN duplicate_object THEN null;
END $$;

DO $$ BEGIN
  CREATE TYPE deploymentstatus AS ENUM ('queued','deploying','active','rolled_back','failed');
EXCEPTION WHEN duplicate_object THEN null;
END $$;