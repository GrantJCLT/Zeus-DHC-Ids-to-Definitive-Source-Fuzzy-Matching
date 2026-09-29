# Usage

How to run the Zeus ↔ Definitive Healthcare identifier audit: what to run, where
to run it, and what you should see. For installing the prerequisites on a new
machine, see [Environment.md](Environment.md). For why the tools behave as they
do, see [CLAUDE.md](CLAUDE.md).

## What you can produce

| Question | Tool | Deliverable | Time |
|---|---|---|---|
| **Accuracy**: of the Zeus entities that carry a DHC ID, how many point at the right Definitive record? | `dhc_match_v2.py run` | `Zeus_DHC_ID_Accuracy_Audit_<date>_<time>.xlsx` | 2–3 min |
| **Coverage**: which Zeus entities carry no DHC ID, and which Definitive record should each one point at? | `dhc_gap_match.py` | `Zeus_DHC_ID_Coverage_Audit_<date>_<time>.xlsx` | 20–30 min |

Each question takes two steps: a **run**, which reads Zeus and Definitive and
writes CSV results, and a **build**, which turns those CSVs into the branded
workbook. A full refresh is the accuracy run, then the coverage run, because the
coverage run can cross-check against the accuracy results.

## Where to run

**From the project root, in PowerShell** (the VS Code integrated terminal is fine):

```powershell
cd "C:\Code\Zeus DHC Ids to Definitive Source Fuzzy Matching"
```

This has to be the working directory. `sources.yaml` names the `.sql` query
files by relative path, and results go to `Results Output\` relative to where you
run.

Every command below starts with `py`. Check that `py` resolves to a Python
that has the project's packages installed:

```powershell
py -c "import rapidfuzz, pyodbc, openpyxl, yaml, databricks.sql; print('ok')"
```

If that fails with `ModuleNotFoundError`, VS Code has probably activated the
incomplete project `.venv`. See "Which Python" in [Environment.md](Environment.md).

## Before every run

1. `$env:ZEUS_SQL_PASSWORD` is set: `[bool]$env:ZEUS_SQL_PASSWORD` prints `True`.
2. The Databricks login is valid: `databricks auth profiles` shows profile `jcl`
   as `Valid YES`. If it doesn't, run `databricks auth login --profile jcl`
   and complete the browser sign-in.
3. You can reach the Zeus failover replica (corporate network or VPN).

---

## 1. Accuracy audit

### Step 1: run

```powershell
py dhc_match_v2.py run --config sources.yaml
```

Optional flags:

| Flag | Effect |
|---|---|
| `--label <x>` | Appends `_x` to the run folder name, e.g. `dhc_match_v2_2026_09_29_1422_x` |
| `--zeus <path>_zeus_extract.csv` | Replays an archived Zeus extract instead of querying Zeus live |
| `--definitive-from "Results Output\<run folder>"` | Replays that run's Definitive snapshots instead of querying Databricks |
| `--no-reverse` | Skips the reverse lookup that proposes corrections (faster, but no `Corrections_Recommended`) |

Use both `--zeus` and `--definitive-from` to rerun a past result fully offline.

**Expected console output**, in order. The comments call out what to check.

```
Run folder  : Results Output/dhc_match_v2_2026_09_29_1422
Databricks  : https://adb-8032826808193104.4.azuredatabricks.net (warehouse 5941bfd954019dc3)
  Definitive Hospital Overview.sql: 9,887 rows -> hospitaloverview
  ... one line per Definitive query (4 in total)
Zeus source : Zeus on prd-jcl-zeus-failover....database.windows.net
  intent    : ReadOnly
  connected to a READ_ONLY database        <-- CHECK 1: must say READ_ONLY
  Client          x,xxx rows ...
  WorkLocation    x,xxx rows ...           <-- CHECK 3: six populations, none zero
  ...
  extract snapshot -> ..._zeus_extract.csv
Zeus rows   : 19,8xx population rows -> 12,8xx distinct entities
  NOTE: +N vs the expected 12,803 ...      <-- CHECK 2: absent, or small and explainable
...
ID testable  : 11,0xx  (86.x% of Zeus)

--- Verdicts (testable population) ---
  ID corroborated                          10,7xx   96.x%
  ...
  CORROBORATED + PROBABLE                  ...      98.x%

--- By Definitive entity type ---
--- By Zeus population (overlapping; entities counted in each) ---
Reverse lookup over N rows...
Recommended corrections: NN

