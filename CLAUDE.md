# Zeus ↔ Definitive Healthcare identifier audit

## What this project does

Measures how often the third-party Definitive Healthcare (DHC) IDs stored in Zeus
(Jackson and Coker's internal CRM) actually point at the right Definitive record.
Verification is by fuzzy comparison of name and address between the two sides —
there is no authoritative key to check against, so the output is a confidence
score and a verdict per row, not a boolean.

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
  `py build_audit_workbook.py --scored <prefix>_scored.csv --config sources.yaml
  [--baseline <earlier>_scored.csv] --out <name>.xlsx`
- `sources.yaml` — column-role and connection config. **This is the only file to
  edit when a new Definitive export arrives.**
- **Six Zeus queries**, `Zeus <X> to Definitive ID data quality evaluation.sql`
  for X in Client, Work Location, HealthSystem, GPO, Agency, VMS. Read live;
  there is no longer a Zeus workbook. Each reads its own `*Info` table and so
  its own column names, mapped to roles per-population under `zeus.sources`.
  See decision #10 for why they are pooled rather than stacked.
- **Identity exports** — one row per Definitive entity, all keyed `DefinitiveId`:
  `Definitive_HospitalOverview.xlsx` (9,870),
  `Definitive_PhysicianGroupOverview.xlsx` (138,385),
  `Definitive_GPO_Overview.xlsx` (212). They share no ids.
- `Definitive_Practice_Locations.xlsx` — **a child table, not an identity
  export.** 399,990 service locations across 176,658 parent ids. Configured
  under `locations:`, never `definitive:`. See decision #9.
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
py dhc_match_v2.py run --config sources.yaml --out audit_2026_08 [--no-reverse]
py dhc_match_v2.py run --config sources.yaml --zeus <archived_extract.csv> ...
```

## Producing a new audit summary

Two commands. Set `TAG` to the run you want (`2026_09`, say) and `PREV` to the
previous run's scored csv, which drives the like-for-like comparison.

```
py dhc_match_v2.py run --config sources.yaml --out audit_<TAG>

py build_audit_workbook.py --scored audit_<TAG>_scored.csv --config sources.yaml \
    --baseline audit_<PREV>_scored.csv --out Zeus_DHC_ID_Accuracy_Audit_<TAG>.xlsx
```

Step 1 writes `audit_<TAG>_scored.csv`, `_unverifiable.csv` and
`_zeus_extract.csv`; step 2 turns them into the branded workbook. Roughly two to
three minutes end to end, most of it reading the 400k-row location export.

Preconditions — all currently satisfied:

- `ZEUS_SQL_PASSWORD` set at User scope. If it is missing the run stops
  immediately and names the variable.
- The four `Definitive_*.xlsx` exports present in the working directory.
- `pyodbc` plus ODBC Driver 17 or 18 installed.

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

**Keep `audit_<TAG>_zeus_extract.csv` with anything you circulate.** Zeus is a
live moving target and the snapshot is the only way to reproduce a figure later.
Verified: replaying it with `--zeus` reproduces the run exactly.

When a **new Definitive export** arrives, run `inspect` on it and update
`sources.yaml` — under `definitive:` for an identity export, or `locations:` if
it has many rows per id (decision #9). When a **new Zeus population** is added,
add a block under `zeus.sources` with that query's own column names; nothing
else needs to change (decision #10).

Every run writes `<out>_zeus_extract.csv`, a snapshot of the exact input it
scored. Zeus is a live moving target and these snapshots are **not** in git (see
"Version control"), so one is still the only way to reproduce a figure later —
keep it with any results you circulate. The `--zeus` flag replays one offline.

## Version control

The folder is a git repo with a **private** GitHub remote,
`GrantJCLT/Zeus-DHC-Ids-to-Definitive-Source-Fuzzy-Matching`. Keep it private:
the history contains licensed Definitive exports and Zeus client records.

Only source is tracked — the two scripts, `sources.yaml`, the three `.sql` files,
this file, and `.gitignore`. Everything else is deliberately ignored:

| Ignored | Why |
|---|---|
| `Definitive_*.xlsx` | Licensed third-party data. A git remote is redistribution — confirm terms with the licence owner before these leave this machine. |
| `audit_*_scored.csv`, `audit_*_unverifiable.csv`, `audit_*_zeus_extract.csv` | Zeus client names and addresses. Regenerable from the query plus `sources.yaml`. |
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
(`audit_2026_08_all6_*`). 19,820 population rows pooled to **12,803 distinct
entities**; 11,099 testable (86.7%); 202,586 reference records.

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

## Decisions that must not be silently reversed

These were derived empirically against this data. Each one exists because the
naive alternative was measurably wrong.

1. **Never quote an accuracy rate against all 207,450 rows.** The Definitive
   extract is hospitals only. An ID absent from it is *unverifiable*, not wrong.
   Quoting 4.6% as an accuracy figure measures the scope of the export, not the
   quality of Zeus. Always state the denominator.

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

Latest deliverable: `Zeus_DHC_ID_Accuracy_Audit_2026_08.xlsx`. The funnel
reconciles (testable + unverifiable = supplied) and the verdict counts sum to
the testable population — worth re-checking after any change, since those two
identities catch most wiring mistakes.

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
`audit_2026_08_live_unverifiable.csv` before buying another export. Licensing
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
