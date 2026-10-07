# Hierarchy logic

How `zeus_hierarchy.py` builds one Zeus **Health System > Client > Work
Location** tree from Definitive ownership and Zeus links: how each entity is
typed, where its Definitive id comes from, how a parent is chosen, and what
every `Zeus_Link_Status` means. Written 2026-10-07 for anyone maintaining the
tool or reviewing its output; the counterpart of
[Matching_Logic.md](Matching_Logic.md). **Update it whenever a rule changes**,
and record the change and its measured effect in the change log at the end.

Contents:

1. What it builds
2. Inputs
3. Entities, types and the universe
4. The Definitive id of an entity
5. The Definitive parent
6. Deciding: `Zeus_Link_Status`
7. Choosing among several Zeus links
8. Links set aside, loops, duplicates
9. Top health system and path
10. Measured results
11. Known limitations and open questions
12. Change log

## 1. What it builds

**Purpose: a read-only comparison baseline.** The migration team derives the
hierarchy that will be used; this one exists so theirs can be validated
against an independent build. Nothing is written back to Zeus or any other
source, and the Excel workbook is the deliverable.

A strict tree: every entity has **one parent or none**, and **one type** -
HealthSystem, Client or WorkLocation. Alternatives are listed on their own
sheets, never kept as extra parents. A parent is always of a higher type, or a
health system under a health system, to any depth (a division under its
system, a VISN under the VA):

| Child | Parent may be | Zeus source | Definitive source |
|---|---|---|---|
| Work location | Client or health system | `dbo.LinkClientWorkLocation` | the work location's owner chain |
| Client | Health system | `dbo.LinkHealthSystemClient` | the client's owner chain |
| Health system | Health system | either link table, where the child is typed HealthSystem (`HealthSystemInfoParentId` is filled on 3 rows) | the health system's owner chain |

The governing rules, decided by Grant on 2026-10-07:

- **A known Definitive ownership or parent relationship beats Zeus, except
  where Definitive completely contradicts Zeus**; those are held and listed.
- **Hospital owners take priority over staffing firms**: a staffing firm or
  physician practice is not the owner of the work locations it staffs.
- **One type per entity; where Zeus gives several, the highest level wins.**
- A client with no health system is expected. Health systems may nest to any
  depth.

## 2. Inputs

| Input | Where from | What it gives |
|---|---|---|
| Accuracy run | `--accuracy <run>_scored.csv`, plus its `_unverifiable.csv` | Every in-scope entity that carries a Definitive id, with a verdict on it |
| Coverage run | `--coverage <run>_gap_candidates.csv`, plus its `_gap_nomatch.csv` | Every in-scope entity that carries none, with a proposed id and tier |
| Definitive hierarchy | `--definitive-hierarchy <dhc_hierarchy run>`, or live | Every hospital, health system and physician group with its owner chain (`dhc_hierarchy.py`) |
| Zeus links | `Zeus hierarchy links.sql`, or `--zeus-links <run>` | Every active work location -> client and client -> health system link, with bookings and link history |
| Import-created entities | `Zeus linked import entities.sql` | Definitive-import-created entities on either end of a link, with the id they were created from; plus every import-created health system |
| Duplicates | `Zeus entity duplicates.sql` | `Entity.DuplicateOfId` for every active entity |

The four audit files partition the in-scope universe (61,682 entities on
2026-10-07); the tool checks that no entity appears in two of them. All three
Zeus inputs and both Definitive snapshots are written into the run folder and
read back from there, so a live run and its replay see identical data.

## 3. Entities, types and the universe

Each node is a Zeus **entity** with one `Entity_Type`: the **highest** of its
Zeus roles, HealthSystem over Client over WorkLocation (Grant, 2026-10-07). A
hospital Zeus flags as both client and work location is a Client; one flagged
as a client and a health system is a HealthSystem. `Zeus_Roles` shows every
flag behind the type. 13,976 entities had more than one role on 2026-10-07,
almost all Client + WorkLocation.

The universe (decision 4, 2026-10-07):

