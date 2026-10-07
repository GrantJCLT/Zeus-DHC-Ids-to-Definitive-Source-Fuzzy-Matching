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
| **Definitive hierarchy**: how Definitive's hospitals, health systems, physician groups and their practice locations nest under their owners | `dhc_hierarchy.py` | `Definitive_Ownership_Hierarchy_<date>_<time>.xlsx` plus `<run>_hierarchy.csv` | about 6 min (1.5 with `--no-locations`) |
| **Definitive-only hierarchy of Zeus ids**: the Definitive ids Zeus holds, each walked up Definitive's own ownership chain, with no Zeus link used | `dhc_only_hierarchy.py` | `Definitive_Only_Hierarchy_<date>_<time>.xlsx` plus `<run>_entities.csv` | about 3 min (under 1 with `--no-imports`), once an accuracy run exists |
| **Zeus hierarchy**: one Health System > Client > Work Location tree for Zeus, from Definitive ownership first and Zeus links second; a read-only baseline to validate the migration team's hierarchy against | `zeus_hierarchy.py` | `Zeus_Entity_Hierarchy_<date>_<time>.xlsx` plus `<run>_hierarchy_edges.csv` | about 1 min, once both audits exist |
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
populations, both full workbooks, and both hierarchies**. About 35 minutes. It
runs:

1. the accuracy run;
2. the coverage run, cross-checked against step 1 (`--claimed`) and scored
   against **step 1's Definitive snapshots** (`--definitive-from`), so both
   audits see exactly the same Definitive data even though the views refresh in
   place;
3. the full accuracy workbook and the full coverage workbook;
4. the Definitive ownership hierarchy (section 3);
5. the Zeus Health System > Client > Work Location hierarchy (section 4), from
   steps 1, 2 and 4.

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
| `py run_all.py` | 4: `Zeus_DHC_ID_Accuracy_Audit_<run>.xlsx`, `Zeus_DHC_ID_Coverage_Audit_<run>.xlsx`, covering all populations, plus the two hierarchy workbooks |
| `py run_all.py --population WorkLocation` | 6: the same 4, **plus** `Zeus_DHC_ID_Accuracy_Audit_WorkLocation_<run>.xlsx` and `Zeus_DHC_ID_Coverage_Audit_WorkLocation_<run>.xlsx` |
| `py run_all.py --population WorkLocation --population Client` | 8: the same 4, plus 2 for Work Location, plus 2 for Client |
| `py run_all.py --population all` | 16: the same 4, plus 2 for each of the six labels under `zeus.sources` in the config |

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
| `--accuracy-only` | Just the accuracy run and its workbook(s), about 3 minutes. Skips both hierarchies, which need the coverage run |
| `--no-hierarchy` | Skips the two hierarchy steps |
| `--limit N` | Coverage scores only the first N entities: a 6-minute end-to-end test. The "extract entities = population" check shows `n/a` then, as expected; the Zeus hierarchy is built over that smaller universe |
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

## 3. Definitive ownership hierarchy

One command. It reads every view under `hierarchy:` in `sources.yaml`:
Definitive Hospital Overview (hospitals and health systems) and, since
2026-10-07, Physician Group Overview. It gives every record one parent, and
walks each chain up to its root:

```
py dhc_hierarchy.py --config sources.yaml     --accuracy "Results Output/<accuracy run>/<accuracy run>_scored.csv"
```

The parent rule is `SfParentAccountId`, else `IdNetwork`, else the record's own
`HospitalId`, which makes it a root. Each view's rule is written in its own
`Definitive * Hierarchy.sql` and nowhere else, and the `Parent_Rule` column
says which step decided each row; `Source_View` says which view the record came
from. `--accuracy` is optional: it adds the Zeus EntityIds that carry each
Definitive id (`Zeus_EntityIds`, `Tree_Zeus_Entity_Count`), so the destination
data can be compared on either key. `--definitive-from <hierarchy run folder>`
replays that run's snapshots, and the output is byte-identical. A run from
before 2026-10-07 has no physician-group snapshot and cannot be replayed.

**Practice locations** (since 2026-10-07) are added as leaves, one level below
the record that owns them. They come from the same `locations:` block and
`Definitive Practice Locations.sql` the audits use, unchanged. Definitive gives
a location no stable id, so each gets a derived `Location_Key`,
`L<parent id>-<12 hex>`, hashed from its name, address, city, state and zip. It
changes when the location is renamed or moves. Every output then leads with
`Node_Id` (the `HospitalId`, or the `Location_Key`), and a location row has
`TypeFirm = Practice Location`, `Immediate_Parent_Rule =
PracticeLocationHospitalId`, a blank `HospitalId`, and `Location_Key`,
`Location_Address` and `Location_Zip` filled. Records gain `Location_Count`
(their own locations) and `Tree_Location_Count`, and their
`Immediate_Child_Count` and `Descendant_Count` now include locations.
`--no-locations` leaves them out: the output is then exactly the records-only
shape, and that is the only way to replay a hierarchy run from before
2026-10-07 15:15, which has no `_dhc_practicelocations` snapshot. GPOs are not
in the hierarchy: they are purchasing affiliations, not owners.

