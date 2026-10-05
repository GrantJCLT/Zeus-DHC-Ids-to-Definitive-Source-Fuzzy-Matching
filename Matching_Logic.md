# Matching logic

How the two audits compare a Zeus entity with a Definitive Healthcare record:
what is normalised, how each field is scored, and how the scores become a
verdict or a tier. Written 2026-10-05 for anyone maintaining the tools or
reviewing their output. **Update it whenever a normalisation map, weight or
threshold changes**, and record the change and its measured effect in the
change log at the end.

Every function named here lives in `dhc_match_v2.py`. `dhc_gap_match.py` imports
them rather than copying them, so both audits normalise and score identically.
The only thing that differs is how scores become a judgement (section 6). The
fuzzy scorers are from the `rapidfuzz` library.

Contents:

1. What is compared
2. Text cleaning
3. Names
4. Street addresses
5. City, state and zip
6. From scores to a judgement
7. Phone (reported beside the judgement, never inside it)
8. Known limitations
9. Change log

## 1. What is compared

Both sides offer several candidates, and the best pairing wins. An extra
candidate can therefore only raise a score, never lower it.

| | Names | Address lines | City / state / zip |
|---|---|---|---|
| **Zeus** | Both name fields (`e.Name` and the `*Info` name), from every population the entity belongs to (decision #10, pooling by `EntityId`) | All three address columns, from every population | Each population row's own |
| **Definitive** | The record's name, its former names in brackets, and the names of its service locations | HQ lines 1–2, plus up to 250 service-location addresses (60 in the coverage tool) | HQ plus every known service location |

`Matched_Zeus_Name` / `Matched_Definitive_Name` and the eight `Matched_*Address`
columns in the output show which pair won. They reproduce `Name_Score` and the
street scores exactly.

## 2. Text cleaning: `_clean()`

Applied to every name, address and city before anything else:

1. Lowercase.
2. `&` becomes ` and `.
3. Every punctuation character becomes a space: `St.` → `st`,
   `Wilkes-Barre` → `wilkes barre`, `Mary's` → `mary s`.
4. Runs of spaces collapse to one, and the ends are trimmed.

## 3. Names: `name_score()`

**Former names.** `split_name()` turns a Definitive name into a primary name
plus aliases (decision #2):

- A bracketed part beginning `FKA`, `F/K/A`, `AKA`, `A/K/A`, `DBA`, `D/B/A`,
  `formerly`, `formerly known as`, `now` or `NKA` becomes an alias.
- Status markers are removed: `(Closed)`, `(Closing)`, `(Inactive)`,
  `(Merged)`, `(New)`, `(Pending)`, `(Proposed)`, `(Under construction)`,
  `(Campus …)`, `(Satellite …)`, `(Reopened)`. The coverage tool reports
  `(Closed)` and `(Merged)` separately as `Suggested_Status_Note`.
- Any other bracketed part over 3 characters is also kept as an alias.

**Service-location names** become further aliases of their parent record. The
coverage tool first drops location names that identify nothing (decision #13):
names shared by 5 or more parent records, such as `Family Medicine`, and branch
labels that are only the branch's own city or a compass word.

**Each comparison: `pair_score()`.** 35% `token_set_ratio` + 65%
`token_sort_ratio`. Both are 0–100 and ignore word order.
`token_set_ratio` alone scores 100 whenever one name's words are a subset of
the other's, so a short generic name would beat the right longer one. The blend
penalises that length gap (decision #3).

**Core names: `name_core()`.** The cleaned name with these generic words
removed (`NOISE_TOKENS`):

| Kind | Words removed |
|---|---|
| Legal form | inc, incorporated, llc, llp, lp, pc, pa, pllc, plc, ltd, corp, corporation, co, company, dba |
| Grammar | the, of, at, and, a, an |
| Generic healthcare | group, system, systems, health, healthcare, medical, center, centre, ctr, hospital, hospitals, clinic, clinics, regional, memorial, community, general, district, services, service, associates, assoc, partners, network, university, univ |
| Saints | st, saint |

Both the full cleaned names and the cores are scored, and the higher score
counts. The core comparison can only rescue a near-miss, never lower a score.
An empty core is skipped. Do not remove `group`, `associates`, `partners` or
`community` from the list (decision #7, and "How `name_core` behaves on
practices" in CLAUDE.md).

**Every combination.** Each Zeus name is scored against each Definitive name,
alias and location name, and the highest score is `Name_Score`.

Names get **no** street-style abbreviation expansion. `Mt` / `Mount` and
`Hosp` / `Hospital` are not equated in names (see section 8).

## 4. Street addresses

### Abbreviations: `norm_addr()`

After cleaning, each word is replaced by its short form from `ADDR_ABBREV`:

| Kind | Mappings |
|---|---|
| Street types | street, str → st · avenue, av → ave · boulevard → blvd · road → rd · drive → dr · lane → ln · court → ct · circle → cir · place → pl · parkway → pkwy · highway → hwy · terrace → ter · trail → trl · square → sq |
| Units | suite → ste · apartment → apt · building → bldg · floor → fl · room → rm |
| Directions | north → n · south → s · east → e · west → w · northeast → ne · northwest → nw · southeast → se · southwest → sw |
| Ordinals | first … tenth → 1st … 10th |
| Other | mount → mt · fort → ft · doctor → dr · saint → st |
| PO Box | `P.O. Box`, `P O Box`, `PO Box` → `po box` |

Then split directions are merged: `n w` → `nw`, and likewise `ne`, `se`, `sw`.
So `N.W.`, `N W`, `North West` and `Northwest` all become `nw`.

Examples: `123 North Main Street` and `123 N. Main St.` both become
`123 n main st`. `1200 N.W. 7th St` and `1200 Northwest 7th Street` both become
`1200 nw 7th st`.

### Two scores per line

- **Street number** (`street_number()`): the leading digits, with an optional
  letter (`12a`). For a PO box it is the box number (`box365`). It must match
  exactly: 100 if equal, 0 if not, blank if either side has none.
- **Street body** (`street_body()`): everything after the number, compared with
  `fuzz.ratio`. That is a 0–100 edit-distance similarity on characters, so word
  order matters.

### Best pair: `addr_scores()`

Every Zeus line is compared with every Definitive line, HQ and locations
alike (decision #6). The pair with the highest street number + street body
wins. `Address_Match_Source` records whether the winning line was the `HQ` or
a `Location`.

**Unit-only lines never compete** (`is_unit_only()`). A line that names only a
unit, such as `Ste A`, `Suite 300`, `Bldg 3`, `2nd Floor`, `Lower Level`,
`Tower 2 Ste 203` or `Mail Stop 4033`, says nothing about which street the
entity is on, so it is left out of the comparison on both sides. The street
line beside it still competes. A line counts as unit-only only when:

- it has no street number; and
- every word is a unit word (`UNIT_TOKENS`: ste, apt, bldg, fl, rm, unit,
  dept, lot, spc, lvl, pmb, level, ofc, office, frnt, lbby, lobby, mail, stop,
  slot, wing, tower, ph, penthouse), a positioning word in front of one
  (`2nd`, `ground`, `lower`, `upper`, `main`), or a short identifier after one
  (`A`, `300`, `A-1`, `101 & 102`).

So `Building 9040 Fitzsimmons Dr` and `Bldg T9 Fort Missoula Rd` stay street
lines, because a street follows the building. `Tower Place` stays a street line
too, because its "identifier" is a street type. A named building with no
street, such as `Fl 2 Tuttleman Bldg`, also stays a street line, because the
building name can match. If every line on one side is unit-only, the street
scores are blank and `Address_Score` rests on city, state and zip.

Measured over every real line on 2026-10-05: 285,948 line occurrences are
unit-only, almost all `Ste …` from the location view's second address column.
2,543 lines that start with a unit word are kept as street lines.

## 5. City, state and zip

Each is compared against **every** site the Definitive record has, not just the
winning address line.

| Field | Normalisation | Score |
|---|---|---|
| City | `norm_city()`: cleaned, then `CITY_ABBREV`: saint → st, sainte → ste, fort → ft, mount → mt | `fuzz.ratio`, best over every pair |
| State | `norm_state()`: full name → two-letter code; two letters kept as they are; anything else → its first two letters, uppercased | 100 if any state matches, else 0 |
| Zip | `norm_zip5()`: digits only, first 5, left-padded with zeros (`2134` → `02134`, repairing Excel's lost zero) | 100 if any zip matches, else 0 |

Cities have their own small map because the street map would turn `Court` or
`Place` inside a city name into street codes.

**Compass words are deliberately not abbreviated in cities.** That was tried
and measured on 2026-10-05. Shortening `West` to `w` lifted `Des Moines` /
`West Des Moines` from 80 to 91 and `Las Vegas` / `North Las Vegas` from 75 to
90. Those are neighbouring cities, now past the coverage tool's `city >= 90`
same-place test, and the change promoted coverage rows to the Strong tier on a
neighbouring city. A shorter normalised string makes any remaining difference
weigh more, so be wary of any city mapping that shortens a prefix.

### Combined address score

`Address_Score` is a weighted average (`ADDR_W`):

| Street number | Street body | City | State | Zip |
|---|---|---|---|---|
| 0.30 | 0.22 | 0.18 | 0.08 | 0.22 |

A blank component (missing on either side) is left out, and the other weights
are rescaled to sum to 1. A blank never counts as 0.

`Confidence_Score` / `Match_Score` adds the name at the same time (`BLEND_W`):
name 0.40, street number 0.20, street body 0.15, city 0.10, state 0.05, zip
0.10. It is for sorting and the coverage tool's runner-up margin. It is never
the judgement (decision #4).

## 6. From scores to a judgement

### Accuracy: `verdict()`

Zeus already holds an id. Name outranks address, because Definitive's address is
often the HQ while Zeus holds the site (decision #4).

| Verdict | Condition (checked in order) |
|---|---|
| ID corroborated | name ≥ 92, or name ≥ 75 and address ≥ 60 |
| Probable - name agrees, address differs | name ≥ 75 |
| Probable - address agrees, name differs | address ≥ 85 and name ≥ 45 |
| Needs review | name ≥ 45 or address ≥ 50 |
| Likely wrong ID | everything else |

Flags beside the verdict:

- `Address_Divergent`: corroborated, but address < 60.
- `Geo_Conflict`: name ≥ 92 and `State_Score` 0, meaning no known location of
  the record is in any of Zeus's states (decision #8).
- `Correction_Recommended`: every row that is not `ID corroborated` gets a
  reverse lookup for the best-named record. A correction is recommended when that
  record is a different id with name ≥ 80 and more than 10 points above the
  supplied id's name score, and address ≥ 60 and no more than 10 points below
  the supplied id's address score. The address conditions stop it proposing
  Plano for Llano (decision #5).

### Coverage: `tier()` in `dhc_gap_match.py`

Nothing is on record, so a name match alone is not enough (decision #11).

**Finding candidates.** For each entity, every Definitive name in the same
state is scored with the same 35/65 blend. That includes service-location names,
and a location's state counts. The top 6 records scoring at least 55 go
forward. An entity with no usable state is searched nationally. Names with fewer
than 4 letters or digits are not searched.

**Scoring.** Each candidate is then scored exactly, as in sections 3–5.
`Match_Margin` is the best candidate's `Match_Score` minus the runner-up's.

Two tests are used:

- **street:** address ≥ 85.
- **same place:** address ≥ 60, or the zip matches, or city ≥ 90 with the
  state matching.

| Tier | Condition (checked in order) |
|---|---|
| No credible match | name < 75 |
| Ambiguous - rival candidates | margin < 3 |
| Strong match - ready to load | name ≥ 92 and either the street test passes, or the name matched the entity's own name or alias with at least 2 core words and the same-place test passes |
| Probable match - review | name ≥ 92, or name ≥ 82 with the same-place test |
| Weak match - review | everything else |

## 7. Phone

Phone is reported beside the verdict and tier and never changes them
(decision #14).

- `norm_phones()` keeps 10-digit North American numbers. A leading 1 is
  dropped, extensions are ignored, and a cell can hold several numbers.
- A number held by 5 or more Definitive records is treated as shared: a
  switchboard or a scheduling line.
- `Phone_Match` is True if a non-shared number agrees, and False if both sides
  have non-shared numbers and none agree. It is blank otherwise, including when
  the only overlap is a shared number.

## 8. Known limitations

These are deliberate or not yet addressed. Each would change scores, so fixing
one means re-measuring against a replayed run (see the change log for how).

1. **Unit text stays in the street body.** `100 Main St Ste 200` against
   `100 Main St` loses street-body score, because `fuzz.ratio` counts the
   extra characters.
2. **`post office` → `po` never applies.** The lookup goes one word at a time,
   so a two-word key cannot match. The box number is still extracted, so the
   street number scores correctly.
3. **Missing street types:** expressway, freeway, plaza, route/rte, pike,
   turnpike, crossing, center/ctr, and ordinals after tenth.
4. **Numeric ordinals.** `First` → `1st` works, but a bare `1` against `1st`
   does not.
5. **Street numbers are all or nothing.** A range (`100-110`) or a transposed
   number (`1234` / `1243`) scores 0.
6. **No acronym, abbreviation or phonetic handling in names.** `UPMC` against
   `University of Pittsburgh Medical Center` does not match, and `Mt` / `Mount`
   and `Hosp` / `Hospital` are not equated in names.
7. **Unknown state names** fall back to their first two letters. That is harmless
   for US data, but could make a false state match.
8. **The selection rule and the reported score can disagree.** The best address
   pair is chosen on street number + street body, but `Address_Score` weights
   them 0.30 / 0.22. See "Known data quirks" in CLAUDE.md.
9. **A street line with no number can still win on body alone.** Its number
   is blank rather than 0, so `Address_Score` drops the number's 0.30 weight.
   Unit-only lines are now excluded (section 4), but a named-building line such
   as `Fl 2 Tuttleman Bldg`, or a line like `Medical Ofc Bldg`, still competes
   this way. These lines are rare: 2,543 occurrences across every source.
10. **`POB 123` is not read as a PO box.** Only `PO Box` / `P.O. Box` is, so
    the box number is not extracted (80 occurrences).

## 9. Change log

Measure every change by replaying a past run's Zeus extract and Definitive
snapshots, before and after, so that only the code differs:

```
py dhc_match_v2.py run --config sources.yaml --zeus <run>/<run>_zeus_extract.csv \
    --definitive-from <run> --label <name>
py dhc_gap_match.py --config sources.yaml --zeus <gap run>/<gap run>_zeus_extract.csv \
    --definitive-from <run> --claimed <run>/<run>_scored.csv --label <name>
```

### 2026-10-05: city abbreviations, `saint` in addresses, split directions

- Added `norm_city()` and `CITY_ABBREV`, used for every city on both sides.
  Before this, cities were only cleaned: `St Louis` / `Saint Louis` scored 84
  and `Ft Worth` / `Fort Worth` 89, both below the coverage tier's
  `city >= 90` same-place test.
- Added `saint → st` to `ADDR_ABBREV`.
- `norm_addr()` now merges split directions (`n w` → `nw`), so `N.W.` equals
  `NW` and `Northwest`.

Measured by replaying `dhc_match_v2_2026_09_30_0746` and
`dhc_gap_match_2026_09_30_0747`, before and after the change. Replaying with
the unchanged code reproduced the accuracy run exactly, and the coverage run
with one score differing and no tier change, so every difference below comes
from the change itself.

**Accuracy (12,803 entities, 11,098 testable).** No verdict moved.
`Address_Divergent` (576), `Geo_Conflict` (27) and `Correction_Recommended` (34)
are unchanged. 64 address scores moved, 47 up and 17 down:

- Street body: 30 changed, 27 up. Mostly `Saint Mary Pl` / `St Mary Pl`, which
  rose from 97.1 to 100.
- City: 34 changed, 19 up. All are real variants that now score 100:
  `Sault Sainte Marie` / `Sault Ste. Marie`, `Fort Pierce` / `Ft. Pierce`,
  `St Croix` / `Saint Croix`.
- The 15 city scores that fell are all pairs of genuinely different cities,
  such as `Fort Eustis` / `Newport News` (52 → 38). They fall because a shorter
  string leaves less incidental overlap.

**Coverage (48,857 entities).**

| Tier | Before | After |
|---|---|---|
| Strong match | 9,682 | 9,682 |
| Probable match | 6,507 | 6,506 |
| Ambiguous | 8,492 | 8,499 |
| Weak match | 7,555 | 7,550 |
| No credible match | 16,557 | 16,556 |

110 entities changed tier, and 77 proposed ids changed. One row entered the
Strong tier and one left it, both with the same proposed id: in each case a
rival record's score crossed the 3-point margin. The other moves are almost all
between Ambiguous and Weak or Probable, the same margin effect on near-ties.

**Tried and reverted:** abbreviating compass words in city names (see section
5). It moved 206 entities, added 7 to the Strong tier, and promoted rows such as
`Des Moines Eye Surgeons` (Des Moines against West Des Moines) to Strong on a
neighbouring city.

**A side effect to know about:** merging split directions also merges a
direction followed by a street *named* for a direction. `S East Ave` (South
East Avenue) and `SE Ave` now normalise alike. That only matters when one side
writes the other form, and it moved no tier in the replay.

### 2026-10-05: unit-only lines excluded from street comparison

Added `is_unit_only()`; `addr_scores()` now skips such lines on both sides
(section 4). Before this, a line like `Ste A` had no street number, so it
competed as a street with its number blank. It won selection whenever its body
beat the real street line's number plus body. `Address_Score` then dropped the
number's 0.30 weight instead of scoring it 0. For example, Zeus
`1800 Saint Julian Place` against Definitive `Ste A` scored 83.4.

The first version of the rule tested only the first word and threw away
`Building 9040 Fitzsimmons Dr`, a building number followed by a street. The
whole-line rule above replaced it before anything was measured.

Measured by replaying the same 2026-09-30 runs against the code before this
change (the city-abbreviation code above):

**Accuracy.** 181 address scores fell, by 21 points on average, and none rose.
Every one was a row where a unit-only line had won: 81 of them had reached
`Address_Score` ≥ 60, and 27 had reached ≥ 85 with no street agreeing. Three
verdicts moved from `ID corroborated` to `Probable - name agrees, address
differs`, each a real street mismatch now visible, such as Zeus `PO Box 1449`
against `101 Harris Rd` for Rappahannock General Hospital. `Address_Divergent`
rose from 576 to 639. `Geo_Conflict` and `Correction_Recommended` are unchanged.

**Coverage.** Unit-only lines had decided the best candidate for 14,003 of
48,857 entities, because the location view's second address column is mostly
suite numbers.

| Tier | Before | After |
|---|---|---|
| Strong match | 9,682 | 9,705 |
| Probable match | 6,506 | 6,595 |
| Ambiguous | 8,499 | 9,412 |
| Weak match | 7,550 | 6,606 |
| No credible match | 16,556 | 16,475 |

- **159 rows left Strong.** 45 had passed the street test (address ≥ 85) only
  through a suite line. For example, `Glenbeigh Hospital-Cleveland` scored 95.5
  against `Ste 210` and now scores 60.3. Most of the rest now have a rival
  within 3 points and are `Ambiguous`.
- **182 rows entered Strong.** 117 of them had been `Ambiguous` or below
  because a rival's score was inflated by a suite line. Billings Clinic,
  Advocate Medical Group and Frederick Pediatric Associates (address 100) are
  examples.
- **6,141 proposed ids changed**, almost all in the review tiers: 3,103
  Ambiguous, 1,339 Weak, 895 No credible match, 673 Probable. Only 131 are in
  Strong, and only 9 of those were Strong both before and after.
- **Ambiguous grew by 913.** Suite-line scores had been separating rival
  candidates on noise. Without that noise, more rivals sit within 3 points of
  each other, which is the honest reading.

The strong tier's `Matched_Via` stays mostly `Name` (7,898 of 9,705), and
7,627 of its rows have street-level agreement (address ≥ 85).
