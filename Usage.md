# Usage

How to run the Zeus ↔ Definitive Healthcare identifier audit: what to run, where
to run it, and what you should see. For installing the prerequisites on a new
machine, see [Environment.md](Environment.md). For why the tools behave as they
do, see [CLAUDE.md](CLAUDE.md). For exactly how names and addresses are
normalised and scored, see [Matching_Logic.md](Matching_Logic.md).

## What you can produce

| Question | Tool | Deliverable | Time |
|---|---|---|---|
| **Accuracy**: of the Zeus entities that carry a DHC ID, how many point at the right Definitive record? | `dhc_match_v2.py run` | `Zeus_DHC_ID_Accuracy_Audit_<date>_<time>.xlsx` | 2–3 min |
| **Coverage**: which Zeus entities carry no DHC ID, and which Definitive record should each one point at? | `dhc_gap_match.py` | `Zeus_DHC_ID_Coverage_Audit_<date>_<time>.xlsx` | 20–30 min |
| **Hierarchy**: how Definitive's hospitals and health systems nest under their owners, for comparison with the migration team's destination data | `dhc_hierarchy.py` | `Definitive_Hospital_Hierarchy_<date>_<time>.xlsx` plus `<run>_hierarchy.csv` | under 1 min |
| **Optional extra:** the same answers limited to one Zeus population, e.g. Work Locations for the third-party data-cleaning group. **An extra workbook alongside the full one, never instead of it** | the same runs, plus a build with `--population WorkLocation` | `Zeus_DHC_ID_Accuracy_Audit_WorkLocation_<date>_<time>.xlsx` and `..._Coverage_Audit_WorkLocation_...` | seconds, once the runs exist |

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

## Run everything at once

```powershell
py run_all.py
```

That one command is the full refresh: **both audits, over all six Zeus
populations, and both full workbooks**. About 30 minutes. It runs:

1. the accuracy run;
2. the coverage run, cross-checked against step 1 (`--claimed`) and scored
   against **step 1's Definitive snapshots** (`--definitive-from`), so both
   audits see exactly the same Definitive data even though the views refresh in
   place;
3. the full accuracy workbook and the full coverage workbook.

### Add the Work Location workbooks as well

```powershell
py run_all.py --population WorkLocation
```

This does **everything the plain command does, and then builds two more
workbooks** limited to Work Location entities, for the third-party
data-cleaning group.

> **`--population` adds workbooks. It never narrows the run.** Both audits
> still read and score every entity in all six populations, and the two full
> workbooks are still built. The Work Location workbooks are an extra view of
> the same results, filtered after scoring. Nothing is left out of anything.

What each form writes:

| Command | Workbooks written |
|---|---|
| `py run_all.py` | 2: `Zeus_DHC_ID_Accuracy_Audit_<run>.xlsx`, `Zeus_DHC_ID_Coverage_Audit_<run>.xlsx`, covering all populations |
| `py run_all.py --population WorkLocation` | 4: the same 2, **plus** `Zeus_DHC_ID_Accuracy_Audit_WorkLocation_<run>.xlsx` and `Zeus_DHC_ID_Coverage_Audit_WorkLocation_<run>.xlsx` |
| `py run_all.py --population WorkLocation --population Client` | 6: the same 2, plus 2 for Work Location, plus 2 for Client |
| `py run_all.py --population all` | 14: the same 2, plus 2 for each of the six labels under `zeus.sources` in the config |

