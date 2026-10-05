#!/usr/bin/env python3
"""
Zeus <-> Definitive Healthcare identifier verification.

Handles any number of Definitive exports (Hospital, Physician Group, Clinic,
IDN, ...) in one run. Definitive names its columns differently per entity type,
so column roles come from a config file. Use --inspect to generate one.

  1. Inspect each new export to learn its columns and get a starting config:
       python dhc_match_v2.py inspect Definitive_PhysicianGroup.xlsx

  2. Write (or extend) a config, then run:
       python dhc_match_v2.py run --config sources.yaml --zeus Zeus.xlsx

  Each run writes into its own folder, "Results Output/dhc_match_v2_<YYYY_MM_DD_HHMM>/".

Requires: pandas, numpy, openpyxl, rapidfuzz  (pyyaml optional - JSON works too)
"""
import argparse
import json
import os
import re
import shutil
import sys
import time

import numpy as np
import pandas as pd
from rapidfuzz import fuzz, process

# ============================================================================
# Normalisation
# ============================================================================
STATES = {
    'alabama': 'AL', 'alaska': 'AK', 'arizona': 'AZ', 'arkansas': 'AR',
    'california': 'CA', 'colorado': 'CO', 'connecticut': 'CT', 'delaware': 'DE',
    'district of columbia': 'DC', 'florida': 'FL', 'georgia': 'GA', 'hawaii': 'HI',
    'idaho': 'ID', 'illinois': 'IL', 'indiana': 'IN', 'iowa': 'IA', 'kansas': 'KS',
    'kentucky': 'KY', 'louisiana': 'LA', 'maine': 'ME', 'maryland': 'MD',
    'massachusetts': 'MA', 'michigan': 'MI', 'minnesota': 'MN', 'mississippi': 'MS',
    'missouri': 'MO', 'montana': 'MT', 'nebraska': 'NE', 'nevada': 'NV',
    'new hampshire': 'NH', 'new jersey': 'NJ', 'new mexico': 'NM', 'new york': 'NY',
    'north carolina': 'NC', 'north dakota': 'ND', 'ohio': 'OH', 'oklahoma': 'OK',
    'oregon': 'OR', 'pennsylvania': 'PA', 'rhode island': 'RI',
    'south carolina': 'SC', 'south dakota': 'SD', 'tennessee': 'TN', 'texas': 'TX',
    'utah': 'UT', 'vermont': 'VT', 'virginia': 'VA', 'washington': 'WA',
    'west virginia': 'WV', 'wisconsin': 'WI', 'wyoming': 'WY', 'puerto rico': 'PR',
    'virgin islands': 'VI', 'guam': 'GU', 'american samoa': 'AS',
}

NOISE_TOKENS = {
    'inc', 'incorporated', 'llc', 'llp', 'lp', 'pc', 'pa', 'pllc', 'plc', 'ltd',
    'corp', 'corporation', 'co', 'company', 'the', 'of', 'at', 'and', 'a', 'an',
    'group', 'system', 'systems', 'health', 'healthcare', 'medical', 'center',
    'centre', 'ctr', 'hospital', 'hospitals', 'clinic', 'clinics', 'regional',
    'memorial', 'community', 'general', 'district', 'services', 'service',
    'associates', 'assoc', 'partners', 'network', 'university', 'univ', 'st',
    'saint', 'dba',
}

ADDR_ABBREV = {
    'street': 'st', 'str': 'st', 'avenue': 'ave', 'av': 'ave',
    'boulevard': 'blvd', 'road': 'rd', 'drive': 'dr', 'lane': 'ln',
    'court': 'ct', 'circle': 'cir', 'place': 'pl', 'parkway': 'pkwy',
    'highway': 'hwy', 'terrace': 'ter', 'trail': 'trl', 'square': 'sq',
    'suite': 'ste', 'apartment': 'apt', 'building': 'bldg', 'floor': 'fl',
    'room': 'rm', 'north': 'n', 'south': 's', 'east': 'e', 'west': 'w',
    'northeast': 'ne', 'northwest': 'nw', 'southeast': 'se', 'southwest': 'sw',
    'post office': 'po', 'first': '1st', 'second': '2nd', 'third': '3rd',
    'fourth': '4th', 'fifth': '5th', 'sixth': '6th', 'seventh': '7th',
    'eighth': '8th', 'ninth': '9th', 'tenth': '10th', 'mount': 'mt',
    'fort': 'ft', 'doctor': 'dr', 'saint': 'st',
}

# City names get their own, smaller map. ADDR_ABBREV cannot be reused: it would
# turn 'Court' or 'Place' inside a city name into street-type codes. Mapping
# applies to both sides, so 'St Louis' / 'Saint Louis' and 'Ft Worth' /
# 'Fort Worth' compare equal instead of scoring 84 and 89 - below the coverage
# tier's `city >= 90` same-place test.
#
# Compass words are deliberately NOT abbreviated. Tried on 2026-10-05: shortening
# 'West' to 'w' lifts 'Des Moines' / 'West Des Moines' from 80 to 91 and
# 'Las Vegas' / 'North Las Vegas' from 75 to 90 - different cities, now past
# the `city >= 90` test - and promoted rows to the coverage Strong tier on a
# neighbouring city.
CITY_ABBREV = {'saint': 'st', 'sainte': 'ste', 'fort': 'ft', 'mount': 'mt'}

# 'N.W.' cleans to 'n w' - two tokens that never equal 'nw' or 'Northwest'.
# Applied by norm_addr only; a city has no compound directionals worth merging.
SPLIT_DIRECTIONAL_RE = re.compile(r'\b([ns]) ([ew])\b')

ALIAS_RE = re.compile(
    r'\((?:\s*(?:fka|f/k/a|aka|a/k/a|dba|d/b/a|formerly(?:\s+known\s+as)?|'
    r'now|nka)\s*)(.+?)\)', re.I)
STATUS_RE = re.compile(
    r'\(\s*(?:closed|closing|inactive|merged|new|pending|proposed|'
    r'under\s+construction|campus|satellite|reopened)[^)]*\)', re.I)


def _clean(s):
    if s is None or (isinstance(s, float) and np.isnan(s)):
        return ''
    s = str(s).lower().replace('&', ' and ')
    s = re.sub(r"[^\w\s]", ' ', s)
    return re.sub(r'\s+', ' ', s).strip()


def name_core(s):
    return ' '.join(t for t in _clean(s).split() if t not in NOISE_TOKENS)


def split_name(s):
    """Return (primary, [aliases]). Definitive embeds former names in parens."""
    if s is None or (isinstance(s, float) and np.isnan(s)):
        return '', []
    s = str(s)
    aliases = [m.strip() for m in ALIAS_RE.findall(s)]
    primary = STATUS_RE.sub(' ', ALIAS_RE.sub(' ', s))
    for extra in re.findall(r'\(([^)]*)\)', primary):
        e = extra.strip()
        if e and len(e) > 3:
            aliases.append(e)
    primary = re.sub(r'\s+', ' ', re.sub(r'\([^)]*\)', ' ', primary)).strip()
    aliases = [a for a in (STATUS_RE.sub(' ', a).strip() for a in aliases) if a]
    return primary, aliases


def norm_addr(s):
    s = _clean(s)
    if not s:
        return ''
    s = re.sub(r'\bp\s*o\s*box\b', 'po box', s)
    s = ' '.join(ADDR_ABBREV.get(t, t) for t in s.split())
    # After the abbreviations, so 'N.W.', 'N W', 'North West' and 'Northwest'
    # all reach 'nw'.
    return SPLIT_DIRECTIONAL_RE.sub(r'\1\2', s)


def norm_city(s):
    return ' '.join(CITY_ABBREV.get(t, t) for t in _clean(s).split())


def street_number(s):
    s = norm_addr(s)
    m = re.match(r'^(\d+[a-z]?)\b', s)
    if m:
        return m.group(1)
    m = re.search(r'\b(?:po )?box (\w+)', s)
    return ('box' + m.group(1)) if m else ''


def street_body(s):
    return re.sub(r'^\d+[a-z]?\s*', '', norm_addr(s)).strip()


def norm_state(s):
    s = _clean(s)
    if not s:
        return ''
    return s.upper() if len(s) == 2 else STATES.get(s, s.upper()[:2])


def norm_zip5(s):
    if s is None or (isinstance(s, float) and np.isnan(s)):
        return ''
    dg = re.sub(r'\D', '', str(s))
    if not dg:
        return ''
    return dg.zfill(5)[:5] if len(dg) < 5 else dg[:5]


