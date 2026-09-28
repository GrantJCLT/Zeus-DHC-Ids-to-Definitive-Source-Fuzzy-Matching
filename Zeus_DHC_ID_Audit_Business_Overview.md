# Zeus ↔ Definitive Healthcare ID Audit: What It Is and Why It Matters

28 September 2026 · Grant Lovern

## In brief

This project checks how well Zeus, our CRM, is linked to Definitive Healthcare, our third-party source of facility and physician-group data. It answers two questions: are the Definitive IDs we already hold correct, and which Zeus records have no Definitive ID but should?

The existing links are in good shape: of the IDs that can be checked, **96.8% point at the right Definitive record**. The bigger problem is gaps: **79% of Zeus entities (48,739 of 61,542) carry no Definitive ID at all**. The tool has found a high-confidence match for 9,702 of them, which alone would lift linked coverage from **20.8% to 36.6%**.

## Why this matters

A Definitive ID is what lets us join a Zeus client, work location or health system to Definitive's data: bed counts, affiliations, parent systems, locations and contacts. A wrong ID quietly attaches the wrong facility's data to a client. A missing ID means that client is invisible to any analysis or reporting that relies on Definitive.

There is no master key that says which Zeus record is which Definitive record. So the only way to check is to compare what each side says about the entity, its **name and address**, and judge how well they agree. The output is therefore a confidence judgement per record, not a simple yes or no.

## The two questions

The project splits every Zeus entity into exactly one of two groups, so the counts always add up to the whole: **61,542 Zeus entities** across clients, work locations, health systems, GPOs, agencies and VMS.

| | Carry a Definitive ID | Carry no Definitive ID |
| --- | --- | --- |
| Entities | 12,803 (20.8%) | 48,739 (79.2%) |
| Question | Is the ID we hold pointing at the right record? | Which Definitive record should it point at? |
| Audit | Accuracy audit | Coverage audit |
| Answer | A verdict per entity, from Confirmed to Likely wrong | A proposed ID per entity, graded Strong to No match |

The coverage gap is about four times larger than the accuracy question, and was invisible until August 2026 because earlier reporting only looked at records that already had an ID. An entity that appears in several Zeus lists (for example, both a client and a work location) is counted once.

## How it works, in plain terms

The tool reads Zeus live (read-only, so it cannot change anything) and compares it with four Definitive exports: hospitals, physician groups, GPOs and about 400,000 service locations.

1. **Gather everything Zeus knows about each entity.** Every name and address it holds across its client, work-location and other records.
2. **Tidy both sides so they compare fairly.** For example, Zeus says "California" where Definitive says "CA", and many hospitals have been renamed, so former names such as "(FKA …)" count too.
3. **Score name and address separately.** Similarity scores from 0 to 100, allowing for typos, word order and suffixes like "LLC".
4. **Check against satellite locations, not just headquarters.** Definitive lists a system's HQ; Zeus often records the site we actually work with. Matching against every known location removed about 30% of false address mismatches.
5. **Give a judgement.**
   - For an existing ID: a **verdict**, such as "ID corroborated" or "Likely wrong identifier".
   - For a missing ID: a **proposed Definitive record** with a **tier** from Strong to No credible match, plus two runner-up alternatives.

The bar is deliberately higher for proposing a new ID than for confirming an existing one. Confirming only needs the name to agree. Proposing needs two independent agreements, such as name and street address, and is marked **Ambiguous** if another Definitive record fits nearly as well.

## What we found: accuracy of existing IDs

The IDs Zeus already holds are overwhelmingly right: 83.9% of all 12,803 are confirmed, and only 19 look wrong. Results are from the run on 12 August 2026.

| Of 12,803 Zeus entities carrying a Definitive ID | Entities | Share |
| --- | --- | --- |
| Confirmed — points at the right record | 10,740 | 83.9% |
| Probably right | 224 | 1.7% |
| Needs review | 116 | 0.9% |
| Likely wrong identifier | 19 | 0.1% |
| Cannot be tested — ID not in any Definitive export we hold | 1,704 | 13.3% |

Of the 11,099 that can be tested, **96.8% are confirmed** and 98.8% are confirmed or probably right. Hospitals confirm at 97.8% and physician groups at 93.5%.

"Cannot be tested" does not mean wrong. It means the ID refers to a record outside the Definitive data we license, so there is nothing to compare against. Two other flags are worth knowing:

- **Address divergent (579):** the name matches but our address matches none of the entity's known locations. Usually our address is out of date, not the ID.
- **Geo conflict (27):** a strong name match, but the entity has no known location in the state Zeus records. These are the most likely to be a wrong ID.

## What we found: coverage of missing IDs

One in five unlinked entities has a strong, ready-to-load match; a third have no credible match in Definitive at all. Results are from the run on 19 August 2026.

| Of 48,739 Zeus entities with no Definitive ID | Entities | Share |
| --- | --- | --- |
| Strong match — proposal ready to load | 9,702 | 19.9% |
| Probable match — needs review | 6,525 | 13.4% |
| Ambiguous — several records fit equally | 8,406 | 17.2% |
| Weak match — needs review | 7,481 | 15.3% |
| No credible match in Definitive | 16,561 | 34.0% |
| No usable name in Zeus | 64 | 0.1% |

