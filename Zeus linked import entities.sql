/* Zeus - Definitive-import-created entities that sit at either end of a
   hierarchy link (one row per entity) */

-- Read by zeus_hierarchy.py through `zeus.linked_import_query_file` in
-- sources.yaml. Azure SQL, on the ReadOnly replica.
--
-- The twelve population queries exclude entities created by a Definitive
-- import (the EntityDescription filter), so the audits never see them. But
-- Zeus links in-scope entities to them - 13,441 work location -> client links
-- and 3,138 client -> health system links on 2026-10-07 - and by decision
-- (2026-10-07) they become hierarchy nodes wherever they are linked to an
-- in-scope entity. Their Definitive id is trusted as created: the record was
-- made from that id. zeus_hierarchy.py still checks the id exists in the
-- Definitive hierarchy before using it.
--
-- Returns every active import-created entity on either end of an active link
-- (Is_Linked = 1), with its id, names and default-address place;
-- zeus_hierarchy.py keeps the ones the universe rule needs. Also returns every
-- active import-created HEALTH SYSTEM, linked or not (Is_Linked = 0 for the
-- unlinked ones): they never become nodes, but where Definitive names a
-- client's health system and Zeus holds an unlinked import record for it,
-- Definitive_Parents_Not_In_Zeus says so. Most Zeus health systems are
-- import-created (2,273 of 3,403 active on 2026-10-07).
--
-- The Definitive id is taken only where its source is Definitive
-- (VerifiedSourceNameId = 1), on Entity or in LinkEntityVerifiedSource, so a
-- non-Definitive identifier (NPI, Axuall, MDStaff) can never pass for one.

WITH Linked AS (
    SELECT WorkLocationInfoId AS EntityId FROM dbo.LinkClientWorkLocation WHERE Archived = 0
    UNION
    SELECT ClientInfoId FROM dbo.LinkClientWorkLocation WHERE Archived = 0
    UNION
    SELECT ClientInfoId FROM dbo.LinkHealthSystemClient WHERE Archived = 0
    UNION
    SELECT HealthSystemInfoId FROM dbo.LinkHealthSystemClient WHERE Archived = 0
),
Levs AS (
    SELECT EntityId,
           MIN(VerifiedSourceId)            AS LEVS_DHC_VerifiedSourceId,
           COUNT(DISTINCT VerifiedSourceId) AS LEVS_DHC_Id_Count
      FROM dbo.LinkEntityVerifiedSource
     WHERE VerifiedSourceNameId = 1
       AND ISNULL(VerifiedSourceId, 0) <> 0
     GROUP BY EntityId
)
SELECT e.EntityId,
       e.Name                              AS Entity_Name,
       TRIM(e.EntityDescription)           AS EntityDescription,
       e.IsClient,
       e.IsWorkLocation,
       e.IsHealthSystem,
       CASE WHEN k.EntityId IS NULL THEN 0 ELSE 1 END AS Is_Linked,
       CASE WHEN e.VerifiedSourceNameId = 1 AND ISNULL(e.VerifiedSourceId, 0) <> 0
            THEN e.VerifiedSourceId END    AS Entity_DHC_VerifiedSourceId,
       lv.LEVS_DHC_VerifiedSourceId,
       lv.LEVS_DHC_Id_Count,
       ci.ClientInfoName,
       wi.WorkLocationInfoName,
       hi.HealthSystemInfoName,
       COALESCE(ca.City, wa.City, ha.City) AS City,
       COALESCE(cs.StateName, ws.StateName, hs.StateName) AS State
  FROM dbo.Entity AS e
  LEFT JOIN Linked AS k ON k.EntityId = e.EntityId
  LEFT JOIN Levs AS lv ON lv.EntityId = e.EntityId
  LEFT JOIN dbo.ClientInfo AS ci ON ci.ClientInfoId = e.EntityId AND ci.Archived = 0
  LEFT JOIN dbo.ClientInfoAddress AS ca ON ca.ClientInfoId = ci.ClientInfoId AND ca.IsDefault = 1
  LEFT JOIN dbo.State AS cs ON cs.StateId = ca.StateId
  LEFT JOIN dbo.WorkLocationInfo AS wi ON wi.WorkLocationInfoId = e.EntityId AND wi.Archived = 0
  LEFT JOIN dbo.WorkLocationInfoAddress AS wa ON wa.WorkLocationInfoId = wi.WorkLocationInfoId AND wa.IsDefault = 1
  LEFT JOIN dbo.State AS ws ON ws.StateId = wa.StateId
  LEFT JOIN dbo.HealthSystemInfo AS hi ON hi.HealthSystemInfoId = e.EntityId AND hi.Archived = 0
  LEFT JOIN dbo.HealthSystemInfoAddress AS ha ON ha.HealthSystemInfoId = hi.HealthSystemInfoId AND ha.IsDefault = 1
  LEFT JOIN dbo.State AS hs ON hs.StateId = ha.StateId
 WHERE e.Archived = 0
   AND ISNULL(TRIM(e.EntityDescription), '') IN (
           'Definitive Physician Group Import',
           'Definitive Provider Import',
           'Definitive Health System Import')
   AND (k.EntityId IS NOT NULL
        OR (e.IsHealthSystem = 1 AND hi.HealthSystemInfoId IS NOT NULL))
