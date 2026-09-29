/* Definitive Healthcare - group purchasing organization overview (identity source) */

-- Read by dhc_match_v2.py and dhc_gap_match.py through the `query_file` of the
-- GPO block under `definitive:` in sources.yaml. Databricks SQL, run on the
-- warehouse named in that file's `databricks:` block.
--
-- One row per GPO, all rows current. Unfiltered on purpose:
-- Definitive_GPO_Overview.xlsx, which this replaced on 2026-09-29, was an
-- unfiltered pull of the same view with HospitalId / HospitalName renamed to
-- DefinitiveId / Name.
--
-- The output column names must match the roles configured for this block
-- (id, name, address, city, state, zip); a run stops and names any that are
-- missing. Extra columns are allowed and are kept in the run's snapshot.

SELECT
    HospitalId,
    HospitalName,
    HeadquartersAddress,
    HeadquartersAddress1,
    HeadquartersCity,
    HeadquartersState,
    HeadquartersZipCode,
    HeadquartersPhone
FROM prd_silver.definitive.grouppurchasingorganizationoverview