Wrote Results Output/<run>/<run>_scored.csv  (11,0xx rows)
Wrote Results Output/<run>/<run>_unverifiable.csv  (1,7xx rows)
```

The figures are indicative, taken from the 2026-08-12 and 2026-09-29 runs. Zeus
and Definitive are both live, so expect some drift. Stop and investigate if:

- the connection line says anything other than `READ_ONLY`. The ReadOnly
  intent isn't being honoured, and the run must not continue against a
  read-write database;
- a `NOTE: ±N vs the expected 12,803` line shows a large jump. The Zeus
  population has moved; find out why before quoting any rate, then update
  `ZEUS_BASELINE_ENTITIES` in `dhc_match_v2.py`;
- a population reports zero rows, which usually means a Zeus column or query
  was renamed.

**Files written**, all in `Results Output\dhc_match_v2_<YYYY_MM_DD_HHMM>\`, each
prefixed with the folder name:

| File | Contents |
|---|---|
| `<run>_scored.csv` | One row per testable Zeus entity: verdict, scores, matched Definitive name, flags |
| `<run>_unverifiable.csv` | Entities whose ID is in no Definitive source |
| `<run>_zeus_extract.csv` | The exact Zeus input that was scored, for replay |
| `<run>_dhc_<table>.parquet` | Snapshot of each Definitive source as queried |
| `<run>_dhc_<table>.sql` | The exact SQL that produced each snapshot |

### Step 2: build the workbook

Pass the scored file path from step 1's `Run folder` line:

```powershell
py build_audit_workbook.py --scored "Results Output\<run>\<run>_scored.csv"
```

Optional: `--baseline "<earlier run>_scored.csv"` adds a section comparing this
run with an earlier one, and `--out <name>.xlsx` renames the output.

This writes `Zeus_DHC_ID_Accuracy_Audit_<run date>_<time>.xlsx` into the same run
folder and prints each sheet with its row count:

```
Wrote Results Output/<run>/Zeus_DHC_ID_Accuracy_Audit_2026_09_29_1422.xlsx
  Summary                         ...
  Methodology                     ...
  Review_Queue                    ...
  Geo_Conflict                    ...
  Address_Divergence              ...
  Corrections_Recommended         ...
  Duplicate_IDs                   ...
  ID_Conflicts                    ...
  Scored_Detail                   ...
  Unreferenced_Definitive         ...
```

The builder reads the run's own Definitive snapshots, and it **stops** if they
are missing rather than query live data. Runs from before 2026-09-29 have no
snapshots; build those with a config that points at the old xlsx exports.

**CHECK 4:** on the `Summary` sheet, testable + unverifiable should equal
supplied, and the verdict counts should sum to testable.

---

## 2. Coverage audit (the missing IDs)

### Step 1: run

```powershell
py dhc_gap_match.py --config sources.yaml `
    --claimed "Results Output\<accuracy run>\<accuracy run>_scored.csv"
```

`--claimed` is optional but recommended. It flags every proposal whose ID
another Zeus entity already carries (`Suggested_Id_Already_In_Zeus`). Point it
at the accuracy run you just did.

Optional flags: `--label`, `--zeus`, `--definitive-from` (as for the accuracy
run), and `--limit N` to score only the first N entities as a quick smoke test.
`py dhc_gap_match.py --config sources.yaml --limit 200` finishes in a few minutes
and exercises every connection.

**Expected console output.** The Definitive and Zeus sections match the
accuracy run, except that the expected baseline is **48,739** entities. The
additional sections are:

```
Building the search space:
  location names usable as identity: ...
    dropped N shared by >= 5 parent ids, ...
  + N parenthetical former names
  ...
  blocked into NN states; largest pool ...

Stage A - retrieving candidates for 48,7xx entities:
    CA  pool  xx,xxx  targets  x,xxx ...    <-- one line per state; the slow part
Stage B - exact scoring:
    scored  x,xxx of 48,7xx ...

--- Coverage: 48,7xx Zeus entities carrying no Definitive id ---
  tier                                entities    share
  Strong match                           9,6xx    19.x%
  Probable match - review                ...
  Ambiguous - rival candidates           8,4xx    17.x%
  Weak match - review                    ...
  No credible match in Definitive       16,5xx    34.x%
  ...
  proposable (strong tier)               ...
  needs a human                          ...

--- By Zeus population (overlapping; entities counted in each) ---
--- Strong tier: which Definitive string matched ---
  Name                   7,8xx             <-- CHECK: mostly Name, not Location
  Alias                  ...
  Location               ...

Wrote Results Output/<run>/<run>_gap_candidates.csv  (32,xxx rows)
Wrote Results Output/<run>/<run>_gap_nomatch.csv  (16,5xx rows)

Total elapsed: 19.5 min
```

Before circulating, check:

1. `connected to a READ_ONLY database`;
2. no large `NOTE: ±N vs the expected 48,739`. If the population moved, find
   out why and then update `GAP_BASELINE_ENTITIES` in `dhc_gap_match.py`;
3. tier counts sum to the population, and `gap_candidates` + `gap_nomatch` rows
   sum to it too;
