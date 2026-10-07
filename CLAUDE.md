# Zeus ↔ Definitive Healthcare identifier audit

## What this project does

Two questions about the same link, over one universe of Zeus entities:

- **Accuracy** — of the entities that carry a Definitive Healthcare (DHC) ID,
  how often does it point at the right Definitive record? `dhc_match_v2.py`.
- **Coverage** — which entities carry no DHC ID at all, and which Definitive
  record should each of them point at? `dhc_gap_match.py`, added 2026-08-19.
- **Hierarchy** — one Health System > Client > Work Location tree for Zeus,
  from Definitive ownership first and Zeus links second, built on the two
  audits' resolved ids. `zeus_hierarchy.py`, added 2026-10-07; see
  `Hierarchy_Logic.md` and decisions #16-#18.

Zeus is Jackson and Coker's internal CRM. Verification is by fuzzy comparison of
name and address between the two sides — there is no authoritative key to check
against, so the output is a confidence score and a verdict (accuracy) or a tier
(coverage) per row, not a boolean.

The two populations **partition** one universe and are defined by complementary
SQL predicates, so their counts add up:

| | Entities | |
|---|---|---|
| Carry a DHC ID — measured for accuracy | 12,803 | 20.8% |
| Carry none — measured for coverage | 48,739 | 79.2% |
| **Total Zeus entities across the six populations** | **61,542** | |

Coverage is the larger problem by a factor of four, and was invisible until
2026-08-19 because every query in the project until then selected only rows that
already had an ID.

Owner: Grant, analytics / BI engineering. Stack context: Zeus is Azure SQL;
the wider BI estate is SQL Server, Azure Databricks, Power BI, Azure DevOps
(`jclt` org, `BI` project).

## Files

- `dhc_match_v2.py` — the tool. Two subcommands, `inspect` and `run`. It is
  self-contained; the `_v2` suffix is historical. (`dhc_id_match.py`, the v1
  single-source scorer, was deleted on 2026-07-31. It still read `HospitalName`,
  `HospitalId` and `EntityName`, all removed in that day's column re-cut, so it
  could no longer run. Recoverable from git history if ever needed — but treat
  anything in it as superseded, not as a reference.)
- `build_audit_workbook.py` — turns a scored run into the branded deliverable.
  Everything in it is derived from the run, so it is re-runnable:
  `py build_audit_workbook.py --scored <run>_scored.csv
  [--baseline <earlier>_scored.csv] [--out <name>.xlsx]`
- `dhc_gap_match.py` — the coverage tool. Finds the entities with no DHC ID and
  proposes one. Imports every normalisation and scoring function from
  `dhc_match_v2`, so the decisions below are single-sourced; what it deliberately
  does **not** inherit is decision #4 (see decision #11).
- `build_coverage_workbook.py` — turns a gap run into the branded deliverable,
  the sibling of `build_audit_workbook.py`. It **imports** that module's palette
  and `_put` / `_table` / `sheet_data` rather than copying them, so the two
  workbooks cannot drift apart; edit the styling in one place only.
  `py build_coverage_workbook.py --candidates <run>_gap_candidates.csv
  [--accuracy <audit>_scored.csv] [--out <name>.xlsx]`
- `run_all.py` — runs everything in order, added 2026-09-30: accuracy run,
  coverage run, both workbooks, then (since 2026-10-07, unless
  `--no-hierarchy` or `--accuracy-only`) `dhc_hierarchy.py` and
  `zeus_hierarchy.py`, and scoped workbooks for each `--population`
  (`--population all`, added 2026-10-05, expands to every `zeus.sources`
  label read from the config, so the list is never hard-coded).
  Calls the four scripts unchanged as subprocesses with its own
  `sys.executable`, chaining them by the `Run folder  :` line each run prints.
  The coverage run gets `--claimed` and **`--definitive-from` the accuracy
  run**, so both audits score against one Definitive state (the views refresh
  in place). Stops at the first failing step; ends with a summary of the
  READ_ONLY, NOTE, WARNING and identity-check lines, exit code 1 if any
  failed. `py run_all.py --limit 200 --label smoke` is a 6-minute end-to-end
  test.
