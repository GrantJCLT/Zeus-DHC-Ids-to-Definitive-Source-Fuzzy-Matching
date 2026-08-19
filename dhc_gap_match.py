#!/usr/bin/env python3
"""
Zeus -> Definitive Healthcare identifier COVERAGE: find the missing ids.

The sibling of dhc_match_v2.py. That tool answers "is the id we hold correct?"
over the 12,803 entities that carry one. This one answers the complement:

  1. Which Zeus objects carry no Definitive id at all?   (the six gap queries)
  2. For those, which Definitive record should they point at?

Everything that normalises or scores a name or an address is imported from
dhc_match_v2, so the decisions recorded in CLAUDE.md are single-sourced. The one
rule this tool must NOT inherit is decision #4, "name outranks address":

    Verifying a supplied id and proposing a new one are different burdens of
    proof. When Zeus already holds an id, a name match corroborates it and a
    divergent address is usually just an out-of-date service location - so the
    verdict leans on the name. When nothing is on record, a name match alone
    establishes only that some Definitive record shares the name. 138,385
    physician groups contain thousands of near-identical names, so a proposal
    with no geographic agreement is a guess. `Match_Tier` therefore requires
    name AND place to agree before it calls anything loadable, and demotes a
    winner that a rival record matches equally well (`Ambiguous`).

Usage:
    py dhc_gap_match.py --config sources.yaml --out gap_2026_08_19
    py dhc_gap_match.py --config sources.yaml --zeus <extract.csv> --out ...
    py dhc_gap_match.py --config sources.yaml --claimed audit_2026_08_12_scored.csv ...

Writes <out>_gap_candidates.csv (one row per Zeus entity, best proposal plus two
alternates), <out>_gap_nomatch.csv, and <out>_zeus_extract.csv - keep that last
one with anything you circulate, for the reason given in CLAUDE.md.
"""
import argparse
import os
import time
from collections import defaultdict

import numpy as np
import pandas as pd
from rapidfuzz import fuzz, process

import dhc_match_v2 as M

# Expected size of the missing-id population, so drift is visible run to run.
# Measured 2026-08-19 over the six gap queries. Its counterpart is
# M.ZEUS_BASELINE_ENTITIES (12,803); the two partition one universe.
GAP_BASELINE_ENTITIES = 48_739

# Stage A keeps this many candidate ids per entity for exact scoring. Raising it
# costs the exact pass linearly; lowering it below ~4 starts to hide rivals,
# which is exactly what the ambiguity test needs to see.
TOP_K = 6

# Stage A floor. A candidate whose blended name score is below this cannot reach
# any actionable tier, so scoring it exactly is wasted work.
STAGE_A_FLOOR = 55.0

# Per-candidate ceiling on service-location names and addresses fed into the
# exact pass. Lower than M.LOC_CAP because this pass scores TOP_K candidates per
# entity rather than one, and an id with 962 locations would dominate the run.
# Reported, never silent.
GAP_LOC_CAP = 60

# A Zeus name needs this many alphanumeric characters to be worth searching on.
# The population contains names that are a single punctuation mark ('.', ';').
MIN_NAME_CHARS = 4

CHUNK = 512          # targets per cdist call, to bound the score matrix
BATCH = 6000         # entities per exact-scoring batch, to bound the location index

# A location name used by this many DISTINCT parent ids identifies nothing.
# Measured over the 399,990-row export: 'family' appears under 154 parents,
# 'gastroenterology' under 53, 'surgery' under 58. Left in the search space they
# let any large system match any similarly-named Zeus practice. 5 drops 1,691
# cores / 29,477 rows (7.5%); see `location_name_filter`.
LOC_NAME_DF_MAX = 5

# Compass words are branch labels, not names: 'East Indianapolis' in
# Indianapolis, 'West' in Avon. See `location_name_filter`.
COMPASS = {'n', 's', 'e', 'w', 'ne', 'nw', 'se', 'sw', 'north', 'south', 'east',
           'west', 'northeast', 'northwest', 'southeast', 'southwest',
           'central', 'main', 'downtown', 'uptown', 'campus', 'annex'}


