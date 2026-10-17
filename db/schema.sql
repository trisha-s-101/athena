-- Platelet exchange schema (CONTRACT.md sections 3, 5, 8 and 9).
-- Safe to run repeatedly: it creates only what is missing and never drops data.
-- Columns are snake_case; api/ converts rows to camelCase JSON.
-- Runs on PostgreSQL 16 (Ubuntu 24.04) and later.

CREATE TABLE IF NOT EXISTS hospitals (
    hospital_id      text PRIMARY KEY,
    name             text NOT NULL,
    lat              double precision NOT NULL,
    lng              double precision NOT NULL,
    size_category    text NOT NULL CHECK (size_category IN ('small', 'medium', 'large')),
    has_haematology  boolean NOT NULL
);

-- Directed: every ordered pair is its own row.
CREATE TABLE IF NOT EXISTS travel_times (
    from_hospital_id  text NOT NULL REFERENCES hospitals,
    to_hospital_id    text NOT NULL REFERENCES hospitals,
    minutes           integer NOT NULL CHECK (minutes >= 0),
    PRIMARY KEY (from_hospital_id, to_hospital_id)
);

CREATE TABLE IF NOT EXISTS units (
    unit_id       text PRIMARY KEY,
    blood_group   text NOT NULL CHECK (blood_group IN ('O+', 'O-', 'A+', 'A-', 'B+', 'B-', 'AB+', 'AB-')),
    collected_at  timestamptz NOT NULL,
    expires_at    timestamptz NOT NULL,
    hospital_id   text NOT NULL REFERENCES hospitals,
    status        text NOT NULL CHECK (status IN ('available', 'reserved', 'inTransit', 'transfused', 'expired')),
    CHECK (expires_at > collected_at)
);

-- /stock and /hospitals filter by hospital and status; expiry counts scan by status and expiry.
CREATE INDEX IF NOT EXISTS units_hospital_status_idx ON units (hospital_id, status);
CREATE INDEX IF NOT EXISTS units_status_expires_idx ON units (status, expires_at);

-- reservation_id ("R000001") is derived from an identity counter so IDs never collide
-- under concurrent inserts. Past 999999 the ID just grows a digit instead of truncating.
CREATE TABLE IF NOT EXISTS reservations (
    reservation_number  bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    reservation_id      text GENERATED ALWAYS AS (
                            'R' || lpad(reservation_number::text, greatest(6, length(reservation_number::text)), '0')
                        ) STORED UNIQUE,
    unit_id             text NOT NULL REFERENCES units,
    from_hospital_id    text NOT NULL REFERENCES hospitals,
    to_hospital_id      text NOT NULL REFERENCES hospitals,
    status              text NOT NULL CHECK (status IN ('accepted', 'completed')),
    created_at          timestamptz NOT NULL,
    completed_at        timestamptz
);

-- Contract section 8: at most one active reservation per unit. This is the backstop
-- behind the conditional UPDATE on units.status that the API does first.
CREATE UNIQUE INDEX IF NOT EXISTS reservations_one_active_per_unit_idx
    ON reservations (unit_id) WHERE status = 'accepted';

-- Every feed event and API action is logged here. /events returns them newest first
-- by event_number, and /metrics reads the sim clock and daily counts from them.
-- blood_group and units are kept for demandUnmet events (shortages, demand history);
-- they are internal and not part of the /events response.
CREATE TABLE IF NOT EXISTS events (
    event_number  bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    event_id      text GENERATED ALWAYS AS (
                      'E' || lpad(event_number::text, greatest(6, length(event_number::text)), '0')
                  ) STORED UNIQUE,
    type          text NOT NULL,
    unit_id       text REFERENCES units,
    hospital_id   text REFERENCES hospitals,
    blood_group   text CHECK (blood_group IN ('O+', 'O-', 'A+', 'A-', 'B+', 'B-', 'AB+', 'AB-')),
    units         integer CHECK (units > 0),
    at            timestamptz NOT NULL,
    detail        text NOT NULL DEFAULT ''
);

CREATE INDEX IF NOT EXISTS events_type_at_idx ON events (type, at);
-- The sim clock is the latest clock event by arrival order, so a restarted sim can rewind it.
CREATE INDEX IF NOT EXISTS events_type_number_idx ON events (type, event_number);
