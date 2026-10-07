/* Definitive Healthcare - physician group ownership hierarchy (one row per group) */

-- Read by dhc_hierarchy.py through the second block under `hierarchy:` in
-- sources.yaml, alongside "Definitive Hospital Hierarchy.sql". Databricks SQL,
-- run on the warehouse named in that file's `databricks:` block.
--
-- Added 2026-10-07 for the Zeus HealthSystem > Client > WorkLocation hierarchy,
-- which needs a parent for every Definitive id a Zeus entity can resolve to -
-- and 2,477 accuracy ids plus ~6,500 strong coverage proposals are physician
-- groups. This reverses the 2026-09-30 note that physician groups were out of
-- scope "at this time".
--
-- Same output columns and the same parent rule as the hospital file, so
-- dhc_hierarchy.py unions the two and walks them as one tree:
--   1. SfParentAccountId, when it exists;
--   2. otherwise NetworkId;
--   3. otherwise the group's own id - a root.
-- Measured 2026-10-07: 143,617 groups, 6,205 (4.3%) with a parent, every one
-- through step 1 (NetworkId is never filled without SfParentAccountId). The
-- parents are hospitals (2,358), health systems (1,080) or corporate owners
-- in neither view (2,767). TypeFirm is Physician Group (142,819), Management
-- Services Organization (467) or Independent Practice Association (331).
--
-- Since 2026-10-07 the view returns every column as a string (it was
-- redefined over re-cut parquet that day), so the ids are cast to INT to match
-- the hospital file.

SELECT
    CAST(HospitalId AS INT)        AS HospitalId,
    HospitalName,
    FirmType                       AS TypeFirm,
    PhysicianGroupType             AS TypeHospital,
    CompanyStatus,
    HeadquartersCity               AS HqCity,
    HeadquartersState              AS HqState,
    CAST(SfParentAccountId AS INT) AS SfParentAccountId,
    SfParentAccountName,
    CAST(NetworkId AS INT)         AS IdNetwork,
    NetworkName                    AS NameNetwork,
    COALESCE(CAST(SfParentAccountId AS INT), CAST(NetworkId AS INT),
             CAST(HospitalId AS INT)) AS ParentId,
    CASE
        WHEN SfParentAccountId IS NOT NULL THEN 'SfParentAccountId'
        WHEN NetworkId IS NOT NULL THEN 'IdNetwork'
        ELSE 'HospitalId'
    END                            AS Parent_Rule
FROM prd_silver.definitive.physiciangroupsoverview