Every record gets **two parents, labelled**, because the tree runs up to four
levels deep (system > division or region > hospital > physician group), five
with a practice location below that, and the
destination system may model either grain:

| Prefix | Meaning | Example for Medical City Denton |
|---|---|---|
| `Immediate_Parent*` | The direct owner, in the full tree. `Immediate_Level` is 0 for a root and up to 4 below it (3 without locations) | HCA Medical City Healthcare (North Texas Division) |
| `Ultimate_Parent*` | The top-level owner, with the tree flattened to two levels. `Ultimate_Level` is 0 or 1 | HCA Healthcare |

They differ only for records with `Has_Intermediate_Parent = True`. A root is
its own immediate and ultimate parent.

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
- `<run>_dhc_hospitalhierarchy.parquet` / `.sql`,
  `<run>_dhc_physiciangrouphierarchy.parquet` / `.sql` and
  `<run>_dhc_practicelocations.parquet` / `.sql`: the snapshots and the SQL
  that produced them.
- `Definitive_Ownership_Hierarchy_<date>_<time>.xlsx`: Summary (records by
  level and type, immediate versus ultimate, by rule, largest ultimate
  parents, identity checks), Methodology, Immediate_Parent, Ultimate_Parent,
  Hierarchy, Roots (those that own something), Hierarchy_Issues, and
  Zeus_Linked if `--accuracy` was given.

What you should see (2026-10-07, run `dhc_hierarchy_2026_10_07_1515`):
549,894 nodes, which are 153,508 records (8,710 hospitals, 1,181 health
systems, 142,819 physician groups, 467 MSOs, 331 IPAs) plus 396,386 practice
locations. They form 195,219 trees, maximum depth 4. 326,844 locations sit
under a record and 69,542 under a parent in no view. There are 86,977
`Parent_Not_In_Definitive` rows, and eight checks ending `OK`. The workbook is
about 167 MB. With `--no-locations`: 142,595 trees (1,566 with more than one
member), maximum depth 3, 2,768 `Parent_Not_In_Definitive` rows, and four
checks. Almost all of
those 2,768 are physician groups owned by a corporate parent that is in
neither view (The US Oncology Network, AMSURG, RadNet, Village Medical, ...);
they are kept, named from `SfParentAccountName`, and flagged. 95.7% of
physician groups have no parent at all. A `FAIL` or a jump in the issue count
means a view changed shape. Look before you circulate.

### Definitive-only hierarchy of the ids Zeus holds

The base is every Zeus entity with a Definitive id, using the id exactly as
Zeus stores it, whatever its verdict. That covers two groups:

- the audited entities: the accuracy run's `_scored.csv` and
  `_unverifiable.csv` together;
- every active entity created by a Definitive import that holds a Definitive
  id, whether it is linked or not. These come from `Zeus import entities.sql`,
  which is queried live on the ReadOnly replica. The audits exclude these
  entities, so their `Verdict` is `Import-created (not audited)`.

Each id is walked up Definitive's ownership chain by the same parent rule as
above. No Zeus link, Zeus role, correction or coverage proposal is used:

```
py dhc_only_hierarchy.py --config sources.yaml \
    --accuracy "Results Output/<accuracy run>/<accuracy run>_scored.csv" \
    [--definitive-from "Results Output/<dhc_hierarchy run>"] \
    [--zeus-imports "Results Output/<earlier dhc_only_hierarchy run>"] \
    [--no-imports]
```

`--zeus-imports` replays the `_zeus_imports.csv` snapshot instead of querying
Zeus. `--no-imports` leaves the import-created entities out. The run takes
about 3 minutes with the import-created entities and under 1 minute without.
Check for `connected to a READ_ONLY database` in the output, as for the audits.

The run writes these files into `Results Output/dhc_only_hierarchy_<date>_<time>/`:

- `<run>_entities.csv`: one row per Zeus entity, with its id's `Id_Status`, its immediate and
  ultimate Definitive parent, and `Immediate_Parent_Zeus_EntityIds` /
  `Ultimate_Parent_Zeus_EntityIds`, the Zeus entities whose own id is that
  parent.