# ============================================================================
# Search space
# ============================================================================
def usable_names(names):
    """Zeus names worth searching on, in pooled order.

    Junk names are harmless when SCORING a supplied id - name_score takes a
    maximum, so 'DO NOT USE - Banner Health' cannot lower anything. They are not
    harmless when GENERATING candidates: a one-character name retrieves an
    arbitrary top-K, which then gets a tier. So they are dropped here, and an
    entity with nothing left is reported rather than matched.
    """
    out = []
    for n in names:
        c = M._clean(n)
        if len(c.replace(' ', '')) >= MIN_NAME_CHARS:
            out.append(n)
    return out


def candidate_states(d, L):
    """[set of states] per reference row.

    Blocking on the HQ state alone would hide any entity that operates in Zeus's
    state through a satellite - the same HQ-versus-service-location gap decision
    #9 addresses. 2,756 ids have a location outside their HQ state.
    """
    if L is not None:
        ls = L[['DHC_Id', 'Loc_State']].dropna()
        ls = ls.assign(st=ls.Loc_State.map(M.norm_state))
        ls = ls[ls.st != '']
        by_id = ls.groupby('DHC_Id').st.apply(set).to_dict()
    else:
        by_id = {}
    states = []
    for did, hq in zip(d.DHC_Id, d.d_state):
        s = set(by_id.get(did, ()))
        if hq:
            s.add(hq)
        states.append(s)
    return states


def location_name_filter(L):
    """Which service-location names are allowed to IDENTIFY a parent id.

    Decision #9 made every location name an alias of its parent, which is right
    when the id is given: aliases can only raise the score of the one record
    being tested. It is not right when the id is being chosen, because an alias
    can now SELECT a record. Two kinds of location name identify nothing:

      1. Names shared across many parents - 'Family Medicine' sits under 77
         different ids, 'Gastroenterology' under 53. Any Zeus practice with a
         specialty in its name matches all of them.
      2. Branch labels - a satellite called 'East Indianapolis' in Indianapolis,
         or simply 'West'. Measured: 'Indianapolis Breast Center' scored 94.4
         against 'East Indianapolis' and was proposed the wrong parent id.

    Both are dropped from the searchable space and from name enrichment. Their
    ADDRESSES are kept: a location's address is evidence of where the parent
    operates no matter how generically the location is labelled.

    Returns (mask over L, {(id, name)} dropped) and reports what it removed.
    """
    nm = L.Loc_Name.where(L.Loc_Name.map(lambda x: isinstance(x, str)))
    core = nm.map(lambda x: M.name_core(x) if isinstance(x, str) else '')
    df = L.assign(core=core)[core != ''].groupby('core').DHC_Id.nunique()
    common = set(df[df >= LOC_NAME_DF_MAX].index)

    city = L.Loc_City.map(lambda x: set(M._clean(x).split()) if isinstance(x, str)
                          else set())
    # What survives once the branch's own city and the compass words are taken
    # out. Nothing left means the name was a label for where, not who.
    residue = [set(c.split()) - cty - COMPASS for c, cty in zip(core, city)]

    is_common = core.isin(common)
    is_label = pd.Series([len(r) == 0 for r in residue], index=L.index)
    named = core != ''
    drop = named & (is_common | is_label)

    d_common = int((named & is_common).sum())
    d_label = int((named & is_label & ~is_common).sum())
    print(f'  location names usable as identity: {int((named & ~drop).sum()):,} '
          f'of {int(named.sum()):,}')
    print(f'    dropped {d_common:,} shared by >= {LOC_NAME_DF_MAX} parent ids, '
          f'{d_label:,} branch labels (city or compass word only)')
    dropped = set(zip(L.DHC_Id[drop], L.Loc_Name[drop]))
    return (named & ~drop), dropped


