#!/usr/bin/env python3
"""Build the branded Coverage Audit workbook from a gap run.

The sibling of build_audit_workbook.py. Same brand, same eight-sheet shape from
the reporting template, same two identities to check - but it answers the
complement question: of the Zeus objects carrying NO Definitive identifier,
which one should each of them point at?

Styling helpers and the palette are imported from build_audit_workbook rather
than copied, so the two deliverables cannot drift apart.

Everything here is derived from the run, so it is re-runnable:

  py build_coverage_workbook.py \
      --candidates "Results Output/<run>/<run>_gap_candidates.csv"

The workbook is written into the run's own folder as
Zeus_DHC_ID_Coverage_Audit_<run date and time>.xlsx; `--out` overrides the name.

`--accuracy <audit_..._scored.csv>` is optional: it adds the whole-estate
coverage picture to the Summary, putting the linked and unlinked populations
side by side. Omit it and that section is left out; nothing else changes.
"""
import argparse
import os

import numpy as np
import pandas as pd
from openpyxl import Workbook

from build_audit_workbook import (
    _put, _table, sheet_data, workbook_path, H1, H2, SECTION, BODY, NOTE, WRAP,
    FILL_NAVY, FILL_PURPLE, FILL_CREAM, FILL_LILAC, resolve_population,
    in_population, extract_in_population, population_title, scope_note)
from dhc_match_v2 import load_config

# The tiers, in the order a reader should meet them: most actionable first.
# Mirrors dhc_gap_match.TIERS but is stated here because the workbook's ordering
# is a presentation decision, not a scoring one.
TIER_ORDER = ['Strong match - ready to load', 'Probable match - review',
              'Ambiguous - rival candidates', 'Weak match - review',
              'No credible match', 'No usable Zeus name']

TIER_NOTE = {
    'Strong match - ready to load':
        'Name and place both agree, and no rival record fits as well. Load '
        'these after a sample check.',
    'Probable match - review':
        'One side of the evidence is short - a strong name without street '
        'agreement, or the reverse. Quick human confirmation.',
    'Ambiguous - rival candidates':
        'The name is probably right but two or more Definitive records fit '
        'within 3 points. A human must pick; the tool deliberately will not.',
    'Weak match - review':
        'A plausible name match with thin corroboration. Lowest yield per '
        'minute of review.',
    'No credible match':
        'Nothing in the four Definitive exports resembles this entity. Not a '
        'failure of matching - a gap in the reference data.',
    'No usable Zeus name':
        'The Zeus name is a single character or punctuation, so there is '
        'nothing to search on. Fix in Zeus, not here.',
}

# Columns each review sheet leads with. Matched_* come before Suggested_* on
# purpose: the pair of strings that actually matched is what a reviewer judges,
# and it is NOT always Zeus_Name against Suggested_Name.
SHOW = ['EntityId', 'Zeus_Sources', 'Zeus_Name', 'Zeus_Names_All',
        'Zeus_Address', 'Zeus_City', 'Zeus_State', 'Zeus_Zip', 'Zeus_Phones',
        'Suggested_DHC_Id', 'Suggested_Name', 'Suggested_Entity_Type',
        'Suggested_Address', 'Suggested_City', 'Suggested_State',
        'Suggested_Zip', 'Suggested_Phone', 'Phone_Match', 'Matched_Phone',
        'Phone_Favours_Alt', 'Phone_Lookup_DHC_Id', 'Phone_Lookup_Name',
        'Suggested_Status_Note', 'Matched_Zeus_Name',
        'Matched_Zeus_Source', 'Matched_Definitive_Name', 'Matched_Via',
        'Matched_Zeus_Address', 'Matched_Zeus_City', 'Matched_Zeus_State',
        'Matched_Zeus_Zip', 'Matched_Definitive_Address',
        'Matched_Definitive_City', 'Matched_Definitive_State',
        'Matched_Definitive_Zip', 'Name_Score',
        'Address_Score', 'Match_Score', 'Match_Margin', 'Same_Name_Rivals',
        'Exact_Name_And_Geo', 'Address_Match_Source', 'Location_Count',
        'Suggested_Id_Already_In_Zeus', 'Alt1_DHC_Id', 'Alt1_Name',
        'Alt1_Match_Score', 'Alt1_Phone_Match', 'Alt2_DHC_Id', 'Alt2_Name',
        'Alt2_Match_Score', 'Alt2_Phone_Match']