- `<run>_hierarchy.csv`: one row per Definitive record in the tree. That is
  each record a Zeus entity points at (`Node_Role = Zeus id`) plus every owner
  above it (`Owner only`). An owner that is in no view gets its own root row.
- The `_immediate` / `_ultimate` edge lists, the snapshots, and the workbook.

Eight identity checks print as `OK`/`FAIL`. A replay from the run's own folder
is byte-identical.

Measured on `dhc_only_hierarchy_2026_10_07_1811_imports` (accuracy run
`0834`, hierarchy snapshot `1515`):

- **Base:** 215,826 entities, of which 12,803 are audited and 203,023
  import-created. 112,218 are placed in the tree.
- **Not placed:** 103,433 have an id in no Definitive source (1,706 audited
  and 101,727 import-created), 170 hold a practice-location parent id, and 5
  hold a GPO id.
- **Tree:** 110,574 records in 97,612 trees, depth ≤ 3. 16,077 entities have
  an owner above them.

**Most import-created physician group ids are no longer in Definitive's
views.** That accounts for 98,320 of the 101,727 unplaced import-created
ids, so expect this figure rather than treating it as a wiring fault.

---

## 4. Zeus entity hierarchy (Health System > Client > Work Location)

A **read-only comparison baseline**: the migration team derives the hierarchy
that will be used, and this one exists to validate theirs. Nothing is written
back to Zeus or any other source; the workbook is the deliverable.

One command, once an accuracy run, a coverage run and a Definitive hierarchy
run exist (`run_all.py` does all four in order):

```
py zeus_hierarchy.py --config sources.yaml `
    --accuracy "Results Output/<accuracy run>/<accuracy run>_scored.csv" `
    --coverage "Results Output/<coverage run>/<coverage run>_gap_candidates.csv" `
    --definitive-hierarchy "Results Output/<dhc_hierarchy run>"
