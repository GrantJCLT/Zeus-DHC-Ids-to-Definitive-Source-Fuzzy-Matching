/* Is Client - entities carrying NO Definitive id */

-- The complement of "Zeus Client to Definitive ID data quality evaluation.sql".
-- Same population, same joins, same EntityDescription exclusion; the ID
-- predicate is inverted. Three things differ deliberately:
--
--   1. NOT EXISTS instead of a LEFT JOIN to LinkEntityVerifiedSource. An entity
--      can hold several rows there, so "has no Definitive id" is a statement
--      about ALL of them, not about one joined row.
--   2. ISNULL() around VerifiedSourceNameId. Negating `= 1` on a NULL yields
--      NULL, not TRUE, so a bare NOT would silently drop every entity whose
--      source name is unset - which is most of this population.
--   3. The two id columns are emitted as typed NULLs. They are NULL by
--      construction here, and selecting the raw column would carry a
--      NON-Definitive identifier (VerifiedSourceNameId 2/4/5/6 - Definitive
--      Executive, NPI, Axuall, MDStaff) into a column the tooling reads as a
--      Definitive id. Other-source linkage is reported separately below.

    SELECT e.EntityId
          ,e.Name AS ClientEntityName
          --,e.EntityDescription
          ,ci.ClientInfoName
          ,cia.Address1 AS ClientAddress1
          ,cia.Address2 AS ClientAddress2
          ,cia.Address3 AS ClientAddress3
          ,cia.City AS ClientCity
          ,cia.Zip AS ClientZip
          ,ciast.StateName AS ClientState
          -- NULL by construction; see note 3 above.
          ,CAST(NULL AS INT) AS Entity_DHC_VerifiedSourceId
          ,CAST(NULL AS INT) AS LEVS_DHC_VerifiedSourceId
          -- Context, not an id: a non-Definitive verified source on this entity.
          -- VerifiedSourceNameId 4 is NPI, which is a deterministic match lever
          -- where it is populated.
          ,ovs.OtherVerifiedSources
      FROM dbo.Entity AS e
      JOIN dbo.ClientInfo AS ci ON ci.ClientInfoId = e.EntityId
 LEFT JOIN dbo.ClientInfoAddress AS cia ON cia.ClientInfoId = ci.ClientInfoId
                                       AND cia.IsDefault = 1
 LEFT JOIN dbo.State AS ciast ON ciast.StateId = cia.StateId
      -- Pre-aggregated once, then hash-joined - not a correlated subquery
      -- evaluated per entity, which is what the FOR XML PATH form this
      -- replaced would have done across 54k rows.
 LEFT JOIN (
                SELECT x.EntityId
                      ,STRING_AGG(x.VerifiedSourceName, ', ')
                           WITHIN GROUP (ORDER BY x.VerifiedSourceName)
                           AS OtherVerifiedSources
                  FROM (
                        SELECT DISTINCT l.EntityId, vsn.VerifiedSourceName
                          FROM dbo.LinkEntityVerifiedSource AS l
                          JOIN dbo.VerifiedSourceName AS vsn
                            ON vsn.VerifiedSourceNameId = l.VerifiedSourceNameId
                         WHERE ISNULL(l.VerifiedSourceId, 0) <> 0
                       ) AS x
              GROUP BY x.EntityId
           ) AS ovs ON ovs.EntityId = e.EntityId
     WHERE e.Archived = 0
       AND ci.Archived = 0
       AND e.IsClient = 1
       -- No Definitive id on the entity itself ...
       AND NOT (ISNULL(e.VerifiedSourceNameId, 0) = 1
                AND ISNULL(e.VerifiedSourceId, 0) <> 0)
       -- ... and none on any of its LinkEntityVerifiedSource rows.
       AND NOT EXISTS
            (
                SELECT 1
                  FROM dbo.LinkEntityVerifiedSource AS l
                 WHERE l.EntityId = e.EntityId
                   AND ISNULL(l.VerifiedSourceNameId, 0) = 1
                   AND ISNULL(l.VerifiedSourceId, 0) <> 0
            )
       -- Identical to the audit queries, so the two populations partition the
       -- same universe and their counts add up.
       AND ISNULL(TRIM(e.EntityDescription), '') NOT IN
            (
             'Definitive Physician Group Import',
             'Definitive Provider Import',
             'Definitive Health System Import'
            )
