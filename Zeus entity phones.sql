/* Phone numbers for every Zeus population - one row per number */

-- Read by dhc_match_v2.py and dhc_gap_match.py through `zeus.phone_query_file`
-- in sources.yaml, alongside the population queries. Not filtered to the
-- audited entities: the tools join on (EntityId, Zeus_Source), so numbers for
-- entities outside the audit are simply unused.
--
-- Each *Info table keeps its own numbers, just as it keeps its own name and
-- address, so each branch is labelled with its population. The labels MUST
-- equal the `label:` values under zeus.sources - that is the join key.
--
-- The *InfoId of each table is the EntityId, the same join the population
-- queries use (e.g. WorkLocationInfo.WorkLocationInfoId = Entity.EntityId).
-- Numbers are returned raw; the tools normalise them to 10 digits and discard
-- anything that is not a usable North American number.

SELECT p.ClientInfoId        AS EntityId, 'Client'       AS Zeus_Source, p.ClientInfoPhoneNumber        AS Phone
  FROM dbo.ClientInfoPhone AS p        WHERE p.Archived = 0
UNION ALL
SELECT p.WorkLocationInfoId  AS EntityId, 'WorkLocation' AS Zeus_Source, p.WorkLocationInfoPhoneNumber  AS Phone
  FROM dbo.WorkLocationInfoPhone AS p  WHERE p.Archived = 0
UNION ALL
SELECT p.HealthSystemInfoId  AS EntityId, 'HealthSystem' AS Zeus_Source, p.HealthSystemInfoPhoneNumber  AS Phone
  FROM dbo.HealthSystemInfoPhone AS p  WHERE p.Archived = 0
UNION ALL
SELECT p.GPOInfoId           AS EntityId, 'GPO'          AS Zeus_Source, p.GPOInfoPhoneNumber           AS Phone
  FROM dbo.GPOInfoPhone AS p           WHERE p.Archived = 0
UNION ALL
SELECT p.AgencyInfoId        AS EntityId, 'Agency'       AS Zeus_Source, p.AgencyInfoPhoneNumber        AS Phone
  FROM dbo.AgencyInfoPhone AS p        WHERE p.Archived = 0
UNION ALL
SELECT p.VMSInfoId           AS EntityId, 'VMS'          AS Zeus_Source, p.VMSInfoPhoneNumber           AS Phone
  FROM dbo.VMSInfoPhone AS p           WHERE p.Archived = 0