1. Every in-scope entity holding a HealthSystem, Client or WorkLocation role
   (`Zeus_Sources` in the audit files).
2. A Definitive-import-created entity is added where a usable Zeus link joins
   it to an entity from step 1, in either direction.
3. Then every entity's Zeus parents are added, repeatedly, until nothing
   changes, so each has its complete parent chain.

Import-created entities that no link reaches are not in the tree, even when
Definitive would make one a parent. `Definitive_Parents_Not_In_Zeus` says when
such a record exists (section 11).

## 4. The Definitive id of an entity

`Resolution_Basis` records which rule gave each entity its id. Only the first
five are used by the Definitive pass (decision 3, 2026-10-07):

| Basis | Source | Rule |
|---|---|---|
| `Supplied-corroborated` | accuracy | `Verdict = ID corroborated`, no `Geo_Conflict` |
| `Supplied-probable` | accuracy | `Verdict` starts `Probable`, no `Geo_Conflict` |
| `Correction` | accuracy | `Correction_Recommended`: the suggested id replaces the supplied one |
| `Proposed-strong` | coverage | `Match_Tier = Strong match - ready to load` |
| `Import-created` | Zeus | The id the import created the entity from |
| `Review` | either | Any other verdict or tier: no id here |
| `Unverifiable`, `No match`, `Import-created (no id)` | either | No id |

`Relation` is `LocationOf` where the audit matched the entity to a **service
location** of the id (`Matched_Via = Location`): the id is then its owner's,
not its own. Otherwise `Is`. Only an `Is` entity can stand for a Definitive
record as somebody's parent: a location of a record is not that record.

## 5. The Definitive parent

For an entity with a Definitive id, walk up its Definitive ownership chain:

- **distance 0**: its own record (absent for a `LocationOf` entity);
- **distance 1**: its direct owner (for `LocationOf`, the id itself);
- **distance 2, 3, ...**: the owners above, to the top of the tree.

At each step, look for a **Zeus entity of a type allowed as this entity's
parent** (section 1) whose id is that record (`Relation = Is`). The nearest
found at distance 0 is the **same-record** candidate; the nearest at distance
1 or more is the **owner** candidate. A health system's parent must be above
it, so distance 0 is skipped for a health system, and nothing is its own
parent.

When several Zeus entities stand for one record, pick in this order: the one
Zeus already links to this child; the nearer type (a work location's Client
before a HealthSystem); in scope over import-created; the stronger resolution
basis; the lowest EntityId. The others are listed in `Shared_Id_Alternates`
(sheet `Shared_Definitive_Id`). Records climbed past without a Zeus entity are
listed in `Skipped_Definitive_*`.

**A same-record candidate is identity, not ownership.** Two Zeus entities on
one Definitive record are the same organisation, which says nothing about who
contracts for work there. So a same-record candidate may **confirm** a Zeus
link (`Agrees`) or **fill** a gap (`Definitive fills`), but only an **owner**
candidate may replace or contradict a Zeus link. See the change log for why.

## 6. Deciding: `Zeus_Link_Status`

| Status | When | The parent used |
|---|---|---|
| `Agrees` | The same-record or owner candidate is one of the entity's Zeus links | That link |
| `Definitive fills` | Zeus has no link; there is a candidate (nearest first) | The candidate |
| `Definitive replaces` | Zeus has links, none agrees, there is an owner candidate, and either at least one Zeus parent is in the **same Definitive tree** as the owner or has **no trusted Definitive id**, or the entity is a **work location whose owner is a hospital or health system while every Zeus parent is a physician group or staffing firm** | The owner. Every overridden link is on `Zeus_Links_Replaced` with `Why_Replaced` |
| `Contradiction` | Every Zeus parent has a trusted id in a **different Definitive tree** from the owner's, and it is not the staffing-firm case above | **The Zeus link (held).** The owner is in `Held_Definitive_Parent_*`; both sides are on `Contradictions` |
| `Zeus only` | No candidate that may decide | The Zeus link (section 7). A same-record candidate that differs is in `Same_Record_Alternative` |
| `No parent` | No candidate and no Zeus link, or a loop was broken here (section 8) | None. **Expected for a client** (confirmed by Grant, 2026-10-07): many clients belong to no health system. An orphan only for a work location |

