"""Normalization + field scoring for Zeus <-> Definitive DHC ID verification."""
import re
import pandas as pd
import numpy as np
from rapidfuzz import fuzz

STATES = {
    'alabama':'AL','alaska':'AK','arizona':'AZ','arkansas':'AR','california':'CA',
    'colorado':'CO','connecticut':'CT','delaware':'DE','district of columbia':'DC',
    'florida':'FL','georgia':'GA','hawaii':'HI','idaho':'ID','illinois':'IL',
    'indiana':'IN','iowa':'IA','kansas':'KS','kentucky':'KY','louisiana':'LA',
    'maine':'ME','maryland':'MD','massachusetts':'MA','michigan':'MI','minnesota':'MN',
    'mississippi':'MS','missouri':'MO','montana':'MT','nebraska':'NE','nevada':'NV',
    'new hampshire':'NH','new jersey':'NJ','new mexico':'NM','new york':'NY',
    'north carolina':'NC','north dakota':'ND','ohio':'OH','oklahoma':'OK','oregon':'OR',
    'pennsylvania':'PA','rhode island':'RI','south carolina':'SC','south dakota':'SD',
    'tennessee':'TN','texas':'TX','utah':'UT','vermont':'VT','virginia':'VA',
    'washington':'WA','west virginia':'WV','wisconsin':'WI','wyoming':'WY',
    'puerto rico':'PR','virgin islands':'VI','guam':'GU','american samoa':'AS',
}

# Corporate / facility-type tokens carry little identifying signal.
NOISE_TOKENS = {
    'inc','incorporated','llc','llp','lp','pc','pa','pllc','plc','ltd','corp',
    'corporation','co','company','the','of','at','and','a','an','group','system',
    'systems','health','healthcare','medical','center','centre','ctr','hospital',
    'hospitals','clinic','clinics','regional','memorial','community','general',
    'district','services','service','associates','assoc','partners','network',
    'university','univ','st','saint','dba',
}

ADDR_ABBREV = {
    'street':'st','str':'st','avenue':'ave','av':'ave','boulevard':'blvd',
    'road':'rd','drive':'dr','lane':'ln','court':'ct','circle':'cir','place':'pl',
    'parkway':'pkwy','highway':'hwy','terrace':'ter','trail':'trl','square':'sq',
    'suite':'ste','apartment':'apt','building':'bldg','floor':'fl','room':'rm',
    'north':'n','south':'s','east':'e','west':'w','northeast':'ne',
    'northwest':'nw','southeast':'se','southwest':'sw','post office':'po',
    'first':'1st','second':'2nd','third':'3rd','fourth':'4th','fifth':'5th',
    'sixth':'6th','seventh':'7th','eighth':'8th','ninth':'9th','tenth':'10th',
    'mount':'mt','fort':'ft','doctor':'dr',
}

# Parenthetical alias markers in Definitive names, e.g. "New Name (FKA Old Name)"
ALIAS_RE = re.compile(
    r'\((?:\s*(?:fka|f/k/a|aka|a/k/a|dba|d/b/a|formerly(?:\s+known\s+as)?|'
    r'now|nka)\s*)(.+?)\)', re.I)
# Status annotations that are not part of any name
STATUS_RE = re.compile(
    r'\(\s*(?:closed|closing|inactive|merged|new|pending|proposed|under\s+construction|'
    r'campus|satellite|reopened)[^)]*\)', re.I)


def _base_clean(s):
    """Uppercase-insensitive punctuation strip, collapse whitespace."""
    if s is None or (isinstance(s, float) and np.isnan(s)):
        return ''
    s = str(s).lower()
    s = s.replace('&', ' and ')
    s = re.sub(r"[^\w\s]", ' ', s)
    s = re.sub(r'\s+', ' ', s).strip()
    return s


def norm_name(s):
    return _base_clean(s)


def name_core(s):
    """Drop generic facility/corporate tokens to expose the distinguishing words."""
    toks = [t for t in _base_clean(s).split() if t not in NOISE_TOKENS]
    return ' '.join(toks)


def split_def_name(s):
    """Return (primary_name, [aliases]) for a Definitive hospital name."""
    if s is None or (isinstance(s, float) and np.isnan(s)):
        return '', []
    s = str(s)
    aliases = [m.strip() for m in ALIAS_RE.findall(s)]
    primary = ALIAS_RE.sub(' ', s)
    primary = STATUS_RE.sub(' ', primary)
    # any leftover parentheticals: keep contents as a weak alias candidate
    for extra in re.findall(r'\(([^)]*)\)', primary):
        e = extra.strip()
        if e and len(e) > 3:
            aliases.append(e)
    primary = re.sub(r'\([^)]*\)', ' ', primary)
    primary = re.sub(r'\s+', ' ', primary).strip()
    aliases = [STATUS_RE.sub(' ', a).strip() for a in aliases]
    aliases = [a for a in aliases if a]
    return primary, aliases