- `zeus_hierarchy.py` — the Zeus Health System > Client > Work Location
  hierarchy, added 2026-10-07. Reads both audits (all four output files, which
  partition the in-scope universe), a `dhc_hierarchy.py` run's snapshots
  (`--definitive-hierarchy`) and three Zeus queries (`--zeus-links` replays
  them): `Zeus hierarchy links.sql` (every active `LinkClientWorkLocation` and
  `LinkHealthSystemClient` row, with bookings and link history), `Zeus linked
  import entities.sql` and `Zeus entity duplicates.sql`. One parent and one
  type per entity (decision #16). Writes `_hierarchy_edges.csv` (the tree),
  `_hierarchy_nodes.csv` (everything, with `Entity_Type` and
  `Zeus_Link_Status`), `_contradictions.csv`, `_zeus_links_replaced.csv`,
  `_zeus_links_dropped.csv`, `_resolution.csv`, the input snapshots, and
  `Zeus_Entity_Hierarchy_<run>.xlsx`. Nine identity checks in `X == Y  OK`
  form (ten with readiness). A replay from its own folder is byte-identical
  (verified 2026-10-07). The rules are in `Hierarchy_Logic.md`; the decisions
  are #16-#18 below.
  **Migration readiness since 2026-10-07:** `Zeus migration readiness.sql`
  (`migration.query_file`, Databricks) unions the migration team's
  `qat_gold.crmmig_rules.healthsystem_summary`, `client_summary` and
  `worklocation_summary`, whose keys (`HealthSystemInfoId`, `ClientInfoId`,
  `WorkLocationInfoId`) are each the Zeus `EntityId`. Each node gets
  `Ready_For_Migration` from the table of its own `Entity_Type`, falling back
  to another table, highest type first, only where that one has no row
  (`Ready_For_Migration_From`), plus each table's own flag
  (`Ready_<Type>_Summary`) and `Ready_Tables_Disagree`, all right after
  `In_Scope` on the Hierarchy sheet and in `_hierarchy_nodes.csv`; a Summary
  section counts them. Keys are unique per table but 1,288 EntityIds are in
  more than one table (Grant chose own-type-first, 2026-10-07). Snapshotted as
  `<run>_migration_readiness.parquet` / `.sql`; `--migration-from <run>`
  replays it, `--no-migration` leaves the columns out (byte-identical to the
  earlier output). Measured on `zeus_hierarchy_2026_10_07_1550_migration`:
  16,887 ready, 55,253 not, 61 in no table (all but one in scope), 18 from
  another type's table, 81 health systems whose tables disagree. Nothing else
  in the outputs changes.
- `Hierarchy_Logic.md` — reference for the Zeus hierarchy, written
  2026-10-07: nodes, universe, resolution bases, the Definitive parent walk,
  every `Zeus_Link_Status`, the Zeus tie-break, duplicates, measured results,
  open questions and a change log. **Update it whenever a hierarchy rule
  changes**, with before/after figures from a replay.
- `dhc_hierarchy.py` — the Definitive ownership hierarchy, added 2026-09-30
  for comparison with the migration team's destination data. It reads every
  block under `hierarchy:` in `sources.yaml` and unions them: Hospital
  Overview (`Definitive Hospital Hierarchy.sql`) and, since 2026-10-07,
  Physician Group Overview (`Definitive Physician Group Hierarchy.sql`;
  decision #18). Parent = `SfParentAccountId`, else `IdNetwork`, else the
  record's own `HospitalId` (a root). The rule lives in each SQL file only, and
  the script just walks it. The workbook is
  `Definitive_Ownership_Hierarchy_<run>.xlsx` (was
  `Definitive_Hospital_Hierarchy_...` before physician groups). With physician
  groups in: 153,508 records, 142,595 trees (1,566 with more than one member),
  depth ≤ 3, 2,768 parents outside both views (corporate owners such as The US
  Oncology Network, AMSURG, RadNet), 95.7% of groups standalone. The
  hospital-only figures that follow are from 2026-09-30.
  Every record gets **both** an `Immediate_Parent*` (direct owner, full tree,
  depth ≤ 2) and an `Ultimate_Parent*` (top-level owner, flattened), labelled.
  Both are kept by Grant's decision on 2026-09-30, because the destination
  system may model divisions (HCA North Texas, VISN 1) as their own accounts
  or not. They differ for 2,247 records (`Has_Intermediate_Parent`). Writes
  `<run>_hierarchy_immediate.csv` and `_ultimate.csv` (one edge list per
  grain), `<run>_hierarchy.csv` (both on one row, with path and counts) and a
  branded workbook, and snapshots the view like the audits.
  `--accuracy <scored.csv>` attaches the Zeus EntityIds per id. The
  comparison against the migration team's data is not built yet, because
  their data's shape is unknown. Measured 2026-09-30: 9,887 records, 2,589
  trees, 683 of them with more than one member, no cycles, 2 parents absent
  from the view (kept, flagged `Parent_Not_In_Definitive`). Every parent is a
  health system; no hospital sits under a hospital.
  **How the rule really behaves:** on every hospital, `SfParentAccountId`
  equals `IdNetwork` (6,937) or both are empty (1,772, standalone). On every
  health system, `IdNetwork` is the record's own id, and `SfParentAccountId`
  is the larger system above it (363). So step 2 never yields a parent that
  steps 1 and 3 would not. It is kept as specified in case Definitive ever
  populates `IdNetwork` without `SfParentAccountId`. Physician groups behave
  the same way (2026-10-07): 6,205 of 143,617 have a parent, every one through
  `SF_PARENT_ACCOUNT_ID`, pointing at a hospital (2,358), a health system
  (1,080) or a corporate owner in neither view (2,767).
  **Practice locations are leaves since 2026-10-07** (decision #19): the
  audits' own `locations:` block and `Definitive Practice Locations.sql`,
  unchanged, add one node per location one level below its parent record,
  keyed `Location_Key` (`L<parent id>-<hash>`); every file then leads with
  `Node_Id` and gains `Location_*` columns. `--no-locations` reproduces the
  records-only output byte for byte, and is the only way to replay a
  hierarchy run without a `_dhc_practicelocations` snapshot. They are added
  after `walk()`, so `zeus_hierarchy.py` (which imports `load_hierarchy()` and
  `walk()`) never sees them. Run `dhc_hierarchy_2026_10_07_1515`: 549,894
  nodes = 153,508 records + 396,386 locations, 195,219 trees, depth ≤ 4;
  326,844 locations sit under a record (300,039 physician groups, 23,482
  hospitals, 3,059 health systems), 69,542 under 54,326 parent ids in no
  view (10 of them GPOs), flagged `Parent_Not_In_Definitive`. About 6 min;
  the workbook is ~167 MB. **GPOs stay out** (Grant, 2026-10-07): they are
  purchasing affiliations, not owners. `hospitaloverview.PrimaryGpoId`
  (7,770 of 9,891, all resolving to the GPO view) is the link if a GPO
  affiliation layer is ever wanted.
- `Zeus_DHC_ID_Audit_Business_Overview.md` — plain-language overview of the
  project for business readers, written 2026-09-28 from the 2026-08-12 and
  2026-08-19 runs. Its figures are hand-copied, so update it after a new run.
- `Usage.md` — operator guide, written 2026-09-29: where to run, the commands
  for both audits, expected console output and the checks to make, files
  written, and common failures. Update it when a flag, output file or sheet
  changes.
- `Environment.md` — handover guide for a new Windows 11 machine, written
  2026-09-29: access to request, software and package versions, secrets and
  Databricks login, which Python to use (the `.venv` trap), and development
  notes. Update it when a dependency or connection setting changes.
- `Matching_Logic.md` — reference for the matching itself, written 2026-10-05:
  every normalisation map (`NOISE_TOKENS`, `ADDR_ABBREV`, `CITY_ABBREV`), how
  names, street lines, city, state and zip are scored, the weights, the verdict
  and tier thresholds, known limitations, and a change log of measured effects.
  **Update it whenever a map, weight or threshold changes**, with before/after
  figures from a replayed run.
- `sources.yaml` — column-role and connection config. **This is the only file to
  edit when a new Definitive export arrives.**
- **Twelve Zeus queries** — two per population, for X in Client, Work Location,
  HealthSystem, GPO, Agency, VMS:
  - `Zeus <X> to Definitive ID data quality evaluation.sql` — entities that
    carry a DHC ID (`query_file` in the config, read by `dhc_match_v2.py`).
  - `Zeus <X> missing Definitive ID.sql` — entities that carry none
    (`gap_query_file`, read by `dhc_gap_match.py`).

  They select the same rows through the same joins with the same
  `EntityDescription` exclusion, and the ID predicate is inverted, so the two
  populations partition one universe. The complement is **not** a bare `NOT`:
  see decision #12. Each reads its own `*Info` table and so its own column names,
  mapped to roles per-population under `zeus.sources` — one mapping serves both
  queries, because the column aliases are identical. See decision #10 for why
  populations are pooled rather than stacked.
- `Zeus entity phones.sql` — every population's phone numbers in one query
  (`zeus.phone_query_file`), labelled with the population so they pool like
  names and addresses. Its `Zeus_Source` labels must equal the `label:` values
  under `zeus.sources`. See decision #14.
- **Four Definitive queries**, one per Databricks view in
  `prd_silver.definitive`, all read live since 2026-09-29 — see "Definitive in
  Databricks" below. Each replaced an xlsx export that was a pull of the same
  view with its columns renamed; the xlsx files are no longer read.

  | Query file | View | Rows 2026-09-29 | Replaced |
  |---|---|---|---|
  | `Definitive Hospital Overview.sql` | `hospitaloverview` | 9,887 | `Definitive_HospitalOverview.xlsx` (9,870) |
  | `Definitive Physician Group Overview.sql` | `physiciangroupsoverview` | 141,801 | `Definitive_PhysicianGroupOverview.xlsx` (138,385) |
  | `Definitive GPO Overview.sql` | `grouppurchasingorganizationoverview` | 213 | `Definitive_GPO_Overview.xlsx` (212) |
  | `Definitive Practice Locations.sql` | `physicianspracticelocations` | 396,386 | `Definitive_Practice_Locations.xlsx` (399,990) |

  The first three are **identity sources**, one row per entity, keyed
  `HospitalId` in every view (for physician groups that is the practice's own
  id, not a parent). They share no ids. The fourth is **a child table, not an
  identity source**: configured under `locations:`, never `definitive:` (decision
  #9), keyed `PracticeLocationHospitalId`, the parent's id. Its view is one row
  per *physician* per location (~4.6M rows); the query's `DISTINCT` and
  `WHERE PracticeLocationHospitalId IS NOT NULL` reduce it to one row per
  location of a known parent — drop either and the location set is wrong
  (~1.09M distinct locations carry no parent id).

  **The physician-group view broke for eight hours on 2026-10-07.** A
  processing error reloaded the parquet behind `physiciangroupsoverview` at
  02:10 Eastern with UPPER_SNAKE names (`HOSPITAL_ID`, `HQ_CITY`), every
  column a string, while the view (owner jborn@) still selected `HospitalId`,
  so every query of it failed `UNRESOLVED_COLUMN` — both audits included. The
  view was redefined over the new files at 10:25 Eastern (mangala.iyer@) and
  works again, but **now returns every column as a string**; the tools convert
  ids with `pd.to_numeric`, and both physician-group queries cast `HospitalId`
  to INT so snapshots keep their type. The 2026-10-07 08:34 runs
  (`dhc_match_v2_2026_10_07_0834` and the coverage, hierarchy and Zeus
  hierarchy runs built on it) read the parquet directly with the names aliased
  back — their snapshot `.sql` files show it — and matched the 2026-10-05 runs
  (12,803 entities, 11,097 testable). That workaround was removed once the view
  was fixed; if a view breaks the same way again, tell its owner rather than
  routing around the governed view. The view also has columns no tool read
  before 2026-10-07: `NetworkId`, `NetworkParentId`, `HospitalParentId`,
  `SfParentAccountId` (the parent; 4.3% filled), `NationalProviderIdNumber`
  (89% filled), `CompanyStatus`, `FirmType`.
- **Three Zeus hierarchy queries**, read by `zeus_hierarchy.py` only (keys
  `hierarchy_query_file`, `linked_import_query_file`, `duplicates_query_file`
  under `zeus:`): `Zeus hierarchy links.sql`, `Zeus linked import
  entities.sql`, `Zeus entity duplicates.sql`. The first two read tables no
  other query touches — `dbo.LinkClientWorkLocation`,
  `dbo.LinkHealthSystemClient`, `dbo.LinkClientWorkLocationHistory`,
  `dbo.BookingClientWorkLocation`, `dbo.Booking`. Measured 2026-10-07 on the
  in-scope population: 99.3% of work locations have a client link (7,905 have
  two or more; 11,996 links are an entity linked to itself); 80% of clients
  have no health system link (2,321 have two or more);
  `HealthSystemInfo.HealthSystemInfoParentId` is filled on 3 rows, so Zeus has
  no health system hierarchy of its own. 13,441 work location -> client and
  3,138 client -> health system links point at Definitive-import-created
  entities, which the audits exclude — hence decision #17's universe rule.
- `Zeus_DHC_ID_Accuracy_Audit.xlsx` — **kept as the reporting format template,
  not as a result.** Its numbers are file-era and must not be quoted; see
  "Reporting template" below for the structure worth reusing.

## Environment

Python 3.10+ with `pandas numpy openpyxl rapidfuzz pyyaml pyodbc`, plus an
ODBC driver (17 or 18 for SQL Server). Definitive paths in `sources.yaml`
resolve relative to the current working directory.

Zeus is read live from the failover replica. Two things are required:

- `ZEUS_SQL_PASSWORD` must be set — the password is never stored in
  `sources.yaml`, only the env var name is.
- `application_intent: ReadOnly` must stay in the connection block. The host is
  a failover-group listener; without the declared intent the connection is
  routed as read-write. `load_zeus()` asserts the landed database is
  `READ_ONLY` and warns if it is not.

```
py dhc_match_v2.py inspect <NewDefinitiveExport.xlsx>
py dhc_match_v2.py run --config sources.yaml [--label <suffix>] [--no-reverse]
py dhc_match_v2.py run --config sources.yaml --zeus <archived_extract.csv> \
    --definitive-from "Results Output/<archived run folder>" ...
```

### Definitive in Databricks

A block under `definitive:` or `locations:` names one of `path:` (a local
export), `query_file:` (a Databricks SQL file, run as written) or `table:` (a
Unity Catalog table or view — shorthand for a `SELECT` of the role columns).
**Each query lives in a `.sql` file, like the Zeus queries** — the four
`Definitive *.sql` files, tracked in git, runnable by hand in the Databricks SQL
editor. Edit it to filter or join; its output column names must
still match the block's roles, and a run stops and names any that are missing.
A `query_file` block also needs `snapshot:`, which names the snapshot file, so
renaming the `.sql` never changes it. Both kinds are read through the
top-level `databricks:` block — workspace host, CLI profile `jcl`, and the
`qat-eus-jcl-Databricks-W-M` warehouse — needing `databricks-sql-connector`,
`databricks-sdk` and `pyarrow`. Authentication is OAuth held by the Databricks
CLI; if a run fails to authenticate, re-run
`databricks auth login --profile jcl`. No secret is stored anywhere.

Databricks is live, so `materialise_tables()` queries each source **once per
run**, writes `<run>_dhc_<snapshot>.parquet` plus a byte-identical copy of the
SQL it ran as `<run>_dhc_<snapshot>.sql`, and repoints the block at the
parquet; everything downstream reads a file exactly as before. The `.sql` copy
records which query produced a snapshot even after the tracked file is edited.
Consequences:

- The snapshot is to Definitive what `_zeus_extract.csv` is to Zeus. **Keep it
  with the run outputs.** `--definitive-from <run folder or prefix>` replays it; with both
  `--zeus` and `--definitive-from` a run is fully offline and reproducible.
  A replaying run **copies** the snapshots (and their `.sql`) into its own
  folder, so its workbook can be built from that folder alone — before
  2026-09-29 it did not, and the builder refused such a run.
- `build_audit_workbook.py` reads the run's own snapshot (derived from the
  `--scored` prefix) and **stops** if it is missing rather than reading live —
  a workbook built from different reference data than the run scored would be
  internally inconsistent. Runs from before 2026-09-29 have no snapshot; build
  those with a config that still points at the xlsx.
- Snapshots are parquet, not csv, so zip codes and ids keep their types.
- **The views are refreshed in place.** The parquet files behind
  `physicianspracticelocations` were all rewritten on 2026-09-29 at 15:32 UTC.
  Two runs an hour apart can read different Definitive data; only the snapshot
  says which a result used.

Verified 2026-09-29, hospitals only, by replaying the 2026-08-12 Zeus extract
against the live view: 11,099 testable and 1,704 unverifiable, both unchanged; 5 verdicts moved,
every one a hospital Definitive has renamed since the xlsx was pulled (3 up,
2 down); 10,740 → 10,741 corroborated. Definitive's `(Closed)` / `(Merged)`
name markers survive in the view (1,134 names versus 1,130 in the xlsx), so
`Suggested_Status_Note` is unaffected. The view also has a `CompanyStatus`
column (Active / Closed / Opening) that the tools do not read yet — 247 hospitals
are `Closed` there with no marker in the name.

**All four views, 2026-09-29**, replaying the archived Zeus extracts so that
only the Definitive side changed (runs `*_2026_09_29_1214_all4_dbx_test`):

- Accuracy, against 2026-08-12: 11,098 testable (−1: Definitive has since
  dropped that id), 10,735 corroborated (was 10,740), 98.8% corroborated-or-
  probable (unchanged), 35 recommended corrections (was 33). 15 verdicts moved,
  5 up and 10 down, every one traced to a Definitive rename or to a location
  name that no longer exists (e.g. Fort Meade VA lost its
  `... - Fort Meade Campus` location, name score 97 → 71).
- Coverage, against 2026-08-19: 19.5 min. Strong 9,702 → 9,665, ambiguous
  8,406 → 8,453, no credible match 16,561 → 16,545 — **the totals barely move,
  but 4,816 entities (9.9%) changed tier and 2,988 proposed ids changed.** Of the
  402 that left the strong tier (365 entered it), 386 trace to Definitive data:
  49 proposed ids no longer exist, 250 had their own locations change, 81 had a
  rival's change, 7 renames or new rival records; 16 are unattributed. Strong-tier
  `Matched_Via` stayed mostly `Name` (7,848 of 9,665).
- Definitive churns faster than the xlsx era suggested: between the 2026-07-31
  export and 2026-09-29, 10,508 of 258,004 location (id, name) pairs vanished
  and 9,714 appeared; 4,916 parent ids lost every location and 5,155 gained
  their first. **A coverage proposal list is only good against the Definitive
  snapshot it came from** — re-run before loading an old one.

## Run folders

Every run writes **everything it produces into its own folder** under
`Results Output/`, named for the program and the minute it started:

```
Results Output/
  dhc_match_v2_2026_09_29_1422/            <- one accuracy run
    dhc_match_v2_2026_09_29_1422_scored.csv
    dhc_match_v2_2026_09_29_1422_unverifiable.csv
    dhc_match_v2_2026_09_29_1422_zeus_extract.csv
    dhc_match_v2_2026_09_29_1422_dhc_hospitaloverview.parquet
    dhc_match_v2_2026_09_29_1422_dhc_hospitaloverview.sql
    Zeus_DHC_ID_Accuracy_Audit_2026_09_29_1422.xlsx
  dhc_gap_match_2026_09_29_1450/           <- one coverage run
    ..._gap_candidates.csv, _gap_nomatch.csv, _zeus_extract.csv, _dhc_*.parquet
    Zeus_DHC_ID_Coverage_Audit_2026_09_29_1450.xlsx
```

- `new_run_prefix()` in `dhc_match_v2.py` creates the folder; both run tools
  call it. Every file inside is prefixed with the folder name, so a file copied
  out still says which run wrote it. There is no `--out` prefix to choose any
  more; `--label <x>` appends `_x` to the folder name (`--out` is still accepted
  as an alias for it). Two runs in the same minute get `_2`, `_3`.
- The workbook builders write **into the run folder they were given**, named for
  that run's date and time (not today's), so `--out` is optional. A bare
  `--out name.xlsx` still lands in the run folder; a path goes where it says.
  Rebuilding an old run therefore overwrites its workbook, so pass `--out`
  elsewhere to compare.
- `--definitive-from` accepts a run folder as well as a prefix.
- The whole folder is git-ignored (`Results Output/`), so one run folder is
  the unit to archive to a governed store alongside a circulated deliverable.

**Folders from before 2026-09-29 were moved in by hand** and keep their original
file names. The folder time is when that run's Zeus extract was written, which
is close to when it started:

| Folder | Files | What it was |
|---|---|---|
| `dhc_match_v2_2026_07_30_1711` | `audit_2026_08_*` | File era. No extract, so the time is when it *finished* |
| `dhc_match_v2_2026_07_31_1133` | `audit_2026_08_live_*` | First live run, Client-only, HQ-only |
| `dhc_match_v2_2026_07_31_1601` | `audit_2026_08_all4_*` | Client-only, all four Definitive sources |
| `dhc_match_v2_2026_08_12_1643` | `audit_2026_08_all6_*` | Six populations |
| `dhc_match_v2_2026_08_12_1701` | `audit_2026_08_12_*` + its workbook | Six populations, re-run: the one the Results figures and `--claimed` come from |
| `dhc_gap_match_2026_08_19_1239` | `gap_2026_08_19_*` + its workbook | First coverage run |

`Zeus_DHC_ID_Accuracy_Audit.xlsx` stays in the project root: it is the reporting
template, not a run's output.

## Producing a new audit summary

Two commands. The first prints `Run folder  : Results Output/<run>`; the second
takes that run's scored file.

```
py dhc_match_v2.py run --config sources.yaml

py build_audit_workbook.py --scored "Results Output/<run>/<run>_scored.csv"
```

`--baseline <earlier>_scored.csv` is **optional**: it adds a section comparing
this run against an earlier one on the entities common to both. Omit it and that
section is left out entirely; nothing else changes.

### One population only: `--population`

Both workbook builders take `--population <label>` (a `zeus.sources` label —
`WorkLocation`, `Client`, `HealthSystem`, ...; case and spaces ignored, so
`"work location"` works). Every sheet, headline, total and identity is then
limited to entities in that population, and the workbook is named
`Zeus_DHC_ID_Accuracy_Audit_<label>_<run>.xlsx` (or `..._Coverage_Audit_...`),
so it never overwrites the full one. Built 2026-09-29 for a third-party
data-cleaning group working the Work Location subset:

```
py build_audit_workbook.py --scored "Results Output/<run>/<run>_scored.csv" \
    --population WorkLocation
py build_coverage_workbook.py --candidates ".../<run>_gap_candidates.csv" \
    --accuracy ".../<accuracy run>_scored.csv" --population WorkLocation
```

**`--population` is additive, never a carve-out:** the runs always score all six
populations and the full workbooks are always built; a scoped workbook is an
*extra* view of the same results (`run_all.py --population X` writes four
workbooks, not two). Usage.md's "`--population` labels" table lists all six
labels with their counts; `VMS` has no testable ID-carrying entity, so its
accuracy Summary states that instead of a rate (a divide-by-zero before
2026-09-30).

It filters the run's **outputs, never the scoring**. A Work Location entity that
is also a Client is still matched on every name and address it holds in any
population (decision #10) — do not get the same effect by filtering the query
instead: adding `e.IsClient = 0` to the Work Location queries was measured on
2026-09-29 and moved 15 accuracy verdicts, all downward, added 6 false
`Geo_Conflict` rows, and dropped 15 entities from both audits entirely (flagged
`IsClient` with no active `ClientInfo` row). Membership means "flagged in that
population", alone or alongside others: 10,047 Work Location entities carry an
id, 5,946 of the 9,228 testable are also Clients. In the scoped accuracy
workbook `Unreferenced_Definitive` means records none of *these* entities points
at, and the coverage workbook's estate section (`--accuracy`) is scoped too.

`Matched_Zeus_Source` says whether a result rests on the population's own name.
On the Work Location subset it rarely does not: of the 5,946 testable Work
Location entities that are also Clients, 159 verdicts rest on a name only the
Client row holds.

Step 1 writes `<run>_scored.csv`, `_unverifiable.csv`,
`_zeus_extract.csv` and one `_dhc_<table>.parquet` per Databricks source; step
2 turns them into the branded workbook in the same folder. Roughly two to
three minutes end to end, most of it reading the 400k-row location export.

Preconditions — all currently satisfied:

- `ZEUS_SQL_PASSWORD` set at User scope. If it is missing the run stops
  immediately and names the variable.
- `pyodbc` plus ODBC Driver 17 or 18 installed.
- A valid Databricks CLI login for profile `jcl` (`databricks auth profiles`
  shows `Valid YES`), plus `databricks-sql-connector databricks-sdk pyarrow`.

Check four things in the step-1 output before circulating anything:

1. `connected to a READ_ONLY database`. Anything else means the ReadOnly intent
   is not being honoured — stop.
2. No `NOTE: ±N vs the expected …` line, or a small explicable one. A large jump
   means the Zeus population moved; find out why before quoting a rate, then
   update `ZEUS_BASELINE_ENTITIES`.
3. Each of the six populations reports a plausible row count. A population
   dropping to zero means a query or a column was renamed.
4. In the workbook: testable + unverifiable = supplied, and the verdict counts
   sum to testable. Those two identities catch most wiring mistakes.

**Keep `<run>_zeus_extract.csv` with anything you circulate.** Zeus is a
live moving target and the snapshot is the only way to reproduce a figure later.
Verified: replaying it with `--zeus` reproduces the run exactly.

When a **new Definitive export** arrives, run `inspect` on it and update
`sources.yaml` — under `definitive:` for an identity export, or `locations:` if
it has many rows per id (decision #9). When a **new Zeus population** is added,
add a block under `zeus.sources` with that query's own column names; nothing
else needs to change (decision #10).

Every run writes `<run>_zeus_extract.csv`, a snapshot of the exact input it
scored. Zeus is a live moving target and these snapshots are **not** in git (see
"Version control"), so one is still the only way to reproduce a figure later —
keep it with any results you circulate. The `--zeus` flag replays one offline.

## Producing a coverage run (the missing IDs)

One command, same config, its own run folder:

```
py dhc_gap_match.py --config sources.yaml \
    --claimed "Results Output/<accuracy run>/<accuracy run>_scored.csv"
```

`--claimed` is **optional**: point it at a scored accuracy run and every proposal
whose ID some other Zeus entity already points at is flagged
(`Suggested_Id_Already_In_Zeus`). That is not an error — a client entity and a
work-location entity legitimately share a Definitive record — but it is worth
seeing before loading. `--zeus <extract.csv>` replays a snapshot offline, and
`--limit N` scores the first N entities for a quick check.

Writes `<run>_gap_candidates.csv` (every entity with a credible proposal,
best plus two alternates), `<run>_gap_nomatch.csv`, and
`<run>_zeus_extract.csv`, plus the `<run>_dhc_<table>.parquet`
Definitive snapshots, all in `Results Output/dhc_gap_match_<date>_<time>/`. The
extract is written on a `--zeus` replay too, so a replayed run's folder is
complete on its own. **Keep the extract and snapshots with anything you
circulate**, for the same reason as the accuracy run; `--definitive-from`
replays the snapshots. Roughly 20–30 minutes, most of it the
400k-row location export and the exact-scoring pass.

The output columns that carry the reasoning, and which reviewers need:

| Column | What it answers |
|---|---|
| `Match_Tier` | The verdict. See decision #11 for what each tier requires |
| `Matched_Zeus_Name` / `Matched_Definitive_Name` | **Which two strings actually matched.** Not the same as `Zeus_Name` / `Suggested_Name`: pooling means the winning Zeus name may not be the first one, and the winning Definitive string may be an alias or a service location. The accuracy output carries the same four `Matched_*` columns since 2026-09-29, from the shared `name_provenance()` in `dhc_match_v2.py`; the pair reproduces `Name_Score` exactly |
| `Matched_Zeus_Source` | Which Zeus population(s) hold the winning Zeus name, e.g. `Client` or `Client\|WorkLocation`. Built in `_pool()`, which records each name's populations |
| `Matched_Zeus_Address/City/State/Zip`, `Matched_Definitive_Address/City/State/Zip` | **The address pair that produced the street scores**, each line with its own place. Added 2026-09-29, both tools. Not the same as `Zeus_Address` (the first pooled address) or the Definitive HQ: where `Address_Match_Source = Location` the Definitive side is a service location — e.g. Zeus `317 Martin Luther King Jr Way, Tacoma` scoring 100 against a satellite whose HQ is `305 S L St`. `addr_scores()` returns the winning Zeus line, `enriched_scores()` an 8th provenance element, and `location_index()` / `_pool()` keep an address → (city, state, zip) map. The pair reproduces `StreetNum_Score` / `StreetName_Score` exactly. `City_Score` and `Zip_Score` are still taken across every known site, so they can agree where the matched pair's city does not |
| `Suggested_Address/City/State/Zip` (coverage) / `DHC_Addr1`, `DHC_City`, `DHC_State`, `DHC_Zip` (accuracy) | The Definitive record's HQ, for reference beside the matched pair. Both are on every review sheet, next to the Zeus columns |
| `Zeus_Phones`, `Suggested_Phone` / `DHC_Phone`, `Phone_Match`, `Matched_Phone` | Decision #14. `Phone_Match` is True / False / blank for the proposed (or supplied) id; blank is absence of evidence, not disagreement |
| `Phone_Favours_Alt`, `Alt1_Phone_Match`, `Alt2_Phone_Match` (coverage) | Exactly one of the three candidates shares the entity's number and it is a runner-up. Sheet `Phone_Favours_Alt` |
| `Phone_Lookup_DHC_Id` / `Phone_Lookup_Name`, `Phone_Points_Elsewhere` | The one Definitive record holding the entity's number, whatever the name says. On the coverage no-match file this is sheet `Phone_Only_Match` (leads the name search missed); on the accuracy unverifiable file it is the only lead an unmatched id has (517 of 1,705 on 2026-09-29); `Phone_Points_Elsewhere` (accuracy) is a supplied id whose number belongs to someone else |
| `Matched_Via` | `Name`, `Alias` or `Location`. `Location` means Definitive lists your entity as a service location of the proposed parent — the ID is the **parent's**, which is usually what you want but should be understood before loading |
| `Match_Margin` | Distance to the runner-up. Below 3 the tier is forced to `Ambiguous` |
| `Same_Name_Rivals` | How many other candidates matched the name about as well |
| `Suggested_Status_Note` | Definitive's own `(Closed)` / `(Merged)` marker on the proposed record |
| `Alt1_*`, `Alt2_*` | What was rejected, so a reviewer can overrule the pick |

Then build the deliverable:

```
py build_coverage_workbook.py \
    --candidates "Results Output/<run>/<run>_gap_candidates.csv" \
    --accuracy "Results Output/<accuracy run>/<accuracy run>_scored.csv"
```

`--accuracy` is **optional**: it adds a whole-estate coverage section to the
Summary, putting the linked and unlinked populations side by side and stating
what loading the strong tier would do to coverage. It reads the scored file
*and* its `_unverifiable.csv` sibling, because both halves are linked entities —
counting only the scored file understates the estate by 1,704.

Twelve sheets, the accuracy workbook's shape applied to the complement question.
`Ready_To_Load` is the actionable one; `Parent_Id_Proposals`,
`Shared_Id_Proposals`, `Id_Already_Linked_In_Zeus` and `Status_Flagged` are the
four populations to understand before loading; `No_Credible_Match` is the input
to any "buy more Definitive data" conversation. The builder re-asserts three
identities and prints OK/FAIL for each: tier counts sum to the population, the
review sheets plus no-match sum to the population, and the extract's entity
count equals the population.

Check in the output before circulating anything:

1. `connected to a READ_ONLY database`, as for the accuracy run.
2. No large `NOTE: ±N vs the expected 48,739 entities`. If the population moved,
   find out why before quoting a rate, then update `GAP_BASELINE_ENTITIES`.
3. The tier counts sum to the supplied population, and
   `gap_candidates` + `gap_nomatch` rows sum to it too.
4. The strong tier's `Matched_Via` breakdown is mostly `Name`. A sudden jump in
   `Location` means the filters in decision #13 have stopped biting.

## Version control

The folder is a git repo with a **private** GitHub remote,
`GrantJCLT/Zeus-DHC-Ids-to-Definitive-Source-Fuzzy-Matching`. Keep it private:
the history contains licensed Definitive exports and Zeus client records.

Only source is tracked — the four scripts plus `run_all.py`, `dhc_hierarchy.py` and `zeus_hierarchy.py`, `sources.yaml`,
the twenty-three `.sql` files (twelve Zeus population queries, the Zeus phone
query, the three Zeus hierarchy queries, four Definitive sources, the hospital
and physician-group hierarchies, the migration readiness query), this file, `Usage.md`, `Environment.md`,
`Matching_Logic.md`, `Hierarchy_Logic.md`, the business overview, and `.gitignore`. Everything else is deliberately ignored:

| Ignored | Why |
|---|---|
| `Definitive_*.xlsx` | Licensed third-party data. A git remote is redistribution — confirm terms with the licence owner before these leave this machine. |
| `Results Output/` | Every run folder: Zeus client names and addresses, Definitive snapshots, workbooks. The suffix rules (`*_scored.csv`, `*_zeus_extract.csv`, …) remain as a backstop for anything written outside it. |
| `*_dhc_*.parquet` | Per-run snapshots of the Databricks-held Definitive tables — the same licensed data as the xlsx exports. |
| `Zeus_DHC_ID_Accuracy_Audit*.xlsx` | Generated by `build_audit_workbook.py`. |
| `__pycache__/`, `.env`, `*.local.yaml` | Artifacts and secrets. |

`sources.yaml` is safe to track: it stores `password_env: ZEUS_SQL_PASSWORD`,
never the secret itself.

Two consequences worth knowing:

- **Reproducibility does not come from git.** Nothing that identifies a
  population or a result is versioned, so a scored run is reproducible only if
  its `_zeus_extract.csv` survives outside the repo. Somewhere governed —
  SharePoint or blob storage, alongside the circulated deliverable — is the right
  home; a working directory is not. This is the live half of what used to be
  open work #5.
- **The first commit still carries the data.** `f7f0e4e` added all 23 files
  (~100 MB) before the ignore rules existed, and it is on `origin/main`. The
  files are out of `HEAD` but remain in history until it is rewritten. See
  open work #5.

## Results

Six Zeus populations against all four Definitive sources, 2026-08-12
(`Results Output/dhc_match_v2_2026_08_12_1701/audit_2026_08_12_*`). 19,820 population rows pooled to **12,803 distinct
entities**; 11,099 testable (86.7%); 202,586 reference records.

**The headline is now stated over the whole population**, not just the testable
part. Decision #1's warning was written when the hospitals-only export left 95%
unverifiable; at 13.3% that framing hid more than it protected. Both denominators
are given, and the untestable remainder is a row rather than an omission:

| Of 12,803 Zeus objects carrying a Definitive identifier | | |
|---|---|---|
| Confirmed — points at the right record | 10,740 | 83.9% |
| Probably right | 224 | 1.7% |
| Needs review | 116 | 0.9% |
| Likely wrong identifier | 19 | 0.1% |
| Cannot be tested — id in no Definitive export | 1,704 | 13.3% |

Those five rows sum to 12,803. Of the 11,099 that can be tested, 96.8% are
confirmed and 98.8% confirmed-or-probable — still the right figure for "of the
ones we can check", and the one the per-population and per-entity-type tables
below use.

| Definitive entity type | Rows | Corroborated |
|---|---|---|
| Hospital | 8,612 | 8,419 (97.8%) |
| PhysicianGroup | 2,478 | 2,317 (93.5%) |
| GPO | 5 | 4 |
| PracticeLocation (location-only ids) | 4 | 0 |

| Zeus population | Testable | Corroborated |
|---|---|---|
| WorkLocation | 9,229 | 8,953 (97.0%) |
| Client | 7,666 | 7,470 (97.4%) |
| HealthSystem | 578 | 556 (96.2%) |
| GPO | 1 | 0 |
| Agency | 1 | 1 |
| VMS | 0 | — (its one entity is unverifiable) |

Populations overlap, so those rows sum to more than 11,099; only 4,881 of the
11,099 testable entities belong to exactly one population.

Whole testable population: 96.8% corroborated, 98.8% corroborated-or-probable,
19 likely-wrong (0.2%), 116 needs-review, 579 `Address_Divergent`,
27 `Geo_Conflict`, 33 recommended corrections, 1,704 unverifiable.

**Pooling paid off and cost nothing.** On the 7,666 Client entities scored both
before and after the other five populations were added: 33 name scores and 241
address scores improved, 15 verdicts moved up to `ID corroborated`, and **no
verdict regressed**. Client corroboration went 97.2% → 97.4% on an identical
row set.

**Earlier single-population figures**, for reference only — the denominators
differ, so these are not a trend: Client-only with all four Definitive sources
was 7,666 testable at 97.2%; Client-only HQ-only was 7,659 at 96.8%.

**What the service-location data bought**, measured against the identical 7,659
rows scored HQ-only earlier the same day:

| | HQ only | + locations |
|---|---|---|
| Corroborated | 96.8% | **97.2%** |
| `Address_Divergent` | 659 | **466** (−29%) |
| `Geo_Conflict` | 25 | **17** |
| Needs review | 70 | **61** |

778 rows matched a satellite address rather than HQ (median `Address_Score` 100).
937 rows gained address score, mean gain 20.8 points; 10 went from
`State_Score` 0 to 100; 45 verdicts changed, all but two upward — the largest
group being 18 rows moving from `Probable - name agrees, address differs` to
`ID corroborated`. No name score decreased.

Widening identity to GPO and location-only ids added just **7 testable rows**.
Essentially all the value came from the address and alias enrichment, not from
the extra identity sources — worth knowing before buying another export.

**Do not compare these to the file era.** The previous figures (105,917 testable,
97.5% hospital / 94.7% practice) came from a 207,450-row workbook that was
**95.6% Definitive-import-created records** — see the `EntityDescription` note
under Known data quirks. Those records are excluded now, so the two runs measure
different populations, not the same population before and after a tweak. The
workbook was deleted on 2026-07-31 and the file-era numbers cannot be
regenerated.

## Coverage results

First coverage run, 2026-08-19 (`Results Output/dhc_gap_match_2026_08_19_1239/`), against the same four
Definitive sources. 54,242 population rows pooled to **48,739 distinct entities
carrying no Definitive identifier** — measured with `--claimed` against the
2026-08-12 accuracy run. 23.7 minutes end to end.

| Of 48,739 Zeus objects with no Definitive identifier | | |
|---|---|---|
| Strong match — proposal ready to load | 9,702 | 19.9% |
| Probable match — review | 6,525 | 13.4% |
| Ambiguous — rival candidates fit equally | 8,406 | 17.2% |
| Weak match — review | 7,481 | 15.3% |
| No credible match in Definitive | 16,561 | 34.0% |
| No usable Zeus name | 64 | 0.1% |

Those six rows sum to 48,739; `gap_candidates` (32,178) + `gap_nomatch` (16,561)
does too. **Acting on the strong tier alone would lift identifier coverage from
20.8% to 36.6%** of all 61,542 Zeus entities. The 22,412 review rows are a
further 36% of the population, but they need a human.

| Zeus population | No identifier | Strong match |
|---|---|---|
| WorkLocation | 29,514 | 5,410 (18.3%) |
| Client | 24,106 | 5,646 (23.4%) |
| HealthSystem | 530 | 118 (22.3%) |
| GPO | 13 | 5 |
| VMS | 27 | 1 |
| Agency | 52 | 0 |

Populations overlap (5,461 entities carry more than one flag), so these sum to
more than 48,739 — the same caveat as decision #10.

**The strong tier is strong.** Median name score 100, median address score 100;
7,767 of 9,702 (80%) have street-level address agreement rather than merely
city/state; 8,024 match the name outright; 3,970 are exact name *and* geography.
By proposed Definitive type: 6,538 PhysicianGroup, 1,593 PracticeLocation,
1,561 Hospital, 10 GPO. By what matched: 7,867 on the entity's own name, 641 on
a parenthetical alias, 1,194 on a service location.

Three things to understand before loading any of it:

- **1,593 strong proposals name an id that an id-carrying Zeus entity already
  points at.** Normal — see the shared-ids note under Known data quirks — but it
  is a business question, not a data question.
- **2,738 strong rows propose an id that another *unlinked* entity also
  proposes**, across 1,049 ids. Investigated, and it is the expected shape
  rather than over-matching: 32 Zeus work locations propose id 1033471
  ("New Season") — they are 32 different clinics in 29 cities, each matching a
  **distinct service location** of that one parent, median address score 100.
  Definitive holds one id for the chain and Zeus holds 32 branches. Whether that
  is the wanted grain is a decision for the business.
- **186 strong proposals name a record Definitive itself marks `(Closed)` or
  `(Merged)`** (1,007 across all tiers). Reported in `Suggested_Status_Note`,
  never auto-demoted: a closed record can be the right id for a historical row.

**`Ambiguous` is doing real work at 17.2%.** These are rows where the name is
probably right but several Definitive records fit within 3 points of each other,
so taking the argmax would silently pick one. `Tampa General Hospital Clinics`
lands here against five same-name rivals. Left as an argmax these would have
been indistinguishable from genuine matches.

**34% have no credible match at all**, which is the single most useful number
for the "should we buy more Definitive data" question — it is a far better
target than the 1,704 unverifiable rows on the accuracy side.

## Decisions that must not be silently reversed

These were derived empirically against this data. Each one exists because the
naive alternative was measurably wrong.

1. **Always state the denominator, and state both.** An ID absent from the
   reference set is *unverifiable*, not wrong — the original form of this rule
   forbade quoting against the full population, because the hospitals-only
   export made 95% of rows untestable and "4.6% accurate" measured the export's
   scope rather than Zeus. With all four Definitive sources only 13.3% are
   untestable, so the honest headline now reports the whole population *with the
   untestable share shown as its own line*, alongside the testable-only rate.
   What is still forbidden is quoting one rate without saying which denominator
   it uses.

2. **Parse `(FKA ...)` aliases out of Definitive names and score against them.**
   3,046 of 9,870 hospital names (31%) carry a parenthetical former name. Without
   alias handling roughly a third of correct IDs get flagged as mismatches purely
   because the facility was renamed. See `split_name()`.

3. **Do not use bare `fuzz.token_set_ratio` for names.** It returns 100 whenever
   one token set is a subset of the other, so short generic names win
   spuriously ("Cleveland Clinic Health System" beat the correct longer match).
   `pair_score()` blends it 35/65 with `token_sort_ratio` to penalise the length
   gap. Verified: exact matches still score 100; the bogus subset case drops
   from 100 to ~66.

4. **Name outranks address, and address is reported separately.** Every
   Definitive address column is HQ-prefixed; Zeus stores the *service location*.
   For multi-site systems these differ legitimately — 421 rows have a perfect
   name match with address agreement under 60. A blended single score conflates
   "is the ID right" with "is our address current". `Verdict` is the field to act
   on; `Confidence_Score` is retained only for sorting and trending.

5. **A recommended correction must not worsen the location fit.** Without that
   guard the reverse lookup proposed Plano for Llano on string similarity alone.
   See the `Correction_Recommended` conditions.

6. **Multi-line address handling is deliberate.** Zeus spreads addresses over
   three columns and the street line is not always in the first
   (`ClientAddress1` = "Box 365", `ClientAddress2` = "417 1st Ave"). Every Zeus
   line is compared against every Definitive line and the best pair wins.
   **Lines that name only a unit (`Ste A`, `2nd Floor`) are excluded on both
   sides** (`is_unit_only()`, 2026-10-05). Before that, such a line competed as
   a street with a blank number and won 181 accuracy rows, 27 of them at
   `Address_Score` ≥ 85 with no street agreeing. A building number followed by
   a street (`Building 9040 Fitzsimmons Dr`) is not unit-only. See
   `Matching_Logic.md`.

7. **Do not strip `group`, `associates`, `partners` or `community` from
   `NOISE_TOKENS`.** This was predicted to be necessary for physician groups and
   measured against the real 138,385-record export instead. It is not — and it
   would be actively harmful. See "How `name_core` behaves on practices" below.
   Confirmed twice: on the file-era population 1,755 legitimate matches would be
   lost to win back 26 questionable ones; re-measured on the live population the
   core step rescues 88 of 2,155 practice rows (4.1%) with median full-string
   score 86.4 — the same near-miss signature, so the conclusion holds on the
   smaller, more meaningful denominator too.

8. **`Geo_Conflict` exists because `Verdict` deliberately cannot express it.**
   A strong name match where **no known location of the entity** is in Zeus's
   state — 17 rows. Decision #4 means these correctly read as
   `ID corroborated`, so the flag is a separate column rather than a verdict
   change. Do not "fix" this by folding state into the verdict; that
   re-conflates the two questions decision #4 separates. Note the definition
   became location-aware on 2026-07-31: it used to mean "the HQ is in another
   state", which produced 8 false alarms against entities that demonstrably
   operate where Zeus says they do.

9. **`Definitive_Practice_Locations.xlsx` must never be an identity source.**
   Its `DefinitiveId` is the *parent* entity's, repeated once per location —
   399,990 rows over 176,658 ids, one id carrying 962 locations. Listed under
   `definitive:` it would hit `drop_duplicates(subset=['DHC_Id'])`, silently
   discarding 223,332 rows and letting one arbitrary location overwrite the
   authoritative name and HQ for the 122,539 ids it shares with the overview
   exports. It belongs under `locations:`, where every location contributes a
   candidate address, city, state, zip and name alias to its parent. This is
   what finally addressed the HQ-versus-service-location gap that decision #4
   exists to work around.

10. **Zeus populations are pooled by `EntityId`, not stacked.** 6,855 of 12,803
    entities carry more than one flag (commonly `IsClient` *and*
    `IsWorkLocation`), and each `*Info` table holds a *different* name and
    address for the same entity. Stacked, an entity would be scored several
    times and the headline denominator would double-count it. Pooled, all its
    names and addresses become candidates and the best match wins — one verdict
    per entity, `Zeus_Sources` recording which populations contributed. Measured
    on the Client subset: 15 verdicts improved, none regressed. The per-
    population breakdown counts an entity once per population it belongs to, so
    those rows deliberately sum to more than the total; say so whenever it is
    quoted. A useful side effect is that junk names are harmless — `name_score`
    takes a maximum, so `DO NOT USE - Banner Health` sitting alongside
    `Banner Health` cannot lower a score.

11. **Coverage must not inherit decision #4's "name outranks address".**
    Verifying a supplied ID and proposing a new one are different burdens of
    proof. When Zeus already holds an ID, a name match corroborates it and a
    divergent address is usually just an out-of-date service location — so the
    verdict leans on the name and the address is reported separately. When
    nothing is on record, a name match alone establishes only that *some*
    Definitive record shares the name, and there are 138,385 physician groups to
    share it with. `Match_Tier` therefore requires **two independent agreements**
    before it calls a proposal loadable: either street-level address agreement
    (`Address_Score >= 85`), or a discriminative match on the entity's own name
    plus same-place agreement. It also demotes any winner a rival record matches
    about as well — `Ambiguous - rival candidates`, and on the live population
    that is the second-largest tier. Do not "simplify" this back to the audit's
    `verdict()`; the two answer different questions.

12. **The missing-ID complement is not a bare `NOT`.** Three things differ from
    naively negating the audit query's ID predicate, and each was a real bug:
    - `NOT EXISTS` against `LinkEntityVerifiedSource`, not a `LEFT JOIN`. An
      entity can hold several rows there, so "has no Definitive ID" is a claim
      about all of them; negating one joined row asks a different question.
    - `ISNULL(e.VerifiedSourceNameId, 0) = 1`. Negating `= 1` on a NULL yields
      NULL, not TRUE, so a bare `NOT` silently drops every entity whose source
      name is unset — which is most of this population.
    - The two ID columns are emitted as **typed NULLs**, not selected raw.
      `VerifiedSourceNameId` has five values (1 Definitive, 2 Definitive
      Executive, 4 NPI, 5 Axuall, 6 MDStaff); selecting `e.VerifiedSourceId`
      directly on a no-Definitive-ID row would carry a **non-Definitive**
      identifier into a column the tooling reads as a DHC ID. Other-source
      linkage is exposed separately as `OtherVerifiedSources`, which is there
      for running the query by hand — `_canonicalise` keeps only the configured
      role columns, so it does not reach the scored output.

13. **A service-location name may enrich a candidate but must not, on its own,
    select one.** Decision #9 made every location name an alias of its parent.
    That is safe when the ID is given — an alias can only raise the score of the
    one record being tested. It is not safe when the ID is being chosen, because
    an alias can now *select* a record. Two classes of location name identify
    nothing and are dropped from the coverage tool's search space and name
    enrichment (never from its **addresses**, which remain evidence of where the
    parent operates):
    - **Shared names** — a name core used by ≥5 distinct parent IDs. `family`
      sits under 154 parents, `family medicine` 77, `gastroenterology` 53.
      Drops 1,691 cores / 29,477 rows (7.5%).
    - **Branch labels** — a name that is only the branch's own city or a compass
      word: `East Indianapolis` in Indianapolis, `West` in Avon.

    Both were found by tracing false positives, not predicted. `Gastroenterology
    Associates, P.A.` (Little Rock) was proposed **UAMS Health Physicians**,
    scoring 96.2 off one of its 135 location names; `Indianapolis Breast Center`
    was proposed an unrelated ENT practice, scoring 94.4 against a satellite
    literally named `East Indianapolis` (document frequency 1, so frequency
    filtering alone would not have caught it). Beyond the filters, a match whose
    winning string *is* a location name reaches the strong tier only with
    street-level address agreement — which is what distinguishes a genuine
    satellite (`Dartmouth Hitchcock - Bedford` → Dartmouth-Hitchcock, address
    100) from a coincidence.

14. **Phone is a third signal, reported beside `Verdict` and `Match_Tier`,
    never folded into them** (added 2026-09-29). Zeus holds phones in each
    population's `*InfoPhone` table (`Zeus entity phones.sql`, one query for all
    six, labelled by population and stored in the Zeus extract as `Z_Phones`);
    Definitive holds them on every HQ and service location (the `phone:` role).
    Numbers are normalised to 10 digits (`norm_phones()`); any number held by
    `PHONE_SHARED_MIN` = 5 or more Definitive ids — 3,079 of them, scheduling
    lines and switchboards — identifies nothing. `Phone_Match` is True when a
    non-shared number agrees, False when both sides hold non-shared numbers and
    none agree, and **blank otherwise, including when the only overlap is a
    shared number**. That last rule matters: treating a shared-number overlap
    as disagreement dropped confirmed-row agreement from 92.4% to 87.1%.
    Measured 2026-09-29 on the live population: 12,438 of 12,803 id-carrying
    entities have a usable phone; on confirmed rows the numbers agree 92.4%
    (8,979 of 9,715); 56 of 117 `Needs review` rows agree; 127 rows carry a
    number that belongs to exactly one *other* record (`Phone_Points_Elsewhere`).
    Kept out of the verdict and the tiers because decisions #4 and #11 define
    those on name and address, and a phone can be stale or a shared office
    line — `Phone_Lookup` proposed `Source Chiropractic` for `Clarksville Ob
    Gyn Associates`. Promoting or demoting on phone is a separate decision to
    take once the flagged rows have been reviewed; adding it changed no
    existing value (verified by replaying the same extract with phones
    stripped).

15. **City names are normalised for saint / sainte / fort / mount, but never
    for compass words** (2026-10-05, `CITY_ABBREV`). Abbreviating `West` to
    `w` was tried. It lifted `Des Moines` / `West Des Moines` from 80 to 91 and
    `Las Vegas` / `North Las Vegas` from 75 to 90, past the coverage tier's
    `city >= 90` same-place test, and promoted coverage rows to Strong on a
    neighbouring city. Any city mapping that shortens a prefix makes the rest
    of the string weigh more; measure it before adding one. Full figures are in
    `Matching_Logic.md`'s change log.

16. **One type per entity, the highest level wins, and the tree is strict**
    (2026-10-07, Grant). One parent per entity; alternatives are listed, never
    kept as extra parents. Each entity is typed by the highest of its Zeus
    roles — HealthSystem over Client over WorkLocation — because the migration
    team's hierarchy, which this one exists to validate, gives every entity one
    type. A parent is always a higher type, or a health system under a health
    system to any depth; a work location may sit directly under a health
    system. Consequences, measured on the first full run's inputs: 13,976
    entities carry several Zeus roles; 14,189 Zeus self-links (a hospital as
    its own client) and 11,573 same-type links (almost all a hospital, now a
    Client, linked as a work location to a staffing firm) no longer fit and
    are set aside and listed; Zeus client links between two entities typed
    HealthSystem become health system edges, and the 8 pairs that pointed at
    each other are broken (`break_loops()`), keeping Definitive's edge where
    there is one. The first build keyed nodes on (EntityId, role) instead;
    that was replaced the same day and should not come back unless the
    comparison target changes.

17. **Definitive ownership beats Zeus, except where it completely contradicts
    Zeus; and a shared Definitive record is identity, not ownership**
    (2026-10-07). Grant's rule: a known Definitive ownership or parent
    relationship takes priority, but where every Zeus parent sits in a
    different Definitive tree (different ultimate owner) the case is a
    `Contradiction` — held, the Zeus link kept for now, listed. The Definitive
    ids trusted for this are corroborated or probable supplied ids (no
    `Geo_Conflict`), recommended corrections and strong coverage proposals;
    Definitive-import-created entities become nodes only where Zeus links them
    to an in-scope entity, plus the parents those need. The first run let a
    Zeus entity on the child's *own* Definitive record (distance 0) override
    Zeus too, and replaced 1,936 contracting clients — SCP Health, HealthTrust
    Workforce Solutions, Sound Inpatient Physicians — with the hospital itself.
    So a same-record match may confirm or fill but never replace or contradict;
    only an owner (distance ≥ 1) may. Work location replacements fell 2,509 ->
    1,336, contradictions 408 -> 240. Full rules in `Hierarchy_Logic.md`.
    **Hospital owners take priority over staffing firms** (Grant, 2026-10-07),
    because staffing firms are not the owners of the work locations they
    staff. Two consequences: a hospital's Definitive owner replaces a Zeus
    client with no trusted Definitive id (1,628 work-location links on the
    single-type run, most often TEAMHealth, Trio, HealthTrust Workforce
    Solutions, SCP Health); and a work location whose Definitive owner is a
    hospital or health system (`TypeFirm`) while every Zeus client is a
    physician group, MSO or practice is **not** a contradiction but
    `Definitive replaces` (200 work locations). Contradictions stay held where
    Zeus names a different hospital or health system (often a merger Zeus has
    not caught up with: Mountain States Health Alliance vs Ballad Health),
    where both sides are physician groups, and at the client and health system
    levels — 110 work locations, 260 clients and 3 health systems on the
    single-type run. Also confirmed that day: a client with no health system
    is expected, and the booking tie-break applies only where Definitive gives
    no parent.

18. **Physician groups are in the Definitive hierarchy** (2026-10-07),
    reversing the 2026-09-30 note that they were out of scope "at this time".
    The Zeus hierarchy needs a parent chain for every id a Zeus entity can
    resolve to, and ~2,500 accuracy ids plus ~6,500 strong coverage proposals
    are physician groups. Same columns and same parent rule as the hospital
    file, unioned in `load_hierarchy()`; ids never overlap between the views,
    and a run stops if they do. GPOs and practice locations stay out of
    *this* union; locations are added afterwards (decision #19).

19. **Practice locations are leaves keyed by a derived key; GPOs are not in
    the ownership hierarchy** (2026-10-07, Grant). Locations come from the
    audits' `Definitive Practice Locations.sql`, unchanged, because its
    `GROUP BY` is already one row per location of a known parent. Definitive
    has no usable location id: `LocationId` and `AddressId` are unique per
    physician row (4,636,059 of each), and `PhysicianGroupLocationId` is null
    on 3,246,445 rows and spans more than one address for 12,213 of its
    233,498 ids. So `Location_Key` = `L<parent id>-` + 12 hex of a SHA-1 over
    the grouped name, address lines, city, state and zip, with NULL and ''
    hashed apart. It is stable while those fields are, and changes when a
    location is renamed or moves; do not treat it as a Definitive id. A
    location is never a parent. GPOs are excluded because a GPO is a
    purchasing affiliation, not an owner; making one a parent would change
    the top-level owner of ~7,800 records.

## Reporting template

`Zeus_DHC_ID_Accuracy_Audit.xlsx` is retained for its **shape**, which is the
agreed way to summarise a run. Eight sheets, each answering one question, with
`freeze_panes='A2'` and an autofilter on every tabular sheet:

| Sheet | Contents |
|---|---|
| `Summary` | Branded title plus a "Headline answer" written in prose, stating the denominator in the sentence itself |
| `Methodology` | One row per assumption — identifier resolution, why the denominator is what it is, normalisation, alias handling. This is where decision #1 lives in a form a reader can't skip |
| `Review_Queue` | Rows needing a human, with the matched Definitive name beside the Zeus name |
| `Address_Divergence` | Strong name, weak address — `Address_Divergent` |
| `Duplicate_IDs` | One DHC id claimed by several Zeus entities, grouped by id |
| `ID_Conflicts` | The two Zeus id columns disagreeing |
| `Scored_Detail` | Everything, full width |
| `Unreferenced_Hospitals` | Definitive records **no** Zeus row points at — reverse coverage |

`build_audit_workbook.py` now generates all of this from a scored run, with
three changes to the hand-built original:

- **`Geo_Conflict`** and **`Corrections_Recommended`** are new sheets. Both
  post-date the template; `Geo_Conflict` is the highest-value review population.
- **`Unreferenced_Definitive`** is generated as an anti-join of the reference
  frame against the scored ids, rather than hand-assembled, and now covers all
  entity types rather than hospitals only.
- The original stored the `ID_Conflicts` flag as the literal formula `=TRUE()`;
  the generator writes real values.

Latest deliverables: **`Zeus_DHC_ID_Accuracy_Audit_2026_08_12.xlsx`** from the
2026-08-12 six-population run, and
**`Zeus_DHC_ID_Coverage_Audit_2026_08_19.xlsx`** from the 2026-08-19 gap run.
The coverage workbook follows the same template applied to the complement
question — see "Producing a coverage run" for its twelve sheets. Each lives in
its run's folder (`dhc_match_v2_2026_08_12_1701` and
`dhc_gap_match_2026_08_19_1239`). Both are
ignored by git (`Zeus_DHC_ID_*.xlsx`); they carry Zeus client names and
addresses. The builders name deliverables with the **run date and time**
(`_YYYY_MM_DD_HHMM`) by default, not the month — Zeus is live, so two runs in one month are
different populations and a month-only name silently overwrites one with the
other.

Three identities should hold, and re-checking them after any change catches most
wiring mistakes:

- the five outcome rows sum to the supplied population (12,803);
- testable + unverifiable = supplied;
- the verdict counts sum to the testable population.

## How `name_core` behaves on practices

`name_core` is a *rescue* mechanism, not a filter. In `name_score` the core
comparison is `max()`-ed with the full-string comparison, so it can only ever
raise a score. An empty core fails safe — the `if zc and dc` guard skips the
core comparison entirely and the full string decides. The dangerous case is a
non-empty but generic core, because two identical single-token cores score
exactly 100, which trips the early return and then the `name >= 92` branch of
`verdict()` — a branch that requires no address agreement at all.

Measured over 134,405 distinct Definitive practice names:

| Core size | Count | Share |
|---|---|---|
| empty | 79 | 0.1% |
| 1 token | 9,901 | 7.4% |
| 2 tokens | 40,423 | 30.1% |
| 3+ tokens | 84,002 | 62.5% |

Two measurements, both supporting decision #7:

- **File-era population** (96,340 practice rows, mostly import-created): the core
  step changes the verdict on 1,755 (1.8%), median full-string score 87.7.
  Generic single-token core plus a bad address, tested directly: 26 rows of
  91,226 corroborated practices (0.03%), all with `State_Score == 100`.
- **Live population** (2,155 practice rows): 88 rescues (4.1%), median
  full-string 86.4. Hospitals: 162 of 5,504 (2.9%), median 85.7.

The higher live rate is expected — import-created records match trivially on the
full string and never needed rescuing, so removing them raises the share of rows
where the core step does real work. The signature is unchanged: near-misses just
under threshold, not manufactured matches. The rescues are legitimate suffix
variants (`Southpoint Anesthesia LLC` → `Southpoint Anesthesia Services LLC`;
`Farmbrook Radiology Associates` → `Farmbrook Radiology`).

## Known data quirks

- Zeus stores full state names ("California"); Definitive stores codes ("CA").
- **Both sides re-cut their column names on 2026-07-31.** All four Definitive
  exports moved to a common `DefinitiveId` key (`HospitalId`, `HOSPITAL_ID` and
  `HOSPITAL_NAME` are gone; physician-group names now live in
  `Definitive_NAME`). The Zeus query renamed `e.Name` from `EntityName` to
  `ClientEntityName`. Both breakages were silent until scoring, so `load_zeus()`
  now validates every configured column up front and names what is missing.
- **Zeus's two name fields are aliases of each other**, not a primary plus a
  fallback. `ClientEntityName` (`e.Name`) and `ClientInfoName` differ on ~11% of
  rows; both are scored and the best match wins, in the forward pass *and* in
  the reverse lookup's candidate selection.
- Some location rows carry a null `Name`. `groupby().first()` skips nulls per
  column, so a location-only identity row gets a name if any of its locations
  has one; where none does, `Name_Score` is 0 and the address decides. That is
  correct behaviour, not a bug.
- `addr_scores()` picks the winning line pair by `street_number + street_body`
  with missing components counted as zero, but the reported `Address_Score`
  weights them 0.30/0.22 via `ADDR_W`. The two objectives can disagree, so a
  pair that wins selection can score marginally lower than the runner-up: 12 of
  7,659 rows moved down slightly when locations widened the candidate pool.
  Aligning the selection metric with `ADDR_W` would fix it and is worth doing,
  but it perturbs every row's address choice, so it has not been changed
  unilaterally.
- **The `EntityDescription` exclusion removes 95.6% of the population, and that
  is the single most important fact about this audit.** The query filters out
  `EntityDescription` in `'Definitive Physician Group Import'`,
  `'Definitive Provider Import'`, `'Definitive Health System Import'` — records
  created *by* a Definitive import, where the DHC ID is essentially
  self-referential. Measured against the live database on 2026-07-31:

  | Filter | Rows |
  |---|---|
  | No extra filters | 207,598 |
  | `IsClient = 1` only | 207,463 (costs 135) |
  | `EntityDescription` exclusion only | 9,203 (**costs 198,395**) |
  | Both — the current query | 9,171 |

  So the old 207,450-row workbook was ~95.6% import-created records, and the
  file-era corroboration rates largely measured whether a Definitive import
  agreed with itself. The live run is a much smaller but far more meaningful
  denominator: IDs a human or process actually chose. `IsClient = 1` is almost
  free by comparison — it removes only 135 rows.
- **The query returns the default address only** (`cia.IsDefault = 1`). Decision
  #6's multi-line handling still applies across `ClientAddress1..3`, but
  alternate addresses for an entity are not considered.
- `Definitive_PhysicianGroupOverview.xlsx` names its key columns `HOSPITAL_ID` /
  `HOSPITAL_NAME`. These are the practice's own id and name, not a parent
  hospital reference — `HOSPITAL_PARENT_ID` is separate. `entity_type` is set
  explicitly in `sources.yaml` because `inspect` cannot infer it from that name.
- Zeus has two name fields, `EntityName` and `ClientInfoName`; they differ on
  10.9% of rows. Both are scored, best wins.
- `LEVS_DHC_VerifiedSourceId` is effectively dead: populated on 77 of 207,450
  rows. Where both ID columns are populated they *disagree* 66 times out of 73.
  17 of the 77 values are 10-digit NPI-shaped numbers — Definitive hospital IDs
  top out at 7 digits, so those cannot be valid. Recommend fixing or retiring
  the column.
- **Shared DHC ids grew a lot with six populations: 4,834 scored rows carry an
  id claimed by another entity.** A client entity and a work-location entity are
  *different* `EntityId`s that legitimately point at the same Definitive record,
  and pooling does not merge them because pooling is keyed on `EntityId`. Mostly
  not an error — do not treat as a defect without checking. Merging by DHC id
  instead would be a different audit (is the id right?) from the one this tool
  performs (does each Zeus record point at the right thing?).
- Definitive uses **one ID namespace across entity types**. Zeus IDs of ≤4
  digits match the hospital extract 99.7%+ of the time; 6–7 digit IDs match only
  1–2.7%. 200,417 Zeus rows (96.6%) carry 6–7 digit IDs, which are almost
  certainly physician groups and practices.

## Open work

**1. ~~Widen the reference set.~~ Largely moot now.** Both exports are in and
configured. On the live population 83.5% of rows are already testable (7,659 of
9,171), so the remaining 1,512 unverifiable rows are a small target — check
`Results Output/dhc_match_v2_2026_07_31_1133/audit_2026_08_live_unverifiable.csv` before buying another export. Licensing
note: confirm redistribution terms with whoever owns the Definitive licence
before exporting a full universe.

**2. ~~Recalibrate for physician groups.~~ Done, and the prediction was wrong.**
See decision #7 and "How `name_core` behaves on practices". The one piece of the
original recommendation still worth considering is **separate passes** with their
own thresholds for facilities vs practices; the stacked run is currently fine
(94.7% vs 97.5% is a believable gap, not a collapse), so this is optional rather
than required.

**3. Hand-label a validation sample.** *Deferred by Grant on 2026-07-31 — other
project work comes first. Unblocked and ready whenever it is picked up.*
`DHC_Matched_Name` is retained in the scored output, so a reviewer can see
what an ID actually points at. The live queue is 70 `Needs review` + 17
`Likely wrong ID` + 25 `Geo_Conflict` + 16 recommended corrections — roughly 130
rows, versus the 2,860 the file-era population implied. Start with the 25
`Geo_Conflict`. Only 10 rows have been labelled so far (8 correct, 1 clearly
wrong — Emory University School of Medicine pointed at Grady Health System — 1
debatable successor-facility case), and those came from the file era.

**4. Decide where this lives long-term.** Currently a local script that reads
Zeus directly — the step to a Databricks job writing a scored Delta table for
Power BI, versioned in the Azure DevOps `BI` project, is now much shorter.

**5. ~~Put this folder under version control.~~ Done 2026-07-31, with two
follow-ups.** The repo exists and source is tracked; see "Version control" for
what is and is not in it. What remains:

- **Purge the data from history.** `f7f0e4e` still holds ~100 MB of licensed
  Definitive exports and Zeus client records on `origin/main`. It is the root
  commit, so `~1` does not resolve — use `git checkout --orphan` or
  `git-filter-repo`, then `push --force-with-lease`. Cheap while the repo is one
  commit, one author and private; it gets harder the longer it waits.
- **Decide where the `_zeus_extract.csv` snapshots live.** Version control does
  not solve reproducibility here, because the snapshots are client data and stay
  ignored. Until they have a governed home, a circulated figure is only
  reproducible for as long as someone's working directory survives.

Note this does not retroactively help the file era: the Zeus workbook was
deleted before the repo existed, so those results remain unreproducible.

**6. Optional: MCP access to Zeus for interactive querying.** There is a
`sqlserver` MCP entry in `~/.claude.json`, but it is under
`projects["C:/Users/glovern"]` — *local* scope for that one directory, not user
scope (which is the file's top level) — so it does not load in this project.
Re-scoping it would need a `.mcp.json` here or a move to the top level, plus a
session restart. **It would not satisfy the ReadOnly requirement**:
`@bilims/mcp-sqlserver` accepts nine env vars and none is `ApplicationIntent`,
with no connection-string passthrough. An MCP server that takes a full
connection string, or a small helper on `load_zeus()`, would be needed instead.
Separately, that entry stores the password in plaintext; `.mcp.json` supports
`${VAR}` expansion and would fix it.

**7. Coverage follow-ups, opened 2026-08-19.** The tool exists and has run; what
it raises:

- **Hand-label a coverage sample, before anything is loaded.** Same argument as
  open work #3, but this queue has no prior labelling at all and proposes
  *changes* rather than confirming existing data, so the cost of being wrong is
  higher. Sample the strong tier — 9,702 rows is too many to eyeball, but ~100
  labelled rows would put a measured precision on it. Start with the 1,194 that
  matched via a service location and the 186 carrying a status marker.
- **Decide the grain for chains.** 2,738 strong proposals share an id with
  another unlinked entity. Definitive models a chain as one parent id plus
  service locations; Zeus models it as many work locations. Pointing 32 branches
  at one id is defensible and is what the data supports, but it should be a
  decision rather than a side effect.
- **NPI is the untouched lever.** `NPI_NUMBER` is in the physician group export,
  and `VerifiedSourceNameId = 4` is NPI on the Zeus side. Where both are
  populated that is a deterministic join, not a fuzzy one — it would both
  resolve `Ambiguous` rows and validate the strong tier independently. Zeus-side
  population is thin (71 entities in the missing-id population carry any
  non-Definitive source), so measure before building.
- **~~A deliverable workbook.~~ Done 2026-08-19** �
  `build_coverage_workbook.py`, twelve sheets, latest output
  `Zeus_DHC_ID_Coverage_Audit_2026_08_19.xlsx`.

**8. Hierarchy follow-ups, opened 2026-10-07.** `zeus_hierarchy.py` exists
and has had its first full run (`zeus_hierarchy_2026_10_07_0858`). **It is a
read-only comparison tool**: the migration team derives the real hierarchy,
and this one is the baseline Grant validates theirs against. Nothing is ever
written back to Zeus or any other source; an Excel deliverable is the output.
What it raises:

- **Compare with the migration team's hierarchy** once their output is
  available. The comparison itself is not built yet.
- **Hand-label ~50 `Contradictions` and ~50 `Zeus_Links_Replaced` rows**, as
  planned, to put a measured precision on the Definitive pass. No reviewer is
  assigned yet (2026-10-07); contradictions keep their Zeus link meanwhile.
- **Health system resolution.** Large Definitive systems (UNC Health,
  Piedmont, Baptist Health - AR) have no Zeus health system node carrying
  their id, so their clients climb past them; 91 have an unlinked
  import-created Zeus record that decision #17's universe rule leaves out.

## Residual weakness

Parent-versus-child entities, and same-named entities in different places. A
Zeus record for a parent company pointed at a subsidiary facility ID (e.g.
"Universal Health Services", King of Prussia PA, mapped to Peachford Hospital,
Atlanta GA) scores low on name and lands in the review queue, but the tool cannot
determine which of the two was intended. Closed and merged facilities are
likewise surfaced for a human rather than resolved automatically. This is a
deliberate limit, not a bug to fix.

The service-location data shrank this materially — `Address_Divergent` fell from
659 to 466 and `Geo_Conflict` from 25 to 17 — because most apparent address
disagreements were Zeus naming a satellite while Definitive named the HQ. What
survives is the harder residue:

- **466 corroborated rows still have `Address_Score < 60`**, now meaning Zeus's
  address matches neither the HQ nor any of the entity's known locations.
- **17 `Geo_Conflict` rows**: a strong name match where no known location of the
  entity is in Zeus's state. Some are legitimate, some are the wrong ID, and the
  tool cannot tell them apart — which is why they are flagged, not reclassified.

The honest reading: name agreement establishes that Zeus and Definitive are
talking about the same *name*, not necessarily the same *entity*. Where an
address agrees — HQ or satellite — that distinction is moot. For the remainder no
amount of string tuning resolves it; only a human, or a third identifier such as
NPI. `NPI_NUMBER` is present in the physician group export and is the obvious
next lever if this needs closing rather than measuring.
