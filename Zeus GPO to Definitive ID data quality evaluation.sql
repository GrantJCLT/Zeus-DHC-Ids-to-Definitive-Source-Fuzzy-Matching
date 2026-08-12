/* Is GPO */

-- with DHC ID
    SELECT e.EntityId
          ,e.Name AS GPOEntityName
          --,e.EntityDescription
          ,ci.GPOInfoName
          ,cia.Address1 AS GPOAddress1
          ,cia.Address2 AS GPOAddress2          
          ,cia.Address3 AS GPOAddress3
          ,cia.City AS GPOCity
          ,cia.Zip AS GPOZip
          ,ciast.StateName AS GPOState
          --,COUNT(DISTINCT e.EntityId) AS theCount
          --,e.VerifiedSourceNameId AS entityVerifSourceNameId
          ,e.VerifiedSourceId AS Entity_DHC_VerifiedSourceId
          --,levs.VerifiedSourceNameId AS linkVerifSourceNameId
          ,levs.VerifiedSourceId AS LEVS_DHC_VerifiedSourceId
      FROM dbo.Entity AS e
      JOIN dbo.GPOInfo AS ci ON ci.GPOInfoId = e.EntityId
 LEFT JOIN dbo.GPOInfoAddress AS cia ON cia.GPOInfoId = ci.GPOInfoId
                                    AND cia.IsDefault = 1
 LEFT JOIN dbo.State AS ciast ON ciast.StateId = cia.StateId
 LEFT JOIN dbo.LinkEntityVerifiedSource AS levs ON levs.EntityId = e.EntityId
     WHERE e.Archived = 0
       AND ci.Archived = 0
       AND e.IsGPO = 1
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