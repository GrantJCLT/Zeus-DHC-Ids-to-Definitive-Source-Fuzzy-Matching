/* CRM migration readiness - one row per Zeus entity per migration summary table */

-- Read by zeus_hierarchy.py through `migration.query_file` in sources.yaml.
-- Databricks SQL, run on the warehouse named in that file's `databricks:`
-- block. Added 2026-10-07 to put the migration team's ready_for_migration
-- flag on the Zeus hierarchy's Hierarchy sheet.
--
-- Each table's Zeus key is the Zeus EntityId: WorkLocationInfoId,
-- ClientInfoId and HealthSystemInfoId all join dbo.Entity on EntityId (see the
-- Zeus *.sql queries), so the three are emitted as one EntityId column, with
-- Migration_Table naming the table a row came from. Each key is unique within
-- its table, but not across them: measured 2026-10-07, 1,288 EntityIds are in
-- more than one table (a health system that also has a client_summary row,
-- for one). zeus_hierarchy.py takes the row from the table matching the
-- entity's hierarchy type and shows every table's flag beside it.
--
-- Measured 2026-10-07: healthsystem_summary 3,379 rows (1,466 ready),
-- client_summary 234,385 (116,455 ready), worklocation_summary 28,327
-- (3,395 ready); ready_for_migration is 0 or 1, never NULL.

SELECT CAST(HealthSystemInfoId AS INT) AS EntityId,
       'HealthSystem'                  AS Migration_Table,
       ready_for_migration             AS Ready_For_Migration
FROM qat_gold.crmmig_rules.healthsystem_summary
UNION ALL
SELECT CAST(ClientInfoId AS INT), 'Client', ready_for_migration
FROM qat_gold.crmmig_rules.client_summary
UNION ALL
SELECT CAST(WorkLocationInfoId AS INT), 'WorkLocation', ready_for_migration
FROM qat_gold.crmmig_rules.worklocation_summary