def norm_addr(s):
    """Normalize a street address line."""
    s = _base_clean(s)
    if not s:
        return ''
    s = re.sub(r'\bp\s*o\s*box\b', 'po box', s)
    toks = [ADDR_ABBREV.get(t, t) for t in s.split()]
    return ' '.join(toks)


def street_number(s):
    """Leading house number, incl. alphanumerics like 4401A."""
    s = norm_addr(s)
    m = re.match(r'^(\d+[a-z]?)\b', s)
    if m:
        return m.group(1)
    m = re.search(r'\b(?:po )?box (\w+)', s)
    return ('box' + m.group(1)) if m else ''


def street_body(s):
    """Address with the leading house number removed."""
    s = norm_addr(s)
    return re.sub(r'^\d+[a-z]?\s*', '', s).strip()


def norm_state(s):
    s = _base_clean(s)
    if not s:
        return ''
    if len(s) == 2:
        return s.upper()
    return STATES.get(s, s.upper()[:2])


def norm_zip5(s):
    if s is None or (isinstance(s, float) and np.isnan(s)):
        return ''
    digits = re.sub(r'\D', '', str(s))
    if not digits:
        return ''
    return digits.zfill(5)[:5] if len(digits) < 5 else digits[:5]


TS_W, TR_W = 0.35, 0.65


def pair_score(a, b):
    """
    Length-aware similarity. token_set_ratio alone returns 100 whenever one
    token set is a subset of the other ("Reid Health" inside "Reid Health
    Connersville"), which inflates short generic names. Blending it with
    token_sort_ratio keeps word-order tolerance while penalizing the length
    gap that a pure subset match hides.
    """
    return TS_W * fuzz.token_set_ratio(a, b) + TR_W * fuzz.token_sort_ratio(a, b)


def name_score(z_names, d_primary, d_aliases):
    """
    Best similarity across every Zeus name x Definitive name/alias pair,
    evaluated both on the full normalized name and on the core tokens with
    generic facility words removed.
    """
    d_all = [x for x in [d_primary] + list(d_aliases) if x]
    z_all = [x for x in z_names if x]
    if not d_all or not z_all:
        return 0.0
    best = 0.0
    for zn in z_all:
        zf, zc = norm_name(zn), name_core(zn)
        for dn in d_all:
            df, dc = norm_name(dn), name_core(dn)
            s = pair_score(zf, df)
            if zc and dc:
                s = max(s, pair_score(zc, dc))
            if s > best:
                best = s
                if best >= 100:
                    return 100.0
    return float(best)


def addr_scores(z_lines, d_lines):
    """
    Best (street-number, street-body) score across all combinations of Zeus and
    Definitive address lines. Zeus splits addresses over three columns and the
    real street line is not always the first, so every line is a candidate.
    Returns (stnum_score, stname_score) on a 0-100 scale, or (nan, nan).
    """
    zc = [x for x in z_lines if x and str(x).strip()]
    dc = [x for x in d_lines if x and str(x).strip()]
    if not zc or not dc:
        return np.nan, np.nan
    best_pair = (-1.0, -1.0, -1.0)  # (combined, stnum, stbody)
    for zl in zc:
        znum, zbody = street_number(zl), street_body(zl)
        for dl in dc:
            dnum, dbody = street_number(dl), street_body(dl)
            if znum and dnum:
                ns = 100.0 if znum == dnum else 0.0
            else:
                ns = np.nan
            bs = float(fuzz.ratio(zbody, dbody)) if (zbody and dbody) else np.nan
            combined = np.nansum([
                0.0 if np.isnan(ns) else ns,
                0.0 if np.isnan(bs) else bs,
            ])
            if combined > best_pair[0]:
                best_pair = (combined, ns, bs)
    return best_pair[1], best_pair[2]


WEIGHTS = {
    'name':   0.40,
    'stnum':  0.20,
    'stname': 0.15,
    'city':   0.10,
    'state':  0.05,
    'zip':    0.10,
}


def composite(row_scores):
    """Weighted composite over available components, renormalized for missing ones."""
    num = 0.0
    den = 0.0
    for k, w in WEIGHTS.items():
        v = row_scores.get(k)
        if v is not None and not (isinstance(v, float) and np.isnan(v)):
            num += w * v
            den += w
    return num / den if den else np.nan


def bucket(score):
    if pd.isna(score):
        return 'Unscored'
    if score >= 90:
        return 'Confident match'
    if score >= 75:
        return 'Probable match'
    if score >= 50:
        return 'Needs review'
    return 'Likely wrong ID'


# ============================================================================
# RUNNER
# ============================================================================
import sys, argparse
from rapidfuzz import process

AW = np.array([0.30, 0.22, 0.18, 0.08, 0.22])   # stnum, stbody, city, state, zip


def load(path, **kw):
    if str(path).lower().endswith(('.csv', '.tsv')):
        return pd.read_csv(path, sep=None, engine='python', dtype=str)
    return pd.read_excel(path, **kw)


