ALTER TABLE event_speakers ADD COLUMN IF NOT EXISTS format TEXT CHECK (format IN ('main','lightning'));
