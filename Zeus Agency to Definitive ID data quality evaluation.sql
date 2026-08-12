/* Is Agency */

-- with DHC ID
    SELECT e.EntityId
          ,e.Name AS AgencyEntityName
          --,e.EntityDescription
          ,ci.AgencyName
          ,cia.Address1 AS AgencyAddress1
          ,cia.Address2 AS AgencyAddress2          
          ,cia.Address3 AS AgencyAddress3
          ,cia.City AS AgencyCity
          ,cia.Zip AS AgencyZip
          ,ciast.StateName AS AgencyState
          --,COUNT(DISTINCT e.EntityId) AS theCount
          --,e.VerifiedSourceNameId AS entityVerifSourceNameId
          ,e.VerifiedSourceId AS Entity_DHC_VerifiedSourceId
          --,levs.VerifiedSourceNameId AS linkVerifSourceNameId
          ,levs.VerifiedSourceId AS LEVS_DHC_VerifiedSourceId
      FROM dbo.Entity AS e
      JOIN dbo.AgencyInfo AS ci ON ci.AgencyInfoId = e.EntityId
 LEFT JOIN dbo.AgencyInfoAddress AS cia ON cia.AgencyInfoId = ci.AgencyInfoId
                                    AND cia.IsDefault = 1
 LEFT JOIN dbo.State AS ciast ON ciast.StateId = cia.StateId
 LEFT JOIN dbo.LinkEntityVerifiedSource AS levs ON levs.EntityId = e.EntityId
     WHERE e.Archived = 0
       AND ci.Archived = 0
       AND e.IsAgency = 1
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