**Same Definitive tree** means the same ultimate owner (`Definitive_Ultimate_Id`):
the root of the record's chain in the Definitive hierarchy. A record with no
owner is its own tree. A Zeus parent that is a `LocationOf` its id belongs to
that id's tree.

**Owners over staffing firms.** A "hospital or health system" here is a
Definitive record with `TypeFirm` Hospital or Health System; anything else -
a physician group, an MSO, an IPA, a practice-location parent - is a non-owner.
A work location's Zeus client that is a non-owner cannot contradict a
Definitive hospital or health system owner, so that case is `Definitive
replaces` with `Why_Replaced = Zeus parent is a physician group or staffing
firm, not an owner`. A contradiction stays held where Zeus names a different
hospital or health system (often a merger or sale Zeus has not caught up
with: Mountain States Health Alliance for what Definitive calls Ballad
Health), where both sides are physician groups, and at the client and health
system levels.

For review, each row of `Contradictions` also names the top health system
each side reaches in this tree (`Zeus_Parent_Top_HealthSystem`,
`Definitive_Parent_Top_HealthSystem`). `Same_Top_HealthSystem` is True where
they meet - Zeus names a predecessor or division that itself sits under
Definitive's owner - and those can be cleared quickly; on 2026-10-07 that was
10 of the 373 held entities.

`Edge_Source` is `Definitive` for the first three statuses and `Zeus` for
`Contradiction` and `Zeus only`. Both ends' `Resolution_Basis` are on every
edge, so an edge resting on a coverage proposal can be told from one resting
on two corroborated ids.

## 7. Choosing among several Zeus links

When Zeus links an entity to several parents and Definitive does not decide
(or the entity is a held contradiction), the first of these that separates
them wins; `Zeus_Choice_Reason` names it:

1. a parent in the child's own Definitive tree;
2. the most recent booking for that client at that work location (actual
   bookings: `Booking.IsBooking = 1`, status Booked, Working or Filled);
3. the most such bookings;
4. an open link history row (`LinkClientWorkLocationHistory.EndDate` empty);
5. the latest link history start;
6. in scope over import-created;
7. the lowest EntityId.

Steps 2 to 5 exist only for work location -> client links. Sheet
`Multi_Parent_Choices` lists every entity with more than one Zeus link.

Confirmed by Grant, 2026-10-07: the most recent booking is the right
tie-break, **but only when no Definitive link is present**. That is how the
tool works: where Definitive gives a parent (`Agrees`, `Definitive fills`,
`Definitive replaces`), bookings are never consulted. The one place the
tie-break runs alongside a Definitive parent is a held `Contradiction`, where
it only chooses which Zeus link to keep while the case awaits review.

## 8. Links set aside, loops, duplicates

**Links single typing cannot hold.** A Zeus link is used only if its parent's
type may hold its child's type (section 1). Two kinds fall out:

- **An entity linked to itself** - Zeus links ~14,000 hospitals to themselves
  as their own client. Typed Client, the hospital is one entity; there is
  nothing to link. Counted on the Summary.
- **Same type or upside down** - a link putting a Client under a Client, or
  a HealthSystem under a Client. Almost all are a hospital (now a Client)
  whose work-location role Zeus linked to a staffing firm or physician group:
  TEAMHealth, Trio, HealthTrust Workforce Solutions, Radiology Partners, SCP
  Health. Listed on `Zeus_Links_Dropped` (`_zeus_links_dropped.csv`).

**Health system loops.** Only health systems can loop - every other edge
climbs a type - and Definitive's own edges cannot, since each climbs its
ownership tree. A loop is therefore always closed by a Zeus link: two Zeus
records of one organisation linked to each other (Baystate Health and Baystate
Health), or a Zeus link running against a Definitive edge (McLeod Regional
Medical Center -> McLeod Health). In each loop the Zeus edge out of the member
with the most entities beneath it is cut (ties: in scope first, then the lower
EntityId), so Definitive's edge survives and the bigger record becomes the top
with its twin beneath it. The cut entity has no parent and `Tree_Issue` says
why (sheet `Loops_Broken`).