def norm_phones(v):
    """Every usable 10-digit North American number in a cell, as a set.

    A cell may hold several numbers joined with '|' (the location query
    collects each location's phones that way). A leading country code 1 is
    dropped and an extension ignored; anything whose area code or exchange
    starts with 0 or 1 is not a real NANP number and is discarded.
    """
    if v is None or (isinstance(v, float) and np.isnan(v)):
        return set()
    out = set()
    for part in re.split(r'[|;,/]', str(v)):
        d = re.sub(r'\D', '', part)
        if len(d) >= 11 and d[0] == '1':
            d = d[1:]
        if len(d) >= 10 and d[0] not in '01' and d[3] not in '01':
            out.add(d[:10])
    return out


# A number held by this many distinct Definitive ids identifies none of them -
# a central scheduling line or a system switchboard. The same reasoning as the
# shared-location-name filter in decision #13.
PHONE_SHARED_MIN = 5


def phone_index(d, L):
    """({id: phones}, {phone: ids}, shared) over every HQ and service location.

    Numbers shared by PHONE_SHARED_MIN or more ids are kept in `by_id` (so a
    match on one can be recognised as inconclusive rather than read as a
    disagreement) but removed from `owners`, which drives Phone_Lookup.
    Built once over the whole reference set, so it is independent of LOC_CAP.
    """
    owners = {}
    pairs = [(d.DHC_Id, d.DHC_Phone)] if 'DHC_Phone' in d else []
    if L is not None and 'Loc_Phone' in L:
        pairs.append((L.DHC_Id, L.Loc_Phone))
    for ids, phones in pairs:
        for i, v in zip(ids, phones):
            if pd.isna(i):
                continue
            for p in norm_phones(v):
                owners.setdefault(p, set()).add(int(i))
    shared = frozenset(p for p, s in owners.items()
                       if len(s) >= PHONE_SHARED_MIN)
    by_id = {}
    for p, s in owners.items():
        for i in s:
            by_id.setdefault(i, set()).add(p)
    owners = {p: s for p, s in owners.items() if p not in shared}
    return by_id, owners, shared


def phone_match(z_phones, dhc_id, by_id, shared=frozenset()):
    """(True/False/None, the agreeing number).

    True: a number both sides hold that identifies the record. False: both
    sides hold identifying numbers and none agree. None otherwise - no usable
    number on one side, or the only overlap is a number shared by
    PHONE_SHARED_MIN+ records, which agrees but identifies nothing.
    """
    zp = set(z_phones or ())
    dp = by_id.get(int(dhc_id), set()) if pd.notna(dhc_id) else set()
    hit = zp & dp
    good = sorted(hit - shared)
    if good:
        return True, good[0]
    if hit or not (zp - shared) or not (dp - shared):
        return None, None
    return False, None


def phone_lookup(z_phones, owners):
    """The one Definitive id holding any of these numbers, or None when there
    is no holder or more than one."""
    ids = set()
    for p in z_phones or ():
        ids |= owners.get(p, set())
    return next(iter(ids)) if len(ids) == 1 else None


def add_phone_columns(df, id_col, d, by_id, owners, shared, prefix='Phone'):
    """Phone_Match / Matched_Phone for the id in `id_col`, plus Phone_Lookup_*
    (the single Definitive record holding the entity's number) and
    Phone_Points_Elsewhere (no match here, but the number is someone else's).

    `df` must carry Z_Phones (a list per row, from _pool).
    """
    res = [phone_match(zp, i, by_id, shared)
           for zp, i in zip(df.Z_Phones, df[id_col])]
    df[f'{prefix}_Match'] = pd.array([r[0] for r in res], dtype='boolean')
    df[f'Matched_{prefix}'] = [r[1] for r in res]
    look = [phone_lookup(zp, owners) for zp in df.Z_Phones]
    df['Phone_Lookup_DHC_Id'] = pd.array(look, dtype='Int64')
    names = d.drop_duplicates('DHC_Id').set_index('DHC_Id').DHC_Name
    df['Phone_Lookup_Name'] = df.Phone_Lookup_DHC_Id.map(names)
    ids = pd.to_numeric(df[id_col], errors='coerce').astype('Int64')
    df['Phone_Points_Elsewhere'] = (df[f'{prefix}_Match'].eq(False).fillna(False)
                                    & df.Phone_Lookup_DHC_Id.notna()
                                    & df.Phone_Lookup_DHC_Id.ne(ids).fillna(True))
    return df


# ============================================================================
# Scoring
# ============================================================================
TS_W, TR_W = 0.35, 0.65
ADDR_W = np.array([0.30, 0.22, 0.18, 0.08, 0.22])  # stnum, stbody, city, state, zip
BLEND_W = {'name': 0.40, 'stnum': 0.20, 'stname': 0.15,
           'city': 0.10, 'state': 0.05, 'zip': 0.10}


def pair_score(a, b):
    """token_set_ratio returns 100 on subsets; blending with token_sort_ratio
    penalises the length gap that hides ('Reid Health' vs 'Reid Health X')."""
    return TS_W * fuzz.token_set_ratio(a, b) + TR_W * fuzz.token_sort_ratio(a, b)


def name_score(z_names, d_primary, d_aliases):
    d_all = [x for x in [d_primary] + list(d_aliases or []) if x]
    z_all = [x for x in z_names if x]
    if not d_all or not z_all:
        return 0.0
    best = 0.0
    for zn in z_all:
        zf, zc = _clean(zn), name_core(zn)
        for dn in d_all:
            df_, dc = _clean(dn), name_core(dn)
            s = pair_score(zf, df_)
            if zc and dc:
                s = max(s, pair_score(zc, dc))
            if s > best:
                best = s
                if best >= 100:
                    return 100.0
    return float(best)


def name_provenance(z_names, primary, aliases, loc_names):
    """Which strings produced the winning name score, and how.

    Mirrors name_score() - the same pairs, the same first-strictly-greater
    tie-break - so its score equals name_score() over primary + aliases +
    loc_names. name_score() hides its own reasoning; reviewers need it. A match
    on the entity's own name is identity evidence, while a match on a service
    location's name is evidence about a satellite.

    Returns (score, zeus_text, definitive_text, via, core_tokens) where `via` is
    Name | Alias | Location and `core_tokens` counts the tokens in the winning
    Definitive core - 1 means a generic single word, the case CLAUDE.md's
    "How name_core behaves on practices" section warns about.
    """
    cands = [(primary, 'Name')] + [(a, 'Alias') for a in (aliases or [])] + \
            [(n, 'Location') for n in (loc_names or [])]
    best = (0.0, '', '', '', 0)
    for zn in z_names:
        if not zn:
            continue
        zf, zc = _clean(zn), name_core(zn)
        for dn, via in cands:
            if not dn:
                continue
            df_, dc = _clean(dn), name_core(dn)
            s = pair_score(zf, df_)
            core_used = False
            if zc and dc:
                sc = pair_score(zc, dc)
                if sc > s:
                    s, core_used = sc, True
            if s > best[0]:
                best = (float(s), zn, dn, via,
                        len((dc if core_used else df_).split()))
    return best


def addr_scores(z_lines, d_lines):
    """Best pair across all address-line combinations; Zeus's street line is
    not always in the first column.

    Returns (street_number_score, street_body_score, winning_d_index,
    winning_z_line). The index identifies which Definitive line won, so the
    caller can tell an HQ match from a service-location match; the Zeus line
    says which of the pooled Zeus addresses it was compared with.
    """
    zc = [x for x in z_lines if x and str(x).strip()]
    dc = [(i, x) for i, x in enumerate(d_lines) if x and str(x).strip()]
    if not zc or not dc:
        return np.nan, np.nan, None, None
    best = (-1.0, np.nan, np.nan, None, None)
    for zl in zc:
        zn, zb = street_number(zl), street_body(zl)
        for di, dl in dc:
            dn, db = street_number(dl), street_body(dl)
            ns = (100.0 if zn == dn else 0.0) if (zn and dn) else np.nan
            bs = float(fuzz.ratio(zb, db)) if (zb and db) else np.nan
            tot = (0 if np.isnan(ns) else ns) + (0 if np.isnan(bs) else bs)
            if tot > best[0]:
                best = (tot, ns, bs, di, zl)
    return best[1], best[2], best[3], best[4]


