/* Is HealthSystem */

-- with DHC ID
    SELECT e.EntityId
          ,e.Name AS HealthSystemEntityName
          --,e.EntityDescription
          ,ci.HealthSystemInfoName
          ,cia.Address1 AS HealthSystemAddress1
          ,cia.Address2 AS HealthSystemAddress2          
          ,cia.Address3 AS HealthSystemAddress3
          ,cia.City AS HealthSystemCity
          ,cia.Zip AS HealthSystemZip
          ,ciast.StateName AS HealthSystemState
          --,COUNT(DISTINCT e.EntityId) AS theCount
          --,e.VerifiedSourceNameId AS entityVerifSourceNameId
          ,e.VerifiedSourceId AS Entity_DHC_VerifiedSourceId
          --,levs.VerifiedSourceNameId AS linkVerifSourceNameId
          ,levs.VerifiedSourceId AS LEVS_DHC_VerifiedSourceId
      FROM dbo.Entity AS e
      JOIN dbo.HealthSystemInfo AS ci ON ci.HealthSystemInfoId = e.EntityId
 LEFT JOIN dbo.HealthSystemInfoAddress AS cia ON cia.HealthSystemInfoId = ci.HealthSystemInfoId
                                             AND cia.IsDefault = 1
 LEFT JOIN dbo.State AS ciast ON ciast.StateId = cia.StateId
 LEFT JOIN dbo.LinkEntityVerifiedSource AS levs ON levs.EntityId = e.EntityId
     WHERE e.Archived = 0
       AND ci.Archived = 0
       AND e.IsHealthSystem = 1
       AND
      (
          (
              e.VerifiedSourceNameId = 1
              AND ISNULL(e.VerifiedSourceId, 0) <> 0
          )
          OR
          (
              levs.VerifiedSourceNameId = 1
              AND ISNULL(levs.VerifiedSourceId, 0) <> 0
          )
      )
       AND ISNULL(TRIM(e.EntityDescription), '') NOT IN
            (
             'Definitive Physician Group Import',
             'Definitive Provider Import',
             'Definitive Health System Import'
            )