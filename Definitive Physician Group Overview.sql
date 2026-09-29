/* Definitive Healthcare - physician group overview (identity source) */

-- Read by dhc_match_v2.py and dhc_gap_match.py through the `query_file` of the
-- PhysicianGroup block under `definitive:` in sources.yaml. Databricks SQL, run
-- on the warehouse named in that file's `databricks:` block.
--
-- One row per physician group, all rows current. Unfiltered on purpose:
-- Definitive_PhysicianGroupOverview.xlsx, which this replaced on 2026-09-29,
-- was an unfiltered pull of the same view with its columns renamed
-- (HospitalId -> DefinitiveId, HospitalName -> Definitive_NAME,
-- HeadquartersAddress -> HQ_ADDRESS, ...). Despite the name, HospitalId here is
-- the practice's own id; HospitalParentId is the parent reference.
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
FROM prd_silver.definitive.physiciangroupsoverview