def weighted(parts, weights):
    p = np.asarray(parts, dtype='float64')
    m = ~np.isnan(p)
    if not m.any():
        return np.nan
    w = np.asarray(weights, dtype='float64')
    return float(np.where(m, p, 0).dot(w) / w[m].sum())


def verdict(name, addr):
    if pd.isna(name):
        return 'Unscored'
    a = 0.0 if pd.isna(addr) else addr
    if name >= 92 or (name >= 75 and a >= 60):
        return 'ID corroborated'
    if name >= 75:
        return 'Probable - name agrees, address differs'
    if a >= 85 and name >= 45:
        return 'Probable - address agrees, name differs'
    return 'Needs review' if (name >= 45 or a >= 50) else 'Likely wrong ID'


# ============================================================================
# Column-role detection
# ============================================================================
ROLES = ('id', 'name', 'address', 'city', 'state', 'zip')
ID_EXCLUDE = re.compile(
    r'(tax|npi|network|parent|gpo|cbsa|340b|provider|sf|stock|dea|ccn|medicare)', re.I)


def guess_mapping(df):
    """Infer which columns hold id/name/address/city/state/zip.

    Primary heuristic: Definitive names its key pair <Entity>Id / <Entity>Name
    (HospitalId + HospitalName, PhysicianGroupId + PhysicianGroupName). Finding
    a matched prefix pair is far more reliable than pattern-matching 'Id',
    which also hits TaxId, IdNetwork, PrimaryGpoId and similar.
    """
    cols = list(df.columns)
    lower = {c.lower(): c for c in cols}
    out = {r: None for r in ROLES}

    for c in cols:
        m = re.match(r'^(.*?)id$', c, re.I)
        if not m or ID_EXCLUDE.search(c):
            continue
        prefix = m.group(1)
        if not prefix:
            continue
        mate = lower.get(f'{prefix}name'.lower())
        if mate:
            out['id'], out['name'] = c, mate
            break

    if out['id'] is None:  # fall back to the first non-excluded *Id column
        for c in cols:
            if re.search(r'id$', c, re.I) and not ID_EXCLUDE.search(c):
                out['id'] = c
                break
    if out['name'] is None:
        for c in cols:
            if re.search(r'name$', c, re.I) and not ID_EXCLUDE.search(c):
                out['name'] = c
                break

    addr = [c for c in cols if re.search(r'address', c, re.I)
            and not re.search(r'(email|url|web|ip)', c, re.I)]
    out['address'] = addr or None
    for role, pat, excl in [('city', r'city', r'cbsa'),
                            ('state', r'state', r'estate|statement'),
                            ('zip', r'zip|postal', r'')]:
        for c in cols:
            if re.search(pat, c, re.I) and (not excl or not re.search(excl, c, re.I)):
                out[role] = c
                break
    return out


def cmd_inspect(paths):
    blocks = []
    for p in paths:
        df = pd.read_excel(p, nrows=200) if not str(p).lower().endswith(
            ('.csv', '.tsv')) else pd.read_csv(p, nrows=200)
        g = guess_mapping(df)
        print(f'\n=== {os.path.basename(p)} ===')
        print(f'{len(df.columns)} columns. Detected roles:')
        for r in ROLES:
            v = g[r]
            flag = '' if v else '   <-- NOT FOUND, set manually'
            print(f'   {r:8} : {v}{flag}')
        print('\nAll columns:')
        for i, c in enumerate(df.columns):
            print(f'   {i:>3} {c}')
        # Case- and separator-insensitive: exports use HospitalId as well as
        # HOSPITAL_ID, and a bare 'Id$' strip leaves the latter unchanged.
        ent = re.sub(r'[_\s]*id$', '', g['id'] or 'Unknown', flags=re.I)
        blocks.append({
            'path': os.path.abspath(p), 'entity_type': ent or 'Unknown',
            'id': g['id'], 'name': g['name'],
            'address': g['address'] or [], 'city': g['city'],
            'state': g['state'], 'zip': g['zip'],
        })

    cfg = {'zeus': {
        'query_file': 'CHANGE_ME_Zeus_query.sql',
        'connection': {
            'driver': 'ODBC Driver 18 for SQL Server',
            'host': 'CHANGE_ME.database.windows.net', 'port': 1433,
            'database': 'Zeus', 'user': 'CHANGE_ME',
            'password_env': 'ZEUS_SQL_PASSWORD',
            'encrypt': True, 'trust_server_certificate': True,
            'application_intent': 'ReadOnly', 'multi_subnet_failover': True,
        },
        'id_columns': ['Entity_DHC_VerifiedSourceId', 'LEVS_DHC_VerifiedSourceId'],
        'key': 'EntityId',
        'name': ['EntityName', 'ClientInfoName'],
        'address': ['ClientAddress1', 'ClientAddress2', 'ClientAddress3'],
        'city': 'ClientCity', 'state': 'ClientState', 'zip': 'ClientZip',
    }, 'definitive': blocks}

    print('\n' + '=' * 70)
    print('Starting config (review the detected roles, then save as sources.yaml):')
    print('=' * 70)
    try:
        import yaml
        print(yaml.safe_dump(cfg, sort_keys=False, default_flow_style=False))
    except ImportError:
        print(json.dumps(cfg, indent=2))


# ============================================================================
# Run
# ============================================================================
def read_any(path, **kw):
    if str(path).lower().endswith(('.csv', '.tsv')):
        return pd.read_csv(path, sep=None, engine='python', **kw)
    if str(path).lower().endswith('.parquet'):
        df = pd.read_parquet(path)
        use = kw.get('usecols')
        return df[[c for c in df.columns if use(c)]] if callable(use) else df
    return pd.read_excel(path, **kw)


# ============================================================================
# Run folders
# ============================================================================
RESULTS_DIR = 'Results Output'


def new_run_prefix(program, label=None, root=RESULTS_DIR):
    """Create this run's own folder and return the file prefix inside it.

    Every run writes to <root>/<program>_<YYYY_MM_DD_HHMM>[_<label>]/, and each
    file in it is named <folder>_<suffix>, so a file copied out of the folder
    still says which program and which run wrote it. The workbook builders
    derive a run's sibling files from that prefix and write beside them.
    """
    run = f'{program}_{time.strftime("%Y_%m_%d_%H%M")}'
    if label:
        run += f'_{label}'
    folder, n = os.path.join(root, run), 2
    while os.path.exists(folder):     # two runs in the same minute
        folder, n = os.path.join(root, f'{run}_{n}'), n + 1
    os.makedirs(folder)
    print(f'Run folder  : {folder}')
    return os.path.join(folder, os.path.basename(folder))


def resolve_prefix(p):
    """A run prefix, or a run folder standing for the prefix of the files in it.

    Folders from before 2026-09-29 hold files named for the old --out prefix
    (audit_2026_08_12_*), not for the folder, so the prefix is read off the one
    extract inside rather than assumed from the folder name.
    """
    if not os.path.isdir(p):
        return p
    hits = [f for f in os.listdir(p) if f.endswith('_zeus_extract.csv')]
    if len(hits) != 1:
        raise SystemExit(f'{p} holds {len(hits)} *_zeus_extract.csv files; '
                         f'pass the run prefix instead of the folder.')
    return os.path.join(p, hits[0][:-len('_zeus_extract.csv')])


# ============================================================================
# Definitive sources held in Databricks
# ============================================================================
ROLE_KEYS = ('id', 'name', 'address', 'city', 'state', 'zip', 'phone')


def _role_columns(b):
    cols = []
    for k in ROLE_KEYS:
        v = b.get(k)
        cols += list(v) if isinstance(v, list) else ([v] if v else [])
    return list(dict.fromkeys(cols))


def _dbx_connect(c):
    """SQL-warehouse connection authenticated through a Databricks CLI profile.

    The profile holds the OAuth login (`databricks auth login --profile ...`),
    so no secret lives in the config or the environment.
    """
    from databricks import sql
    from databricks.sdk.core import Config
    if not c.get('warehouse_id'):
        raise SystemExit('databricks.warehouse_id is required in the config.')
    dc = Config(profile=c.get('profile'), host=c.get('host'))
    return sql.connect(server_hostname=dc.host.replace('https://', ''),
                       http_path=f'/sql/1.0/warehouses/{c["warehouse_id"]}',
                       credentials_provider=lambda: dc.authenticate)


