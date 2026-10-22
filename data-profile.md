### admissions.csv.gz (275 rows)

| column | nulls | distinct | min | max | most common |
|---|---|---|---|---|---|
| subject_id | 0 | 100 | 10000032 | 10040025 | 10014354, 10015860, 10002930 |
| hadm_id | 0 | 275 | 20044587 | 29974575 | 24181354, 25926192, 23983182 |
| admittime | 0 | 275 | 2110-04-11 15:08:00 | 2201-12-11 12:00:00 | 2196-02-24 14:38:00, 2153-09-17 17:08:00, 2134-08-18 02:02:00 |
| dischtime | 0 | 275 | 2110-04-14 15:00:00 | 2201-12-17 13:45:00 | 2196-03-04 14:02:00, 2153-09-25 13:20:00, 2134-08-23 19:35:00 |
| deathtime | 260 | 15 | 2111-11-15 17:20:00 | 2201-07-13 23:27:00 | 2111-11-15 17:20:00, 2115-10-12 22:20:00, 2177-03-29 14:15:00 |
| admission_type | 0 | 9 | AMBULATORY OBSERVATION | URGENT | EW EMER., OBSERVATION ADMIT, URGENT |
| admit_provider_id | 0 | 170 | P00P3O | P99YFT | P41R5N, P3529J, P233F6 |
| admission_location | 0 | 10 | CLINIC REFERRAL | WALK-IN/SELF REFERRAL | EMERGENCY ROOM, PHYSICIAN REFERRAL, TRANSFER FROM HOSPITAL |
| discharge_location | 42 | 10 | ACUTE HOSPITAL | SKILLED NURSING FACILITY | HOME HEALTH CARE, HOME, SKILLED NURSING FACILITY |
| insurance | 0 | 3 | Medicaid | Other | Other, Medicare, Medicaid |
| language | 0 | 2 | ? | ENGLISH | ENGLISH, ? |
| marital_status | 12 | 4 | DIVORCED | WIDOWED | SINGLE, MARRIED, WIDOWED |
| race | 0 | 14 | BLACK/AFRICAN AMERICAN | WHITE - OTHER EUROPEAN | WHITE, BLACK/AFRICAN AMERICAN, UNKNOWN |
| edregtime | 93 | 181 | 2110-11-30 04:45:00 | 2201-10-30 10:48:00 | 2193-08-05 05:04:00, 2196-02-24 12:15:00, 2134-08-17 16:24:00 |
| edouttime | 93 | 181 | 2110-11-30 08:03:00 | 2201-10-30 12:25:00 | 2193-08-05 12:00:00, 2196-02-24 17:07:00, 2134-08-18 03:15:00 |
| hospital_expire_flag | 0 | 2 | 0 | 1 | 0, 1 |

### d_icd_diagnoses.csv.gz (109,775 rows)

| column | nulls | distinct | min | max | most common |
|---|---|---|---|---|---|
| icd_code | 0 | 109282 | 0010 | Z9989 | V122, V140, V141 |
| icd_version | 0 | 2 | 10 | 9 | 10, 9 |
| long_title | 0 | 106327 | "Light-for-dates" with signs o | von Gierke disease | Assault by other specified mea, Other specified disorders of b, Acute salpingitis and oophorit |

### diagnoses_icd.csv.gz (4,506 rows)

| column | nulls | distinct | min | max | most common |
|---|---|---|---|---|---|
| subject_id | 0 | 100 | 10000032 | 10040025 | 10014354, 10040025, 10015860 |
| hadm_id | 0 | 275 | 20044587 | 29974575 | 22987108, 24540843, 29757856 |
| seq_num | 0 | 39 | 1 | 9 | 1, 2, 3 |
| icd_code | 0 | 1472 | 00845 | Z9981 | 4019, E785, 2724 |
| icd_version | 0 | 2 | 10 | 9 | 10, 9 |

### patients.csv.gz (100 rows)

| column | nulls | distinct | min | max | most common |
|---|---|---|---|---|---|
| subject_id | 0 | 100 | 10000032 | 10040025 | 10014729, 10003400, 10002428 |
| gender | 0 | 2 | F | M | M, F |
| anchor_age | 0 | 50 | 21 | 91 | 63, 66, 78 |
| anchor_year | 0 | 62 | 2110 | 2201 | 2137, 2146, 2125 |
| anchor_year_group | 0 | 2 | 2011 - 2013 | 2014 - 2016 | 2014 - 2016, 2011 - 2013 |
| dod | 69 | 31 | 2111-11-15 | 2201-12-24 | 2137-09-02, 2143-03-30, 2146-02-09 |

### transfers.csv.gz (1,190 rows)

