/* Zeus - every active Definitive-import-created entity that carries a
   Definitive id (one row per entity) */

-- Read by dhc_only_hierarchy.py through `zeus.import_query_file` in
-- sources.yaml. Azure SQL, on the ReadOnly replica.
--
-- The twelve population queries exclude entities created by a Definitive
-- import (the EntityDescription filter), so the audits never see them. The
-- Definitive-only hierarchy takes every Definitive id Zeus holds as its base,
-- so it needs them too. Unlike "Zeus linked import entities.sql" (read by
-- zeus_hierarchy.py), this query has NO link condition: it reads no
-- LinkClientWorkLocation or LinkHealthSystemClient row, because the
-- Definitive-only hierarchy must not use Zeus's own hierarchy.
--
-- The Definitive id is taken only where its source is Definitive
-- (VerifiedSourceNameId = 1), on Entity or in LinkEntityVerifiedSource, so a
-- non-Definitive identifier (NPI, Axuall, MDStaff) can never pass for one.
-- Entities with neither are left out: they hold no Definitive id.

WITH Levs AS (
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
   AND ((e.VerifiedSourceNameId = 1 AND ISNULL(e.VerifiedSourceId, 0) <> 0)
        OR lv.EntityId IS NOT NULL)