4. the strong tier's `Matched_Via` is mostly `Name`. A jump in `Location`
   means the location-name filters have stopped working (CLAUDE.md decision #13).

**Files written**, in `Results Output\dhc_gap_match_<YYYY_MM_DD_HHMM>\`:
`<run>_gap_candidates.csv` (every entity with a credible proposal, best plus two
alternates), `<run>_gap_nomatch.csv`, `<run>_zeus_extract.csv`, and the
`<run>_dhc_<table>.parquet` / `.sql` snapshots.

### Step 2: build the workbook

```powershell
py build_coverage_workbook.py `
    --candidates "Results Output\<gap run>\<gap run>_gap_candidates.csv" `
    --accuracy "Results Output\<accuracy run>\<accuracy run>_scored.csv"
```

`--accuracy` is optional. It adds a whole-estate section to the Summary: linked
versus unlinked entities, and what loading the strong tier would do to coverage.

This writes `Zeus_DHC_ID_Coverage_Audit_<run date>_<time>.xlsx` into the gap run's
folder, lists its twelve sheets, then re-checks three identities:

```
Wrote Results Output/<run>/Zeus_DHC_ID_Coverage_Audit_2026_09_29_1450.xlsx
  Summary / Methodology / Ready_To_Load / Review_Probable / Ambiguous_Rivals /
  Review_Weak / Parent_Id_Proposals / Shared_Id_Proposals /
  Id_Already_Linked_In_Zeus / Status_Flagged / No_Credible_Match / Candidates_Detail

Identity checks:
  tier counts sum to population    48,7xx == 48,7xx  OK
  review sheets + no-match = pop   48,7xx == 48,7xx  OK
  extract entities = population    48,7xx == 48,7xx  OK
```

Any `FAIL` means something is wired wrong. Don't circulate the workbook.

How to read it: `Ready_To_Load` is the actionable sheet. Before loading anything
from it, understand `Parent_Id_Proposals`, `Shared_Id_Proposals`,
`Id_Already_Linked_In_Zeus` and `Status_Flagged`. `No_Credible_Match` is the
input to any "buy more Definitive data" discussion.

---

## Other tasks

### A new Definitive export or view arrives

```powershell
py dhc_match_v2.py inspect "<NewExport>.xlsx"
```

This prints the detected column roles and a starter config block. Paste it into
`sources.yaml`: under `definitive:` if the export has one row per ID, or
under `locations:` if it has many rows per ID. `sources.yaml` is the only file
that should need editing. For a Databricks view, add a `.sql` file alongside the
existing `Definitive *.sql` files and a block with `query_file:` and
`snapshot:`.

### A new Zeus population is added

Write its two queries (`Zeus <X> to Definitive ID data quality evaluation.sql`
and `Zeus <X> missing Definitive ID.sql`), then add a block under
`zeus.sources` in `sources.yaml` mapping its column names to roles. No code
change is needed.

### Reproduce a past figure

```powershell
$run = "Results Output\dhc_match_v2_2026_09_29_1422"
py dhc_match_v2.py run --config sources.yaml `
    --zeus "$run\dhc_match_v2_2026_09_29_1422_zeus_extract.csv" `
    --definitive-from $run --label replay
```

Verified: replaying an extract reproduces the run exactly.

## After a run: what to keep

The whole `Results Output\` folder is git-ignored. It holds Zeus client names
and addresses and licensed Definitive data. **A run folder is the unit to
archive.** Copy the whole folder to a governed store (SharePoint or blob
storage) alongside any workbook you circulate. Without the `_zeus_extract.csv`
and the `_dhc_*.parquet` snapshots, a figure can't be reproduced later, because
both Zeus and the Definitive views change in place.

A coverage proposal list is only valid against the Definitive snapshot it came
from. Rerun it before loading an old one.

After a new run, update the hand-copied figures in
`Zeus_DHC_ID_Audit_Business_Overview.md` and the Results sections of
`CLAUDE.md`.

## Common failures

| Message | Cause | Fix |
|---|---|---|
| `Environment variable ZEUS_SQL_PASSWORD is not set` | Variable missing, or the terminal was opened before it was set | Set it at User scope (Environment.md), then open a new terminal |
| `ModuleNotFoundError: No module named 'rapidfuzz'` (or `pyodbc`, `yaml`, …) | `py` points at a Python without the packages, usually the `.venv` | See "Which Python" in Environment.md |
| `Data source name not found and no default driver specified` | ODBC Driver 18 not installed | Install it, or change `driver:` in `sources.yaml` to `ODBC Driver 17 for SQL Server` |
| Login timeout / TCP error on port 1433 | Not on the corporate network, or the firewall doesn't allow your IP | Connect the VPN, or ask the Zeus DBA to allow access |
| Databricks auth or token error | CLI OAuth login expired | `databricks auth login --profile jcl` |
| `... is missing [column]` naming a Zeus or Definitive column | A query or view renamed a column | Fix the `.sql` alias or the role mapping in `sources.yaml` |
| Builder stops: snapshot missing | The run folder has no `_dhc_*.parquet` (pre-2026-09-29, or files moved) | Build with a config that points at the xlsx exports, or rerun |
| `PermissionError` writing the `.xlsx` | The workbook is open in Excel | Close it and rebuild |