The run time is the same either way; each extra pair of workbooks takes under a
minute. For the labels you can use and what each contains, see
[`--population` labels](#--population-labels) below.

### What you see

Each step is the ordinary script described below, run with the same Python as
`run_all.py`, so the console shows its normal output. The first step that
fails stops everything. The end is a summary:

```
Summary  (2x.x min)
    1.6 min  1. Accuracy run
   2x.x min  2. Coverage run
   ...
Checks:
  OK   1. Accuracy run: connected to a READ_ONLY database
  OK   2. Coverage run: connected to a READ_ONLY database
  NOTE 2. Coverage run: NOTE: +118 vs the expected 48,739 entities ...
  OK   4. Coverage workbook: tier counts sum to population    48,857 == 48,857  OK
  ...
Workbooks:
  Results Output\dhc_match_v2_...\Zeus_DHC_ID_Accuracy_Audit_....xlsx
  ...
All steps finished and every check passed.
```

A `NOTE` line is repeated for you to judge (see check 2 below); anything marked
`FAIL` or `WARN` is listed again under "Needs attention before circulating", and
the command exits with code 1.

| Option | Effect |
|---|---|
| `--population <label>` | **Adds** workbooks limited to that population, beside the full ones; repeatable. `all` means every `zeus.sources` label in the config. Never changes what is run or scored. See [`--population` labels](#--population-labels) |
| `--label <x>` | Suffix for both run folders |
| `--accuracy-only` | Just the accuracy run and its workbook(s), about 3 minutes |
| `--limit N` | Coverage scores only the first N entities: a 4-minute end-to-end test. The "extract entities = population" check shows `n/a` then, as expected |
| `--no-reverse` | Accuracy run skips the reverse lookup |
| `--config <file>` | Default `sources.yaml` |

`py run_all.py --limit 200 --label smoke` is the quick way to confirm every
connection and step works before a full run. Delete its folders afterwards.

### `--population` labels

The label is a population name from `zeus.sources` in `sources.yaml`. There are
six. Case and spaces are ignored (`workLocation` and `"work location"` both
work); an unknown label stops the build and lists the valid ones.

| Label | Which Zeus entities | Carry a DHC ID (testable) | Of those, in this population only | Carry no ID (strong match) | Of those, in this population only |
|---|---|---|---|---|---|
| `Client` | `IsClient = 1`, names and addresses from `ClientInfo` | 9,171 (7,665) | 2,389 | 24,139 (5,631) | 18,684 |
| `WorkLocation` | `IsWorkLocation = 1`, from `WorkLocationInfo` | 10,047 (9,228) | 3,405 | 29,599 (5,395) | 24,243 |
| `HealthSystem` | `IsHealthSystem = 1`, from `HealthSystemInfo` | 599 (578) | 154 | 531 (117) | 407 |
| `GPO` | `IsGPO = 1`, from `GPOInfo` | 1 (1) | 0 | 13 (5) | 4 |
| `Agency` | `IsAgency = 1`, from `AgencyInfo` | 1 (1) | 0 | 52 (0) | 45 |
| `VMS` | `IsVMS = 1`, from `VMSInfo` | 1 (0) | 0 | 27 (1) | 12 |

Figures from the 2026-09-29 live runs; Zeus is live, so expect drift. Reading
the table:

- **Populations overlap.** An entity flagged both `IsClient` and
  `IsWorkLocation` is one entity, scored once, and it appears in **both** the
  `Client` and the `WorkLocation` workbooks. About 6,000 of the ID-carrying
  entities are in both. So the rows add up to more than the real totals, which
  are 12,803 with an ID and 48,857 without.
- **"In this population only"** counts entities with no other flag. The rest
  are shared. `Matched_Zeus_Source` on each row says whether its result rests
  on this population's name or on another one's.
- **`GPO`, `Agency` and `VMS` are tiny.** Their workbooks build, but they're
  nearly empty. `VMS` has no testable ID-carrying entity, and its accuracy
  Summary says so rather than giving a rate.
- **`--population` is repeatable** on `run_all.py`: each label gives its own
  pair of workbooks. `--population all` builds a pair for every label,
  including the three near-empty ones above. The single-workbook builders
  below take one label per run, and do not accept `all`.
- **Which to build.** `Client` and `HealthSystem` are worth building
  alongside `WorkLocation` for any team working those records. Build `GPO`,
  `Agency` and `VMS` only when someone asks for them.

The sections below run the same steps one at a time.

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
Run folder  : Results Output\dhc_match_v2_2026_09_29_1647
Zeus source : Zeus on prd-jcl-zeus-failover....database.windows.net
  intent    : ReadOnly
  connected to a READ_ONLY database        <-- CHECK 1: must say READ_ONLY
  Client           9,1xx rows ...
  WorkLocation    10,0xx rows ...          <-- CHECK 3: six populations, none zero
  ...
  phones         356,xxx rows  (Zeus entity phones.sql)
  extract snapshot -> ..._zeus_extract.csv
Zeus rows   : 19,8xx population rows -> 12,8xx distinct entities
  NOTE: +N vs the expected 12,803 ...      <-- CHECK 2: absent, or small and explainable

Definitive tables:
Databricks  : https://adb-8032826808193104.4.azuredatabricks.net (warehouse 5941bfd954019dc3)
  Definitive Hospital Overview.sql: 9,887 rows -> ..._dhc_hospitaloverview.parquet
  ... one line per Definitive query (4 in total)
...
Phones      : 12,4xx of 12,8xx entities carry a usable Zeus phone; ... 3,0xx shared by 5+ ids ignored
ID testable  : 11,0xx  (86.x% of Zeus)

--- Verdicts (testable population) ---
  ID corroborated                          10,7xx   96.x%
  ...
  CORROBORATED + PROBABLE                  ...      98.x%

--- Phone (independent of Verdict) ---
  phone on both sides                      10,0xx
    numbers agree                           9,2xx   91.x%
    number belongs to another record          1xx  <-- review (Phone_Points_Elsewhere sheet)
  Needs review      phone agrees   56 / points elsewhere  7 of 117

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
| `<run>_scored.csv` | One row per testable Zeus entity: verdict, scores, the matched name and address pair, the Definitive HQ, phone check, flags |
| `<run>_unverifiable.csv` | Entities whose ID is in no Definitive source. `Phone_Lookup_DHC_Id` / `_Name` is the one Definitive record holding the entity's phone, where there is exactly one: the only lead these rows have |
| `<run>_zeus_extract.csv` | The exact Zeus input that was scored, including each entity's phones (`Z_Phones`), for replay |
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
  Phone_Points_Elsewhere          ...
  Duplicate_IDs                   ...
  ID_Conflicts                    ...
  Scored_Detail                   ...
  Unreferenced_Definitive         ...
```

`Phone_Points_Elsewhere` lists supplied IDs whose phone number belongs to
exactly one *other* Definitive record. It's the phone check's review queue; the
verdict itself is unchanged.

The builder reads the run's own Definitive snapshots, and it **stops** if they
are missing rather than query live data. Runs from before 2026-09-29 have no
snapshots; build those with a config that points at the old xlsx exports.

**CHECK 4:** on the `Summary` sheet, testable + unverifiable should equal
supplied, and the verdict counts should sum to testable.

### An extra workbook for one population (`--population`)

After building the full workbook above, you can **also** build one limited to a
single Zeus population, for example the Work Location subset the third-party
data-cleaning group is working. Run the builder a second time with
`--population`:

```powershell
py build_audit_workbook.py --scored "Results Output\<run>\<run>_scored.csv" `
    --population WorkLocation
```

- **This adds a workbook; it replaces and narrows nothing.** The run already
  scored every population, and the full workbook stays as it is. Build it first
  without `--population`, then again with it.
- The label is one of the six in [`--population` labels](#--population-labels).
  An unknown label stops with the list of valid ones.
- It writes `Zeus_DHC_ID_Accuracy_Audit_WorkLocation_<date>_<time>.xlsx` beside
  the full workbook, never over it.
- Every sheet, headline and total covers only that population, and the Summary and
  Methodology say so.
- **It filters the results, not the matching.** Each entity was still matched on
  every name and address it holds in any population.
- **"Work Location" means any entity flagged as a Work Location, including
  those that are also Clients** (about 6,000 of the 10,000 that carry an ID). To
  see whether a result rests on the Work Location name or the Client one, read
  `Matched_Zeus_Source`.
- Don't get a subset by editing the Zeus queries instead. Filtering there removes
  address evidence and drops entities from both audits; see CLAUDE.md,
  "One population only".

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

Phones: 42,0xx of 48,8xx entities carry a usable Zeus phone; 3,0xx Definitive numbers shared by 5+ ids ignored

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
--- Phone check on the pick (independent of the tier) ---
  tier                                confirms  no match  favours alt  no phone
  Strong match - ready to load           6,7xx     1,9xx          1xx       9xx
  ...                                                           <-- review "favours alt" rows
  No credible match, but the phone belongs to exactly one Definitive record: 2,4xx
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
folder, lists its fourteen sheets, then re-checks three identities:

```
Wrote Results Output/<run>/Zeus_DHC_ID_Coverage_Audit_2026_09_29_1647.xlsx
  Summary / Methodology / Ready_To_Load / Review_Probable / Ambiguous_Rivals /
  Review_Weak / Parent_Id_Proposals / Shared_Id_Proposals /
  Id_Already_Linked_In_Zeus / Status_Flagged / Phone_Favours_Alt /
  Phone_Only_Match / No_Credible_Match / Candidates_Detail

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

The two phone sheets are review queues. The tiers themselves don't use phone:

- `Phone_Favours_Alt`: the entity's phone matches one of the two runners-up,
  not the pick. The rows in `Ready_To_Load` are the ones to check first.
- `Phone_Only_Match`: no name match was credible, but the entity's phone
  belongs to exactly one Definitive record (`Phone_Lookup_DHC_Id`). These are
  leads for review, not proposals to load. A phone can be stale or a shared
  office line.

To **also** build a Work Location coverage workbook, run the builder a second
time with `--population WorkLocation`, exactly as for the accuracy workbook. This
adds a workbook beside the full one and changes nothing else (labels:
[`--population` labels](#--population-labels)):

```powershell
py build_coverage_workbook.py `
    --candidates "Results Output\<gap run>\<gap run>_gap_candidates.csv" `
    --accuracy "Results Output\<accuracy run>\<accuracy run>_scored.csv" `
    --population WorkLocation
```

The identity checks then run on the Work Location population. The estate
section covers only Work Location entities, linked and unlinked.

---

## Reading the review sheets

Every review sheet in both workbooks puts the two sides next to each other,
left to right:

| Column group | What it is |
|---|---|
| `Zeus_*` | What Zeus holds: every name, address and phone pooled across the entity's populations |
| `DHC_*` (accuracy) / `Suggested_*` (coverage) | The Definitive record's **HQ**: name, address, city, state, zip, phone |
| `Matched_Zeus_Name`, `Matched_Definitive_Name`, `Matched_Via`, `Matched_Zeus_Source` | The two names that actually produced `Name_Score`. `Matched_Via` says whether the Definitive side was the record's name, a former name (`Alias`) or a service location (`Location`). `Matched_Zeus_Source` says which Zeus population holds that name |
| `Matched_Zeus_Address/City/State/Zip`, `Matched_Definitive_Address/City/State/Zip` | The two addresses that produced the street scores |
| `Phone_Match`, `Matched_Phone`, `Phone_Lookup_*` | The phone check (below) |

**The matched address isn't always the HQ.** Where `Address_Match_Source` is
`Location`, the Zeus address matched one of the record's service locations, and
`Matched_Definitive_*` shows that site. A Zeus clinic can score 100 against its
own satellite while the HQ is elsewhere. Compare the matched pair, not the HQ.

**The phone check never changes a verdict or tier.** `Phone_Match` is:

- `True`: a Zeus number equals one of the record's numbers (HQ or any site);
- `False`: both sides have usable numbers and none agree;
- blank: one side has no usable number, or the only overlap is a number shared
  by five or more Definitive records (a switchboard). Blank means no evidence
  either way, not disagreement.

Treat `True` as strong supporting evidence and `False` as a reason to look
closer. On confirmed accuracy rows the phones agree about 92% of the time, so
some disagreement is normal: numbers change.

## 3. Hospital ownership hierarchy

One command. It reads Definitive Hospital Overview only (hospitals and health
systems), gives every record one parent, and walks each chain up to its root:

```
py dhc_hierarchy.py --config sources.yaml     --accuracy "Results Output/<accuracy run>/<accuracy run>_scored.csv"
```

The parent rule is `SfParentAccountId`, else `IdNetwork`, else the record's own
`HospitalId`, which makes it a root. The rule is written in
`Definitive Hospital Hierarchy.sql` and nowhere else, and the `Parent_Rule`
column says which step decided each row. `--accuracy` is optional: it adds the
Zeus EntityIds that carry each Definitive id (`Zeus_EntityIds`,
`Tree_Zeus_Entity_Count`), so the destination data can be compared on either
key. `--definitive-from <hierarchy run folder>` replays that run's snapshot,
and the output is byte-identical.

Every record gets **two parents, labelled**, because the tree runs up to three
levels deep (system > division or region > hospital), and the destination
system may model either grain:

| Prefix | Meaning | Example for Medical City Denton |
|---|---|---|
| `Immediate_Parent*` | The direct owner, in the full tree. `Immediate_Level` is 0 for a root and up to 2 below it | HCA Medical City Healthcare (North Texas Division) |
| `Ultimate_Parent*` | The top-level owner, with the tree flattened to two levels. `Ultimate_Level` is 0 or 1 | HCA Healthcare |

They differ only for the 2,247 records with `Has_Intermediate_Parent = True`.
A root is its own immediate and ultimate parent.

Written to `Results Output/dhc_hierarchy_<date>_<time>/`:

- `<run>_hierarchy_immediate.csv`: one edge per record, record → direct
  owner. The full tree.
- `<run>_hierarchy_ultimate.csv`: one edge per record, record → top-level
  owner. The flattened tree, with the skipped division named in
  `Intermediate_ParentId` / `Intermediate_ParentName`.
- `<run>_hierarchy.csv`: everything on one row per record, sorted by tree:
  both parents, `Path_Ids` / `Path_Names` (root first, `" > "`-separated),
  `Immediate_Child_Count`, `Descendant_Count`, `Hierarchy_Issue`, and the Zeus
  columns. Hand the migration team the edge list that matches their grain, or
  this file if they want both.
- `<run>_dhc_hospitalhierarchy.parquet` / `.sql`: the snapshot and the SQL
  that produced it.
- `Definitive_Hospital_Hierarchy_<date>_<time>.xlsx`: Summary (records by
  level, immediate versus ultimate, by rule, largest ultimate parents,
  identity checks), Methodology, Immediate_Parent, Ultimate_Parent,
  Hierarchy, Roots, Hierarchy_Issues, and Zeus_Linked if `--accuracy` was
  given.

What you should see (2026-09-30): 9,887 records, 2,589 trees (683 with more
than one member), maximum depth 2, two `Parent_Not_In_Definitive` rows, and
four `OK` checks. A `FAIL` or a jump in the issue count means the view changed
shape. Look before you circulate.

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

- The replay copies the earlier run's Definitive snapshots (and their `.sql`)
  into its own folder, so its workbook can be built from that folder alone.
- The same works for the coverage tool: `dhc_gap_match.py` takes `--zeus` and
  `--definitive-from` too.
- Extracts from before 2026-09-29 carry no phones. A replay of one prints
  `note: this extract predates phone capture` and leaves the phone columns
  blank; everything else is unaffected.

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
| VS Code marks the `Definitive *.sql` files full of errors (`Invalid object name 'prd_silver...'`, `'array_sort' is not a recognized built-in function`) | The editor checks every `.sql` file as SQL Server. These four are Databricks SQL | False alarm. To check one, run it in the Databricks SQL editor |
| `--population 'X' is not in this run; choose one of [...]` | The label isn't a `zeus.sources` label | Use one from the list, e.g. `WorkLocation` |