def build_search_space(d, L, loc_ok=None):
    """Searchable name rows: every identity name AND every service-location name.

    Location names must be searchable, not merely available for enrichment. A
    Zeus work location is commonly named after the satellite ('Dartmouth
    Hitchcock - Bedford') while the identity export holds the parent's name, so a
    search over identity names alone would never retrieve the right parent id -
    and stage B's location enrichment cannot rescue it, because enrichment only
    ever sees candidates that already reached the top K on the identity name.

    Rows are deduplicated on (id, name core): an id with 962 locations usually
    repeats a handful of distinct names.
    """
    ids = list(d.DHC_Id)
    cores = [M.name_core(x) for x in d.d_primary]
    fulls = [M._clean(x) for x in d.d_primary]

    # First parenthetical former name (decision #2). Later aliases and every
    # location name are still scored exactly in stage B; stage A only has to
    # achieve recall.
    alias_ids, alias_cores, alias_fulls = [], [], []
    for did, al in zip(d.DHC_Id, d.d_aliases):
        if al:
            alias_ids.append(did)
            alias_cores.append(M.name_core(al[0]))
            alias_fulls.append(M._clean(al[0]))
    ids += alias_ids
    cores += alias_cores
    fulls += alias_fulls
    print(f'  + {len(alias_ids):,} parenthetical former names')

    n_identity = len(d)
    row_of_id = {int(v): i for i, v in enumerate(d.DHC_Id)}

    loc_rows = []
    if L is not None:
        Lf = L[loc_ok] if loc_ok is not None else L
        seen = set()
        for did, nm in zip(Lf.DHC_Id, Lf.Loc_Name):
            if not isinstance(nm, str) or not nm.strip():
                continue
            c = M.name_core(nm)
            k = (did, c)
            if k in seen:
                continue
            seen.add(k)
            loc_rows.append((did, c, M._clean(nm)))
        ids += [r[0] for r in loc_rows]
        cores += [r[1] for r in loc_rows]
        fulls += [r[2] for r in loc_rows]
        print(f'  + {len(loc_rows):,} distinct location names, searchable as '
              f'aliases of their parent id')

    return (np.asarray(ids, dtype='int64'), cores, fulls, n_identity, row_of_id)


# ============================================================================
# Stage A - blocked, chunked candidate retrieval
# ============================================================================
def blended(tgts, cands):
    """M.pair_score, vectorised. Same 35/65 blend, for decision #3's reason."""
    ts = process.cdist(tgts, cands, scorer=fuzz.token_set_ratio,
                       workers=-1, dtype=np.uint8).astype(np.float32)
    tr = process.cdist(tgts, cands, scorer=fuzz.token_sort_ratio,
                       workers=-1, dtype=np.uint8).astype(np.float32)
    return M.TS_W * ts + M.TR_W * tr


def retrieve(z, cand_ids, cores, fulls, pools):
    """Top-K candidate ids per Zeus entity, blocked by state.

    Returns ({entity row -> {dhc_id: stage-A name score}}, rows with no name).
    """
    # Which entities search which state. An entity pooled across populations can
    # hold more than one state; each is searched and the best result kept.
    targets_by_state = defaultdict(list)      # state -> [(row, name)]
    no_state, no_name = [], []
    names_u = list(z.Z_Names_U)
    for i, (names, states) in enumerate(zip(names_u, z.Z_States_N)):
        if not names:
            no_name.append(i)
            continue
        st = [s for s in states if s in pools]
        if not st:
            no_state.append(i)
            continue
        for s in st:
            for n in names:
                targets_by_state[s].append((i, n))

    print(f'  {len(no_name):,} entities have no usable name; {len(no_state):,} '
          f'have no state matching any candidate pool (searched nationally)')
    pools = dict(pools)
    if no_state:
        targets_by_state['*'] = [(i, n) for i in no_state for n in names_u[i]]
        pools['*'] = np.arange(len(cores), dtype='int64')

    best = defaultdict(dict)
    order = sorted(targets_by_state, key=lambda s: -len(targets_by_state[s]))
    t0 = time.time()
    done = 0
    total = sum(len(v) for v in targets_by_state.values())
    for st in order:
        pool = pools[st]
        if not len(pool):
            continue
        pc = [cores[j] or fulls[j] for j in pool]
        pf = [fulls[j] for j in pool]
        tg = targets_by_state[st]
        for a in range(0, len(tg), CHUNK):
            block = tg[a:a + CHUNK]
            tc = [M.name_core(n) or M._clean(n) for _, n in block]
            tf = [M._clean(n) for _, n in block]
            # max(core-vs-core, full-vs-full) - M.name_score's own rule.
            s = np.maximum(blended(tc, pc), blended(tf, pf))
            k = min(TOP_K * 3, s.shape[1])     # rows collapse to fewer ids
            top = np.argpartition(-s, k - 1, axis=1)[:, :k]
            for r, (ent, _) in enumerate(block):
                cols = top[r]
                for col, v in zip(cols, s[r, cols]):
                    if v < STAGE_A_FLOOR:
                        continue
                    did = int(cand_ids[pool[col]])
                    if v > best[ent].get(did, -1.0):
                        best[ent][did] = float(v)
            done += len(block)
        print(f'    {st:2}  pool {len(pool):>7,}  targets {len(tg):>7,}  '
              f'{done/total:5.1%} done, {(time.time()-t0)/60:.1f} min elapsed',
              flush=True)

    return ({e: dict(sorted(v.items(), key=lambda kv: -kv[1])[:TOP_K])
             for e, v in best.items()}, no_name)


