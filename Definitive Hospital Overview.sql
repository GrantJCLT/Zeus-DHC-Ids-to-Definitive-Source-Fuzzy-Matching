/* Definitive Healthcare - hospital overview (identity source) */

-- Read by dhc_match_v2.py and dhc_gap_match.py through the `query_file` of the
-- Hospital block under `definitive:` in sources.yaml. Databricks SQL, run on
-- the warehouse named in that file's `databricks:` block.
--
-- One row per hospital, all rows current - not a history table. Unfiltered on
-- purpose: Definitive_HospitalOverview.xlsx, which this replaced on 2026-09-29,
-- was an unfiltered pull of the same view.
--
-- The output column names must match the roles configured for this block
-- (id, name, address, city, state, zip); a run stops and names any that are
-- missing. Extra columns are allowed and are kept in the run's snapshot.

SELECT
    HospitalId,
    HospitalName,
    AddressHq,
    Address1Hq,
    HqCity,
    HqState,
    HqZipCode,
    PhoneHq
FROM prd_silver.definitive.hospitaloverview
