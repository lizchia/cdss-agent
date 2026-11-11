-- Deterministic SYNTHETIC data for local development and tests. Contains no real patients.
-- Timestamps are relative to now() so "recent" queries always return rows.

BEGIN;

SELECT setseed(0.42);

-- 50 patients with stable UUIDs derived from their index: md5('synthetic-patient-<n>')::uuid
INSERT INTO patients (patient_id, mrn, birth_date, sex)
SELECT md5('synthetic-patient-' || n)::uuid,
       'SYN' || lpad(n::text, 6, '0'),
       (current_date - ((25 + floor(random() * 65))::int * 365 + floor(random() * 365)::int)),
       (ARRAY['female', 'male'])[1 + (n % 2)]
FROM generate_series(1, 50) AS n;

-- One current ICU admission per patient, admitted 1-6 days ago.
INSERT INTO admissions (admission_id, patient_id, admit_time, discharge_time, care_unit)
SELECT md5('synthetic-admission-' || n)::uuid,
       md5('synthetic-patient-' || n)::uuid,
       now() - make_interval(hours => 24 + floor(random() * 120)::int),
       NULL,
       (ARRAY['MICU', 'SICU', 'CCU'])[1 + (n % 3)]
FROM generate_series(1, 50) AS n;

-- Hourly vitals for the past 96 hours. Every 5th patient is physiologically unstable.
INSERT INTO vitals (patient_id, recorded_at, heart_rate_bpm, systolic_bp_mmhg,
                    diastolic_bp_mmhg, respiratory_rate, spo2_percent, temperature_c)
SELECT md5('synthetic-patient-' || n)::uuid,
       date_trunc('hour', now()) - make_interval(hours => h),
       round((CASE WHEN n % 5 = 0 THEN 110 ELSE 78 END + random() * 20)::numeric, 1),
       round((CASE WHEN n % 5 = 0 THEN 88 ELSE 118 END + random() * 18)::numeric, 1),
       round((CASE WHEN n % 5 = 0 THEN 50 ELSE 70 END + random() * 12)::numeric, 1),
       round((CASE WHEN n % 5 = 0 THEN 24 ELSE 14 END + random() * 6)::numeric, 1),
       round((CASE WHEN n % 5 = 0 THEN 89 ELSE 95 END + random() * 4)::numeric, 1),
       round((CASE WHEN n % 5 = 0 THEN 38.2 ELSE 36.6 END + random() * 0.9)::numeric, 1)
FROM generate_series(1, 50) AS n
CROSS JOIN generate_series(0, 95) AS h;

-- Labs every 12 hours: lactate, creatinine, WBC (LOINC coded).
INSERT INTO labs (patient_id, collected_at, loinc_code, test_name, value, unit, ref_low, ref_high)
SELECT md5('synthetic-patient-' || n)::uuid,
       date_trunc('hour', now()) - make_interval(hours => h * 12),
       t.loinc, t.name,
       round((CASE WHEN n % 5 = 0 THEN t.sick ELSE t.well END * (0.85 + random() * 0.3))::numeric, 2),
       t.unit, t.lo, t.hi
FROM generate_series(1, 50) AS n
CROSS JOIN generate_series(0, 7) AS h
CROSS JOIN (VALUES
    ('2524-7', 'Lactate', 'mmol/L', 1.2, 3.8, 0.5, 2.0),
    ('2160-0', 'Creatinine', 'mg/dL', 0.9, 2.1, 0.6, 1.2),
    ('6690-2', 'WBC', '10*3/uL', 7.5, 17.0, 4.0, 11.0)
) AS t (loinc, name, unit, well, sick, lo, hi);

-- Medications: everyone on DVT prophylaxis; unstable patients also on norepinephrine
-- and piperacillin-tazobactam. One discontinued med per patient exercises the "active" filter.
INSERT INTO medications (patient_id, drug_name, dose, route, frequency, start_time, end_time)
SELECT md5('synthetic-patient-' || n)::uuid, m.drug, m.dose, m.route, m.freq,
       now() - interval '2 days',
       CASE WHEN m.stopped THEN now() - interval '1 day' END
FROM generate_series(1, 50) AS n
CROSS JOIN (VALUES
    ('Enoxaparin', '40 mg', 'SC', 'q24h', false, false),
    ('Ondansetron', '4 mg', 'IV', 'q8h PRN', true, false),
    ('Norepinephrine', '0.08 mcg/kg/min', 'IV', 'continuous', false, true),
    ('Piperacillin-tazobactam', '4.5 g', 'IV', 'q6h', false, true)
) AS m (drug, dose, route, freq, stopped, unstable_only)
WHERE NOT m.unstable_only OR n % 5 = 0;

-- Diagnoses.
INSERT INTO diagnoses (patient_id, icd10_code, description, onset_date, status)
SELECT md5('synthetic-patient-' || n)::uuid, d.code, d.descr, current_date - d.days_ago, d.status
FROM generate_series(1, 50) AS n
CROSS JOIN (VALUES
    ('I10', 'Essential (primary) hypertension', 2000, 'active', false),
    ('J18.9', 'Pneumonia, unspecified organism', 3, 'active', false),
    ('K35.80', 'Unspecified acute appendicitis', 900, 'resolved', false),
    ('A41.9', 'Sepsis, unspecified organism', 2, 'active', true),
    ('R65.21', 'Severe sepsis with septic shock', 1, 'active', true)
) AS d (code, descr, days_ago, status, unstable_only)
WHERE NOT d.unstable_only OR n % 5 = 0;

COMMIT;
