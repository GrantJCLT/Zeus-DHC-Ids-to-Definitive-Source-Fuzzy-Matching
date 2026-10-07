/* Zeus - entities marked as a duplicate of another (one row per duplicate) */

-- Read by zeus_hierarchy.py through `zeus.duplicates_query_file` in
-- sources.yaml. Azure SQL, on the ReadOnly replica.
--
-- Entity.DuplicateOfId names the surviving record. zeus_hierarchy.py remaps a
-- duplicate to its survivor - in every link and as a Definitive parent target -
-- when the survivor holds the same role in the hierarchy, and lists each remap
-- on Duplicates_Remapped. A duplicate whose survivor is not a hierarchy node
-- (archived, or outside the universe) is left as it is and flagged.
-- 1,597 in-scope HealthSystem / Client / WorkLocation entities were marked on
-- 2026-10-07.

SELECT e.EntityId,
       e.DuplicateOfId,
       s.Archived AS Survivor_Archived
  FROM dbo.Entity AS e
  LEFT JOIN dbo.Entity AS s ON s.EntityId = e.DuplicateOfId
 WHERE e.Archived = 0
   AND e.DuplicateOfId IS NOT NULL
   AND e.DuplicateOfId <> e.EntityId