**Duplicates.** An entity marked `DuplicateOfId` another (followed to the end
of the chain) is replaced by its survivor wherever the survivor has the same
type: in every link, and as a Definitive parent. The duplicate is dropped.
Links that become the same pair are merged, adding their bookings. A duplicate
whose survivor is archived, outside the universe or of another type is left as
it is. Sheet `Duplicates_Remapped` lists every merge.

## 9. Top health system and path

`Top_HealthSystem_*` is the highest health system reached by walking the
chosen parents up from the entity; `Path_Names` shows the chain, top first,
each name tagged `[HS]`, `[Client]` or `[WL]`. An entity with no health system
above it has no top health system. `Definitive_Ultimate_*` is separate: the top
of the entity's own Definitive chain, whether or not Zeus has an entity for it.

## 10. Measured results

2026-10-07, replaying the inputs of the first full live run
(`zeus_hierarchy_2026_10_07_0858`, built on `dhc_match_v2_2026_10_07_0834`,
`dhc_gap_match_2026_10_07_0835` and `dhc_hierarchy_2026_10_07_0856`) with
single typing and the staffing-firm rule (`zeus_hierarchy_2026_10_07_1103_singletype`):

- 61,682 in-scope entities across the four audit files, no overlap.
- 72,201 entities in the tree: 27,715 work locations, 42,718 clients, 1,768
  health systems; 11,688 of them import-created; 13,976 typed by the highest
  of several Zeus roles.
- 52,637 usable Zeus links. Set aside: 14,189 self-links, 11,573 same-type or
  upside-down links (11,172 a Client under a Client, 401 a HealthSystem under
  a Client). 3,129 duplicates merged into their survivor; 8 health system
  loops broken.

| Level | Agrees | Fills | Replaces | Contradiction | Zeus only | No parent |
|---|---|---|---|---|---|---|
| Work location -> client or health system | 2,844 | 51 | 2,228 | 110 | 22,247 | 235 |
| Client -> health system | 5,675 | 624 | 1,312 | 260 | 8,021 | 26,826 |
| Health system -> health system | 58 | 365 | 47 | 3 | 105 | 1,190 |

- Work locations hang under a client (22,784) or directly under a health
  system (4,696). 10,112 of the 27,715 (36%) reach a health system at the top.
- 15,892 of the 42,718 clients have a health system; the rest have none,
  which is expected.
- Of 32,360 resolved ids, 24,909 are in the Definitive hierarchy. The rest
  are practice-location parents, GPOs, or ids in no current view, including
  import-created physician-group ids. Each is treated as its own root.
- 2,132 entities sit under 1,035 Definitive health systems or corporate
  owners that no Zeus entity of a usable type stands for
  (`Definitive_Parents_Not_In_Zeus`; 91 of those have an unlinked
  import-created Zeus record).

## 11. Known limitations and open questions

- **Ownership wins over contracting (decided 2026-10-07).** At the work
  location level, `Definitive replaces` puts the hospital's owning system in
  place of the client Zeus records. 1,628 of the 3,202 replaced links name a
  Zeus client with no trusted Definitive id, most often a staffing firm:
  TEAMHealth (108), Trio (91), HealthTrust Workforce Solutions (75), SCP
  Health (43). Another 200 work locations are replaced under the
  staffing-firm rule. Grant's ruling: hospital owners take priority.
- **A practice location of a physician group is not always owned by it.**
  Definitive's practice-location view lists where a group's physicians
  practise, including hospitals the group does not own. A work location
  matched to such a location (`Relation = LocationOf`) gets the group as its
  owner. 436 replaced work locations are `LocationOf`.
- **Health systems are under-resolved.** Only 1,130 in-scope Zeus health
  systems exist, and some large Definitive systems (UNC Health, Baptist Health
  - AR, Piedmont Healthcare) have no Zeus health system with their id, so
  their clients climb past them or get no parent.