def run(zeus_path, def_path, out_path):
    z = load(zeus_path)
    d = load(def_path)

    ent = pd.to_numeric(z['Entity_DHC_VerifiedSourceId'], errors='coerce')
    lev = pd.to_numeric(z['LEVS_DHC_VerifiedSourceId'], errors='coerce')
    z['DHC_Id'] = ent.fillna(lev)
    z['DHC_Id_Source'] = np.where(ent.notna(), 'Entity',
                                  np.where(lev.notna(), 'LEVS', 'None'))
    z['DHC_Id_Conflict'] = ent.notna() & lev.notna() & (ent != lev)

    split = d['HospitalName'].map(split_def_name)
    d['def_primary'] = [p for p, a in split]
    d['def_aliases'] = [a for p, a in split]
    d['def_state'] = d['HqState'].map(norm_state)
    d['def_zip5'] = d['HqZipCode'].map(norm_zip5)
    d['def_city_n'] = d['HqCity'].map(_base_clean)
    d = d.rename(columns={'HospitalId': 'DHC_Id'})
    d['DHC_Id'] = pd.to_numeric(d['DHC_Id'], errors='coerce').astype('Int64')

    zj = z.merge(d[['DHC_Id', 'HospitalName', 'def_primary', 'def_aliases',
                    'AddressHq', 'Address1Hq', 'HqCity', 'def_city_n',
                    'HqState', 'def_state', 'HqZipCode', 'def_zip5']],
                 on='DHC_Id', how='left', indicator=True)
    zj['ID_Found_In_Definitive'] = zj['_merge'] == 'both'
    sub = zj[zj.ID_Found_In_Definitive].drop(columns='_merge').copy()

    recs = []
    for r in sub.itertuples(index=False):
        nm = name_score([r.EntityName, r.ClientInfoName], r.def_primary, r.def_aliases)
        an, ab = addr_scores([r.ClientAddress1, r.ClientAddress2, r.ClientAddress3],
                            [r.AddressHq, r.Address1Hq])
        zc, dc = _base_clean(r.ClientCity), r.def_city_n
        cs = float(fuzz.ratio(zc, dc)) if (zc and dc) else np.nan
        zs_, ds_ = norm_state(r.ClientState), r.def_state
        st = (100.0 if zs_ == ds_ else 0.0) if (zs_ and ds_) else np.nan
        zz = norm_zip5(r.ClientZip)
        zp = (100.0 if zz == r.def_zip5 else 0.0) if (zz and r.def_zip5) else np.nan
        parts = np.array([an, ab, cs, st, zp], dtype='float64')
        m = ~np.isnan(parts)
        addr_sc = float(np.where(m, parts, 0).dot(AW) / AW[m].sum()) if m.any() else np.nan
        recs.append((nm, an, ab, cs, st, zp, addr_sc))

    cols = ['Name_Score', 'StreetNum_Score', 'StreetName_Score', 'City_Score',
            'State_Score', 'Zip_Score', 'Address_Score']
    for i, c in enumerate(cols):
        sub[c] = np.round([x[i] for x in recs], 1)

    sub['Confidence_Score'] = [
        round(composite({'name': a, 'stnum': b, 'stname': c,
                         'city': e, 'state': f_, 'zip': g}), 1)
        for a, b, c, e, f_, g in zip(sub.Name_Score, sub.StreetNum_Score,
                                     sub.StreetName_Score, sub.City_Score,
                                     sub.State_Score, sub.Zip_Score)]

    def verdict(n, a):
        if pd.isna(n):
            return 'Unscored'
        a = 0.0 if pd.isna(a) else a
        if n >= 92 or (n >= 75 and a >= 60):
            return 'ID corroborated'
        if n >= 75:
            return 'Probable - name agrees, address differs'
        if a >= 85 and n >= 45:
            return 'Probable - address agrees, name differs'
        return 'Needs review' if (n >= 45 or a >= 50) else 'Likely wrong ID'

    sub['Verdict'] = [verdict(n, a) for n, a in zip(sub.Name_Score, sub.Address_Score)]
    sub['Address_Divergent'] = (sub.Verdict == 'ID corroborated') & (sub.Address_Score < 60)

    total = len(sub)
    print(f'Zeus rows                : {len(z):,}')
    print(f'Testable (id in extract) : {total:,}')
    for k, v in sub.Verdict.value_counts().items():
        print(f'  {k:42} {v:6,}  {v/total:6.1%}')

    sub.drop(columns=['def_primary', 'def_aliases', 'def_city_n',
                      'def_state', 'def_zip5']).to_csv(out_path, index=False)
    print(f'\nWrote {out_path}')
    return sub


if __name__ == '__main__':
    ap = argparse.ArgumentParser(
        description='Score Zeus DHC identifiers against a Definitive hospital extract.')
    ap.add_argument('zeus')
    ap.add_argument('definitive')
    ap.add_argument('-o', '--out', default='dhc_id_scored.csv')
    a = ap.parse_args()
    run(a.zeus, a.definitive, a.out)