# ============================================================================
# Stage B - exact scoring of the retrieved candidates
# ============================================================================
def location_index_capped(L, need_ids):
    """M.location_index with this tool's tighter cap."""
    saved = M.LOC_CAP
    M.LOC_CAP = GAP_LOC_CAP
    try:
        return M.location_index(L, need_ids)
    finally:
        M.LOC_CAP = saved


def name_provenance(z_names, primary, aliases, loc_names):
    """Which strings produced the winning name score, and how.

    M.name_score returns a maximum over Zeus names x (primary, aliases,
    location names), in both full-string and noise-stripped-core form. That is
    the right score but it hides its own reasoning, and here the reasoning
    decides the tier: a match on the entity's own name is identity evidence,
    while a match on a service location's name is evidence about a satellite
    and needs the address to confirm which entity owns it.

    Returns (score, zeus_text, definitive_text, via, core_tokens) where `via` is
    Name | Alias | Location and `core_tokens` counts the tokens in the winning
    Definitive core - 1 means a generic single word, the case CLAUDE.md's
    "How name_core behaves on practices" section warns about.
    """
    cands = [(primary, 'Name')] + [(a, 'Alias') for a in (aliases or [])] + \
            [(n, 'Location') for n in (loc_names or [])]
    best = (0.0, '', '', '', 0)
    for zn in z_names:
        zf, zc = M._clean(zn), M.name_core(zn)
        for dn, via in cands:
            if not dn:
                continue
            df_, dc = M._clean(dn), M.name_core(dn)
            s = M.pair_score(zf, df_)
            core_used = False
            if zc and dc:
                sc = M.pair_score(zc, dc)
                if sc > s:
                    s, core_used = sc, True
            if s > best[0]:
                best = (float(s), zn, dn, via,
                        len((dc if core_used else df_).split()))
    return best


COLS_B = ['ent', 'Suggested_DHC_Id', 'Suggested_Name', 'Suggested_Entity_Type',
          'StageA_Score', 'Name_Score', 'StreetNum_Score', 'StreetName_Score',
          'City_Score', 'State_Score', 'Zip_Score', 'Address_Match_Source',
          'Address_Score', 'Match_Score', 'Location_Count',
          'Matched_Zeus_Name', 'Matched_Definitive_Name', 'Matched_Via',
          'Matched_Core_Tokens']

BLEND_ORDER = ('name', 'stnum', 'stname', 'city', 'state', 'zip')


def usable_loc(entry, did, dropped):
    """A location index entry with the non-identifying names removed.

    Addresses are untouched - see `location_name_filter`.
    """
    if entry is None:
        return None
    names = [n for n in entry['names'] if (did, n) not in dropped]
    if len(names) == len(entry['names']):
        return entry
    return {**entry, 'names': names}


