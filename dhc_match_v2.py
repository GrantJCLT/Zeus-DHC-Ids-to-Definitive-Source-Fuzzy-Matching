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

Requires: pandas, numpy, openpyxl, rapidfuzz  (pyyaml optional - JSON works too)
"""
import argparse
import json
import os
import re
import sys

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
    'fort': 'ft', 'doctor': 'dr',
}

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
    return ' '.join(ADDR_ABBREV.get(t, t) for t in s.split())


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


def addr_scores(z_lines, d_lines):
    """Best pair across all address-line combinations; Zeus's street line is
    not always in the first column.

    Returns (street_number_score, street_body_score, winning_d_index). The
    index identifies which Definitive line won, so the caller can tell an HQ
    match from a service-location match.
    """
    zc = [x for x in z_lines if x and str(x).strip()]
    dc = [(i, x) for i, x in enumerate(d_lines) if x and str(x).strip()]
    if not zc or not dc:
        return np.nan, np.nan, None
    best = (-1.0, np.nan, np.nan, None)
    for zl in zc:
        zn, zb = street_number(zl), street_body(zl)
        for di, dl in dc:
            dn, db = street_number(dl), street_body(dl)
            ns = (100.0 if zn == dn else 0.0) if (zn and dn) else np.nan
            bs = float(fuzz.ratio(zb, db)) if (zb and db) else np.nan
            tot = (0 if np.isnan(ns) else ns) + (0 if np.isnan(bs) else bs)
            if tot > best[0]:
                best = (tot, ns, bs, di)
    return best[1], best[2], best[3]


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
    return pd.read_excel(path, **kw)


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
        rows.append({
            'EntityId': eid,
            'Zeus_Sources': '|'.join(srcs),
            'Zeus_Source_Count': len(srcs),
            'Z_Names': uniq([v for c in Z_NAMES for v in g[c]]),
            'Z_Addrs': uniq([v for c in Z_ADDRS for v in g[c]]),
            'Z_Cities': uniq(g.Z_City),
            'Z_States': uniq(g.Z_State),
            'Z_Zips': [x for x in dict.fromkeys(g.Z_Zip) if pd.notna(x)],
            **ids,
        })
    return pd.DataFrame(rows)


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
    else:
        import pyodbc
        c = zc.get('connection') or {}
        srcs = zc.get('sources') or []
        if not srcs:
            raise SystemExit('zeus config needs `sources` (or `path`).')
        print(f'Zeus source : {c.get("database")} on {c.get("host")}')
        print(f'  intent    : {c.get("application_intent", "ReadWrite")}')
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
                label = s.get('label') or os.path.basename(s['query_file'])
                raw = pd.read_sql(open(s['query_file']).read(), cx)
                frames.append(_canonicalise(raw, s, idc, label))
                print(f'  {label:14} {len(raw):>7,} rows  '
                      f'({os.path.basename(s["query_file"])})')
        u = pd.concat(frames, ignore_index=True)

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
    delta = len(z) - ZEUS_BASELINE_ENTITIES
    if delta:
        print(f'  NOTE: {delta:+,} vs the expected '
              f'{ZEUS_BASELINE_ENTITIES:,} entities. Expected drift as Zeus '
              f'changes; investigate anything large, then update '
              f'ZEUS_BASELINE_ENTITIES.')
    return z.reset_index(drop=True)


def _read_roles(b, cols):
    """Read only the configured role columns from one export."""
    use = [b.get(k) for k in cols if not isinstance(b.get(k), list)]
    use += [c for k in cols for c in (b.get(k) or []) if isinstance(b.get(k), list)]
    use = [c for c in use if c]
    return read_any(b['path'], usecols=lambda c, u=set(use): c in u)


def _identity_frame(b):
    df = _read_roles(b, ('id', 'name', 'address', 'city', 'state', 'zip'))
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
    d['d_city_n'] = d['DHC_City'].map(_clean)
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
        df = _read_roles(b, ('id', 'name', 'address', 'city', 'state', 'zip'))
        ac = [c for c in (b.get('address') or []) if c in df.columns]
        out = pd.DataFrame({
            'DHC_Id': pd.to_numeric(df[b['id']], errors='coerce').astype('Int64'),
            'Loc_Name': df[b['name']].astype('object') if b.get('name') else None,
            'Loc_Addr1': df[ac[0]] if len(ac) > 0 else None,
            'Loc_Addr2': df[ac[1]] if len(ac) > 1 else None,
            'Loc_City': df[b['city']] if b.get('city') else None,
            'Loc_State': df[b['state']] if b.get('state') else None,
            'Loc_Zip': df[b['zip']] if b.get('zip') else None,
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
        idx[int(key)] = {
            'n': len(g),
            'names': names[:LOC_CAP], 'addrs': addrs[:LOC_CAP],
            'cities': {_clean(x) for x in g.Loc_City
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
    """
    aliases = list(ent['aliases'] or []) + (loc['names'] if loc else [])
    nm = name_score(z_names, ent['primary'], aliases)

    hq_lines = [x for x in ent['lines'] if x and str(x).strip()]
    d_lines = hq_lines + (loc['addrs'] if loc else [])
    an, ab, src = addr_scores(z_lines, d_lines)
    source = '' if src is None else ('HQ' if src < len(hq_lines) else 'Location')

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
    return nm, an, ab, cs, st, zp, source


