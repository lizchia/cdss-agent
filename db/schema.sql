-- Minimal clinical schema for the CDSS agent (synthetic data only in non-prod).
-- The application role is read-only; db_tool also opens connections with
-- default_transaction_read_only=on.

BEGIN;

CREATE TABLE IF NOT EXISTS patients (
    patient_id   UUID PRIMARY KEY,
    mrn          TEXT        NOT NULL UNIQUE,
    birth_date   DATE        NOT NULL,
    sex          TEXT        NOT NULL CHECK (sex IN ('female', 'male', 'other', 'unknown')),
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS admissions (
    admission_id   UUID PRIMARY KEY,
    patient_id     UUID        NOT NULL REFERENCES patients (patient_id),
    admit_time     TIMESTAMPTZ NOT NULL,
    discharge_time TIMESTAMPTZ,
    care_unit      TEXT        NOT NULL,
    CHECK (discharge_time IS NULL OR discharge_time >= admit_time)
);
CREATE INDEX IF NOT EXISTS ix_admissions_patient ON admissions (patient_id, admit_time DESC);

CREATE TABLE IF NOT EXISTS vitals (
    vital_id          BIGSERIAL PRIMARY KEY,
    patient_id        UUID        NOT NULL REFERENCES patients (patient_id),
    recorded_at       TIMESTAMPTZ NOT NULL,
    heart_rate_bpm    NUMERIC(5, 1),
    systolic_bp_mmhg  NUMERIC(5, 1),
    diastolic_bp_mmhg NUMERIC(5, 1),
    respiratory_rate  NUMERIC(4, 1),
    spo2_percent      NUMERIC(4, 1),
    temperature_c     NUMERIC(4, 1)
);
CREATE INDEX IF NOT EXISTS ix_vitals_patient_time ON vitals (patient_id, recorded_at DESC);

CREATE TABLE IF NOT EXISTS labs (
    lab_id       BIGSERIAL PRIMARY KEY,
    patient_id   UUID        NOT NULL REFERENCES patients (patient_id),
    collected_at TIMESTAMPTZ NOT NULL,
    loinc_code   TEXT        NOT NULL,
    test_name    TEXT        NOT NULL,
    value        NUMERIC     NOT NULL,
    unit         TEXT        NOT NULL,
    ref_low      NUMERIC,
    ref_high     NUMERIC
);
CREATE INDEX IF NOT EXISTS ix_labs_patient_time ON labs (patient_id, collected_at DESC);

CREATE TABLE IF NOT EXISTS medications (
    medication_id BIGSERIAL PRIMARY KEY,
    patient_id    UUID        NOT NULL REFERENCES patients (patient_id),
    drug_name     TEXT        NOT NULL,
    dose          TEXT        NOT NULL,
    route         TEXT        NOT NULL,
    frequency     TEXT        NOT NULL,
    start_time    TIMESTAMPTZ NOT NULL,
    end_time      TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS ix_medications_patient_active
    ON medications (patient_id) WHERE end_time IS NULL;

CREATE TABLE IF NOT EXISTS diagnoses (
    diagnosis_id BIGSERIAL PRIMARY KEY,
    patient_id   UUID NOT NULL REFERENCES patients (patient_id),
    icd10_code   TEXT NOT NULL,
    description  TEXT NOT NULL,
    onset_date   DATE,
    status       TEXT NOT NULL CHECK (status IN ('active', 'resolved'))
);
CREATE INDEX IF NOT EXISTS ix_diagnoses_patient_status ON diagnoses (patient_id, status);

-- Read-only group role; grant it to the login user the app connects with.
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'cdss_readonly') THEN
        CREATE ROLE cdss_readonly NOLOGIN;
    END IF;
END
$$;
GRANT USAGE ON SCHEMA public TO cdss_readonly;
GRANT SELECT ON patients, admissions, vitals, labs, medications, diagnoses TO cdss_readonly;

COMMIT;