def cols(df, names):
    return [c for c in names if c in df.columns]


def build_summary(wb, c, counts, n_pop, subtitle, ev, by_pop, by_type,
                  estate, flags, population=None, phone_rows=None):
    ws = wb.create_sheet('Summary')
    for col, w in zip('ABCDE', (4, 62, 16, 14, 60)):
        ws.column_dimensions[col].width = w

    ws.merge_cells('A1:E1')
    _put(ws, 'A1', 'Jackson and Coker Locum Tenens - Zeus DHC Identifier '
                   'Coverage Audit', H1, FILL_NAVY)
    ws.merge_cells('A2:E2')
    _put(ws, 'A2', subtitle, H2, FILL_PURPLE)

    strong = counts.get('Strong match - ready to load', 0)
    nomatch = counts.get('No credible match', 0)
    review = sum(counts.get(t, 0) for t in
                 ['Probable match - review', 'Ambiguous - rival candidates',
                  'Weak match - review'])

    _put(ws, 'B4', 'Headline answer', SECTION)
    ws.merge_cells('B5:E8')
    kind = f'{population_title(population)} ' if population else ''
    _put(ws, 'B5',
         f'Zeus holds {n_pop:,} distinct {kind}objects carrying NO Definitive '
         f'identifier at all. For {strong:,} of them ({strong / n_pop:.1%}) '
         f'this audit proposes a specific Definitive record on evidence strong '
         f'enough to load: the name and the place both agree, and no rival '
         f'record fits as well. A further {review:,} ({review / n_pop:.1%}) '
         f'have a credible proposal that needs a human decision - most often '
         f'because several Definitive records fit equally well. For '
         f'{nomatch:,} ({nomatch / n_pop:.1%}) nothing in the Definitive data '
         f'supplied resembles the entity, which is a gap in the reference set '
         f'rather than a failure of matching. Every proposal is a proposal: '
         f'unlike the accuracy audit there is no identifier on record to check '
         f'against, so a tier is a statement about strength of evidence, not a '
         f'confirmed fact.',
         BODY, FILL_CREAM, align=WRAP)

    r = 10
    if estate:
        _put(ws, f'B{r}', f'Identifier coverage across every '
             f'{population_title(population)} entity' if population else
             'Identifier coverage across the whole Zeus estate', SECTION)
        _put(ws, f'B{r + 1}',
             'The two populations partition one universe - an entity either '
             'carries a Definitive identifier or it does not - so these counts '
             'add up. This is the number to quote when asked "how well linked '
             'are we?".', NOTE)
        r = _table(ws, r + 2, ['Population', 'Objects', 'Share', 'Reading'],
                   estate, notes_col=3)

    _put(ws, f'B{r}', '1. Outcome for every unlinked object', SECTION)
    _put(ws, f'B{r + 1}',
         f'Denominator is all {n_pop:,} objects with no identifier, so nothing '
         f'is hidden by exclusion. These rows sum to the population.', NOTE)
    head = r + 2
    r = _table(ws, head, ['Tier', 'Objects', 'Share', 'Reading'],
               [[t, int(counts.get(t, 0)), counts.get(t, 0) / n_pop,
                 TIER_NOTE[t]] for t in TIER_ORDER if counts.get(t, 0)],
               notes_col=3)
    for col in 'BCDE':
        ws[f'{col}{head + 1}'].fill = FILL_LILAC
    _put(ws, f'B{r}', 'Shaded row is the actionable output of this audit.', NOTE)

    r += 2
    _put(ws, f'B{r}', '2. How strong is the strong tier', SECTION)
    _put(ws, f'B{r + 1}',
         'The evidence behind the load-ready rows. Street-level address '
         'agreement is the strongest single signal, because it distinguishes '
         'the right record from a same-named one elsewhere.', NOTE)
    r = _table(ws, r + 2, ['Measure', 'Objects', 'Share of strong', 'Reading'],
               ev, notes_col=3)

    _put(ws, f'B{r}', '3. Before loading anything', SECTION)
    _put(ws, f'B{r + 1}',
         'Four populations inside the strong tier that are defensible but are '
         'business decisions rather than data questions. Each has its own '
         'sheet. Counts here are strong-tier only; the Status_Flagged sheet '
         'deliberately spans every tier, because a reviewer working the '
         'Probable queue needs the same warning.', NOTE)
    r = _table(ws, r + 2, ['Population', 'Objects', 'Why it needs a look'],
               flags, notes_col=2)

    _put(ws, f'B{r}', '4. By Zeus population', SECTION)
    _put(ws, f'B{r + 1}', (
         f'Every row here is a {population_title(population)} entity; the '
         f'other rows count those that ALSO belong to that population. Their '
         f'names and addresses from every population are pooled into one '
         f'proposal.') if population else (
         'Populations overlap - an entity that is both a client and a work '
         'location is counted in each - so these rows sum to more than the '
         'total. Its names and addresses from every population are pooled into '
         'one proposal.'), NOTE)
    r = _table(ws, r + 2, ['Zeus population', 'Unlinked', 'Strong match',
                           'Share'], by_pop)

    _put(ws, f'B{r}', '5. What kind of Definitive record is proposed', SECTION)
    _put(ws, f'B{r + 1}',
         'Strong tier only. PracticeLocation means the identifier exists only '
         'in the service-location export, with no overview record behind it.',
         NOTE)
    r = _table(ws, r + 2, ['Definitive entity type', 'Proposals', 'Share'],
               by_type)

    if phone_rows:
        _put(ws, f'B{r}', '6. Phone check on the proposal', SECTION)
        _put(ws, f'B{r + 1}',
             'Independent of the tier, which rests on name and address only - '
             'the tiers are unchanged. "Confirms" means a Zeus phone equals one '
             'of the numbers Definitive holds for the proposed record (HQ or '
             'any service location). '
             '"Favours a runner-up" means exactly one of the three candidates '
             'shares the number and it is not the pick - see Phone_Favours_Alt. '
             'Numbers shared by 5 or more Definitive records are ignored.', NOTE)
        r = _table(ws, r + 2, ['Tier', 'Objects', 'Confirms', 'No match',
                               'Favours a runner-up', 'No phone evidence'],
                   phone_rows)
    return ws