```

Every entity gets **one type** - the highest of its Zeus roles, HealthSystem
over Client over WorkLocation, so a hospital Zeus flags as client and work
location is a Client - and **one parent or none**. A parent is always a higher
type, or a health system under a health system to any depth: a work location
sits under a client or a health system, a client under a health system.
Definitive ownership comes first and Zeus links complete it. The rules are in
[Hierarchy_Logic.md](Hierarchy_Logic.md). In short:

- Each entity's Definitive id comes from the audits: supplied ids rated
  `ID corroborated` or `Probable` (no `Geo_Conflict`), recommended
  corrections, and `Strong match` coverage proposals. Definitive-import-created
  entities that Zeus links to in-scope ones are included too, with the id they
  were created from.
- The Definitive parent is the nearest record up the entity's Definitive
  ownership chain that a Zeus entity of an allowed parent type stands for.
- **Definitive wins** where it knows an owner, and **hospital owners outrank
  staffing firms**. Where Zeus names a *different hospital or health system*
  (or, above work locations, any parent in a different Definitive tree), that
  is a `Contradiction`: the Zeus link is **kept for now** and listed for
  review. A Zeus entity on the *same* Definitive record confirms or fills, but
  never overrides a Zeus link.
- Otherwise the Zeus link stands. With several, the tie-break is the child's
  own Definitive tree, then bookings, then link history.
- Zeus links that one type per entity cannot hold - a hospital linked to
  itself, a client under a client - are set aside, and two health systems
  linked to each other are separated (`Loops_Broken`).

The column to act on is `Zeus_Link_Status`:

| Status | Meaning |
|---|---|
| `Agrees` | Definitive's parent is one Zeus already links |
| `Definitive fills` | Zeus had no link; Definitive supplied one |
| `Definitive replaces` | Zeus linked a parent in the same Definitive tree, one with no trusted Definitive id, or - for a work location - only staffing firms or physician groups where Definitive names a hospital or health system owner. Definitive's owner is used. Sheet `Zeus_Links_Replaced` lists each overridden link and why |
| `Contradiction` | Every Zeus parent is in a different Definitive tree, and it is not the staffing-firm case. **Held**: the Zeus link is kept until reviewed. Sheet `Contradictions` |
| `Zeus only` | Definitive has no parent for it; the Zeus link is used |
| `No parent` | Neither source has one, or a loop was broken here (`Tree_Issue` says so). Expected for a client with no health system; an orphan for a work location |

**Migration readiness** (since 2026-10-07): the Hierarchy sheet and
`_hierarchy_nodes.csv` carry the migration team's `ready_for_migration`, read
live from `qat_gold.crmmig_rules` through `Zeus migration readiness.sql`.
Three tables: `healthsystem_summary`, `client_summary`, `worklocation_summary`.
Each is keyed by an `*InfoId` that is the Zeus `EntityId`. The columns sit
right after `In_Scope`:

| Column | Meaning |
|---|---|
| `Ready_For_Migration` | 1 ready, 0 not, blank in none of the tables. Taken from the table of the entity's own `Entity_Type` |
| `Ready_For_Migration_From` | The table used. It differs from the entity's own type only where that table has no row; then the next table, highest type first, is used |
| `Ready_HealthSystem_Summary`, `Ready_Client_Summary`, `Ready_WorkLocation_Summary` | Each table's own flag, blank where it has no row. Some EntityIds are in several tables |
| `Ready_Tables_Disagree` | True where those flags differ |

The Summary sheet counts them by type, and an identity check confirms that
ready + not ready + in no table = nodes. On 2026-10-07: 16,887 ready, 55,253
not, 61 in no table, 81 health systems whose tables disagree.
`--migration-from <run folder>` replays an earlier run's
`_migration_readiness.parquet`. `--no-migration` leaves the columns out.

`--zeus-links <run folder>` and `--definitive-hierarchy <run folder>` both
accept an earlier `zeus_hierarchy` run, and with the same audit files (and
`--migration-from` the same folder) the output is byte-identical. Without `--zeus-links` the three Zeus queries
(`Zeus hierarchy links.sql`, `Zeus linked import entities.sql`,
`Zeus entity duplicates.sql`) run live, in seconds.

Written to `Results Output/zeus_hierarchy_<date>_<time>/`:

- `<run>_hierarchy_edges.csv`: **the tree**, one row per child: child and
  its `Entity_Type`, parent and its type, `Zeus_Link_Status`, both ends'
  `Resolution_Basis`.
- `<run>_hierarchy_nodes.csv`: one row per entity, everything: `Entity_Type`
  and the `Zeus_Roles` behind it, its resolved id, the chosen parent and why,
  `Definitive_Distance` (0 same record, 1 direct owner, 2+ higher), the
  Definitive records climbed past, every Zeus link with the reason one was
  chosen, the held Definitive parent for a contradiction, `Top_HealthSystem_*`,
  `Path_Names` and `Tree_Issue`.
- `<run>_contradictions.csv`, `<run>_zeus_links_replaced.csv`,
  `<run>_zeus_links_dropped.csv`: the review lists.
- `<run>_resolution.csv`: the Definitive id (or none) and type of every
  in-scope entity and every import-created one in the tree, with
  `In_Definitive_Hierarchy`.
- `<run>_zeus_links.csv`, `_zeus_linked_imports.csv`, `_zeus_duplicates.csv`
  and `<run>_dhc_*hierarchy.parquet`: the inputs, for replay. **Keep them with
  anything you circulate.**
- `Zeus_Entity_Hierarchy_<date>_<time>.xlsx`: Summary, Methodology,
  Hierarchy, Contradictions, Zeus_Links_Replaced, Zeus_Links_Dropped,
  Loops_Broken, Multi_Parent_Choices, Definitive_Parents_Not_In_Zeus,
  Shared_Definitive_Id, Orphans, Duplicates_Remapped.

What you should see (2026-10-07, the first full run's inputs): 72,201 entities
(27,715 work locations, 42,718 clients, 1,768 health systems; 11,688
import-created), the `connected to a READ_ONLY database` line on a live run,
nine checks ending `OK`, 8 health system loops broken, and at the work location
level 2,844 `Agrees`, 2,228 `Definitive replaces`, 110 `Contradiction` and
22,247 `Zeus only`. A large swing in `Definitive replaces` or `Contradiction`,
or more than a handful of loops, means the audits, Zeus or Definitive moved;
look before you circulate.

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
from. Rerun it before loading an old one. The same holds for a Zeus hierarchy:
it rests on both audits and on that day's Zeus links, so archive its folder
with the two audit folders it was built from.

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
| VS Code marks the `Definitive *.sql` files full of errors (`Invalid object name 'prd_silver...'`, `'array_sort' is not a recognized built-in function`, `Incorrect syntax near '`'`) | The editor checks every `.sql` file as SQL Server. These six are Databricks SQL | False alarm. To check one, run it in the Databricks SQL editor |
| `UNRESOLVED_COLUMN ... HospitalId cannot be resolved. Did you mean ... HQ_CITY ...` from a Definitive view | The files behind the view were reloaded with different column names and the view was not updated. Happened to `physiciangroupsoverview` on 2026-10-07 (02:10 to 10:25 Eastern) | An upstream processing error: tell the view's owner (`databricks tables get prd_silver.definitive.<view> --profile jcl` shows who). Don't work around it in the `.sql` files; wait for the fix and rerun |
| `--population 'X' is not in this run; choose one of [...]` | The label isn't a `zeus.sources` label | Use one from the list, e.g. `WorkLocation` |