def score_exact(z, d, L, retrieved, dropped):
    """Full M.enriched_scores for every retained (entity, candidate) pair."""
    dd = d.reset_index(drop=True)
    row_of_id = {int(v): i for i, v in enumerate(dd.DHC_Id)}
    zn = list(z.Z_Names_U)
    za = list(z.Z_Addrs)
    zc = list(z.Z_Cities_N)
    zs = list(z.Z_States_N)
    zz = list(z.Z_Zips_N)
    bw = [M.BLEND_W[k] for k in BLEND_ORDER]

    rows = []
    ents = sorted(retrieved)
    capped_total = 0
    for a in range(0, len(ents), BATCH):
        batch = ents[a:a + BATCH]
        need = {i for e in batch for i in retrieved[e]}
        loc, capped = location_index_capped(L, need)
        capped_total += capped
        for e in batch:
            for did, stage_a in retrieved[e].items():
                p = dd.iloc[row_of_id[did]]
                lc = usable_loc(loc.get(did), did, dropped)
                ent = {'primary': p.d_primary, 'aliases': p.d_aliases,
                       'lines': (p.DHC_Addr1, p.DHC_Addr2), 'city': p.d_city_n,
                       'state': p.d_state, 'zip': p.d_zip5}
                nm, an, ab, cs, st, zp, src = M.enriched_scores(
                    zn[e], za[e], zc[e], zs[e], zz[e], ent, lc)
                _, ztxt, dtxt, via, ctok = name_provenance(
                    zn[e], p.d_primary, p.d_aliases, lc['names'] if lc else [])
                rows.append((
                    e, did, p.DHC_Name, p.DHC_Entity_Type, stage_a,
                    nm, an, ab, cs, st, zp, src,
                    M.weighted([an, ab, cs, st, zp], M.ADDR_W),
                    M.weighted([nm, an, ab, cs, st, zp], bw),
                    (loc.get(did) or {}).get('n', 0), ztxt, dtxt, via, ctok))
        print(f'    scored {min(a + BATCH, len(ents)):>7,} of {len(ents):,} '
              f'entities', flush=True)
    if capped_total:
        print(f'  note: {capped_total:,} candidate ids exceeded the '
              f'{GAP_LOC_CAP}-location cap; the rest were not scored')
    return pd.DataFrame(rows, columns=COLS_B)


# ============================================================================
# Tiering
# ============================================================================
# Ambiguity threshold on Match_Score. Two Definitive records this close are not
# separable by the string evidence available, and taking the argmax would
# silently choose one of them.
MARGIN_MIN = 3.0

TIERS = ['Strong match - ready to load', 'Probable match - review',
         'Ambiguous - rival candidates', 'Weak match - review',
         'No credible match', 'No usable Zeus name']


def tier(name, addr, city, state, zip_, margin, via, core_tokens):
    """Two independent agreements are required to call a proposal loadable.

    `street` is agreement on the street line itself; `geo` is the weaker "same
    place" test that city, state or zip can satisfy. A name match plus geo is
    not sufficient on its own, because the two commonest false positives both
    clear it:

      - the name came from a service location, so it identifies a satellite and
        not necessarily its owner (see `location_name_filter`); and
      - the name matched only after noise stripping left a single generic token
        ('cardiology' vs 'cardiology'), the case CLAUDE.md documents under
        "How name_core behaves on practices".

    So Strong needs either street-level address agreement - which settles both -
    or a discriminative match on the entity's OWN name plus same-place agreement.
    """
    street = addr >= 85
    geo = (addr >= 60) or (zip_ == 100) or (city >= 90 and state == 100)
    own = via in ('Name', 'Alias') and core_tokens >= 2
    if name < 75:
        return 'No credible match'
    if margin < MARGIN_MIN:
        # A rival record fits as well. The name is probably right; which record
        # it belongs to is not decidable from name and address alone.
        return 'Ambiguous - rival candidates'
    if name >= 92 and (street or (own and geo)):
        return 'Strong match - ready to load'
    if name >= 92 or (name >= 82 and geo):
        return 'Probable match - review'
    return 'Weak match - review'