def cmd_run(cfg, out_prefix, reverse=True):
    zc = cfg['zeus']
    z = load_zeus(zc, out_prefix)

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
    z['Z_Cities_N'] = [[_clean(x) for x in v if _clean(x)] for v in z.Z_Cities]
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

    rows = []
    for r in sub.itertuples(index=False):
        ent = {'primary': r.d_primary, 'aliases': r.d_aliases,
               'lines': (r.DHC_Addr1, r.DHC_Addr2), 'city': r.d_city_n,
               'state': r.d_state, 'zip': r.d_zip5}
        rows.append(enriched_scores(
            r.Z_Names, r.Z_Addrs, r.Z_Cities_N, r.Z_States_N, r.Z_Zips_N,
            ent, LOC.get(int(r.DHC_Id)) if pd.notna(r.DHC_Id) else None))

    for i, c in enumerate(['Name_Score', 'StreetNum_Score', 'StreetName_Score',
                           'City_Score', 'State_Score', 'Zip_Score']):
        sub[c] = np.round([x[i] for x in rows], 1)
    sub['Address_Match_Source'] = [x[6] for x in rows]
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
            nm, an, ab, cs, st2, zp, _ = enriched_scores(
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
        return out.drop(columns=[c for c in
                                 ['Z_Names', 'Z_Addrs', 'Z_Cities', 'Z_States',
                                  'Z_Zips', 'Z_Cities_N', 'Z_States_N',
                                  'Z_Zips_N', 'd_primary', 'd_aliases',
                                  'd_city_n', 'd_state', 'd_zip5', 'core',
                                  'core_alias'] if c in out.columns])

    lead = ['EntityId', 'Zeus_Sources', 'Zeus_Source_Count', 'Zeus_Name',
            'Zeus_Names_All', 'Zeus_Address', 'Zeus_Addresses_All',
            'Zeus_City', 'Zeus_State', 'Zeus_Zip']
    detail = flatten(sub)
    detail = detail[[c for c in lead if c in detail.columns] +
                    [c for c in detail.columns if c not in lead]]
    detail.to_csv(f'{out_prefix}_scored.csv', index=False)
    print(f'\nWrote {out_prefix}_scored.csv  ({len(detail):,} rows)')

    unver = zj[~zj.ID_Found]
    if len(unver):
        u = flatten(unver)
        cols = ['EntityId', 'Zeus_Sources', 'Zeus_Name', 'Zeus_Names_All',
                'Zeus_City', 'Zeus_State', 'DHC_Id', 'DHC_Id_Source']
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
    r.add_argument('--out', default='dhc_audit')
    r.add_argument('--no-reverse', action='store_true',
                   help='skip the reverse lookup (faster)')
    a = ap.parse_args()

    if a.cmd == 'inspect':
        cmd_inspect(a.files)
    else:
        cfg = load_config(a.config)
        if a.zeus:
            # An explicit file overrides the live query, not the reverse.
            cfg['zeus']['path'] = a.zeus
            cfg['zeus'].pop('query_file', None)
        cmd_run(cfg, a.out, reverse=not a.no_reverse)


if __name__ == '__main__':
    main()