def _dbx_source(b):
    """(label, snapshot name, SQL) for a Databricks block.

    `query_file` runs a .sql file as written; `table` is shorthand for a SELECT
    of the role columns. The snapshot name is `snapshot:` when given, so
    renaming the .sql file never changes what a run's snapshot is called.
    """
    if b.get('query_file'):
        qf = b['query_file']
        if not b.get('snapshot'):
            raise SystemExit(f'Definitive block with query_file "{qf}" needs a '
                             f'`snapshot:` name in the config.')
        return os.path.basename(qf), b['snapshot'], open(qf, newline='').read()
    cols = ', '.join(f'`{x}`' for x in _role_columns(b))
    return (b['table'], b.get('snapshot') or b['table'].split('.')[-1],
            f'SELECT {cols} FROM {b["table"]}')


def dbx_snapshot_path(prefix, name):
    return f'{prefix}_dhc_{name}.parquet'


def materialise_tables(cfg, prefix, replay=False, copy_to=None):
    """Swap every Databricks source for a parquet snapshot beside the run outputs.

    Databricks is live, so an xlsx no longer pins the reference data. Each
    source is queried once per run, written to <prefix>_dhc_<snapshot>.parquet
    with the SQL that produced it beside it as .sql, and the block repointed at
    the parquet; everything downstream reads a file as before. With `replay`
    the snapshot is reused instead of querying - the workbook builders do this
    so a workbook describes the data its run actually scored. A run replaying
    another run's snapshots passes `copy_to` (its own prefix): the snapshots
    are copied into its folder, so every run folder holds its own inputs.
    """
    blocks = [b for b in (cfg.get('definitive') or []) +
              (cfg.get('locations') or [])
              if b.get('query_file') or b.get('table')]
    if not blocks:
        return
    if replay:
        for b in blocks:
            label, name, _ = _dbx_source(b)
            snap = dbx_snapshot_path(prefix, name)
            if not os.path.exists(snap):
                # Reading live here would describe different data from the run.
                raise SystemExit(
                    f'No Definitive snapshot {snap} for {label}.\n'
                    f'  The run that wrote {prefix}_* either predates Databricks '
                    f'sourcing or its snapshot was moved; keep the snapshot '
                    f'with the run outputs.')
            if copy_to:
                dst = dbx_snapshot_path(copy_to, name)
                for ext in ('.parquet', '.sql'):
                    src = snap[:-len('.parquet')] + ext
                    if os.path.exists(src):
                        shutil.copyfile(src, dst[:-len('.parquet')] + ext)
                print(f'  {label}: snapshot {snap} -> {dst}')
                snap = dst
            else:
                print(f'  {label}: snapshot {snap}')
            b['path'] = snap
        return
    c = cfg.get('databricks') or {}
    print(f'Databricks  : {c.get("host")} (warehouse {c.get("warehouse_id")})')
    with _dbx_connect(c) as cx, cx.cursor() as cur:
        for b in blocks:
            label, name, q = _dbx_source(b)
            cur.execute(q)
            df = cur.fetchall_arrow().to_pandas()
            missing = [x for x in _role_columns(b) if x not in df.columns]
            if missing:
                raise SystemExit(
                    f'Definitive source "{label}" is missing column(s): '
                    f'{missing}\n  returned: {list(df.columns)}\n'
                    f'  fix sources.yaml or the query so they match.')
            snap = dbx_snapshot_path(prefix, name)
            df.to_parquet(snap, index=False)
            # newline='' so the copy is byte-identical to the .sql it came from.
            with open(snap[:-len('.parquet')] + '.sql', 'w', newline='') as f:
                f.write(q)
            print(f'  {label}: {len(df):,} rows -> {snap}')
            b['path'] = snap


def load_config(path):
    txt = open(path).read()
    if path.lower().endswith(('.yaml', '.yml')):
        import yaml
        return yaml.safe_load(txt)
    return json.loads(txt)


# Expected distinct-entity count across the six populations, so drift is visible
# run to run. Update it deliberately when the population genuinely changes.
#
# Not to be confused with the 207,450-row file-era extract: that predated the
# EntityDescription exclusion and was ~95.6% Definitive-import-created records
# (198,395 of 207,598 measured 2026-07-31). Comparing against it would report a
# 95% "drop" that is a change of scope, not a regression.
ZEUS_BASELINE_ENTITIES = 12_803


def _conn_str(c):
    """ODBC connection string from the `connection` block.

    ApplicationIntent is config-driven: the host is a failover-group listener
    and reaching the readable secondary requires declaring the intent, but a
    future non-replica host should not need a code change.
    """
    pw_env = c.get('password_env')
    if not pw_env:
        raise SystemExit('zeus.connection.password_env is required '
                         '(the password must not live in the config file)')
    pw = os.environ.get(pw_env)
    if not pw:
        raise SystemExit(f'Environment variable {pw_env} is not set. '
                         f'Set it to the {c.get("user")} password and re-run.')
    parts = [
        f'DRIVER={{{c.get("driver", "ODBC Driver 18 for SQL Server")}}}',
        f'SERVER={c["host"]},{c.get("port", 1433)}',
        f'DATABASE={c["database"]}',
        f'UID={c["user"]}', f'PWD={pw}',
        f'Encrypt={"yes" if c.get("encrypt", True) else "no"}',
        f'TrustServerCertificate='
        f'{"yes" if c.get("trust_server_certificate") else "no"}',
    ]
    if c.get('application_intent'):
        parts.append(f'ApplicationIntent={c["application_intent"]}')
    if c.get('multi_subnet_failover'):
        parts.append('MultiSubnetFailover=Yes')
    if c.get('connect_timeout'):
        parts.append(f'Connect Timeout={c["connect_timeout"]}')
    return ';'.join(parts)


# Canonical shape every Zeus population is mapped onto, so downstream code is
# free of per-population column names.
Z_NAMES = ['Z_Name1', 'Z_Name2']
Z_ADDRS = ['Z_Addr1', 'Z_Addr2', 'Z_Addr3']
Z_CANON = ['EntityId', 'Zeus_Source'] + Z_NAMES + Z_ADDRS + \
          ['Z_City', 'Z_State', 'Z_Zip']


def _canonicalise(df, src, idc, label):
    """Map one population's columns onto the canonical schema."""
    wanted = list(src.get('name') or []) + list(src.get('address') or []) + \
        [src.get('city'), src.get('state'), src.get('zip')] + list(idc) + \
        ['EntityId']
    missing = [c for c in wanted if c and c not in df.columns]
    if missing:
        raise SystemExit(
            f'Zeus population "{label}" is missing column(s): {missing}\n'
            f'  available: {list(df.columns)}\n'
            f'  fix sources.yaml or the query so they match.')
    names = list(src.get('name') or [])
    addrs = list(src.get('address') or [])
    out = pd.DataFrame({'EntityId': df['EntityId'], 'Zeus_Source': label})
    for i, c in enumerate(Z_NAMES):
        out[c] = df[names[i]] if i < len(names) else None
    for i, c in enumerate(Z_ADDRS):
        out[c] = df[addrs[i]] if i < len(addrs) else None
    out['Z_City'] = df[src['city']] if src.get('city') else None
    out['Z_State'] = df[src['state']] if src.get('state') else None
    out['Z_Zip'] = df[src['zip']] if src.get('zip') else None
    for c in idc:
        out[c] = df[c]
    return out


