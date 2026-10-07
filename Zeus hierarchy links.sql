/* Zeus - the entity-to-entity links that make the HealthSystem > Client >
   WorkLocation hierarchy (one row per active link) */

-- Read by zeus_hierarchy.py through `zeus.hierarchy_query_file` in sources.yaml.
-- Azure SQL, on the ReadOnly replica like every other Zeus query.
--
-- Two link tables, unioned into one child -> parent edge list:
--   dbo.LinkClientWorkLocation  (ClientInfoId, WorkLocationInfoId)
--       child = the work location, parent = the client
--   dbo.LinkHealthSystemClient  (HealthSystemInfoId, ClientInfoId)
--       child = the client, parent = the health system
-- Zeus has no health system -> parent health system link worth reading:
-- HealthSystemInfo.HealthSystemInfoParentId is filled on 3 rows (2026-10-07).
--
-- Both ends must be active in the role the link gives them: Entity not
-- archived, the role flag set, and the role's *Info row not archived. Every
-- such link is returned, including links between two Definitive-import-created
-- entities; zeus_hierarchy.py decides which import-created entities become
-- nodes (those linked to an in-scope entity), so that rule is in one place.
-- Measured 2026-10-07 against the in-scope population: 99.3% of work locations
-- have at least one client link (7,905 have two or more); 80% of clients have
-- no health system link (2,321 have two or more).
--
-- Is_Import mirrors the EntityDescription exclusion in the population queries.
-- Duplicates (Entity.DuplicateOfId) come from "Zeus entity duplicates.sql";
-- zeus_hierarchy.py remaps a duplicate to its survivor before using a link.
--
-- Bookings / Last_Booked: actual bookings (Booking.IsBooking = 1, status
-- Booked, Working or Filled, not archived) for that client at that work
-- location, via dbo.BookingClientWorkLocation. History_*: the link's dated
-- history in dbo.LinkClientWorkLocationHistory. Both are tie-breaks for a
-- work location with several clients and nothing from Definitive; both are
-- NULL for health system links.

WITH Ent AS (
    SELECT e.EntityId,
           CASE WHEN ISNULL(TRIM(e.EntityDescription), '') IN (
                    'Definitive Physician Group Import',
                    'Definitive Provider Import',
                    'Definitive Health System Import')
                THEN 1 ELSE 0 END AS Is_Import,
           e.IsClient, e.IsWorkLocation, e.IsHealthSystem
      FROM dbo.Entity AS e
     WHERE e.Archived = 0
),
Bk AS (
    SELECT v.ClientInfoId, v.WorkLocationInfoId,
           COUNT(DISTINCT b.BookingId) AS Bookings,
           MAX(b.BookedDate)           AS Last_Booked
      FROM dbo.BookingClientWorkLocation AS v
      JOIN dbo.Booking AS b ON b.BookingId = v.BookingId
     WHERE b.Archived = 0
       AND b.IsBooking = 1
       AND b.BookingStatusId IN (1, 2, 3)          -- Booked, Working, Filled
     GROUP BY v.ClientInfoId, v.WorkLocationInfoId
),
Hist AS (
    SELECT ClientInfoId, WorkLocationInfoId,
           MAX(BeginDate) AS History_Last_Begin,
           MAX(CASE WHEN EndDate IS NULL THEN 1 ELSE 0 END) AS History_Open
      FROM dbo.LinkClientWorkLocationHistory
     WHERE Archived = 0
     GROUP BY ClientInfoId, WorkLocationInfoId
),
CW AS (
    SELECT l.WorkLocationInfoId, l.ClientInfoId, MIN(l.Created) AS Link_Created
      FROM dbo.LinkClientWorkLocation AS l
     WHERE l.Archived = 0
     GROUP BY l.WorkLocationInfoId, l.ClientInfoId
),
HC AS (
    SELECT l.ClientInfoId, l.HealthSystemInfoId, MIN(l.Created) AS Link_Created
      FROM dbo.LinkHealthSystemClient AS l
     WHERE l.Archived = 0
     GROUP BY l.ClientInfoId, l.HealthSystemInfoId
)
SELECT 'ClientWorkLocation'   AS Link_Type,
       cw.WorkLocationInfoId  AS Child_EntityId,
       'WorkLocation'         AS Child_Role,
       cw.ClientInfoId        AS Parent_EntityId,
       'Client'               AS Parent_Role,
       ce.Is_Import           AS Child_Is_Import,
       pe.Is_Import           AS Parent_Is_Import,
       cw.Link_Created,
       bk.Bookings,
       bk.Last_Booked,
       h.History_Last_Begin,
       h.History_Open
  FROM CW AS cw
  JOIN Ent AS ce ON ce.EntityId = cw.WorkLocationInfoId AND ce.IsWorkLocation = 1
  JOIN dbo.WorkLocationInfo AS wi ON wi.WorkLocationInfoId = cw.WorkLocationInfoId
                                 AND wi.Archived = 0
  JOIN Ent AS pe ON pe.EntityId = cw.ClientInfoId AND pe.IsClient = 1
  JOIN dbo.ClientInfo AS ci ON ci.ClientInfoId = cw.ClientInfoId
                           AND ci.Archived = 0
  LEFT JOIN Bk AS bk ON bk.ClientInfoId = cw.ClientInfoId
                    AND bk.WorkLocationInfoId = cw.WorkLocationInfoId
  LEFT JOIN Hist AS h ON h.ClientInfoId = cw.ClientInfoId
                     AND h.WorkLocationInfoId = cw.WorkLocationInfoId

UNION ALL

SELECT 'HealthSystemClient'   AS Link_Type,
       hc.ClientInfoId        AS Child_EntityId,
       'Client'               AS Child_Role,
       hc.HealthSystemInfoId  AS Parent_EntityId,
       'HealthSystem'         AS Parent_Role,
       ce.Is_Import,
       pe.Is_Import,
       hc.Link_Created,
       NULL, NULL, NULL, NULL
  FROM HC AS hc
  JOIN Ent AS ce ON ce.EntityId = hc.ClientInfoId AND ce.IsClient = 1
  JOIN dbo.ClientInfo AS ci ON ci.ClientInfoId = hc.ClientInfoId
                           AND ci.Archived = 0
  JOIN Ent AS pe ON pe.EntityId = hc.HealthSystemInfoId AND pe.IsHealthSystem = 1
  JOIN dbo.HealthSystemInfo AS hi ON hi.HealthSystemInfoId = hc.HealthSystemInfoId
                                 AND hi.Archived = 0