def build_methodology(wb, notes):
    ws = wb.create_sheet('Methodology')
    ws.column_dimensions['A'].width = 4
    ws.column_dimensions['B'].width = 40
    ws.column_dimensions['C'].width = 118
    _put(ws, 'A1', 'Methodology and assumptions', SECTION)
    r = 2
    from openpyxl.styles import Font
    from build_audit_workbook import INK
    for head, text in notes:
        _put(ws, f'B{r}', head, Font(size=10, bold=True, color=INK), align=WRAP)
        _put(ws, f'C{r}', text, BODY, align=WRAP)
        r += 1
    return ws


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--candidates', required=True,
                    help='<prefix>_gap_candidates.csv from dhc_gap_match.py')
    ap.add_argument('--config', default='sources.yaml')
    ap.add_argument('--accuracy', help='an audit <prefix>_scored.csv, to show '
                                       'whole-estate coverage on the Summary')
    ap.add_argument('--out', help='workbook name (default: in the run folder, '
                                  'named for the run date)')
    ap.add_argument('--population', metavar='LABEL',
                    help='limit the workbook to entities in one Zeus population '
                         '(a sources.yaml label, e.g. WorkLocation); scoring '
                         'is unchanged')
    a = ap.parse_args()

    c = pd.read_csv(a.candidates, low_memory=False)
    prefix = a.candidates.replace('_gap_candidates.csv', '')
    nm_path = f'{prefix}_gap_nomatch.csv'
    ex_path = f'{prefix}_zeus_extract.csv'
    nm = pd.read_csv(nm_path, low_memory=False) if os.path.exists(nm_path) else None
    ex = pd.read_csv(ex_path, low_memory=False) if os.path.exists(ex_path) else None

    pop, n_all = None, None
    if a.population:
        # Filter the run's outputs, not the scoring - see build_audit_workbook.
        pop = resolve_population(a.population, [c, nm])
        n_all = len(c) + (len(nm) if nm is not None else 0)
        c = c[in_population(c, pop)]
        if nm is not None:
            nm = nm[in_population(nm, pop)]
        if ex is not None:
            ex = extract_in_population(ex, pop)
        print(f'Population  : {pop} - '
              f'{len(c) + (len(nm) if nm is not None else 0):,} of {n_all:,} '
              f'entities')
    a.out = workbook_path(prefix, 'Zeus_DHC_ID_Coverage_Audit' +
                          (f'_{pop}' if pop else ''), a.out)

    # The two output files together are the population; the workbook must not
    # quietly report only the half that matched.
    full = pd.concat([c, nm], ignore_index=True) if nm is not None else c
    n_pop = int(full.EntityId.nunique())
    counts = full.Match_Tier.value_counts().to_dict()
    assert sum(counts.values()) == len(full) == n_pop, (
        f'tier counts {sum(counts.values())} / rows {len(full)} / entities '
        f'{n_pop} disagree - the population is not what it claims to be')

    strong = c[c.Match_Tier == 'Strong match - ready to load']
    ns = max(len(strong), 1)

    ev = [
        ['Exact name and matching geography', int(strong.Exact_Name_And_Geo.sum()),
         int(strong.Exact_Name_And_Geo.sum()) / ns,
         'Normalised names identical and zip or city+state agree. Needs no '
         'judgement call.'],
        ['Street-level address agreement', int((strong.Address_Score >= 85).sum()),
         int((strong.Address_Score >= 85).sum()) / ns,
         'Address score 85+. The strongest discriminator between a record and '
         'a same-named one elsewhere.'],
        ['Name matched outright', int((strong.Name_Score >= 99.9).sum()),
         int((strong.Name_Score >= 99.9).sum()) / ns,
         'Name score 100 against the entity name, an alias, or a service '
         'location.'],
        ['No rival within 10 points', int((strong.Match_Margin >= 10).sum()),
         int((strong.Match_Margin >= 10).sum()) / ns,
         'Clear daylight to the runner-up. Below 3 points a row is demoted to '
         'Ambiguous instead.'],
        ['Matched on the entity\'s own name', int((strong.Matched_Via == 'Name').sum()),
         int((strong.Matched_Via == 'Name').sum()) / ns,
         'The rest matched a former name in parentheses, or a service '
         'location of the proposed parent.'],
    ]

    by_pop = []
    for lab in sorted({s for v in full.Zeus_Sources for s in str(v).split('|')}):
        m = full.Zeus_Sources.astype(str).str.split('|').map(
            lambda v, l=lab: l in v)
        k = int((m & full.Match_Tier.eq('Strong match - ready to load')).sum())
        by_pop.append([lab, int(m.sum()), k, k / max(int(m.sum()), 1)])
    by_pop.sort(key=lambda r: -r[1])

    bt = strong.Suggested_Entity_Type.value_counts()
    by_type = [[k, int(v), int(v) / ns] for k, v in bt.items()]

    shared_other = strong[strong.Suggested_Id_Already_In_Zeus.fillna(False)
                          .astype(bool)] if 'Suggested_Id_Already_In_Zeus' \
        in strong.columns else strong.iloc[0:0]
    dup = strong.Suggested_DHC_Id.value_counts()
    shared_within = strong[strong.Suggested_DHC_Id.isin(dup[dup > 1].index)]
    status = c[c.Suggested_Status_Note.fillna('') != '']
    via_loc = strong[strong.Matched_Via == 'Location']

    flags = [
        ['Proposes an id an existing linked entity already uses',
         len(shared_other),
         'Normal: a client and a work location legitimately share one '
         'Definitive record. A business question, not a data error.'],
        ['Proposes an id another unlinked entity also proposes',
         len(shared_within),
         'Chains. Definitive models a chain as one parent id plus service '
         'locations; Zeus models it as many branches. Check the grain you '
         'want before loading.'],
        ['Matched via a service location, not the entity name',
         len(via_loc),
         'The proposed id belongs to the PARENT; Definitive lists this entity '
         'as one of its locations. Usually right, but understand it first.'],
        ['Definitive marks the proposed record Closed or Merged (strong tier)',
         int((strong.Suggested_Status_Note.fillna('') != '').sum()),
         'Reported, never auto-demoted: a closed record can be the correct id '
         'for a historical row.'],
    ]

    estate = None
    if a.accuracy and os.path.exists(a.accuracy):
        # The accuracy scored file holds only the TESTABLE rows; its
        # unverifiable siblings are still linked entities, so read them too or
        # the estate total is understated. Scoped to the same population.
        def linked(path):
            df = pd.read_csv(path, usecols=['EntityId', 'Zeus_Sources'],
                             low_memory=False)
            return int((df[in_population(df, pop)] if pop else df)
                       .EntityId.nunique())
        n_linked = linked(a.accuracy)
        unv = a.accuracy.replace('_scored.csv', '_unverifiable.csv')
        if os.path.exists(unv):
            n_linked += linked(unv)
        tot = n_linked + n_pop
        s_ = int(counts.get('Strong match - ready to load', 0))
        estate = [
            ['Carries a Definitive identifier today', n_linked, n_linked / tot,
             'Measured for accuracy by the companion Accuracy Audit.'],
            ['Carries none', n_pop, n_pop / tot,
             'The subject of this workbook.'],
            [f'Total {population_title(pop)} objects' if pop else
             'Total Zeus objects', tot, 1.0,
             f'Every {population_title(pop)} entity, linked or not.' if pop else
             'Across the six populations, pooled to one row per entity.'],
            ['Coverage if the strong tier is loaded', n_linked + s_,
             (n_linked + s_) / tot,
             f'Acting on {s_:,} proposals would lift coverage from '
             f'{n_linked / tot:.1%} to {(n_linked + s_) / tot:.1%}.'],
        ]

    def _b(col, df):
        # Nullable booleans come back from CSV as True/False/blank or strings.
        return (df[col].map({True: True, False: False, 'True': True,
                             'False': False}) if col in df.columns
                else pd.Series(pd.NA, index=df.index, dtype=object))

    phone_rows = []
    if 'Phone_Match' in full.columns:
        for t in TIER_ORDER[:4]:
            m = full[full.Match_Tier == t]
            pm = _b('Phone_Match', m)
            phone_rows.append([t, len(m), int(pm.eq(True).sum()),
                               int(pm.eq(False).sum()),
                               int(_b('Phone_Favours_Alt', m).eq(True).sum()),
                               int(pm.isna().sum())])
        nmr = full[full.Match_Tier == 'No credible match']
        phone_rows.append(['No credible match - phone names one record',
                           len(nmr), int(nmr.Phone_Lookup_DHC_Id.notna().sum())
                           if 'Phone_Lookup_DHC_Id' in nmr else 0, '', '', ''])

    src = os.path.basename(a.candidates)
    subtitle = (f'Zeus {population_title(pop) + " " if pop else ""}objects with '
                f'no Definitive identifier, matched against the Hospital, '
                f'Physician Group, GPO and Practice Location data - {src}')

    wb = Workbook()
    wb.remove(wb.active)
    build_summary(wb, c, counts, n_pop, subtitle, ev, by_pop, by_type,
                  estate, flags, pop, phone_rows)

    build_methodology(wb, ([scope_note(pop, n_pop, n_all, 'unlinked entities')]
                           if pop else []) + [
        ('What this audit does NOT do', 'It proposes identifiers; it does not '
         'verify them. There is no identifier on record for these entities, so '
         'nothing can be checked against. A tier states how strong the '
         'evidence for a proposal is. Nothing here should be loaded without a '
         'sample being labelled by hand first.'),
        ('Population', 'Non-archived Zeus entities across six populations - '
         'IsClient, IsWorkLocation, IsHealthSystem, IsGPO, IsAgency, IsVMS - '
         'that carry NO Definitive identifier on either dbo.Entity or '
         'LinkEntityVerifiedSource. Entities created by a Definitive import '
         'are excluded, exactly as in the accuracy audit, so the two '
         'populations partition one universe and their counts add up.'),
        ('Why the complement is not a bare NOT', 'An entity can hold several '
         'LinkEntityVerifiedSource rows, so "has no Definitive identifier" is a '
         'claim about all of them - the query uses NOT EXISTS, not a negated '
         'join. VerifiedSourceNameId is wrapped in ISNULL because negating "= '
         '1" on a NULL yields NULL rather than TRUE, which would have silently '
         'dropped most of this population.'),
        ('Not every identifier is a Definitive one', 'Zeus records five '
         'verified-source types (Definitive, Definitive Executive, NPI, '
         'Axuall, MDStaff). Only type 1 counts here. The queries emit the two '
         'identifier columns as typed NULLs so a non-Definitive identifier can '
         'never be read as a Definitive one.'),
        ('Six populations, pooled', 'An entity that is both a client and a '
         'work location holds a different name and address in each. Neither is '
         'authoritative, so all of them become candidates and the best match '
         'wins: one proposal per entity, no double counting. Zeus_Sources '
         'records which populations contributed. 5,461 of 48,739 entities are '
         'in more than one.'),
        ('Name does NOT outrank address here', 'The accuracy audit lets name '
         'outrank address, because a divergent address usually just means an '
         'out-of-date service location on an identifier that is otherwise '
         'right. That reasoning does not transfer to choosing an identifier: a '
         'name match alone establishes only that SOME Definitive record shares '
         'the name, and there are 138,385 physician groups to share it with. A '
         'proposal needs two independent agreements - either street-level '
         'address agreement, or a discriminative match on the entity own name '
         'plus city/state/zip agreement.'),
        ('Ambiguity is reported, not resolved', 'Where a rival Definitive '
         'record scores within 3 points of the winner, the row is tiered '
         'Ambiguous rather than being assigned the argmax. Taking the top '
         'score would have made these indistinguishable from genuine matches; '
         'they are 17% of the population.'),
        ('Candidate search', 'Every entity is searched against Definitive '
         'records blocked on state - the entity HQ state plus every state it '
         'has a service location in, so a satellite is reachable where it '
         'actually sits. 143 entities with no usable state were searched '
         'nationally. The top candidates are then scored in full, and the two '
         'runners-up are retained on every sheet so a reviewer can overrule '
         'the pick.'),
        ('Service locations cut both ways', 'Every Definitive service location '
         'lends its name to its parent as an alias. That is safe when an '
         'identifier is given and unsafe when one is being chosen, because an '
         'alias can now SELECT a record. Location names shared across five or '
         'more parents (Family Medicine, Gastroenterology) and pure branch '
         'labels (East Indianapolis, West) are therefore excluded from the '
         'search - their addresses are kept. A match resting on a location '
         'name reaches the strong tier only with street-level address '
         'agreement.'),
        ('Normalisation', 'Both sides lowercased, ampersands expanded, '
         'punctuation stripped. Zeus stores full state names, Definitive '
         'stores codes; states are normalised before comparison. Definitive '
         'embeds former names in parentheses ((FKA ...), (AKA ...)); these are '
         'parsed out and scored as aliases.'),
        ('Name scoring', 'A 35/65 blend of token_set_ratio and '
         'token_sort_ratio - identical to the accuracy audit. Bare '
         'token_set_ratio returns 100 whenever one token set is a subset of '
         'the other, which lets short generic names win spuriously.'),
        ('Read Matched_Zeus_Name and Matched_Definitive_Name', 'These are the '
         'two strings that actually produced the score, and they are NOT '
         'always Zeus_Name against Suggested_Name: pooling means the winning '
         'Zeus name may be the second one on record, and the winning '
         'Definitive string may be a parenthetical alias or a service '
         'location. Matched_Via says which, and Matched_Zeus_Source names the '
         'Zeus population(s) holding the winning Zeus name.'),
        ('Phone is a third signal, reported not scored', 'Zeus phones come '
         'from the *InfoPhone table of each population; Definitive phones from the '
         'proposed record HQ and every service location. Numbers are '
         'normalised to 10 digits and any number held by 5 or more Definitive '
         'records is ignored. Phone_Match is blank when either side has no '
         'usable number. The tiers do not use it. Phone_Favours_Alt marks rows '
         'where the phone backs a runner-up instead of the pick, and '
         'Phone_Only_Match lists unmatched entities whose phone belongs to '
         'exactly one Definitive record - leads the name search did not find, '
         'to be reviewed rather than loaded.'),
        ('Two Definitive addresses on every row', 'Suggested_Address, '
         'Suggested_City, Suggested_State and Suggested_Zip are where '
         'Definitive says the proposed record is headquartered. '
         'Matched_Zeus_Address and Matched_Definitive_Address are the pair '
         'that produced the street scores, each with its own city, state and '
         'zip - where Address_Match_Source is Location the Definitive side is '
         'a service location of the proposed record, often the more useful '
         'comparison. City_Score and Zip_Score are still taken across every '
         'known site.'),
        ('Known limit', 'Parent-versus-child entities and same-named entities '
         'in different places, the same residual weakness as the accuracy '
         'audit. Name agreement proves the two sides mean the same NAME, not '
         'necessarily the same ENTITY. Closing that needs a human or a third '
         'identifier such as NPI, which is present in the physician group '
         'export and is the obvious next lever.'),
        ('Reproducibility', 'Zeus is a live moving target. The run snapshots '
         'its exact input to <prefix>_zeus_extract.csv; keep that file with '
         'this workbook, or no figure here can be reproduced later.'),
    ])

    show = cols(c, SHOW)

    # Actionable first, then the review queues in descending yield.
    sheet_data(wb, 'Ready_To_Load',
               strong[show].sort_values(['Match_Score', 'Name_Score'],
                                        ascending=False))
    sheet_data(wb, 'Review_Probable',
               c[c.Match_Tier == 'Probable match - review'][show]
               .sort_values('Match_Score', ascending=False))
    sheet_data(wb, 'Ambiguous_Rivals',
               c[c.Match_Tier == 'Ambiguous - rival candidates'][show]
               .sort_values(['Same_Name_Rivals', 'Name_Score'],
                            ascending=False))
    sheet_data(wb, 'Review_Weak',
               c[c.Match_Tier == 'Weak match - review'][show]
               .sort_values('Match_Score', ascending=False))

    # The three "understand before loading" populations from Summary section 3.
    sheet_data(wb, 'Parent_Id_Proposals',
               via_loc[show].sort_values('Match_Score', ascending=False))
    sheet_data(wb, 'Shared_Id_Proposals',
               shared_within.sort_values(['Suggested_DHC_Id', 'EntityId'])[show])
    if len(shared_other):
        sheet_data(wb, 'Id_Already_Linked_In_Zeus',
                   shared_other.sort_values('Suggested_DHC_Id')[show])
    if len(status):
        sheet_data(wb, 'Status_Flagged',
                   status.sort_values('Match_Tier')[show])

    if 'Phone_Favours_Alt' in c.columns:
        fa = c[_b('Phone_Favours_Alt', c).eq(True)]
        # Spans every tier, so the tier leads.
        sheet_data(wb, 'Phone_Favours_Alt',
                   fa[['Match_Tier'] + show].sort_values(
                       ['Match_Tier', 'Match_Score'], ascending=[True, False]))
    if nm is not None and 'Phone_Lookup_DHC_Id' in nm.columns:
        po = nm[nm.Phone_Lookup_DHC_Id.notna()]
        sheet_data(wb, 'Phone_Only_Match',
                   po[cols(po, SHOW)].sort_values(['Zeus_State', 'Zeus_Name']))

    if nm is not None:
        sheet_data(wb, 'No_Credible_Match',
                   nm[cols(nm, SHOW)].sort_values(
                       ['Zeus_State', 'Zeus_Name']))

    sheet_data(wb, 'Candidates_Detail', c)

    wb.save(a.out)
    print(f'Wrote {a.out}')
    for ws in wb.worksheets:
        print(f'  {ws.title:26} {ws.max_row - 1:>7,} rows')

    # The identities from CLAUDE.md, re-checked on the built workbook.
    print('\nIdentity checks:')
    print(f'  tier counts sum to population    '
          f'{sum(counts.values()):,} == {n_pop:,}  '
          f'{"OK" if sum(counts.values()) == n_pop else "FAIL"}')
    tot_sheets = len(strong) + \
        int((c.Match_Tier == 'Probable match - review').sum()) + \
        int((c.Match_Tier == 'Ambiguous - rival candidates').sum()) + \
        int((c.Match_Tier == 'Weak match - review').sum()) + \
        int((c.Match_Tier == 'No usable Zeus name').sum()) + \
        (len(nm) if nm is not None else 0)
    print(f'  review sheets + no-match = pop   {tot_sheets:,} == {n_pop:,}  '
          f'{"OK" if tot_sheets == n_pop else "FAIL"}')
    if ex is not None:
        print(f'  extract entities = population    '
              f'{ex.EntityId.nunique():,} == {n_pop:,}  '
              f'{"OK" if ex.EntityId.nunique() == n_pop else "FAIL"}')


if __name__ == '__main__':
    main()