def _pool(u, idc):
    """One row per EntityId, pooling every population's names and addresses.

    An entity in both IsClient and IsWorkLocation has two names and two
    addresses on record. Neither is authoritative, so both become candidates
    and the best match wins - the same rule applied to Definitive locations.
    """
    def uniq(vals):
        return [v for v in dict.fromkeys(vals)
                if isinstance(v, str) and v.strip()]

    rows = []
    for eid, g in u.groupby('EntityId', sort=False):
        ids = {}
        for c in idc:
            v = pd.to_numeric(g[c], errors='coerce').dropna()
            ids[c] = int(v.iloc[0]) if len(v) else None
        srcs = sorted(dict.fromkeys(g.Zeus_Source))
        # Which population(s) hold each name, so a verdict can say whether it
        # rests on, say, the Client name or the Work Location name.
        # Likewise where each address line sits (its row's city/state/zip), so
        # the matched Zeus line is shown with its own place, not every pooled
        # city. First row with the line wins.
        name_src, addr_geo = {}, {}
        for r in g.itertuples(index=False):
            for c in Z_NAMES:
                v = getattr(r, c)
                if isinstance(v, str) and v.strip():
                    name_src.setdefault(v, set()).add(r.Zeus_Source)
            for c in Z_ADDRS:
                v = getattr(r, c)
                if isinstance(v, str) and v.strip() and v not in addr_geo:
                    addr_geo[v] = (r.Z_City, r.Z_State,
                                   r.Z_Zip if pd.notna(r.Z_Zip) else None)
        rows.append({
            'EntityId': eid,
            'Zeus_Sources': '|'.join(srcs),
            'Zeus_Source_Count': len(srcs),
            'Z_Name_Sources': {k: '|'.join(sorted(v))
                               for k, v in name_src.items()},
            'Z_Addr_Geo': addr_geo,
            # Every population's numbers, pooled like names and addresses.
            # norm_phones, not a split: a replayed CSV may read one number as
            # a float ('5551234567.0').
            'Z_Phones': sorted({p for v in g.Z_Phones.dropna()
                                for p in norm_phones(v)}),
            'Z_Names': uniq([v for c in Z_NAMES for v in g[c]]),
            'Z_Addrs': uniq([v for c in Z_ADDRS for v in g[c]]),
            'Z_Cities': uniq(g.Z_City),
            'Z_States': uniq(g.Z_State),
            'Z_Zips': [x for x in dict.fromkeys(g.Z_Zip) if pd.notna(x)],
            **ids,
        })
    return pd.DataFrame(rows)


def _attach_phones(u, phones):
    """Add Z_Phones - that population row's usable numbers, '|'-joined.

    `phones` is the phone query's result: EntityId, Zeus_Source (a population
    label) and Phone. Keyed on the population as well as the entity, because
    each *Info table holds its own numbers, just as it holds its own name and
    address. Stored in the extract so a replay has the same phones.
    """
    if phones is None or not len(phones):
        u['Z_Phones'] = None
        return u
    ph = phones.assign(_p=phones.Phone.map(norm_phones))
    ph = ph[ph._p.map(len) > 0]
    agg = (ph.groupby(['EntityId', 'Zeus_Source'])._p
           .agg(lambda s: '|'.join(sorted(set().union(*s)))).rename('Z_Phones'))
    return u.merge(agg.reset_index(), on=['EntityId', 'Zeus_Source'], how='left')


def load_zeus(zc, out_prefix=None):
    """Every Zeus population, canonicalised, unioned and pooled by EntityId.

    `sources` reads the database (one query per population); `path` replays an
    archived canonical union for an offline re-run.
    """
    idc = list(zc.get('id_columns') or [])
    if zc.get('path'):
        print(f'Zeus source : {zc["path"]} (archived extract)')
        u = read_any(zc['path'])
        missing = [c for c in Z_CANON + idc if c not in u.columns]
        if missing:
            raise SystemExit(f'Archived extract is missing {missing}; it must '
                             f'be a <prefix>_zeus_extract.csv from a live run.')
        if 'Z_Phones' not in u.columns:
            print('  note: this extract predates phone capture (2026-09-29); '
                  'Phone_Match will be blank throughout.')
            u['Z_Phones'] = None
    else:
        import pyodbc
        c = zc.get('connection') or {}
        srcs = zc.get('sources') or []
        if not srcs:
            raise SystemExit('zeus config needs `sources` (or `path`).')
        print(f'Zeus source : {c.get("database")} on {c.get("host")}')
        print(f'  intent    : {c.get("application_intent", "ReadWrite")}')
        # Which key names the query file. The missing-id audit reuses these
        # same role mappings against a different query per population, so it
        # sets query_key rather than duplicating the `sources` block.
        qk = zc.get('query_key', 'query_file')
        frames = []
        with pyodbc.connect(_conn_str(c)) as cx:
            upd = cx.execute(
                "SELECT DATABASEPROPERTYEX(DB_NAME(), 'Updateability')"
            ).fetchval()
            print(f'  connected to a {upd} database')
            if c.get('application_intent') == 'ReadOnly' and upd != 'READ_ONLY':
                print('  WARNING: ReadOnly intent was requested but this '
                      'connection landed on a writable database.')
            for s in srcs:
                qf = s.get(qk)
                if not qf:
                    raise SystemExit(f'Zeus population "{s.get("label")}" has '
                                     f'no `{qk}` in the config.')
                label = s.get('label') or os.path.basename(qf)
                raw = pd.read_sql(open(qf).read(), cx)
                frames.append(_canonicalise(raw, s, idc, label))
                print(f'  {label:14} {len(raw):>7,} rows  '
                      f'({os.path.basename(qf)})')
            phones = None
            if zc.get('phone_query_file'):
                pq = zc['phone_query_file']
                phones = pd.read_sql(open(pq).read(), cx)
                print(f'  {"phones":14} {len(phones):>7,} rows  '
                      f'({os.path.basename(pq)})')
        u = pd.concat(frames, ignore_index=True)
        u = _attach_phones(u, phones)

    # LinkEntityVerifiedSource can return several rows per entity within one
    # population; collapse those before pooling across populations.
    before = len(u)
    u = u.drop_duplicates(subset=['EntityId', 'Zeus_Source'] + Z_NAMES +
                          Z_ADDRS, keep='first')
    if len(u) < before:
        print(f'  collapsed {before - len(u):,} duplicate population rows')

    if out_prefix:
        snap = f'{out_prefix}_zeus_extract.csv'
        u.to_csv(snap, index=False)
        print(f'  extract snapshot -> {snap}  ({len(u):,} rows)')

    z = _pool(u, idc)
    multi = int((z.Zeus_Source_Count > 1).sum())
    print(f'Zeus rows   : {len(u):,} population rows -> {len(z):,} distinct '
          f'entities')
    print(f'  {multi:,} entities appear in more than one population '
          f'(names and addresses pooled)')
    base = zc.get('baseline_entities', ZEUS_BASELINE_ENTITIES)
    delta = (len(z) - base) if base else 0
    if delta:
        print(f'  NOTE: {delta:+,} vs the expected '
              f'{base:,} entities. Expected drift as Zeus '
              f'changes; investigate anything large, then update the '
              f'baseline.')
    return z.reset_index(drop=True)


def _read_roles(b, cols):
    """Read only the configured role columns from one export."""
    use = [b.get(k) for k in cols if not isinstance(b.get(k), list)]
    use += [c for k in cols for c in (b.get(k) or []) if isinstance(b.get(k), list)]
    use = [c for c in use if c]
    return read_any(b['path'], usecols=lambda c, u=set(use): c in u)


def _identity_frame(b):
    df = _read_roles(b, ROLE_KEYS)
    ac = [c for c in (b.get('address') or []) if c in df.columns]
    return pd.DataFrame({
        'DHC_Id': pd.to_numeric(df[b['id']], errors='coerce').astype('Int64'),
        'DHC_Entity_Type': b.get('entity_type', 'Unknown'),
        'DHC_Name': df[b['name']].astype('object'),
        'DHC_Addr1': df[ac[0]] if len(ac) > 0 else None,
        'DHC_Addr2': df[ac[1]] if len(ac) > 1 else None,
        'DHC_City': df[b['city']] if b.get('city') else None,
        'DHC_State': df[b['state']] if b.get('state') else None,
        'DHC_Zip': df[b['zip']] if b.get('zip') else None,
        'DHC_Phone': df[b['phone']] if b.get('phone') else None,
    })


def load_definitive(blocks, extra_identity=None):
    """Stack every Definitive identity export into one reference frame with a
    canonical schema, tagged by entity type.

    `extra_identity` carries rows synthesised from the location file for ids
    that have no overview record - see `locations_as_identity`.
    """
    frames = []
    for b in blocks:
        out = _identity_frame(b)
        print(f'  loaded {len(out):>8,}  {b.get("entity_type")}  '
              f'({os.path.basename(b["path"])})')
        frames.append(out)
    if extra_identity is not None and len(extra_identity):
        print(f'  loaded {len(extra_identity):>8,}  PracticeLocation  '
              f'(ids with no overview record)')
        frames.append(extra_identity)

    d = pd.concat(frames, ignore_index=True).dropna(subset=['DHC_Id'])
    dupes = d.DHC_Id.duplicated().sum()
    if dupes:
        print(f'  WARNING: {dupes:,} duplicate Definitive ids across exports; '
              f'keeping first occurrence')
        d = d.drop_duplicates(subset=['DHC_Id'], keep='first')
    sp = d['DHC_Name'].map(split_name)
    d['d_primary'] = [p for p, a in sp]
    d['d_aliases'] = [a for p, a in sp]
    d['d_city_n'] = d['DHC_City'].map(norm_city)
    d['d_state'] = d['DHC_State'].map(norm_state)
    d['d_zip5'] = d['DHC_Zip'].map(norm_zip5)
    return d.reset_index(drop=True)