- **Import-created health systems outside the universe.** Most Zeus health
  systems are import-created (2,273 of 3,403 active). An unlinked one is not
  in the tree (decision 4), even where it is exactly the record Definitive
  names; `Unlinked_Import_Zeus_Record` on `Definitive_Parents_Not_In_Zeus`
  lists them. Adding them would widen decision 4.
- **Zeus duplicates of health systems.** Six of the eight loops were two Zeus
  records with the same name (Baystate Health, WellStar, BayCare, Emory St
  Joseph's, Strategic Behavioral Health, UnityPoint) that `DuplicateOfId`
  does not mark. The tree keeps both, one under the other.
- **The audits and the hierarchy can be a day apart.** The hierarchy views are
  snapshotted when `dhc_hierarchy.py` runs, the identity views when the
  accuracy run does; `run_all.py` runs them minutes apart. A resolved id
  missing from the hierarchy is treated as its own root.

## 12. Change log

### 2026-10-07: created

First build, against the 2026-10-05 audits. A node was an entity in one role,
(EntityId, role), so an entity Zeus flags in two roles appeared twice.

### 2026-10-07: a same-record match may confirm or fill, never override

The first run let any Definitive candidate replace or contradict a Zeus link,
including one at distance 0 - a Zeus client on the work location's own
Definitive record, usually the hospital itself. That replaced 1,936 Zeus
clients with the hospital: Taylor Regional Hospital lost SCP Health, Sunrise
Hospital lost HealthTrust Workforce Solutions, and Mount Carmel East was a
contradiction against Sound Inpatient Physicians. Sharing a Definitive record
is identity, not the ownership or parent relationship the rule is about, so a
same-record candidate now only confirms or fills; the search continues up the
chain for an owner, which alone may replace or contradict.

Measured on identical inputs (replay of the 2026-10-05 audits):

| Work location -> client | Before | After |
|---|---|---|
| Agrees | 10,767 | 11,142 |
| Definitive fills | 54 | 54 |
| Definitive replaces | 2,509 | 1,336 |
| Contradiction | 408 | 240 |
| Zeus only | 26,765 | 27,731 |

Client -> health system moved little (replaces 1,361 -> 1,322, contradictions
274 -> 272).

### 2026-10-07: one type per entity; owners over staffing firms; loops

Three changes, decided by Grant the same day and measured together on the
first full run's inputs (`zeus_hierarchy_2026_10_07_0858` replayed as
`zeus_hierarchy_2026_10_07_1103_singletype`):

- **One type per entity, the highest level wins.** The migration team's
  hierarchy gives each entity one type, so a node is now the entity, not
  (entity, role). A work location may hang under a client or a health system,
  and a health system under a health system. 89,024 role-nodes became 72,201
  entities; 14,189 self-links and 11,573 same-type links no longer fit and
  are set aside.
- **Owners over staffing firms.** Of the 238 held work-location
  contradictions, 176 had only physician groups or staffing firms as Zeus
  clients, and 143 of those had a hospital or health system as Definitive's
  owner. Those now replace instead of being held: work-location
  contradictions fell to 110.
- **Loops.** Single typing lets Zeus client links between two health systems
  become health system edges, and 8 pairs pointed at each other (16 entities,
  383 counting everything beneath them). Each loop is now broken (section 8);
  the cycle check failed until it was.

| Work location level | Role-nodes (before) | Entities (after) |
|---|---|---|
| Nodes | 40,749 | 27,715 |
| Agrees | 11,138 | 2,844 |
| Definitive fills | 53 | 51 |
| Definitive replaces | 1,338 | 2,228 |
| Contradiction | 238 | 110 |
| Zeus only | 27,745 | 22,247 |
| No parent | 237 | 235 |

`Agrees` fell because most agreements were a hospital's self-link, which
single typing removes; `Definitive replaces` rose with the staffing-firm rule
and because an owner typed HealthSystem may now be a work location's parent.