def flatten(o):
    """List columns are for scoring; a CSV wants readable text."""
    o = o.copy()
    o['Zeus_Name'] = [v[0] if v else '' for v in o.Z_Names]
    o['Zeus_Names_All'] = [' | '.join(v) for v in o.Z_Names]
    o['Zeus_Address'] = [v[0] if v else '' for v in o.Z_Addrs]
    o['Zeus_Addresses_All'] = [' | '.join(v) for v in o.Z_Addrs]
    o['Zeus_City'] = [' | '.join(v) for v in o.Z_Cities]
    o['Zeus_State'] = [' | '.join(v) for v in o.Z_States]
    o['Zeus_Zip'] = [' | '.join(str(x) for x in v) for v in o.Z_Zips]
    return o.drop(columns=[c for c in
                           ['Z_Names', 'Z_Addrs', 'Z_Cities', 'Z_States',
                            'Z_Zips', 'Z_Names_U', 'Z_Cities_N', 'Z_States_N',
                            'Z_Zips_N', 'Entity_DHC_VerifiedSourceId',
                            'LEVS_DHC_VerifiedSourceId'] if c in o.columns])


LEAD = ['EntityId', 'Zeus_Sources', 'Zeus_Source_Count', 'Match_Tier',
        'Zeus_Name', 'Zeus_Names_All', 'Zeus_Address', 'Zeus_Addresses_All',
        'Zeus_City', 'Zeus_State', 'Zeus_Zip', 'Suggested_DHC_Id',
        'Suggested_Name', 'Suggested_Entity_Type',
        'Suggested_Status_Note', 'Name_Score',
        'Address_Score', 'Match_Score', 'Match_Margin', 'Same_Name_Rivals',
        'Exact_Name_And_Geo', 'Matched_Zeus_Name', 'Matched_Definitive_Name',
        'Matched_Via']