| column | nulls | distinct | min | max | most common |
|---|---|---|---|---|---|
| subject_id | 0 | 100 | 10000032 | 10040025 | 10014354, 10040025, 10015860 |
| hadm_id | 54 | 275 | 20044587 | 29974575 | 23300884, 23831430, 20291550 |
| transfer_id | 0 | 1190 | 30014085 | 39997902 | 30030230, 32533329, 37922399 |
| eventtype | 0 | 4 | ED | transfer | transfer, discharge, admit |
| careunit | 275 | 31 | Cardiac Surgery | Vascular | Emergency Department, Medicine, Med/Surg |
| intime | 0 | 1190 | 2110-04-11 15:09:36 | 2201-12-17 13:48:45 | 2174-05-31 14:21:47, 2125-10-03 12:25:27, 2189-06-13 17:25:44 |
| outtime | 275 | 915 | 2110-04-11 15:52:22 | 2201-12-17 13:48:45 | 2154-01-09 11:53:26, 2125-10-03 12:25:27, 2129-04-11 17:45:53 |

### diagnosis.csv.gz (545 rows)

| column | nulls | distinct | min | max | most common |
|---|---|---|---|---|---|
| subject_id | 0 | 63 | 10000032 | 10040025 | 10014354, 10040025, 10015860 |
| stay_id | 0 | 221 | 30094124 | 39968716 | 38319705, 36323598, 39202185 |
| seq_num | 0 | 9 | 1 | 9 | 1, 2, 3 |
| icd_code | 0 | 288 | 0389 | Z992 | 4019, Z794, I10 |
| icd_version | 0 | 2 | 10 | 9 | 10, 9 |
| icd_title | 0 | 288 | ABDOMINAL PAIN LLQ | Weakness | HYPERTENSION NOS, Long term (current) use of ins, Essential (primary) hypertensi |

### edstays.csv.gz (222 rows)

| column | nulls | distinct | min | max | most common |
|---|---|---|---|---|---|
| subject_id | 0 | 64 | 10000032 | 10040025 | 10014354, 10040025, 10015860 |
| hadm_id | 50 | 171 | 20093566 | 29974575 | 29079034, 23300884, 26706939 |
| stay_id | 0 | 222 | 30094124 | 39968716 | 37887480, 34176810, 32103106 |
| intime | 0 | 222 | 2112-09-17 18:46:00 | 2201-10-30 10:48:00 | 2125-03-19 12:36:00, 2154-02-05 17:09:00, 2154-08-03 15:31:00 |
| outtime | 0 | 222 | 2112-09-17 19:50:00 | 2201-10-30 12:25:00 | 2125-03-19 16:59:47, 2154-02-05 22:54:00, 2154-08-03 22:29:00 |
| gender | 0 | 2 | F | M | F, M |
| race | 0 | 12 | BLACK/AFRICAN AMERICAN | WHITE - OTHER EUROPEAN | WHITE, BLACK/AFRICAN AMERICAN, HISPANIC/LATINO - CUBAN |
| arrival_transport | 0 | 4 | AMBULANCE | WALK IN | AMBULANCE, WALK IN, UNKNOWN |
| disposition | 0 | 7 | ADMITTED | TRANSFER | ADMITTED, HOME, TRANSFER |

### triage.csv.gz (222 rows)

| column | nulls | distinct | min | max | most common |
|---|---|---|---|---|---|
| subject_id | 0 | 64 | 10000032 | 10040025 | 10014354, 10040025, 10015860 |
| stay_id | 0 | 222 | 30094124 | 39968716 | 33211001, 30701739, 30115213 |
| temperature | 26 | 42 | 100 | 99.9 | 98.2, 98, 98.1 |
| heartrate | 24 | 70 | 100 | 99 | 98, 95, 84 |
| resprate | 23 | 13 | 14 | 32 | 18, 16, 20 |
| o2sat | 24 | 14 | 100 | 99 | 100, 98, 99 |
| sbp | 23 | 85 | 100 | 99 | 138, 133, 106 |
| dbp | 23 | 65 | 100 | 99 | 68, 74, 65 |
| pain | 21 | 18 | 0 | uta | 0, 8, 10 |
| acuity | 15 | 4 | 1 | 4 | 2, 3, 1 |
| chiefcomplaint | 0 | 182 | ? AORTIC DISECTION | s/p cardiac arrest | Abd pain, Chest pain, Altered mental status |

### vitalsign.csv.gz (1,038 rows)

| column | nulls | distinct | min | max | most common |
|---|---|---|---|---|---|
| subject_id | 0 | 54 | 10000032 | 10040025 | 10014354, 10002930, 10015860 |
| stay_id | 0 | 206 | 30094124 | 39968716 | 32287800, 37202404, 30952335 |
| charttime | 0 | 1038 | 2113-12-13 11:04:00 | 2201-07-07 18:55:00 | 2125-03-19 13:22:00, 2125-03-19 18:28:00, 2125-03-19 13:07:00 |
| temperature | 459 | 76 | 100 | 99.8 | 98, 98.2, 97.8 |
| heartrate | 30 | 92 | 100 | 99 | 70, 76, 84 |
| resprate | 48 | 29 | 10 | 9 | 18, 16, 20 |
| o2sat | 67 | 14 | 10 | 99 | 100, 98, 99 |
| sbp | 40 | 121 | 100 | 99 | 122, 124, 121 |
| dbp | 40 | 76 | 100 | 99 | 70, 65, 68 |
| rhythm | 1005 | 8 | Atrial Fibrillation | sr | Sinus Rhythm, Atrial Fibrillation, Sinus Tachycardia |
| pain | 302 | 38 | 0 | uta | 0, 8, 5 |