# Per-id ceiling on location names and addresses fed into scoring. One id has
# 962 locations; scoring every one against every Zeus name line is wasted work
# long before that. Capping is reported, never silent.
LOC_CAP = 250


def load_locations(blocks):
    """Service-location rows: MANY per Definitive id.

    The id is the parent entity's, so these are never identity rows - they
    enrich the entity they belong to.
    """
    if not blocks:
        return None
    frames = []
    for b in blocks:
        df = _read_roles(b, ROLE_KEYS)
        ac = [c for c in (b.get('address') or []) if c in df.columns]
        out = pd.DataFrame({
            'DHC_Id': pd.to_numeric(df[b['id']], errors='coerce').astype('Int64'),
            'Loc_Name': df[b['name']].astype('object') if b.get('name') else None,
            'Loc_Addr1': df[ac[0]] if len(ac) > 0 else None,
            'Loc_Addr2': df[ac[1]] if len(ac) > 1 else None,
            'Loc_City': df[b['city']] if b.get('city') else None,
            'Loc_State': df[b['state']] if b.get('state') else None,
            'Loc_Zip': df[b['zip']] if b.get('zip') else None,
            'Loc_Phone': df[b['phone']] if b.get('phone') else None,
        })
        print(f'  loaded {len(out):>8,}  locations  '
              f'({os.path.basename(b["path"])})')
        frames.append(out)
    L = pd.concat(frames, ignore_index=True).dropna(subset=['DHC_Id'])
    print(f'           {L.DHC_Id.nunique():>8,}  distinct ids carry locations')
    return L


def locations_as_identity(L, known_ids):
    """Identity rows for ids present only in the location file."""
    if L is None:
        return None
    extra = L[~L.DHC_Id.isin(known_ids)]
    if not len(extra):
        return None
    first = extra.groupby('DHC_Id', sort=False).first().reset_index()
    return pd.DataFrame({
        'DHC_Id': first.DHC_Id,
        'DHC_Entity_Type': 'PracticeLocation',
        'DHC_Name': first.Loc_Name,
        'DHC_Addr1': first.Loc_Addr1, 'DHC_Addr2': first.Loc_Addr2,
        'DHC_City': first.Loc_City, 'DHC_State': first.Loc_State,
        'DHC_Zip': first.Loc_Zip,
        'DHC_Phone': first.Loc_Phone if 'Loc_Phone' in first else None,
    })


def location_index(L, need_ids):
    """{id: {names, addrs, cities, states, zips}} for the ids we will score."""
    if L is None:
        return {}, 0
    L = L[L.DHC_Id.isin(need_ids)]
    idx, capped = {}, 0
    for key, g in L.groupby('DHC_Id', sort=False):
        names = [x for x in dict.fromkeys(g.Loc_Name)
                 if isinstance(x, str) and x.strip()]
        addrs = [x for x in dict.fromkeys(
            list(g.Loc_Addr1) + list(g.Loc_Addr2))
            if isinstance(x, str) and x.strip()]
        if len(names) > LOC_CAP or len(addrs) > LOC_CAP:
            capped += 1
        # Where each address line is, as Definitive wrote it, so a matched
        # satellite line can be shown with its own city/state/zip rather than
        # the HQ's. First location with the line wins.
        geo = {}
        for r in g.itertuples(index=False):
            for a in (r.Loc_Addr1, r.Loc_Addr2):
                if isinstance(a, str) and a.strip() and a not in geo:
                    geo[a] = (r.Loc_City, r.Loc_State, r.Loc_Zip)
        idx[int(key)] = {
            'n': len(g),
            'names': names[:LOC_CAP], 'addrs': addrs[:LOC_CAP],
            'addr_geo': geo,
            'cities': {norm_city(x) for x in g.Loc_City
                       if isinstance(x, str)} - {''},
            'states': {norm_state(x) for x in g.Loc_State
                       if isinstance(x, str)} - {''},
            'zips': {norm_zip5(x) for x in g.Loc_Zip} - {''},
        }
    return idx, capped


def enriched_scores(z_names, z_lines, zcities, zstates, zzips, ent, loc):
    """Every score for one Zeus entity against one Definitive entity.

    Both sides are multi-valued: Zeus pools names and addresses across every
    population the entity belongs to, and the Definitive side offers its HQ plus
    every known service location. Each component takes the best available
    match, so extra candidates can only ever raise a score.

    The 8th element says which address pair produced the street scores:
    {'zeus_addr', 'dhc_addr', 'dhc_geo'}, where dhc_geo is the matched service
    location's (city, state, zip) and None for an HQ line or no match.
    """
    aliases = list(ent['aliases'] or []) + (loc['names'] if loc else [])
    nm = name_score(z_names, ent['primary'], aliases)

    hq_lines = [x for x in ent['lines'] if x and str(x).strip()]
    d_lines = hq_lines + (loc['addrs'] if loc else [])
    an, ab, src, zline = addr_scores(z_lines, d_lines)
    source = '' if src is None else ('HQ' if src < len(hq_lines) else 'Location')
    dline = None if src is None else d_lines[src]
    prov = {'zeus_addr': zline, 'dhc_addr': dline, 'source': source,
            'dhc_geo': (loc.get('addr_geo', {}).get(dline)
                        if source == 'Location' else None)}

    cities = ([ent['city']] if ent['city'] else []) + \
             (sorted(loc['cities']) if loc else [])
    cs = max((float(fuzz.ratio(zc, c)) for zc in zcities for c in cities),
             default=np.nan) if (zcities and cities) else np.nan

    states = ({ent['state']} if ent['state'] else set()) | \
             (loc['states'] if loc else set())
    st = (100.0 if (set(zstates) & states) else 0.0) \
        if (zstates and states) else np.nan

    zips = ({ent['zip']} if ent['zip'] else set()) | \
           (loc['zips'] if loc else set())
    zp = (100.0 if (set(zzips) & zips) else 0.0) if (zzips and zips) else np.nan
    return nm, an, ab, cs, st, zp, source, prov


# The address pair behind Address_Score, one set per side. Definitive city/state/
# zip are the matched line's own - a satellite's for a Location match, the HQ's
# otherwise. City_Score and Zip_Score are still computed across every known site.
MATCHED_ADDR_COLS = ['Matched_Zeus_Address', 'Matched_Zeus_City',
                     'Matched_Zeus_State', 'Matched_Zeus_Zip',
                     'Matched_Definitive_Address', 'Matched_Definitive_City',
                     'Matched_Definitive_State', 'Matched_Definitive_Zip']


def matched_address(prov, z_addr_geo, hq_geo):
    """The eight MATCHED_ADDR_COLS values for one scored pair.

    `z_addr_geo` is the entity's {address: (city, state, zip)} from _pool;
    `hq_geo` is the Definitive record's HQ (city, state, zip).
    """
    za, da = prov.get('zeus_addr'), prov.get('dhc_addr')
    zg = (z_addr_geo or {}).get(za, (None,) * 3) if za else (None,) * 3
    if not da:
        dg = (None,) * 3
    elif prov.get('source') == 'HQ':
        dg = hq_geo
    else:
        dg = prov.get('dhc_geo') or (None,) * 3
    return (za, *zg, da, *dg)