def main():
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--config', required=True)
    ap.add_argument('--out', default='dhc_gap')
    ap.add_argument('--zeus', help='replay an archived _zeus_extract.csv')
    ap.add_argument('--claimed', help='a <prefix>_scored.csv from '
                    'dhc_match_v2.py, to flag proposals whose id some other '
                    'Zeus entity already points at')
    ap.add_argument('--limit', type=int, help='first N entities only (testing)')
    a = ap.parse_args()

    t_start = time.time()
    cfg = M.load_config(a.config)
    zc = cfg['zeus']
    # Same populations, same role mappings, complement query.
    zc['query_key'] = 'gap_query_file'
    zc['baseline_entities'] = GAP_BASELINE_ENTITIES
    if a.zeus:
        zc['path'] = a.zeus
    z = M.load_zeus(zc, None if a.zeus else a.out)

    z['Z_Names_U'] = [usable_names(v) for v in z.Z_Names]
    z['Z_Cities_N'] = [[M._clean(x) for x in v if M._clean(x)] for v in z.Z_Cities]
    z['Z_States_N'] = [sorted({M.norm_state(x) for x in v} - {''})
                       for v in z.Z_States]
    z['Z_Zips_N'] = [sorted({M.norm_zip5(x) for x in v} - {''}) for v in z.Z_Zips]
    if a.limit:
        z = z.head(a.limit).copy()
        print(f'  --limit: {len(z):,} entities')
    z = z.reset_index(drop=True)

    print('\nDefinitive location sources:')
    L = M.load_locations(cfg.get('locations'))
    print('\nDefinitive identity sources:')
    known = set()
    for b in cfg['definitive']:
        col = pd.to_numeric(M._read_roles(b, ('id',))[b['id']], errors='coerce')
        known |= set(col.dropna().astype('int64'))
    d = M.load_definitive(cfg['definitive'], M.locations_as_identity(L, known))
    print(f'  total reference records: {len(d):,}')

    print('\nBuilding the search space:')
    if L is not None:
        loc_ok, dropped = location_name_filter(L)
    else:
        loc_ok, dropped = None, set()
    cand_ids, cores, fulls, n_identity, row_of_id = build_search_space(
        d, L, loc_ok)
    print(f'  {len(cand_ids):,} searchable name rows over '
          f'{len(row_of_id):,} distinct ids')

    cs = candidate_states(d, L)
    pools = defaultdict(list)
    for i in range(n_identity):
        for st in cs[i]:
            pools[st].append(i)
    # An alias or location row is blocked on its parent id's state set, so a
    # satellite is retrievable in the state it actually sits in.
    for j in range(n_identity, len(cand_ids)):
        r = row_of_id.get(int(cand_ids[j]))
        if r is None:
            continue
        for st in cs[r]:
            pools[st].append(j)
    pools = {k: np.asarray(v, dtype='int64') for k, v in pools.items()}
    print(f'  blocked into {len(pools)} states; largest pool '
          f'{max(len(v) for v in pools.values()):,}')

    print(f'\nStage A - retrieving candidates for {len(z):,} entities:')
    retrieved, no_name = retrieve(z, cand_ids, cores, fulls, pools)
    print(f'  {len(retrieved):,} entities retrieved at least one candidate '
          f'above the stage-A floor of {STAGE_A_FLOOR:.0f}')

    print('\nStage B - exact scoring:')
    sc = score_exact(z, d, L, retrieved, dropped)

    # Best and runner-up per entity, and the margin between them.
    sc = sc.sort_values(['ent', 'Match_Score'], ascending=[True, False])
    sc['rank'] = sc.groupby('ent').cumcount()
    idx = range(len(z))
    best = sc[sc['rank'] == 0].set_index('ent')
    second = sc[sc['rank'] == 1].set_index('ent')
    margin = (best.Match_Score -
              second.Match_Score.reindex(best.index)).fillna(100.0)

    out = z.copy()
    out['Candidates_Considered'] = [len(retrieved.get(i, {})) for i in idx]
    for c in ['Suggested_DHC_Id', 'Suggested_Name', 'Suggested_Entity_Type',
              'Name_Score', 'Address_Score', 'City_Score', 'State_Score',
              'Zip_Score', 'StreetNum_Score', 'StreetName_Score',
              'Match_Score', 'Address_Match_Source', 'Location_Count',
              'StageA_Score', 'Matched_Zeus_Name', 'Matched_Definitive_Name',
              'Matched_Via', 'Matched_Core_Tokens']:
        out[c] = best[c].reindex(idx).values
    out['Match_Margin'] = np.round(
        pd.to_numeric(margin.reindex(idx), errors='coerce').values, 1)

    # Same-name rivals: how many OTHER retrieved candidates match the name about
    # as well as the winner. A large number is the "thousands of near-identical
    # practice names" failure mode made visible on the row it affects.
    bn = sc.ent.map(best.Name_Score)
    riv = sc[sc.Name_Score >= bn - 2].groupby('ent').size() - 1
    out['Same_Name_Rivals'] = riv.reindex(idx).fillna(0).astype(int).values

    # Two alternates, so a reviewer can see what was rejected and why.
    for r in (1, 2):
        alt = sc[sc['rank'] == r].set_index('ent')
        out[f'Alt{r}_DHC_Id'] = alt.Suggested_DHC_Id.reindex(idx).values
        out[f'Alt{r}_Name'] = alt.Suggested_Name.reindex(idx).values
        out[f'Alt{r}_Match_Score'] = alt.Match_Score.reindex(idx).values

    z0 = lambda s: pd.to_numeric(s, errors='coerce').fillna(0)
    out['Match_Tier'] = [
        'No usable Zeus name' if not u else
        tier(n, ad, c, s, zp, mg, via, ct)
        for u, n, ad, c, s, zp, mg, via, ct in zip(
            out.Z_Names_U, z0(out.Name_Score), z0(out.Address_Score),
            z0(out.City_Score), z0(out.State_Score), z0(out.Zip_Score),
            out.Match_Margin.fillna(100.0), out.Matched_Via.fillna(''),
            z0(out.Matched_Core_Tokens))]
    out.loc[out.Suggested_DHC_Id.isna() & (out.Z_Names_U.map(len) > 0),
            'Match_Tier'] = 'No credible match'

    # Highest-precision subset: the normalised names are equal outright and the
    # place agrees. Worth separating because it needs no judgement call.
    out['Exact_Name_And_Geo'] = [
        bool(u) and isinstance(sn, str) and
        any(M._clean(x) == M._clean(sn) for x in u) and
        ((zp == 100) or (c >= 95 and s == 100))
        for u, sn, zp, c, s in zip(
            out.Z_Names_U, out.Suggested_Name, z0(out.Zip_Score),
            z0(out.City_Score), z0(out.State_Score))]

    # Definitive parks status in the name - '(Closed)', '(Merged)'. A closed
    # record can still be the right id for a historical Zeus row, so this is
    # reported rather than demoted, but nobody should load one unknowingly.
    out['Suggested_Status_Note'] = [
        ' '.join(m.strip() for m in M.STATUS_RE.findall(str(v)))
        if isinstance(v, str) else '' for v in out.Suggested_Name]
    n_st = int((out.Suggested_Status_Note != '').sum())
    if n_st:
        print(f'\n{n_st:,} proposals name a Definitive record carrying a status '
              f'marker (Closed / Merged / ...); see Suggested_Status_Note.')

    if a.claimed and os.path.exists(a.claimed):
        cl = pd.read_csv(a.claimed, usecols=['DHC_Id'])
        claimed = set(pd.to_numeric(cl.DHC_Id, errors='coerce')
                      .dropna().astype('int64'))
        out['Suggested_Id_Already_In_Zeus'] = [
            bool(pd.notna(v) and int(v) in claimed) for v in out.Suggested_DHC_Id]
        n_cl = int(out.Suggested_Id_Already_In_Zeus.sum())
        print(f'\nCross-check against {a.claimed}: {n_cl:,} proposals name an id '
              f'that another Zeus entity already points at. Legitimate for a '
              f'client/work-location pair (see CLAUDE.md), but review before '
              f'loading.')

    # ---- report ----
    n = len(out)
    print(f'\n--- Coverage: {n:,} Zeus entities carrying no Definitive id ---')
    print(f'  {"tier":34}{"entities":>10}{"share":>9}')
    for t in TIERS:
        m = int((out.Match_Tier == t).sum())
        if m:
            print(f'  {t:34}{m:>10,}{m/n:>9.1%}')
    load = int(out.Match_Tier.eq('Strong match - ready to load').sum())
    rev = int(out.Match_Tier.isin(['Probable match - review',
                                   'Ambiguous - rival candidates',
                                   'Weak match - review']).sum())
    print(f'  {"-"*51}')
    print(f'  {"proposable (strong tier)":34}{load:>10,}{load/n:>9.1%}')
    print(f'  {"needs a human":34}{rev:>10,}{rev/n:>9.1%}')
    print(f'  {"exact name + geo agreement":34}'
          f'{int(out.Exact_Name_And_Geo.sum()):>10,}')

    print('\n--- By Zeus population (overlapping; entities counted in each) ---')
    labels = sorted({s for v in out.Zeus_Sources for s in v.split('|')})
    print(f'  {"population":16}{"entities":>10}{"strong":>9}{"pct":>8}')
    for l in labels:
        m = out.Zeus_Sources.str.split('|').map(lambda v, l=l: l in v)
        k = int((m & out.Match_Tier.eq('Strong match - ready to load')).sum())
        print(f'  {l:16}{int(m.sum()):>10,}{k:>9,}{k/max(int(m.sum()),1):>8.1%}')

    strong = out[out.Match_Tier == 'Strong match - ready to load']
    if len(strong):
        print('\n--- Strong tier: which Definitive string matched ---')
        for k, v in strong.Matched_Via.value_counts().items():
            print(f'  {k:20}{v:>8,}')
        print('\n--- Proposed Definitive entity type, strong tier ---')
        for k, v in strong.Suggested_Entity_Type.value_counts().items():
            print(f'  {k:20}{v:>8,}')

    o = flatten(out)
    o = o[[c for c in LEAD if c in o.columns] +
          [c for c in o.columns if c not in LEAD]]
    hit = o[o.Match_Tier != 'No credible match']
    miss = o[o.Match_Tier == 'No credible match']
    hit.to_csv(f'{a.out}_gap_candidates.csv', index=False)
    print(f'\nWrote {a.out}_gap_candidates.csv  ({len(hit):,} rows)')
    if len(miss):
        keep = [c for c in LEAD if c in miss.columns and
                not c.startswith(('Suggested', 'Alt'))]
        miss[keep].to_csv(f'{a.out}_gap_nomatch.csv', index=False)
        print(f'Wrote {a.out}_gap_nomatch.csv  ({len(miss):,} rows)')
    print(f'\nTotal elapsed: {(time.time() - t_start) / 60:.1f} min')
    return o


if __name__ == '__main__':
    main()
