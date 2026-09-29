/* Definitive Healthcare - practice locations (LOCATION source, not identity) */

-- Read by dhc_match_v2.py and dhc_gap_match.py through the `query_file` of the
-- block under `locations:` in sources.yaml - NEVER under `definitive:`, see
-- CLAUDE.md decision #9. Databricks SQL, run on the warehouse named in that
-- file's `databricks:` block.
--
-- The view is one row per PHYSICIAN per location (~4.6M rows). DISTINCT over
-- the location columns reduces it to one row per location; PracticeLocation-
-- HospitalId is the PARENT entity's Definitive id, repeated per location.
--
-- Both clauses matter:
--   * DISTINCT - without it every location is repeated once per physician,
--     multiplying the location work roughly twelvefold for no new evidence.
--   * IS NOT NULL - about 1.09M distinct locations carry no parent id. They
--     cannot enrich any entity, and they are what made this view look 4.6x
--     larger than the xlsx it replaced.
--
-- This is the query that produced Definitive_Practice_Locations.xlsx
-- (399,990 rows, 176,658 ids), which this replaced on 2026-09-29 - there it
-- read the view's parquet path directly and aliased the columns to
-- DefinitiveId / Name. On 2026-09-29 it returned 396,386 rows over 176,897 ids.
--
-- The output column names must match the roles configured for this block;
-- a run stops and names any that are missing.

-- Phones: a location can list several numbers across its physicians. They are
-- collected into one '|'-joined column with GROUP BY rather than added to the
-- DISTINCT, which would split one location into a row per number and change
-- every location count. GROUP BY over the same seven columns returns exactly
-- the rows DISTINCT did (both treat NULLs as equal).

SELECT
    PracticeLocationHospitalId,
    Location,
    HeadquartersAddress,
    HeadquartersAddress1,
    HeadquartersCity,
    HeadquartersState,
    HeadquartersZipCode,
    concat_ws('|', array_sort(collect_set(HeadquartersPhone))) AS Phones
FROM prd_silver.definitive.physicianspracticelocations
WHERE PracticeLocationHospitalId IS NOT NULL
GROUP BY
    PracticeLocationHospitalId,
    Location,
    HeadquartersAddress,
    HeadquartersAddress1,
    HeadquartersCity,
    HeadquartersState,
    HeadquartersZipCode