def cmd_run(cfg, out_prefix, reverse=True, definitive_from=None):
    zc = cfg['zeus']
    z = load_zeus(zc, out_prefix)

    print('\nDefinitive tables:')
    if definitive_from:
        materialise_tables(cfg, definitive_from, replay=True,
                           copy_to=out_prefix)
    else:
        materialise_tables(cfg, out_prefix)

    print('\nDefinitive location sources:')
    L = load_locations(cfg.get('locations'))

    print('\nDefinitive identity sources:')
    known = set()
    for b in cfg['definitive']:
        col = pd.to_numeric(_read_roles(b, ('id',))[b['id']], errors='coerce')
        known |= set(col.dropna().astype('int64'))
    d = load_definitive(cfg['definitive'], locations_as_identity(L, known))
    print(f'  total reference records: {len(d):,}\n')

    idc = zc['id_columns']
    resolved = None
    src = pd.Series('None', index=z.index)
    for c in idc:
        v = pd.to_numeric(z[c], errors='coerce')
        resolved = v if resolved is None else resolved.fillna(v)
        src = src.where(~(src.eq('None') & v.notna()), c)
    z['DHC_Id'] = resolved.astype('Int64')
    z['DHC_Id_Source'] = src
    if len(idc) > 1:
        a = pd.to_numeric(z[idc[0]], errors='coerce')
        b = pd.to_numeric(z[idc[1]], errors='coerce')
        z['DHC_Id_Conflict'] = a.notna() & b.notna() & (a != b)
    else:
        z['DHC_Id_Conflict'] = False

    # Pooled candidates, normalised once per entity rather than per comparison.
    z['Z_Cities_N'] = [[norm_city(x) for x in v if norm_city(x)] for v in z.Z_Cities]
    z['Z_States_N'] = [sorted({norm_state(x) for x in v} - {''})
                       for v in z.Z_States]
    z['Z_Zips_N'] = [sorted({norm_zip5(x) for x in v} - {''})
                     for v in z.Z_Zips]

    # Keep the Definitive name: without it a reviewer cannot see what an id
    # actually points at, which makes the review queue unlabelable.
    zj = z.merge(d.rename(columns={'DHC_Name': 'DHC_Matched_Name'}),
                 on='DHC_Id', how='left', indicator=True)
    zj['ID_Found'] = zj['_merge'] == 'both'
    zj = zj.drop(columns='_merge')

    # Phone: a third signal, independent of name and address. Reported beside
    # the verdict, never folded into it (decision #4 keeps Verdict about name
    # and address). Computed before the testable split so an unverifiable id
    # still gets a Phone_Lookup - the one Definitive record holding its number.
    by_id, owners, shared = phone_index(d, L)
    zj = add_phone_columns(zj, 'DHC_Id', d, by_id, owners, shared)
    print(f'Phones      : {int(zj.Z_Phones.map(len).gt(0).sum()):,} of {len(zj):,} '
          f'entities carry a usable Zeus phone; {len(owners):,} Definitive '
          f'numbers usable, {len(shared):,} shared by {PHONE_SHARED_MIN}+ ids '
          f'ignored')
    sub = zj[zj.ID_Found].copy()

    print(f'ID populated : {z.DHC_Id.notna().sum():,}')
    print(f'ID testable  : {len(sub):,}  ({len(sub)/max(len(z),1):.1%} of Zeus)\n')
    if not len(sub):
        print('Nothing testable. Check that the id columns and exports line up.')
        return

    LOC, capped = location_index(L, set(sub.DHC_Id.dropna().astype('int64')))
    if LOC:
        print(f'Locations in play: {len(LOC):,} of the scored ids carry one or '
              f'more service locations')
        if capped:
            print(f'  note: {capped:,} ids exceeded the {LOC_CAP}-location cap; '
                  f'the rest were not scored')

    rows, prov = [], []
    for r in sub.itertuples(index=False):
        ent = {'primary': r.d_primary, 'aliases': r.d_aliases,
               'lines': (r.DHC_Addr1, r.DHC_Addr2), 'city': r.d_city_n,
               'state': r.d_state, 'zip': r.d_zip5}
        loc = LOC.get(int(r.DHC_Id)) if pd.notna(r.DHC_Id) else None
        rows.append(enriched_scores(
            r.Z_Names, r.Z_Addrs, r.Z_Cities_N, r.Z_States_N, r.Z_Zips_N,
            ent, loc))
        _, ztxt, dtxt, via, _ = name_provenance(
            r.Z_Names, r.d_primary, r.d_aliases, loc['names'] if loc else [])
        prov.append((ztxt, r.Z_Name_Sources.get(ztxt, ''), dtxt, via) +
                    matched_address(rows[-1][7], r.Z_Addr_Geo,
                                    (r.DHC_City, r.DHC_State, r.DHC_Zip)))

    for i, c in enumerate(['Name_Score', 'StreetNum_Score', 'StreetName_Score',
                           'City_Score', 'State_Score', 'Zip_Score']):
        sub[c] = np.round([x[i] for x in rows], 1)
    sub['Address_Match_Source'] = [x[6] for x in rows]
    # Which two strings produced Name_Score. Pooling means the winning Zeus
    # name may come from any population the entity belongs to;
    # Matched_Zeus_Source names it, so e.g. a Work Location entity that is also
    # a Client can be seen to rest on its Client name.
    # The address pair behind Address_Score, likewise: Zeus_Address is only the
    # first pooled address, and the Definitive line may be a satellite.
    for i, c in enumerate(['Matched_Zeus_Name', 'Matched_Zeus_Source',
                           'Matched_Definitive_Name', 'Matched_Via'] +
                          MATCHED_ADDR_COLS):
        sub[c] = [x[i] for x in prov]
    sub['Location_Count'] = [
        (LOC.get(int(i), {}).get('n', 0) if pd.notna(i) else 0)
        for i in sub.DHC_Id]

    sub['Address_Score'] = np.round([
        weighted(x[1:6], ADDR_W) for x in rows], 1)
    sub['Confidence_Score'] = np.round([
        weighted(x[:6],
                 [BLEND_W['name'], BLEND_W['stnum'], BLEND_W['stname'],
                  BLEND_W['city'], BLEND_W['state'], BLEND_W['zip']])
        for x in rows], 1)
    sub['Verdict'] = [verdict(n, a) for n, a in
                      zip(sub.Name_Score, sub.Address_Score)]
    sub['Address_Divergent'] = (sub.Verdict == 'ID corroborated') & \
                               (sub.Address_Score < 60)
    # A strong name match in the wrong state is the signature of a parent/child
    # mix-up or a same-named practice elsewhere. Verdict is left alone (name
    # outranks address by design); this surfaces them as their own queue.
    sub['Geo_Conflict'] = (sub.Name_Score >= 92) & (sub.State_Score == 0)

    total = len(sub)
    print('--- Verdicts (testable population) ---')
    for k, v in sub.Verdict.value_counts().items():
        print(f'  {k:42} {v:>7,}  {v/total:6.1%}')
    ok = sub.Verdict.str.startswith(('ID corroborated', 'Probable')).sum()
    print(f'  {"CORROBORATED + PROBABLE":42} {ok:>7,}  {ok/total:6.1%}')

    gc = int(sub.Geo_Conflict.sum())
    ad = int(sub.Address_Divergent.sum())
    print(f'\n  {"Address divergent (corroborated, addr<60)":42} {ad:>7,}')
    print(f'  {"Geo conflict (name>=92, state disagrees)":42} {gc:>7,}'
          f'  <-- review separately')

    pm = sub.Phone_Match
    print(f'\n--- Phone (independent of Verdict) ---')
    print(f'  {"phone on both sides":42} {int(pm.notna().sum()):>7,}')
    print(f'  {"  numbers agree":42} {int(pm.eq(True).sum()):>7,}  '
          f'{pm.eq(True).sum() / max(int(pm.notna().sum()), 1):6.1%}')
    print(f'  {"  number belongs to another record":42} '
          f'{int(sub.Phone_Points_Elsewhere.sum()):>7,}  <-- review')
    for v in ['Needs review', 'Likely wrong ID']:
        s_ = sub[sub.Verdict == v]
        print(f'  {v:42} phone agrees {int(s_.Phone_Match.eq(True).sum()):>5,} / '
              f'points elsewhere {int(s_.Phone_Points_Elsewhere.sum()):>5,} '
              f'of {len(s_):,}')

    if 'DHC_Entity_Type' in sub.columns and sub.DHC_Entity_Type.nunique() > 1:
        print('\n--- By Definitive entity type ---')
        g = sub.groupby('DHC_Entity_Type').agg(
            Rows=('Verdict', 'size'),
            Corroborated=('Verdict', lambda s: (s == 'ID corroborated').sum()))
        g['Pct'] = (g.Corroborated / g.Rows).map('{:.1%}'.format)
        print(g.to_string())

    # Populations overlap, so an entity is counted once per population it
    # belongs to. These rows therefore sum to more than the testable total.
    print('\n--- By Zeus population (overlapping; entities counted in each) ---')
    labels = sorted({s for v in sub.Zeus_Sources for s in v.split('|')})
    print(f'  {"population":16} {"rows":>7} {"corroborated":>13} {"pct":>7}')
    for lab in labels:
        m = sub.Zeus_Sources.str.split('|').map(lambda v, l=lab: l in v)
        n = int(m.sum())
        ok = int((sub[m].Verdict == 'ID corroborated').sum())
        print(f'  {lab:16} {n:>7,} {ok:>13,} {ok/max(n,1):>7.1%}')
    solo = int((sub.Zeus_Source_Count == 1).sum())
    print(f'  ({solo:,} of {len(sub):,} testable entities belong to exactly '
          f'one population)')

    # ---- reverse lookup on non-corroborated rows ----
    if reverse:
        need = sub[sub.Verdict != 'ID corroborated']
        print(f'\nReverse lookup over {len(need):,} rows...')
        d['core'] = d['d_primary'].map(name_core)
        d['core_alias'] = [name_core(a[0]) if a else '' for a in d['d_aliases']]
        by_state = {s: g for s, g in d.groupby('d_state')}

        def blended(tgt, cands):
            ts = process.cdist([tgt], cands, scorer=fuzz.token_set_ratio,
                               workers=-1)[0]
            tr = process.cdist([tgt], cands, scorer=fuzz.token_sort_ratio,
                               workers=-1)[0]
            return TS_W * ts + TR_W * tr

        def pick(r):
            pool = None
            for st in r.Z_States_N:            # any population's state will do
                p = by_state.get(st)
                if p is not None and len(p):
                    pool = p if pool is None else pd.concat([pool, p])
            if pool is None or not len(pool):
                pool = d
            cores, aliases = pool['core'].tolist(), pool['core_alias'].tolist()
            # Every pooled Zeus name is an alias of the others, so each one gets
            # to nominate a candidate and the best overall wins - the same rule
            # the forward pass applies via name_score.
            best = None
            for zn in r.Z_Names:
                tgt = name_core(zn) or _clean(zn)
                if not tgt:
                    continue
                s = np.maximum(blended(tgt, cores), blended(tgt, aliases))
                best = s if best is None else np.maximum(best, s)
            if best is None:
                return pool.iloc[0]
            return pool.iloc[int(np.argmax(best))]

        # Two passes: choose candidates first so the location index is built
        # once for exactly the ids needed, instead of rescanning 400k location
        # rows per candidate.
        picks = [pick(r) for r in need.itertuples(index=False)]
        suggest_loc, _ = location_index(
            L, {int(p.DHC_Id) for p in picks})

        recs = []
        for r, p in zip(need.itertuples(index=False), picks):
            # Same location enrichment as the forward pass, otherwise
            # Suggested_Address_Score is not comparable to Address_Score and
            # the Correction_Recommended guards compare unlike quantities.
            ent = {'primary': p.d_primary, 'aliases': p.d_aliases,
                   'lines': (p.DHC_Addr1, p.DHC_Addr2), 'city': p.d_city_n,
                   'state': p.d_state, 'zip': p.d_zip5}
            cand_loc = suggest_loc.get(int(p.DHC_Id))
            nm, an, ab, cs, st2, zp, _, _ = enriched_scores(
                r.Z_Names, r.Z_Addrs, r.Z_Cities_N, r.Z_States_N, r.Z_Zips_N,
                ent, cand_loc)
            recs.append({
                zc['key']: getattr(r, zc['key']),
                'Suggested_DHC_Id': int(p.DHC_Id),
                'Suggested_Name': p.DHC_Name if 'DHC_Name' in p else p.d_primary,
                'Suggested_Entity_Type': p.DHC_Entity_Type,
                'Suggested_Name_Score': round(nm, 1),
                'Suggested_Address_Score': round(
                    weighted([an, ab, cs, st2, zp], ADDR_W), 1),
                'Suggestion_Is_Different_Id': int(p.DHC_Id) != int(r.DHC_Id),
            })
        if recs:
            sub = sub.merge(pd.DataFrame(recs), on=zc['key'], how='left')
            sub['Correction_Recommended'] = (
                sub.Suggestion_Is_Different_Id.fillna(0).astype(bool)
                & (sub.Suggested_Name_Score >= 80)
                & (sub.Suggested_Name_Score > sub.Name_Score + 10)
                & (sub.Suggested_Address_Score >= 60)
                & (sub.Suggested_Address_Score >= sub.Address_Score - 10))
            n = int(sub.Correction_Recommended.sum())
            print(f'Recommended corrections: {n:,}')

    def flatten(df):
        """List columns are for scoring; a CSV wants readable text."""
        out = df.copy()
        out['Zeus_Name'] = [v[0] if v else '' for v in out.Z_Names]
        out['Zeus_Names_All'] = [' | '.join(v) for v in out.Z_Names]
        out['Zeus_Address'] = [v[0] if v else '' for v in out.Z_Addrs]
        out['Zeus_Addresses_All'] = [' | '.join(v) for v in out.Z_Addrs]
        out['Zeus_City'] = [' | '.join(v) for v in out.Z_Cities]
        out['Zeus_State'] = [' | '.join(v) for v in out.Z_States]
        out['Zeus_Zip'] = [' | '.join(str(x) for x in v) for v in out.Z_Zips]
        out['Zeus_Phones'] = [' | '.join(v) for v in out.Z_Phones]
        return out.drop(columns=[c for c in
                                 ['Z_Names', 'Z_Addrs', 'Z_Cities', 'Z_States',
                                  'Z_Zips', 'Z_Phones', 'Z_Name_Sources',
                                  'Z_Addr_Geo',
                                  'Z_Cities_N', 'Z_States_N',
                                  'Z_Zips_N', 'd_primary', 'd_aliases',
                                  'd_city_n', 'd_state', 'd_zip5', 'core',
                                  'core_alias'] if c in out.columns])

    lead = ['EntityId', 'Zeus_Sources', 'Zeus_Source_Count', 'Zeus_Name',
            'Zeus_Names_All', 'Zeus_Address', 'Zeus_Addresses_All',
            'Zeus_City', 'Zeus_State', 'Zeus_Zip', 'Zeus_Phones']
    detail = flatten(sub)
    detail = detail[[c for c in lead if c in detail.columns] +
                    [c for c in detail.columns if c not in lead]]
    detail.to_csv(f'{out_prefix}_scored.csv', index=False)
    print(f'\nWrote {out_prefix}_scored.csv  ({len(detail):,} rows)')

    unver = zj[~zj.ID_Found]
    if len(unver):
        u = flatten(unver)
        # Phone_Lookup_* is the one lead an unverifiable row has: the
        # Definitive record that holds the entity's phone number, if any.
        cols = ['EntityId', 'Zeus_Sources', 'Zeus_Name', 'Zeus_Names_All',
                'Zeus_City', 'Zeus_State', 'Zeus_Phones', 'DHC_Id',
                'DHC_Id_Source', 'Phone_Lookup_DHC_Id', 'Phone_Lookup_Name']
        u[[c for c in cols if c in u.columns]].to_csv(
            f'{out_prefix}_unverifiable.csv', index=False)
        print(f'Wrote {out_prefix}_unverifiable.csv  ({len(unver):,} rows)')
    return detail


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sp = ap.add_subparsers(dest='cmd', required=True)
    i = sp.add_parser('inspect', help='show columns and emit a starting config')
    i.add_argument('files', nargs='+')
    r = sp.add_parser('run', help='score Zeus ids against the Definitive exports')
    r.add_argument('--config', required=True)
    r.add_argument('--zeus', help='read Zeus from this file instead of the '
                                  'configured query (offline re-run)')
    r.add_argument('--label', '--out', dest='label',
                   help='optional suffix for the run folder name; the folder '
                        f'is always "{RESULTS_DIR}/dhc_match_v2_<date>_<time>"')
    r.add_argument('--results-dir', default=RESULTS_DIR)
    r.add_argument('--no-reverse', action='store_true',
                   help='skip the reverse lookup (faster)')
    r.add_argument('--definitive-from', metavar='PREFIX',
                   help='reuse the Databricks snapshots of an earlier run '
                        '(<PREFIX>_dhc_*.parquet, or that run\'s folder) '
                        'instead of querying live')
    a = ap.parse_args()

    if a.cmd == 'inspect':
        cmd_inspect(a.files)
    else:
        cfg = load_config(a.config)
        if a.zeus:
            # An explicit file overrides the live query, not the reverse.
            cfg['zeus']['path'] = a.zeus
            cfg['zeus'].pop('query_file', None)
        prefix = new_run_prefix('dhc_match_v2', a.label, a.results_dir)
        cmd_run(cfg, prefix, reverse=not a.no_reverse,
                definitive_from=a.definitive_from and
                resolve_prefix(a.definitive_from))


if __name__ == '__main__':
    main()