The strong tier is genuinely strong: 80% of it agrees down to the street address, not just the city. Loading it would take linked coverage from 20.8% to 36.6% of all Zeus entities. The 22,412 probable, ambiguous and weak rows could add more, but each needs a person to decide.

Three patterns in the strong tier need a business view before loading:

- **Chains (2,738 proposals).** Definitive often holds one ID for a chain; Zeus holds each branch. For example, 32 separate "New Season" clinics in 29 cities all match one Definitive parent.
- **Already used elsewhere (1,593 proposals).** The proposed ID is already on another Zeus entity, typically a client and its work location sharing one facility.
- **Closed or merged (186 proposals).** Definitive marks the record closed or merged. It may still be right for a historical client.

The 16,561 with no credible match are the best evidence for any decision about buying more Definitive data.

## What you receive

Each run produces a branded Excel workbook, named with its run date. Each sheet answers one question, and every table can be filtered.

| Workbook | Latest edition | Start with | Then look at |
| --- | --- | --- | --- |
| Accuracy audit | Zeus_DHC_ID_Accuracy_Audit_2026_08_12.xlsx | **Summary**, then **Review_Queue** (records needing a person) | **Geo_Conflict** (likeliest wrong IDs), **Corrections_Recommended** (a better ID the tool suggests), **Address_Divergence** (addresses to update) |
| Coverage audit | Zeus_DHC_ID_Coverage_Audit_2026_08_19.xlsx | **Summary**, then **Ready_To_Load** (strong proposals) | **Parent_Id_Proposals**, **Shared_Id_Proposals**, **Id_Already_Linked_In_Zeus**, **Status_Flagged**, then **No_Credible_Match** |

Every row shows the Zeus name beside the Definitive name it matched, so a reviewer can judge it at a glance. On the coverage side, the two runner-up candidates are shown too, so a reviewer can overrule the pick.

Both workbooks contain client names and addresses. Share them on a need-to-know basis, and keep the matching Zeus snapshot with any copy you circulate: Zeus changes daily, and the snapshot is the only way to reproduce a figure later.

## Reading the results with care

- **Always say which base a percentage uses.** "96.8%" is of the 11,099 testable IDs; "83.9%" is of all 12,803. Both are true; quoting one without its base misleads.
- **A matching name is not proof of the same entity.** Parent companies, subsidiaries and same-named practices in different towns can look alike. The tool flags these for review rather than guessing.
- **Nothing has been hand-checked at scale yet.** The confidence tiers are well-founded but not yet measured against a labelled sample. No proposed ID should be loaded into Zeus until one is.
- **Records created by Definitive imports are excluded.** About 198,000 Zeus records were created by a Definitive import, so their IDs would trivially agree. Leaving them out means the results measure IDs a person or process actually chose. It also means these figures cannot be compared with older reports that included them.
- **Figures are a snapshot.** Zeus is live, so a later run will give slightly different counts.

## Decisions needed and next steps

The fastest win is to validate and load the 9,702 strong proposals; three decisions come first.

| Question for the business | Why it matters | Recommendation |
| --- | --- | --- |
| Should each branch of a chain point at the chain's one Definitive ID? | Affects 2,738 strong proposals and how chains appear in reporting | Decide explicitly; the data supports it, but it should not happen by default |
| May two Zeus entities share one Definitive ID? | Affects 1,593 strong proposals, mostly a client and its work location | Usually yes; confirm the rule |
| Should closed or merged Definitive records be linked? | Affects 186 strong proposals | Link where the Zeus record is historical; otherwise review |

Recommended next steps, in order:

- [ ] Hand-check about 100 strong coverage proposals to put a measured accuracy on the tier before loading.
- [ ] Review the 27 geo conflicts and 19 likely-wrong IDs from the accuracy audit.
- [ ] Agree who reviews the 22,412 probable, ambiguous and weak proposals, and how.
- [ ] Use the 16,561 unmatched entities to size any further Definitive data purchase.
- [ ] Explore NPI numbers as an exact second key; they would settle many ambiguous cases.
- [ ] Move the tool from a local script to a scheduled Databricks job feeding Power BI, so results refresh automatically.

## Glossary

| Term | Meaning |
| --- | --- |
| Zeus | Jackson and Coker's internal CRM |
| Definitive Healthcare (DHC) | Licensed third-party database of hospitals, physician groups, GPOs and their locations |
| Definitive ID | Definitive's unique number for one of its records; the link between the two systems |
| Entity | One Zeus organisation record, counted once even if it is both a client and a work location |
| Testable | An existing ID that appears in the Definitive data we hold, so it can be checked |
| Corroborated / Confirmed | Name, and usually address, agree with the record the ID points at |
| Service location | A satellite site Definitive lists under a parent organisation |
| Strong / Probable / Ambiguous / Weak | Confidence tiers for a proposed ID, from ready to load down to needs careful review |
| Geo conflict | Name matches, but the entity has no known location in the state Zeus records |
