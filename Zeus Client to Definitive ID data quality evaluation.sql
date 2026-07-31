/* Is Client */

-- with DHC ID
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
          --,COUNT(DISTINCT e.EntityId) AS theCount
          --,e.VerifiedSourceNameId AS entityVerifSourceNameId
          ,e.VerifiedSourceId AS Entity_DHC_VerifiedSourceId
          --,levs.VerifiedSourceNameId AS linkVerifSourceNameId
          ,levs.VerifiedSourceId AS LEVS_DHC_VerifiedSourceId
      FROM dbo.Entity AS e
      JOIN dbo.ClientInfo AS ci ON ci.ClientInfoId = e.EntityId
 LEFT JOIN dbo.ClientInfoAddress AS cia ON cia.ClientInfoId = ci.ClientInfoId
                                       AND cia.IsDefault = 1
 LEFT JOIN dbo.State AS ciast ON ciast.StateId = cia.StateId
 LEFT JOIN dbo.LinkEntityVerifiedSource AS levs ON levs.EntityId = e.EntityId
     WHERE e.Archived = 0
       AND ci.Archived = 0
       AND e.IsClient = 1
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