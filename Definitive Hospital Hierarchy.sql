/* Definitive Healthcare - hospital ownership hierarchy (one row per record) */

-- Read by dhc_hierarchy.py through the `query_file` of the block under
-- `hierarchy:` in sources.yaml. Databricks SQL, run on the warehouse named in
-- that file's `databricks:` block.
--
-- Hospital Overview only, by rule (2026-09-30). It holds both hospitals
-- (TypeFirm 'Hospital') and health systems (TypeFirm 'Health System'), so one
-- view carries every level of the tree.
--
-- The parent rule, applied in order:
--   1. SfParentAccountId, when it exists;
--   2. otherwise IdNetwork;
--   3. otherwise HospitalId - the record is its own parent, i.e. a root.
-- A health system whose IdNetwork is its own id is therefore also a root.
--
-- Parent_Rule records which step decided. dhc_hierarchy.py walks ParentId up
-- to the root; it does not re-derive the rule, so this file is the only place
-- it is defined.
--
-- Measured 2026-09-30: 9,887 rows, 2,587 roots, no cycles, 2 parents absent
-- from the view (reported as Parent_Not_In_Definitive, never dropped).

SELECT
    HospitalId,
    HospitalName,
    TypeFirm,
    TypeHospital,
    CompanyStatus,
    HqCity,
    HqState,
    SfParentAccountId,
    SfParentAccountName,
    IdNetwork,
    NameNetwork,
    COALESCE(SfParentAccountId, IdNetwork, HospitalId) AS ParentId,
    CASE
        WHEN SfParentAccountId IS NOT NULL THEN 'SfParentAccountId'
        WHEN IdNetwork IS NOT NULL THEN 'IdNetwork'
        ELSE 'HospitalId'
    END AS Parent_Rule
FROM prd_silver.definitive.hospitaloverview
