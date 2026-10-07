#!/usr/bin/env python3
"""Zeus HealthSystem > Client > WorkLocation hierarchy: Definitive first, Zeus
to complete it. A read-only comparison baseline for the hierarchy the
migration team derives; nothing is ever written back to any source.

One parent per entity - a strict tree; alternates are listed, never kept as
extra edges. Each entity has ONE type, the highest of its Zeus roles:
HealthSystem over Client over WorkLocation, so a hospital Zeus flags as both
client and work location is a Client. A parent is always a higher type, or a
health system under a health system, to any depth:

  WorkLocation -> Client or HealthSystem   Zeus: dbo.LinkClientWorkLocation
  Client       -> HealthSystem             Zeus: dbo.LinkHealthSystemClient
  HealthSystem -> HealthSystem             Definitive, and Zeus client links
                                           whose child is typed HealthSystem

Decided 2026-10-07 (Grant):
  1. strict tree, alternates listed;
  2. a known Definitive ownership / parent relationship beats Zeus, except
     where Definitive completely contradicts Zeus - those are held (the Zeus
     link stays for now) and listed on Contradictions. A hospital owner
     outranks a staffing firm or physician practice, so a work location whose
     Zeus clients are only those is not a contradiction;
  3. the Definitive ids trusted for this are supplied ids rated
     `ID corroborated` or `Probable ...` (not Geo_Conflict), recommended
     corrections, and `Strong match` coverage proposals;
  4. Definitive-import-created Zeus entities are nodes only where Zeus links
     them to an in-scope entity, plus the parents those nodes need;
  5. one type per entity, the highest level wins.
The rules in full, with what each status means, are in Hierarchy_Logic.md.

  py zeus_hierarchy.py --config sources.yaml
      --accuracy "Results Output/<accuracy run>/<run>_scored.csv"
      --coverage "Results Output/<coverage run>/<run>_gap_candidates.csv"
      [--definitive-hierarchy "Results Output/<dhc_hierarchy run>"]
      [--zeus-links "Results Output/<earlier zeus_hierarchy run>"]
      [--label <suffix>]

Each audit file's sibling (_unverifiable.csv, _gap_nomatch.csv) is read too:
the four files partition the in-scope universe. Without --definitive-hierarchy
the Definitive hierarchy views are queried live, and without --zeus-links the
Zeus links are; either way the inputs are snapshotted into this run's folder,
so `--definitive-hierarchy` and `--zeus-links` pointed at it replay it exactly.

Writes into "Results Output/zeus_hierarchy_<YYYY_MM_DD_HHMM>/":
  <run>_hierarchy_nodes.csv        one row per entity: its type, parent and why
  <run>_hierarchy_edges.csv        the tree as child -> parent, one per child
  <run>_contradictions.csv         Definitive against Zeus, held for review
  <run>_zeus_links_replaced.csv    Zeus links that Definitive overrode
  <run>_zeus_links_dropped.csv     Zeus links single typing cannot hold
  <run>_resolution.csv             the Definitive id (or none) of each entity
  <run>_zeus_links.csv, _zeus_linked_imports.csv, _zeus_duplicates.csv
  <run>_dhc_*hierarchy.parquet/.sql
  Zeus_Entity_Hierarchy_<run date and time>.xlsx
"""
import argparse
import os
import shutil
import warnings
from collections import defaultdict

import numpy as np
import pandas as pd
from openpyxl import Workbook

from dhc_match_v2 import RESULTS_DIR, _dbx_connect, load_config, \
    new_run_prefix, zeus_connect
from dhc_hierarchy import _xl, load_hierarchy, resolve_hierarchy_prefix, walk
from build_audit_workbook import FILL_NAVY, FILL_PURPLE, H1, H2, SECTION, \
    WRAP, _put, _table, build_methodology, sheet_data, workbook_path

ROLES = ['WorkLocation', 'Client', 'HealthSystem']      # lowest level first
RANK = {r: i for i, r in enumerate(ROLES)}
SHORT = {'WorkLocation': 'WL', 'Client': 'Client', 'HealthSystem': 'HS'}
# The types an entity of each type may hang under: any higher level, and a
# health system under another health system (Grant, 2026-10-07).
PARENT_TYPES = {'WorkLocation': ['Client', 'HealthSystem'],
                'Client': ['HealthSystem'],
                'HealthSystem': ['HealthSystem']}
LEVEL = {'WorkLocation': 'WorkLocation -> Client or HealthSystem',
         'Client': 'Client -> HealthSystem',
         'HealthSystem': 'HealthSystem -> parent HealthSystem'}
# Definitive record types that own facilities. A Zeus client of any other
# type (a physician group, a staffing firm) cannot contradict one.
OWNER_TYPES = ('Hospital', 'Health System')

STRONG = 'Strong match - ready to load'
# The Definitive ids the Definitive pass may use (decision 3, plus decision 4's
# import-created ids), strongest first. Among several Zeus entities sharing a
# Definitive id, the stronger basis is preferred.
TRUSTED = ['Supplied-corroborated', 'Supplied-probable', 'Correction',
           'Proposed-strong', 'Import-created']
BASIS_RANK = {b: i for i, b in enumerate(TRUSTED)}

AGREES, FILLS, REPLACES = 'Agrees', 'Definitive fills', 'Definitive replaces'
CONTRA, ZEUS, NOPARENT = 'Contradiction', 'Zeus only', 'No parent'
STATUSES = [AGREES, FILLS, REPLACES, CONTRA, ZEUS, NOPARENT]
EXTERNAL = '(parent not in the Definitive views)'
SEP = ' > '

# Why one Zeus link beat another, in the order the tie-break applies them.
Z_REASONS = ["in the child's own Definitive tree", 'most recent booking',
             'most bookings', 'open link history', 'latest link history start',
             'in scope (not import-created)', 'lowest EntityId']


# ============================================================================
# Inputs
# ============================================================================
def _flag(df, col):
    """A True/False column, whether it arrived as bool, bit or text."""
    if col not in df.columns:
        return pd.Series(False, index=df.index)
    return df[col].astype(str).str.strip().str.lower().isin(['true', '1', '1.0'])


def _id(s):
    return pd.to_numeric(s, errors='coerce').astype('Int64')


def sibling(path, suffix, new):
    if not path.endswith(suffix):
        raise SystemExit(f'{path} should end in {suffix}')
    p = path[:-len(suffix)] + new
    if not os.path.exists(p):
        raise SystemExit(f'Missing {p}: it is the other half of '
                         f'{os.path.basename(path)}, so keep the run folder '
                         f'intact.')
    return p


AUDIT_COLS = ['EntityId', 'Zeus_Sources', 'Zeus_Name', 'Zeus_City',
              'Zeus_State']


def load_audits(scored, candidates):
    """One row per in-scope Zeus entity, with the Definitive id it resolves to.

    The accuracy run (_scored + _unverifiable) holds every entity that carries
    an id, the coverage run (_gap_candidates + _gap_nomatch) every one that
    does not; together they are the in-scope universe. Returns the rows and
    each file's entity count, for the partition check.
    """
    na = lambda idx: pd.Series(pd.NA, index=idx, dtype='Int64')
    s = pd.read_csv(scored, low_memory=False)
    v = s.Verdict.fillna('')
    geo = _flag(s, 'Geo_Conflict')
    corr = _flag(s, 'Correction_Recommended')
    good = (v.eq('ID corroborated') | v.str.startswith('Probable')) & ~geo
    loc = s.get('Matched_Via', pd.Series('', index=s.index)).eq('Location')
    sugg = (_id(s.Suggested_DHC_Id) if 'Suggested_DHC_Id' in s
            else na(s.index))
    a = s[AUDIT_COLS].copy()
    a['Audit'] = 'Accuracy'
    a['Audit_Detail'] = v + np.where(geo, ' + Geo_Conflict', '')
    a['Supplied_DHC_Id'] = _id(s.DHC_Id)
    # A recommended correction outranks the supplied id: it needs a much
    # better name score and an address no worse (decision #5).
    a['Resolution_Basis'] = np.select(
        [corr, good & v.eq('ID corroborated'), good],
        ['Correction', 'Supplied-corroborated', 'Supplied-probable'],
        'Review')
    a['Resolved_DHC_Id'] = sugg.where(corr, a.Supplied_DHC_Id.where(good))
    # Matched_Via = Location: the entity matched a service location of the
    # id, so the id is its owner's, not its own.
    a['Relation'] = np.where(corr, 'Is', np.where(
        good, np.where(loc, 'LocationOf', 'Is'), ''))
    a['Audit_Name'] = np.where(corr, s.get('Suggested_Name'),
                               s.DHC_Matched_Name)
    a['Audit_Type'] = np.where(corr, s.get('Suggested_Entity_Type'),
                               s.DHC_Entity_Type)

    u = pd.read_csv(sibling(scored, '_scored.csv', '_unverifiable.csv'),
                    low_memory=False)
    b = u[AUDIT_COLS].copy()
    b['Audit'] = 'Accuracy (unverifiable)'
    b['Audit_Detail'] = 'Supplied id is in no Definitive source'
    b['Supplied_DHC_Id'] = _id(u.DHC_Id)
    b['Resolution_Basis'] = 'Unverifiable'
    b['Resolved_DHC_Id'] = na(u.index)
    b['Relation'] = ''

    c = pd.read_csv(candidates, low_memory=False)
    strong = c.Match_Tier.eq(STRONG)
    cc = c[AUDIT_COLS].copy()
    cc['Audit'] = 'Coverage'
    cc['Audit_Detail'] = c.Match_Tier
    cc['Supplied_DHC_Id'] = na(c.index)
    cc['Resolution_Basis'] = np.where(strong, 'Proposed-strong', 'Review')
    cc['Resolved_DHC_Id'] = _id(c.Suggested_DHC_Id).where(strong)
    cc['Relation'] = np.where(strong, np.where(
        c.Matched_Via.eq('Location'), 'LocationOf', 'Is'), '')
    cc['Audit_Name'] = c.Suggested_Name
    cc['Audit_Type'] = c.Suggested_Entity_Type

    n = pd.read_csv(sibling(candidates, '_gap_candidates.csv',
                            '_gap_nomatch.csv'), low_memory=False)
    nn = n[AUDIT_COLS].copy()
    nn['Audit'] = 'Coverage (no match)'
    nn['Audit_Detail'] = n.Match_Tier
    nn['Supplied_DHC_Id'] = na(n.index)
    nn['Resolution_Basis'] = 'No match'
    nn['Resolved_DHC_Id'] = na(n.index)
    nn['Relation'] = ''

    counts = [('accuracy scored', len(a)), ('accuracy unverifiable', len(b)),
              ('coverage candidates', len(cc)), ('coverage no-match', len(nn))]
    ent = pd.concat([a, b, cc, nn], ignore_index=True).rename(columns={
        'Zeus_Name': 'Name', 'Zeus_City': 'City', 'Zeus_State': 'State'})
    ent['EntityId'] = ent.EntityId.astype(int)
    ent['In_Scope'] = True
    ent['Is_Linked'] = True
    ent['Import_Description'] = None
    return ent, counts


def import_rows(imp):
    """Import-created entities in the same shape as load_audits' rows. All of
    them; build_universe decides which become nodes (decision 4)."""
    rid = _id(imp.Entity_DHC_VerifiedSourceId).fillna(
        _id(imp.LEVS_DHC_VerifiedSourceId))
    flags = {r: _flag(imp, f'Is{r}') for r in ROLES}
    srcs = ['|'.join(sorted(r for r in ROLES if flags[r].iloc[i]))
            for i in range(len(imp))]
    name = imp.Entity_Name.fillna(imp.ClientInfoName).fillna(
        imp.WorkLocationInfoName).fillna(imp.HealthSystemInfoName)
    return pd.DataFrame({
        'EntityId': imp.EntityId.astype(int),
        'Zeus_Sources': srcs,
        'Name': name, 'City': imp.City, 'State': imp.State,
        'Audit': 'Import-created',
        'Audit_Detail': imp.EntityDescription,
        'Supplied_DHC_Id': rid,
        'Resolution_Basis': np.where(rid.notna(), 'Import-created',
                                     'Import-created (no id)'),
        'Resolved_DHC_Id': rid,
        'Relation': np.where(rid.notna(), 'Is', ''),
        'Audit_Name': None, 'Audit_Type': None,
        'In_Scope': False,
        'Is_Linked': _flag(imp, 'Is_Linked'),
        'Import_Description': imp.EntityDescription,
    })


ZEUS_SNAPSHOTS = [('hierarchy_query_file', 'zeus_links'),
                  ('linked_import_query_file', 'zeus_linked_imports'),
                  ('duplicates_query_file', 'zeus_duplicates')]


def load_zeus_links(zc, prefix, replay=None):
    """The three Zeus hierarchy queries, live or replayed, always written to
    this run's folder and then read back from it - so a live run and its
    replay see byte-identical inputs."""
    if replay:
        src = replay
        if os.path.isdir(src):
            hits = [f for f in os.listdir(src) if f.endswith('_zeus_links.csv')]
            if len(hits) != 1:
                raise SystemExit(f'{src} holds {len(hits)} *_zeus_links.csv '
                                 f'files; pass the run prefix instead.')
            src = os.path.join(src, hits[0][:-len('_zeus_links.csv')])
        print(f'Zeus links  : replayed from {src}_*')
        for _, name in ZEUS_SNAPSHOTS:
            df = pd.read_csv(f'{src}_{name}.csv', low_memory=False)
            df.to_csv(f'{prefix}_{name}.csv', index=False)
    else:
        missing = [k for k, _ in ZEUS_SNAPSHOTS if not zc.get(k)]
        if missing:
            raise SystemExit(f'zeus config needs {missing} for the hierarchy.')
        with zeus_connect(zc.get('connection') or {}) as cx, \
                warnings.catch_warnings():
            warnings.simplefilter('ignore', UserWarning)   # pandas vs pyodbc
            for key, name in ZEUS_SNAPSHOTS:
                df = pd.read_sql(open(zc[key]).read(), cx)
                df.to_csv(f'{prefix}_{name}.csv', index=False)
                print(f'  {name:20} {len(df):>7,} rows  '
                      f'({os.path.basename(zc[key])})')
    out = [pd.read_csv(f'{prefix}_{name}.csv', low_memory=False)
           for _, name in ZEUS_SNAPSHOTS]
    links = out[0]
    for c in ('Link_Created', 'Last_Booked', 'History_Last_Begin'):
        links[c] = pd.to_datetime(links[c], errors='coerce')
    return out


# The migration team's readiness tables (qat_gold.crmmig_rules), by the
# hierarchy type each one describes. Each table's key is the Zeus EntityId.
MIGRATION_TABLES = {'HealthSystem': 'healthsystem_summary',
                    'Client': 'client_summary',
                    'WorkLocation': 'worklocation_summary'}
MIGRATION_FLAGS = {t: f'Ready_{t}_Summary' for t in MIGRATION_TABLES}
MIGRATION_COLUMNS = (['Ready_For_Migration', 'Ready_For_Migration_From']
                     + list(MIGRATION_FLAGS.values())
                     + ['Ready_Tables_Disagree'])
MIGRATION_SNAPSHOT = '_migration_readiness'


def load_migration(cfg, prefix, replay=None):
    """`migration.query_file` (one row per EntityId per readiness table),
    queried live on the Databricks warehouse or replayed, always written to
    this run's folder as <run>_migration_readiness.parquet, with the SQL that
    produced it beside it as .sql, and read back from there."""
    snap = f'{prefix}{MIGRATION_SNAPSHOT}'
    if replay:
        src = replay
        if os.path.isdir(src):
            tail = f'{MIGRATION_SNAPSHOT}.parquet'
            hits = [f for f in os.listdir(src) if f.endswith(tail)]
            if len(hits) != 1:
                raise SystemExit(f'{src} holds {len(hits)} *{tail} files; '
                                 f'pass the run prefix, or --no-migration.')
            src = os.path.join(src, hits[0][:-len(tail)])
        if not os.path.exists(f'{src}{MIGRATION_SNAPSHOT}.parquet'):
            raise SystemExit(f'No {src}{MIGRATION_SNAPSHOT}.parquet; pass '
                             f'--no-migration to replay a run without one.')
        for ext in ('.parquet', '.sql'):
            if os.path.exists(f'{src}{MIGRATION_SNAPSHOT}{ext}'):
                shutil.copyfile(f'{src}{MIGRATION_SNAPSHOT}{ext}', snap + ext)
        print(f'Migration   : replayed from {src}{MIGRATION_SNAPSHOT}.parquet')
    else:
        m = cfg.get('migration') or {}
        if not m.get('query_file'):
            raise SystemExit('No `migration: query_file:` in the config; pass '
                             '--no-migration to build without readiness.')
        q = open(m['query_file']).read()
        with _dbx_connect(cfg.get('databricks') or {}) as cx, \
                cx.cursor() as cur:
            cur.execute(q)
            df = cur.fetchall_arrow().to_pandas()
        df.to_parquet(snap + '.parquet', index=False)
        # newline='' so the copy is byte-identical to the .sql it came from.
        with open(snap + '.sql', 'w', newline='') as f:
            f.write(q)
        print(f'Migration   : {len(df):,} rows ({m["query_file"]}) -> '
              f'{snap}.parquet')
    df = pd.read_parquet(snap + '.parquet')
    need = {'EntityId', 'Migration_Table', 'Ready_For_Migration'}
    if need - set(df.columns):
        raise SystemExit(f'Migration readiness is missing '
                         f'{sorted(need - set(df.columns))}; returned '
                         f'{list(df.columns)}.')
    df['EntityId'] = pd.to_numeric(df.EntityId).astype('Int64')
    dup = df[df.duplicated(['EntityId', 'Migration_Table'], keep=False)]
    if len(dup):
        raise SystemExit(f'{dup.EntityId.nunique():,} EntityId(s) appear more '
                         f'than once in one readiness table; each key is meant '
                         f'to be unique within its table.')
    return df


def attach_migration(n, mig):
    """Ready_For_Migration per node, from the readiness table of the node's
    own type; where that table has no row, from another table, highest type
    first, and Ready_For_Migration_From says which. Every table's own flag is
    kept beside it (Ready_<Type>_Summary), since 1,288 EntityIds sit in more
    than one table, and Ready_Tables_Disagree marks a node whose tables give
    different flags."""
    w = mig.pivot(index='EntityId', columns='Migration_Table',
                  values='Ready_For_Migration')
    n = n.copy()
    for t, col in MIGRATION_FLAGS.items():
        n[col] = (n.EntityId.map(w[t]) if t in w else pd.Series(
            pd.NA, index=n.index)).astype('Int64')
    ready, frm = [], []
    for row in n[['Entity_Type'] + list(MIGRATION_FLAGS.values())] \
            .itertuples(index=False):
        flags = dict(zip(MIGRATION_FLAGS, row[1:]))
        order = [row.Entity_Type] + [t for t in reversed(ROLES)
                                     if t != row.Entity_Type]
        hit = next((t for t in order if pd.notna(flags[t])), None)
        ready.append(pd.NA if hit is None else flags[hit])
        frm.append(None if hit is None else MIGRATION_TABLES[hit])
    n['Ready_For_Migration'] = pd.array(ready, dtype='Int64')
    n['Ready_For_Migration_From'] = frm
    n['Ready_Tables_Disagree'] = n[list(MIGRATION_FLAGS.values())] \
        .nunique(axis=1) > 1
    lead = NODE_COLUMNS[:NODE_COLUMNS.index('In_Scope') + 1]
    return n[lead + MIGRATION_COLUMNS
             + [c for c in NODE_COLUMNS if c not in lead]]


# ============================================================================
# Universe: nodes, the links between them, duplicates remapped
# ============================================================================
def survivors(dup):
    """EntityId -> the record it is ultimately a duplicate of."""
    nxt = dict(zip(dup.EntityId.astype(int), dup.DuplicateOfId.astype(int)))
    out = {}
    for e in nxt:
        s, seen = e, {e}
        while s in nxt and nxt[s] not in seen:
            s = nxt[s]
            seen.add(s)
        out[e] = s
    return out


def entity_types(ent):
    """EntityId -> its one type: the highest of its HealthSystem, Client and
    WorkLocation roles (Grant, 2026-10-07: if there is a conflict, the highest
    level wins). Entities with none of the three roles get no type."""
    out = {}
    for e, z in zip(ent.EntityId, ent.Zeus_Sources):
        roles = [r for r in str(z).split('|') if r in RANK]
        if roles:
            out[e] = max(roles, key=RANK.get)
    return out


def build_universe(ent, links, surv, etype):
    """The nodes, the Zeus links between them, and what was set aside.

    Nodes start as every typed in-scope entity. An import-created entity joins
    where a usable link touches an in-scope node, and then every node's
    parents are added until nothing changes, so each node has its whole parent
    chain (decision 4). A duplicate is replaced by its survivor wherever the
    survivor has the same type; the duplicate itself is dropped.

    A Zeus link is usable when its parent's type may hold its child's type
    (PARENT_TYPES). Single typing makes two kinds unusable: an entity linked
    to itself (a hospital flagged as its own client is now one Client), and a
    link between two entities of the same lower type (a client "under" another
    client) or upside down. The first are counted; the second are returned for
    the Zeus_Links_Dropped sheet.
    """
    in_scope = {e for e in ent.EntityId[ent.In_Scope] if e in etype}
    linked_imp = {e for e in ent.EntityId[~ent.In_Scope & ent.Is_Linked]
                  if e in etype}
    cand = in_scope | linked_imp
    remap = {e: s for e, s in surv.items()
             if s != e and e in cand and s in cand and etype[e] == etype[s]}
    cand -= set(remap)

    L = links.copy()
    L['Child_EntityId'] = L.Child_EntityId.map(lambda e: remap.get(e, e))
    L['Parent_EntityId'] = L.Parent_EntityId.map(lambda e: remap.get(e, e))
    L = L[L.Child_EntityId.isin(cand) & L.Parent_EntityId.isin(cand)]
    # A remap, or a pair linked both ways round the Info tables, can make two
    # links the same pair; keep one, pooling the evidence.
    L = (L.groupby(['Child_EntityId', 'Parent_EntityId'], as_index=False)
         .agg(Link_Types=('Link_Type', lambda s: '|'.join(sorted(set(s)))),
              Link_Created=('Link_Created', 'min'),
              Bookings=('Bookings', 'sum'), Last_Booked=('Last_Booked', 'max'),
              History_Last_Begin=('History_Last_Begin', 'max'),
              History_Open=('History_Open', 'max')))
    L['Child_Type'] = L.Child_EntityId.map(etype)
    L['Parent_Type'] = L.Parent_EntityId.map(etype)
    self_link = L.Child_EntityId == L.Parent_EntityId
    fits = pd.Series([p in PARENT_TYPES[c] for c, p in
                      zip(L.Child_Type, L.Parent_Type)], index=L.index)
    good, bad = L[~self_link & fits], L[~self_link & ~fits]

    nodes = in_scope - set(remap)
    child, parent = list(good.Child_EntityId), list(good.Parent_EntityId)
    for c, p in zip(child, parent):
        if c in nodes or p in nodes:
            nodes.update((c, p))
    grew = True
    while grew:
        grew = False
        for c, p in zip(child, parent):
            if c in nodes and p not in nodes:
                nodes.add(p)
                grew = True
    good = good[good.Child_EntityId.isin(nodes)
                & good.Parent_EntityId.isin(nodes)].reset_index(drop=True)
    bad = bad[bad.Child_EntityId.isin(nodes)].reset_index(drop=True)
    n_self = int((self_link & L.Child_EntityId.isin(nodes)).sum())
    return nodes, good, bad, n_self, remap


# ============================================================================
# Definitive
# ============================================================================
class Definitive:
    """Ancestry, name, type and ultimate root for every Definitive id."""

    def __init__(self, h, ent):
        ids = [int(x) for x in h.HospitalId]
        self.known = set(ids)
        self.name = dict(zip(ids, h.HospitalName))
        self.type = dict(zip(ids, h.TypeFirm))
        self.root = dict(zip(ids, (int(x) for x in h.RootId)))
        self.anc = {i: [int(x) for x in p.split(SEP)][::-1]
                    for i, p in zip(ids, h.Path_Ids)}
        # Parents missing from every view end a path as its root.
        for rid, rn in zip(h.RootId, h.RootName):
            rid = int(rid)
            if rid not in self.known:
                self.name.setdefault(rid, rn)
                self.type.setdefault(rid, EXTERNAL)
                self.root.setdefault(rid, rid)
                self.anc.setdefault(rid, [rid])
        # Ids only the audits know: GPOs, and parents known only from the
        # practice-location view. Each is its own root.
        for rid, nm, tp in zip(ent.Resolved_DHC_Id, ent.Audit_Name,
                               ent.Audit_Type):
            if pd.notna(rid) and int(rid) not in self.anc:
                rid = int(rid)
                self.name[rid], self.type[rid] = nm, tp
                self.root[rid], self.anc[rid] = rid, [rid]

    def ancestry(self, rid, relation):
        """(distance, id), nearest first. Distance 0 is the entity's own
        record; for a LocationOf entity the resolved id is already its owner,
        so its chain starts at 1."""
        chain = self.anc.get(rid, [rid])
        start = 1 if relation == 'LocationOf' else 0
        return [(start + i, a) for i, a in enumerate(chain)]

    def root_of(self, rid):
        return self.root.get(rid, rid)


# ============================================================================
# Decision
# ============================================================================
def _ts(v):
    return 0 if pd.isna(v) else pd.Timestamp(v).value


def decide(nodes, etype, L, ent, D):
    """One parent per entity: the Definitive pass, then Zeus.

    Returns one record per entity, plus the rows for the Contradictions and
    Zeus_Links_Replaced lists.
    """
    E = ent.drop_duplicates('EntityId').set_index('EntityId')
    rid = {e: (None if pd.isna(x) else int(x))
           for e, x in E.Resolved_DHC_Id.items()}
    rel, basis = E.Relation.to_dict(), E.Resolution_Basis.to_dict()
    in_scope, name = E.In_Scope.to_dict(), E.Name.to_dict()

    def tree(e):
        return None if rid.get(e) is None else D.root_of(rid[e])

    # Which entities stand for each Definitive record. Only Relation 'Is': an
    # entity that is a location of a record cannot stand for it.
    target = defaultdict(list)
    for e in nodes:
        if rid.get(e) is not None and rel.get(e) == 'Is':
            target[rid[e]].append(e)

    zpar = defaultdict(list)
    for x in L.itertuples(index=False):
        zpar[x.Child_EntityId].append(x)

    def zeus_pick(zs, child_tree):
        def key(z):
            t = tree(z.Parent_EntityId)
            return (0 if child_tree is not None and t == child_tree else 1,
                    -_ts(z.Last_Booked),
                    -(0 if pd.isna(z.Bookings) else z.Bookings),
                    -(0 if pd.isna(z.History_Open) else z.History_Open),
                    -_ts(z.History_Last_Begin),
                    0 if in_scope.get(z.Parent_EntityId) else 1,
                    z.Parent_EntityId)
        ranked = sorted(zs, key=key)
        if len(ranked) == 1:
            return ranked[0].Parent_EntityId, ''
        k0, k1 = key(ranked[0]), key(ranked[1])
        why = next(Z_REASONS[i] for i in range(len(k0)) if k0[i] != k1[i])
        return ranked[0].Parent_EntityId, why

    def describe(e):
        return f'{e} {name.get(e)}'

    recs, contra, replaced = [], [], []
    for e in sorted(nodes, key=lambda x: (RANK[etype[x]], x)):
        t = etype[e]
        allowed = PARENT_TYPES[t]
        zs = sorted(zpar.get(e, []), key=lambda z: z.Parent_EntityId)
        zids = {z.Parent_EntityId for z in zs}
        # Nearest entity of an allowed parent type on the entity's own
        # Definitive record (distance 0, `same`) and on an owner above it
        # (distance >= 1, `owner`): each is (pick, distance, via id, others).
        # Among several on one record: the one Zeus links, then the nearer
        # type (a work location's Client before a HealthSystem), in scope,
        # stronger basis, lowest EntityId.
        same = owner = None
        skipped = []
        if rid.get(e) is not None:
            for d, a in D.ancestry(rid[e], rel[e]):
                if t == 'HealthSystem' and d == 0:
                    continue        # a health system's parent is above it
                cands = [c for c in target.get(a, ())
                         if c != e and etype[c] in allowed]
                if not cands:
                    skipped.append((d, a))
                    continue
                cands.sort(key=lambda c: (
                    0 if c in zids else 1, RANK[etype[c]],
                    0 if in_scope.get(c) else 1,
                    BASIS_RANK.get(basis.get(c), 9), c))
                hit = (cands[0], d, a, cands[1:])
                if d == 0:
                    same = hit
                    continue
                owner = hit
                break
        child_tree = tree(e)
        held = same_alt = None
        why = ''
        pick = dist = via = None
        alts = []
        # An entity on the SAME Definitive record is identity, not ownership:
        # it may confirm a Zeus link or fill a gap, but only an owner can
        # replace or contradict one (2026-10-07, after the first run replaced
        # 1,936 contracting clients - SCP Health, Sound Inpatient Physicians -
        # with the hospital itself).
        agree = next((x for x in (same, owner) if x and x[0] in zids), None)
        decider = agree or (owner if zs else (same or owner))
        if decider is not None:
            pick, dist, via, alts = decider
        elif zs and same is not None:
            same_alt = same[0]
        # Records climbed past on the way to the Definitive parent used; all
        # of those looked at when there is none.
        skipped = [a for d, a in skipped if dist is None or d < dist]
        if pick is not None:
            if pick in zids:
                status, parent = AGREES, pick
            elif not zs:
                status, parent = FILLS, pick
            else:
                dtree = D.root_of(via)
                zt = [tree(z.Parent_EntityId) for z in zs]
                elsewhere = all(x is not None and x != dtree for x in zt)
                # A hospital owner outranks a staffing firm or physician
                # practice (Grant, 2026-10-07): a work location whose Zeus
                # clients are all non-owners does not contradict its owner.
                staffing = (t == 'WorkLocation'
                            and D.type.get(via) in OWNER_TYPES
                            and not any(D.type.get(rid.get(z.Parent_EntityId))
                                        in OWNER_TYPES for z in zs))
                if elsewhere and not staffing:
                    status, held = CONTRA, pick
                    parent, why = zeus_pick(zs, child_tree)
                    for z, zr in zip(zs, zt):
                        contra.append({
                            'Entity_Type': t, 'EntityId': e,
                            'Name': name.get(e),
                            'Resolved_DHC_Id': rid.get(e),
                            'Child_Definitive_Root': child_tree,
                            'Zeus_Parent_EntityId': z.Parent_EntityId,
                            'Zeus_Parent_Type': z.Parent_Type,
                            'Zeus_Parent_Name': name.get(z.Parent_EntityId),
                            'Zeus_Parent_Resolved_DHC_Id':
                                rid.get(z.Parent_EntityId),
                            'Zeus_Parent_TypeFirm':
                                D.type.get(rid.get(z.Parent_EntityId)),
                            'Zeus_Parent_Definitive_Root': zr,
                            'Zeus_Parent_Root_Name': D.name.get(zr),
                            'Zeus_Parent_Kept': z.Parent_EntityId == parent,
                            'Definitive_Parent_EntityId': pick,
                            'Definitive_Parent_Type': etype[pick],
                            'Definitive_Parent_Name': name.get(pick),
                            'Definitive_Via_Id': via,
                            'Definitive_Via_Name': D.name.get(via),
                            'Definitive_Via_TypeFirm': D.type.get(via),
                            'Definitive_Distance': dist,
                            'Definitive_Root': dtree,
                            'Definitive_Root_Name': D.name.get(dtree)})
                else:
                    status, parent = REPLACES, pick
                    for z, zr in zip(zs, zt):
                        replaced.append({
                            'Entity_Type': t, 'EntityId': e,
                            'Name': name.get(e),
                            'Replaced_Zeus_Parent_EntityId': z.Parent_EntityId,
                            'Replaced_Zeus_Parent_Type': z.Parent_Type,
                            'Replaced_Zeus_Parent_Name':
                                name.get(z.Parent_EntityId),
                            'Replaced_Parent_Resolution_Basis':
                                basis.get(z.Parent_EntityId),
                            'Replaced_Parent_Resolved_DHC_Id':
                                rid.get(z.Parent_EntityId),
                            'Replaced_Parent_TypeFirm':
                                D.type.get(rid.get(z.Parent_EntityId)),
                            'Why_Replaced': (
                                'Zeus parent has no trusted Definitive id'
                                if zr is None else
                                'Same Definitive tree as the Definitive parent'
                                if zr == dtree else
                                'Zeus parent is a physician group or staffing '
                                'firm, not an owner' if elsewhere else
                                'Different Definitive tree (another Zeus '
                                'link shares the tree or has no trusted id)'),
                            'Bookings': z.Bookings, 'Last_Booked': z.Last_Booked,
                            'Definitive_Parent_EntityId': pick,
                            'Definitive_Parent_Type': etype[pick],
                            'Definitive_Parent_Name': name.get(pick),
                            'Definitive_Via_Id': via,
                            'Definitive_Via_Name': D.name.get(via),
                            'Definitive_Via_TypeFirm': D.type.get(via),
                            'Definitive_Distance': dist})
        elif zs:
            status = ZEUS
            parent, why = zeus_pick(zs, child_tree)
        else:
            status, parent = NOPARENT, None
        recs.append({
            'EntityId': e, 'Entity_Type': t, 'Level': LEVEL[t],
            'Parent_Type': etype[parent] if parent is not None else None,
            'Parent_EntityId': parent,
            'Zeus_Link_Status': status,
            'Edge_Source': ('Definitive' if status in (AGREES, FILLS, REPLACES)
                            else 'Zeus' if status in (CONTRA, ZEUS) else ''),
            'Definitive_Distance': dist if status != CONTRA else None,
            'Definitive_Via_Id': via if status != CONTRA else None,
            'Definitive_Via_Name': D.name.get(via) if status != CONTRA else None,
            'Definitive_Via_TypeFirm': (D.type.get(via) if status != CONTRA
                                        else None),
            'Skipped_Definitive_Ids': ' | '.join(str(a) for a in skipped),
            'Skipped_Definitive_Names': ' | '.join(
                str(D.name.get(a)) for a in skipped),
            '_skipped': skipped,
            'Zeus_Link_Count': len(zs),
            'Zeus_Linked_Parents': ' | '.join(
                f'{describe(z.Parent_EntityId)} [{SHORT[z.Parent_Type]}]'
                for z in zs),
            'Zeus_Choice_Reason': why,
            'Held_Definitive_Parent_EntityId': held,
            'Held_Definitive_Parent_Name': name.get(held) if held else None,
            'Same_Record_Alternative': (describe(same_alt)
                                        if same_alt is not None else ''),
            'Shared_Id_Alternates': ' | '.join(describe(c) for c in alts),
            'Tree_Issue': '',
        })
    return recs, contra, replaced


def break_loops(recs, name, in_scope):
    """Cut the one Zeus edge that closes each loop of health systems.

    Only health systems can loop - every other edge climbs a type - and
    Definitive's own edges cannot, since each climbs its ownership tree. So a
    loop is always closed by a Zeus link: usually two Zeus records of one
    organisation linked to each other (Baystate Health and Baystate Health),
    or a Zeus link running against a Definitive edge (McLeod Health). In each
    loop the Zeus edge out of the member with the most entities beneath it is
    cut (ties: in scope first, then the lower EntityId): Definitive's edge
    survives, and the bigger record becomes the top with its twin beneath it.
    The cut entity is left with no parent and says why in Tree_Issue.
    """
    by = {x['EntityId']: x for x in recs}
    up = {e: x['Parent_EntityId'] for e, x in by.items()
          if x['Parent_EntityId'] is not None}
    loops, done = [], set()
    for s in sorted(up):
        path, e = [], s
        while e in up and e not in path and e not in done:
            path.append(e)
            e = up[e]
        if e in path:
            loops.append(path[path.index(e):])
        done.update(path)
    kids = defaultdict(list)
    for c, p in up.items():
        kids[p].append(c)

    def beneath(e, loop):
        seen, stack = set(), [c for c in kids[e] if c not in loop]
        while stack:
            c = stack.pop()
            if c not in seen:
                seen.add(c)
                stack.extend(kids[c])
        return len(seen)

    cut = []
    for loop in loops:
        ring = set(loop)
        zeus = [e for e in loop if by[e]['Edge_Source'] == 'Zeus'] or loop
        e = min(zeus, key=lambda m: (-beneath(m, ring),
                                     0 if in_scope.get(m) else 1, m))
        x, p = by[e], by[e]['Parent_EntityId']
        x['Tree_Issue'] = (f'Loop broken: its parent {p} {name.get(p)} '
                           f'sat beneath it')
        x.update(Parent_EntityId=None, Parent_Type=None, Edge_Source='',
                 Zeus_Link_Status=NOPARENT, Definitive_Distance=None,
                 Definitive_Via_Id=None, Definitive_Via_Name=None,
                 Definitive_Via_TypeFirm=None)
        cut.append(e)
    return cut


def top_and_path(recs, name, etype):
    """Each entity's top health system and its path, walking chosen parents."""
    up = {x['EntityId']: x['Parent_EntityId'] for x in recs
          if x['Parent_EntityId'] is not None}
    for x in recs:
        e, seen, chain, issue = x['EntityId'], set(), [], x['Tree_Issue']
        while e is not None:
            if e in seen:
                issue = 'Cycle'
                break
            seen.add(e)
            chain.append(e)
            e = up.get(e)
        hs = [c for c in chain if etype[c] == 'HealthSystem']
        x['Top_HealthSystem_EntityId'] = hs[-1] if hs else None
        x['Top_HealthSystem_Name'] = name.get(hs[-1]) if hs else None
        x['Path_Names'] = SEP.join(f'{str(name.get(c)).strip()} '
                                   f'[{SHORT[etype[c]]}]' for c in chain[::-1])
        x['Tree_Issue'] = issue


# ============================================================================
# Outputs
# ============================================================================
NODE_COLUMNS = [
    'EntityId', 'Entity_Type', 'Zeus_Roles', 'Name', 'City', 'State',
    'Zeus_Sources', 'In_Scope',
    'Resolution_Basis', 'Audit_Detail', 'Resolved_DHC_Id', 'Relation',
    'Resolved_Definitive_Name', 'Resolved_TypeFirm',
    'Definitive_Ultimate_Id', 'Definitive_Ultimate_Name',
    'Level', 'Parent_EntityId', 'Parent_Type', 'Parent_Name',
    'Parent_In_Scope', 'Parent_Resolution_Basis', 'Parent_Resolved_DHC_Id',
    'Zeus_Link_Status', 'Edge_Source', 'Definitive_Distance',
    'Definitive_Via_Id', 'Definitive_Via_Name', 'Definitive_Via_TypeFirm',
    'Skipped_Definitive_Ids', 'Skipped_Definitive_Names',
    'Zeus_Link_Count', 'Zeus_Linked_Parents', 'Zeus_Choice_Reason',
    'Held_Definitive_Parent_EntityId', 'Held_Definitive_Parent_Name',
    'Same_Record_Alternative', 'Shared_Id_Alternates',
    'Top_HealthSystem_EntityId',
    'Top_HealthSystem_Name', 'Path_Names', 'Tree_Issue']
EDGE_COLUMNS = ['EntityId', 'Entity_Type', 'Name', 'Parent_EntityId',
                'Parent_Type', 'Parent_Name', 'Zeus_Link_Status',
                'Edge_Source', 'Resolution_Basis', 'Parent_Resolution_Basis',
                'Definitive_Distance', 'Top_HealthSystem_EntityId',
                'Top_HealthSystem_Name']


def zeus_roles(zs):
    """The HealthSystem / Client / WorkLocation flags behind a type, highest
    first, e.g. 'Client|WorkLocation' for a hospital typed Client."""
    return '|'.join(sorted((r for r in str(zs).split('|') if r in RANK),
                           key=RANK.get, reverse=True))


def node_frame(recs, ent, D):
    E = ent.drop_duplicates('EntityId').set_index('EntityId')
    n = pd.DataFrame(recs).drop(columns='_skipped')
    for c in ('Name', 'City', 'State', 'Zeus_Sources', 'In_Scope',
              'Resolution_Basis', 'Audit_Detail', 'Relation'):
        n[c] = n.EntityId.map(E[c])
    n['Zeus_Roles'] = n.Zeus_Sources.map(zeus_roles)
    n['Resolved_DHC_Id'] = n.EntityId.map(E.Resolved_DHC_Id).astype('Int64')
    r = n.Resolved_DHC_Id
    n['Resolved_Definitive_Name'] = r.map(lambda x: None if pd.isna(x)
                                          else D.name.get(int(x)))
    n['Resolved_TypeFirm'] = r.map(lambda x: None if pd.isna(x)
                                   else D.type.get(int(x)))
    n['Definitive_Ultimate_Id'] = r.map(
        lambda x: pd.NA if pd.isna(x) else D.root_of(int(x))).astype('Int64')
    n['Definitive_Ultimate_Name'] = n.Definitive_Ultimate_Id.map(
        lambda x: None if pd.isna(x) else D.name.get(int(x)))
    p = n.Parent_EntityId
    n['Parent_Name'] = p.map(E.Name)
    n['Parent_In_Scope'] = p.map(E.In_Scope)
    n['Parent_Resolution_Basis'] = p.map(E.Resolution_Basis)
    n['Parent_Resolved_DHC_Id'] = p.map(E.Resolved_DHC_Id).astype('Int64')
    for c in ('Parent_EntityId', 'Definitive_Distance', 'Definitive_Via_Id',
              'Held_Definitive_Parent_EntityId', 'Top_HealthSystem_EntityId'):
        n[c] = pd.to_numeric(n[c]).astype('Int64')
    return n[NODE_COLUMNS]


def dropped_frame(bad, name):
    """Zeus links single typing cannot hold, for the Zeus_Links_Dropped sheet."""
    if not len(bad):
        return pd.DataFrame()
    d = bad.copy()
    d['Child_Name'] = d.Child_EntityId.map(name)
    d['Parent_Name'] = d.Parent_EntityId.map(name)
    d['Why_Dropped'] = [
        f'Both are {c}' if c == p else f'A {p} cannot hold a {c}'
        for c, p in zip(d.Child_Type, d.Parent_Type)]
    return d[['Child_EntityId', 'Child_Type', 'Child_Name', 'Parent_EntityId',
              'Parent_Type', 'Parent_Name', 'Link_Types', 'Bookings',
              'Last_Booked', 'Why_Dropped']]


def parents_not_in_zeus(recs, ent, D):
    """Definitive health systems (or owners outside the views) above a Zeus
    entity that no Zeus entity of a usable type stands for; with any unlinked
    import-created Zeus health system that could."""
    kids = defaultdict(list)
    for x in recs:
        for a in x['_skipped']:
            if D.type.get(a) in ('Health System', EXTERNAL):
                kids[a].append(x)
    if not kids:
        return pd.DataFrame()
    unl = ent[~ent.In_Scope & ~ent.Is_Linked & ent.Resolved_DHC_Id.notna()
              & ent.Zeus_Sources.str.contains('HealthSystem')]
    hint = unl.groupby(unl.Resolved_DHC_Id.astype(int)).apply(
        lambda g: ' | '.join(f'{e} {n}' for e, n in zip(g.EntityId, g.Name)),
        include_groups=False).to_dict()
    rows = []
    for a, xs in kids.items():
        rows.append({
            'Definitive_Id': a, 'Definitive_Name': D.name.get(a),
            'TypeFirm': D.type.get(a),
            'Zeus_Entities_Beneath': len(xs),
            **{f'{t}s_Beneath': sum(x['Entity_Type'] == t for x in xs)
               for t in ROLES},
            'Got_A_Higher_Definitive_Parent': sum(
                x['Edge_Source'] == 'Definitive' for x in xs),
            'Unlinked_Import_Zeus_Record': hint.get(a),
            'Example_Entities': ' | '.join(
                f'{x["EntityId"]} [{SHORT[x["Entity_Type"]]}]'
                for x in xs[:5])})
    return (pd.DataFrame(rows)
            .sort_values(['Zeus_Entities_Beneath', 'Definitive_Id'],
                         ascending=[False, True]).reset_index(drop=True))


def checks(counts, ent, n, edges):
    """Identities that must hold, as (label, left, right)."""
    in_scope = ent[ent.In_Scope]
    rows = [('audit files: entities = distinct entities (no overlap)',
             sum(c for _, c in counts), int(in_scope.EntityId.nunique())),
            ('nodes = distinct entities (one type each)',
             len(n), int(n.EntityId.nunique()))]
    for t in ROLES:
        s = n[n.Entity_Type == t]
        rows.append((f'{t}: with a parent + No parent = entities',
                     int(s.Parent_EntityId.notna().sum()
                         + (s.Zeus_Link_Status == NOPARENT).sum()), len(s)))
    rows += [
        ('status counts = nodes',
         int(n.Zeus_Link_Status.isin(STATUSES).sum()), len(n)),
        ('edges whose parent is a node = edges',
         int(edges.Parent_EntityId.isin(n.EntityId).sum()), len(edges)),
        ('edges whose parent type may hold the child = edges',
         sum(p in PARENT_TYPES[c] for c, p in
             zip(edges.Entity_Type, edges.Parent_Type)), len(edges)),
        ('nodes in a cycle = 0', int((n.Tree_Issue == 'Cycle').sum()), 0),
    ]
    if 'Ready_For_Migration' in n:
        r = n.Ready_For_Migration
        rows.append(('ready + not ready + in no readiness table = nodes',
                     int((r == 1).sum() + (r == 0).sum() + r.isna().sum()),
                     len(n)))
    return rows


def print_checks(rows):
    for k, a, b in rows:
        print(f'  {k:<56} {a:,} == {b:,}  {"OK" if a == b else "FAIL"}')


# ============================================================================
# Workbook
# ============================================================================
def build_workbook(path, run, n, contra, repl, dropped, n_self, pniz, remaps,
                   ent, counts, check_rows, inputs):
    wb = Workbook()
    wb.remove(wb.active)
    ws = wb.create_sheet('Summary')
    for col, w in zip('ABCDEFGHI', (4, 40, 12, 12, 12, 14, 14, 12, 12)):
        ws.column_dimensions[col].width = w
    ws.merge_cells('A1:I1')
    _put(ws, 'A1', 'Jackson and Coker Locum Tenens - Zeus Health System > '
                   'Client > Work Location Hierarchy', H1, FILL_NAVY)
    ws.merge_cells('A2:I2')
    _put(ws, 'A2', f'Run {run} - Definitive first, Zeus to complete it; a '
                   f'read-only comparison baseline', H2, FILL_PURPLE)

    by = {t: n[n.Entity_Type == t] for t in ROLES}
    wl, cl = by['WorkLocation'], by['Client']

    def share(s, statuses):
        return int(s.Zeus_Link_Status.isin(statuses).sum())
    defin = [AGREES, FILLS, REPLACES]
    multi = int(n.Zeus_Roles.str.contains('|', regex=False).sum())
    _put(ws, 'B4', 'Headline', SECTION)
    ws.merge_cells('B5:I11')
    _put(ws, 'B5',
         f'{len(n):,} Zeus entities, each with one type - the highest of its '
         f'Zeus roles: {len(wl):,} work locations, {len(cl):,} clients and '
         f'{len(by["HealthSystem"]):,} health systems. {multi:,} carry more '
         f'than one role in Zeus and are typed by the highest. '
         f'{int((~n.In_Scope.astype(bool)).sum()):,} are '
         f'Definitive-import-created records that Zeus links to in-scope '
         f'entities. Every entity has one parent or none. '
         f'Work locations: {share(wl, defin):,} parents come from Definitive '
         f'({share(wl, [AGREES]):,} agreeing with Zeus, {share(wl, [FILLS]):,} '
         f'filling a gap, {share(wl, [REPLACES]):,} replacing a Zeus link), '
         f'{share(wl, [ZEUS]):,} from Zeus alone, {share(wl, [CONTRA]):,} held '
         f'where Definitive contradicts Zeus, and {share(wl, [NOPARENT]):,} '
         f'have none. Clients: {share(cl, defin):,} health systems from '
         f'Definitive ({share(cl, [FILLS]):,} where Zeus had none), '
         f'{share(cl, [ZEUS]):,} from Zeus alone, {share(cl, [CONTRA]):,} '
         f'held, {share(cl, [NOPARENT]):,} with no health system, which is '
         f'expected. Contradictions keep their Zeus link until reviewed.',
         align=WRAP)

    r = _table(ws, 13, ['Level', 'Entities'] + STATUSES,
               [[LEVEL[k], len(s)] + [int((s.Zeus_Link_Status == st).sum())
                                      for st in STATUSES]
                for k, s in by.items()])
    _put(ws, f'B{r}', 'Entity type: the highest Zeus role wins', SECTION)
    combos = n.groupby(['Zeus_Roles', 'Entity_Type']).size().reset_index(
        name='k').sort_values(['k', 'Zeus_Roles'], ascending=[False, True])
    r = _table(ws, r + 1, ['Zeus roles', 'Entity type', 'Entities'],
               [[x.Zeus_Roles, x.Entity_Type, int(x.k)]
                for x in combos.itertuples(index=False)])
    _put(ws, f'B{r}', 'Zeus links set aside by single typing', SECTION)
    r = _table(ws, r + 1, ['Kind', 'Links', 'Meaning'], [
        ['Entity linked to itself', n_self,
         'A hospital flagged as its own client is now one Client; there is '
         'nothing to link'],
        ['Same type, or upside down', len(dropped),
         'E.g. a Client under another Client. Listed on Zeus_Links_Dropped'],
        ['Health system loops broken',
         int(n.Tree_Issue.str.startswith('Loop broken').sum()),
         'Two health systems Zeus linked to each other; one edge cut. Listed '
         'on Loops_Broken']],
        notes_col=2)
    _put(ws, f'B{r}', 'Where a Definitive parent was found', SECTION)
    d = n[n.Edge_Source == 'Definitive']
    r = _table(ws, r + 1, ['Level', 'Same record (0)', 'Direct owner (1)',
                           'Higher owner (2+)', 'Skipped a level'],
               [[LEVEL[k], int((s.Definitive_Distance == 0).sum()),
                 int((s.Definitive_Distance == 1).sum()),
                 int((s.Definitive_Distance >= 2).sum()),
                 int((s.Skipped_Definitive_Ids != '').sum())]
                for k, s in ((k, d[d.Entity_Type == k]) for k in ROLES)])
    _put(ws, f'B{r}', 'Definitive id behind each entity', SECTION)
    basis = ent[ent.EntityId.isin(n.EntityId)].drop_duplicates('EntityId')
    r = _table(ws, r + 1, ['Resolution basis', 'Entities', 'Used by the '
                                                           'Definitive pass'],
               [[b, len(g), 'Yes' if b in TRUSTED else 'No']
                for b, g in basis.groupby('Resolution_Basis')])
    tops = (wl[wl.Top_HealthSystem_EntityId.notna()]
            .groupby(['Top_HealthSystem_EntityId', 'Top_HealthSystem_Name'])
            .size().rename('WLs').reset_index()
            .sort_values(['WLs', 'Top_HealthSystem_EntityId'],
                         ascending=[False, True]).head(15))
    _put(ws, f'B{r}', 'Largest health systems by work locations beneath',
         SECTION)
    r = _table(ws, r + 1, ['Health system', 'EntityId', 'Work locations'],
               [[x.Top_HealthSystem_Name, int(x.Top_HealthSystem_EntityId),
                 int(x.WLs)] for x in tops.itertuples(index=False)])
    if 'Ready_For_Migration' in n:
        _put(ws, f'B{r}', 'Migration readiness (qat_gold.crmmig_rules)',
             SECTION)
        rows = []
        for t in ROLES[::-1] + ['All']:
            s = n if t == 'All' else n[n.Entity_Type == t]
            own = s.Entity_Type.map(MIGRATION_TABLES)
            rows.append([t, len(s), int((s.Ready_For_Migration == 1).sum()),
                         int((s.Ready_For_Migration == 0).sum()),
                         int(s.Ready_For_Migration.isna().sum()),
                         int((s.Ready_For_Migration_From.notna()
                              & (s.Ready_For_Migration_From != own)).sum()),
                         int(s.Ready_Tables_Disagree.sum())])
        r = _table(ws, r + 1, ['Entity type', 'Entities', 'Ready (1)',
                               'Not ready (0)', 'In no table',
                               "From another type's table",
                               'Tables disagree'], rows)
    _put(ws, f'B{r}', 'Inputs', SECTION)
    r = _table(ws, r + 1, ['Input', 'Value'],
               [[k, v] for k, v in inputs] +
               [[f'Entities in {k}', c] for k, c in counts])
    _put(ws, f'B{r}', 'Identity checks', SECTION)
    _table(ws, r + 1, ['Check', 'Left', 'Right', 'Result'],
           [[k, a, b, 'OK' if a == b else 'FAIL'] for k, a, b in check_rows])

    build_methodology(wb, METHODOLOGY + (
        MIGRATION_METHODOLOGY if 'Ready_For_Migration' in n else []))
    sheet_data(wb, 'Hierarchy', _xl(n))
    sheet_data(wb, 'Contradictions', _xl(contra))
    sheet_data(wb, 'Zeus_Links_Replaced', _xl(repl))
    sheet_data(wb, 'Zeus_Links_Dropped', _xl(dropped))
    sheet_data(wb, 'Loops_Broken', _xl(n[n.Tree_Issue.str.startswith(
        'Loop broken')]))
    multi_p = n[n.Zeus_Link_Count > 1]
    sheet_data(wb, 'Multi_Parent_Choices', _xl(multi_p[[
        'EntityId', 'Entity_Type', 'Name', 'City', 'State', 'Zeus_Link_Count',
        'Zeus_Linked_Parents', 'Parent_EntityId', 'Parent_Type', 'Parent_Name',
        'Zeus_Link_Status', 'Edge_Source', 'Zeus_Choice_Reason']]))
    sheet_data(wb, 'Definitive_Parents_Not_In_Zeus', _xl(pniz))
    sheet_data(wb, 'Shared_Definitive_Id', _xl(n[n.Shared_Id_Alternates != ''][[
        'EntityId', 'Entity_Type', 'Name', 'Parent_EntityId', 'Parent_Type',
        'Parent_Name', 'Definitive_Via_Id', 'Definitive_Via_Name',
        'Shared_Id_Alternates']]))
    sheet_data(wb, 'Orphans', _xl(n[(n.Entity_Type == 'WorkLocation')
                                    & (n.Zeus_Link_Status == NOPARENT)]))
    sheet_data(wb, 'Duplicates_Remapped', _xl(remaps))
    wb.save(path)


METHODOLOGY = [
    ('What this is', 'One Zeus Health System > Client > Work Location '
                     'hierarchy, built from Definitive ownership first and '
                     'completed from Zeus links, as a read-only baseline to '
                     'compare the migration team\'s hierarchy against. A '
                     'strict tree: every entity has one parent or none, and '
                     'the alternatives are listed on their own sheets, never '
                     'kept as extra parents (decided 2026-10-07).'),
    ('Entity type', 'Each entity has one type, the highest of its Zeus roles: '
                    'HealthSystem over Client over WorkLocation (decided '
                    '2026-10-07). A hospital Zeus flags as both client and work '
                    'location is a Client. Zeus_Roles shows every flag behind '
                    'the type.'),
    ('Levels', 'A parent is always a higher type, or a health system under a '
               'health system to any depth: a work location sits under a '
               'client or a health system, a client under a health system, a '
               'health system under a health system. Zeus links come from '
               'LinkClientWorkLocation and LinkHealthSystemClient; a link that '
               'does not fit the types - an entity linked to itself, or a '
               'client under a client - is set aside (Zeus_Links_Dropped).'),
    ('Universe', 'Every in-scope entity of the two audits (the accuracy and '
                 'coverage runs together) that holds a HealthSystem, Client or '
                 'WorkLocation role. A Definitive-import-created entity is '
                 'added where Zeus links it to an in-scope entity, and then '
                 'each entity\'s parents are added until the chain is complete '
                 '(decided 2026-10-07).'),
    ('Definitive id of an entity', 'Taken from the audits: a supplied id rated '
                                   'ID corroborated or Probable without a '
                                   'Geo_Conflict; a recommended correction; '
                                   'a Strong coverage proposal; or, for an '
                                   'import-created entity, the id it was '
                                   'created from. Anything else has no '
                                   'Definitive id here and can only take a '
                                   'Zeus parent. Resolution_Basis says which. '
                                   'Relation = LocationOf where the entity '
                                   'matched a service location of the id, '
                                   'i.e. the id is its owner\'s.'),
    ('Definitive parent', 'Walk up the entity\'s Definitive ownership chain - '
                          'its own record (distance 0), its direct owner (1), '
                          'and so on to the top - and take the nearest record '
                          'that a Zeus entity of an allowed parent type stands '
                          'for (Relation Is). A health system\'s parent must be '
                          'above it. A Zeus entity on the same record may '
                          'confirm or fill, but only an owner (distance 1 or '
                          'more) may replace or contradict a Zeus link. Several '
                          'entities on one record: the one Zeus already links, '
                          'then the nearer type, then in scope, then the '
                          'stronger basis, then the lowest EntityId (others on '
                          'Shared_Definitive_Id). Records climbed past are in '
                          'Skipped_Definitive_*.'),
    ('Zeus_Link_Status', 'Agrees: Definitive\'s parent is one of Zeus\'s. '
                         'Definitive fills: Zeus had no link. Definitive '
                         'replaces: Zeus linked another parent in the same '
                         'Definitive tree, one with no trusted Definitive id, '
                         'or - for a work location - only physician groups or '
                         'staffing firms where Definitive names a hospital or '
                         'health system owner. Contradiction: every Zeus parent '
                         'sits in a different Definitive tree and the case is '
                         'not that one; held - the Zeus link is kept for now - '
                         'and listed. Zeus only: no Definitive parent. No '
                         'parent: neither source has one (expected for many '
                         'clients).'),
    ('Owners over staffing firms', 'Hospital owners take priority (decided '
                                   '2026-10-07): a staffing firm or physician '
                                   'practice is not the owner of the work '
                                   'locations it staffs, so it cannot '
                                   'contradict Definitive\'s hospital or health '
                                   'system owner. A Zeus client whose '
                                   'Definitive record is a hospital or health '
                                   'system can, and stays held.'),
    ('Same Definitive tree', 'Two records are in the same tree when they have '
                             'the same ultimate owner (Definitive_Ultimate_Id) '
                             'in the Definitive hierarchy. A record with no '
                             'owner is its own tree.'),
    ('Choosing among Zeus links', 'When Zeus links an entity to several parents '
                                  'and Definitive gives none: a parent in the '
                                  'entity\'s own Definitive tree, then the most '
                                  'recent booking, the most bookings, an open '
                                  'link history, the latest history start, in '
                                  'scope over import-created, the lowest '
                                  'EntityId. Zeus_Choice_Reason names the step '
                                  'that decided.'),
    ('Duplicates', 'An entity marked DuplicateOfId another is replaced by its '
                   'survivor - in every link and as a Definitive parent - where '
                   'the survivor has the same type. Duplicates_Remapped lists '
                   'each.'),
    ('Health system loops', 'Two health systems can point at each other: Zeus '
                            'links two records of one organisation to each '
                            'other, or runs a link against Definitive. In each '
                            'such loop the Zeus edge out of the record with '
                            'the most entities beneath it is cut, so '
                            'Definitive\'s edge survives and the bigger record '
                            'becomes the top. The cut entity has no parent and '
                            'Tree_Issue says why (sheet Loops_Broken).'),
    ('Top health system', 'Top_HealthSystem_* is the highest health system '
                          'reached by walking the chosen parents. Path_Names '
                          'shows that chain, top first, each name tagged with '
                          'its type.'),
    ('Reproducibility', 'Zeus and Definitive both change in place. The run '
                        'folder holds the Zeus link snapshots and the '
                        'Definitive hierarchy snapshots it used; pass the '
                        'folder as --zeus-links and --definitive-hierarchy, '
                        'with the same audit files, to regenerate it exactly.'),
]


MIGRATION_METHODOLOGY = [
    ('Ready_For_Migration', 'The migration team\'s ready_for_migration flag '
                            '(1 ready, 0 not) from qat_gold.crmmig_rules: '
                            'healthsystem_summary, client_summary and '
                            'worklocation_summary, keyed HealthSystemInfoId, '
                            'ClientInfoId and WorkLocationInfoId, each the '
                            'Zeus EntityId. An entity takes the flag from the '
                            'table of its own Entity_Type; where that table '
                            'has no row, from another table, highest type '
                            'first, and Ready_For_Migration_From names the '
                            'table used. Blank: the entity is in none of the '
                            'three. Some EntityIds are in more than one table, '
                            'so each table\'s own flag is shown as '
                            'Ready_<Type>_Summary, and Ready_Tables_Disagree '
                            'marks those whose tables differ. Snapshotted per '
                            'run as _migration_readiness.parquet; '
                            '--migration-from replays it.'),
]


# ============================================================================
# Main
# ============================================================================
def main():
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--config', required=True)
    ap.add_argument('--accuracy', required=True, metavar='SCORED_CSV',
                    help='an accuracy run\'s _scored.csv (its '
                         '_unverifiable.csv is read too)')
    ap.add_argument('--coverage', required=True, metavar='CANDIDATES_CSV',
                    help='a coverage run\'s _gap_candidates.csv (its '
                         '_gap_nomatch.csv is read too)')
    ap.add_argument('--definitive-hierarchy', metavar='RUN',
                    help='replay the Definitive hierarchy snapshots of a '
                         'dhc_hierarchy or zeus_hierarchy run (folder or '
                         'prefix); default: query the views live')
    ap.add_argument('--zeus-links', metavar='RUN',
                    help='replay the Zeus link snapshots of an earlier '
                         'zeus_hierarchy run (folder or prefix); default: '
                         'query Zeus live')
    ap.add_argument('--migration-from', metavar='RUN',
                    help='replay the migration readiness snapshot of an '
                         'earlier zeus_hierarchy run (folder or prefix); '
                         'default: query qat_gold.crmmig_rules live')
    ap.add_argument('--no-migration', action='store_true',
                    help='leave the migration readiness columns out (the '
                         'pre-2026-10-07 output)')
    ap.add_argument('--label', help='optional suffix for the run folder name')
    ap.add_argument('--results-dir', default=RESULTS_DIR)
    a = ap.parse_args()

    cfg = load_config(a.config)
    ent, counts = load_audits(a.accuracy, a.coverage)
    prefix = new_run_prefix('zeus_hierarchy', a.label, a.results_dir)
    for k, c in counts:
        print(f'  {k:<22}: {c:>7,} entities')

    links, imp, dup = load_zeus_links(cfg.get('zeus') or {}, prefix,
                                      a.zeus_links)
    imp_rows = import_rows(imp)
    clash = set(imp_rows.EntityId) & set(ent.EntityId)
    if clash:
        print(f'  WARNING: {len(clash):,} import-created entities are also in '
              f'the audit files; the audit row is used.')
        imp_rows = imp_rows[~imp_rows.EntityId.isin(clash)]
    ent = pd.concat([ent, imp_rows], ignore_index=True)

    src = resolve_hierarchy_prefix(cfg, a.definitive_hierarchy)
    h = walk(load_hierarchy(cfg, prefix, src))
    D = Definitive(h, ent)
    print(f'Definitive  : {len(h):,} hierarchy records')

    etype = entity_types(ent)
    nodes, L, bad, n_self, remap = build_universe(ent, links, survivors(dup),
                                                  etype)
    recs, contra, replaced = decide(nodes, etype, L, ent, D)
    E = ent.drop_duplicates('EntityId').set_index('EntityId')
    name = E.Name.to_dict()
    cut = break_loops(recs, name, E.In_Scope.to_dict())
    top_and_path(recs, name, etype)
    n = node_frame(recs, ent, D)
    mig = None
    if not a.no_migration:
        mig = load_migration(cfg, prefix, a.migration_from)
        n = attach_migration(n, mig)
    edges = n[n.Parent_EntityId.notna()][EDGE_COLUMNS]
    contra = pd.DataFrame(contra)
    if len(contra):
        # Where each side of a contradiction ends up in this tree. Often both
        # reach the same top system - Zeus names a division or a merged
        # predecessor (Mountain States Health Alliance) that itself sits under
        # Definitive's owner (Ballad Health) - which a reviewer can clear fast.
        top = dict(zip(n.EntityId, n.Top_HealthSystem_EntityId))
        for side in ('Zeus_Parent', 'Definitive_Parent'):
            t = contra[f'{side}_EntityId'].map(top)
            contra[f'{side}_Top_HealthSystem'] = [
                None if pd.isna(x) else f'{int(x)} {name.get(int(x))}' for x in t]
        contra['Same_Top_HealthSystem'] = (
            contra.Zeus_Parent_Top_HealthSystem.notna()
            & contra.Zeus_Parent_Top_HealthSystem.eq(
                contra.Definitive_Parent_Top_HealthSystem))
    repl = pd.DataFrame(replaced)
    dropped = dropped_frame(bad, name)
    pniz = parents_not_in_zeus(recs, ent, D)
    remaps = pd.DataFrame(
        [{'EntityId': e, 'Entity_Type': etype[e], 'Name': name.get(e),
          'Survivor_EntityId': s, 'Survivor_Name': name.get(s)}
         for e, s in sorted(remap.items())],
        columns=['EntityId', 'Entity_Type', 'Name', 'Survivor_EntityId',
                 'Survivor_Name'])

    is_node = ent.EntityId.isin(n.EntityId)
    res = ent[ent.In_Scope | is_node].drop(columns=['Is_Linked']).copy()
    res['Is_Node'] = res.EntityId.isin(n.EntityId)
    res['Entity_Type'] = res.EntityId.map(etype)
    res['In_Definitive_Hierarchy'] = res.Resolved_DHC_Id.map(
        lambda x: pd.notna(x) and int(x) in D.known)

    n.to_csv(f'{prefix}_hierarchy_nodes.csv', index=False)
    edges.to_csv(f'{prefix}_hierarchy_edges.csv', index=False)
    contra.to_csv(f'{prefix}_contradictions.csv', index=False)
    repl.to_csv(f'{prefix}_zeus_links_replaced.csv', index=False)
    dropped.to_csv(f'{prefix}_zeus_links_dropped.csv', index=False)
    res.to_csv(f'{prefix}_resolution.csv', index=False)

    in_n = ~n.In_Scope.astype(bool)
    print(f'Entities    : {len(n):,}  ('
          + ', '.join(f'{(n.Entity_Type == t).sum():,} {t}' for t in ROLES)
          + f'); {int(in_n.sum()):,} import-created; '
          f'{int(n.Zeus_Roles.str.contains("|", regex=False).sum()):,} '
          f'typed by the highest of several Zeus roles')
    print(f'Zeus links  : {len(L):,} usable between entities; {n_self:,} '
          f'self-links and {len(bad):,} same-type or upside-down links set '
          f'aside; {len(remap):,} duplicate(s) merged into their survivor; '
          f'{len(cut):,} health system loop(s) broken')
    for t in ROLES:
        s = n[n.Entity_Type == t]
        print(f'  {LEVEL[t]}')
        for st in STATUSES:
            k = int((s.Zeus_Link_Status == st).sum())
            if k:
                print(f'    {st:<22}: {k:>7,}')
    rids = res.Resolved_DHC_Id.dropna().astype(int)
    print(f'  resolved ids in the Definitive hierarchy: '
          f'{int(rids.isin(D.known).sum()):,} of {len(rids):,} (the rest are '
          f'GPOs, practice-location parents or ids Definitive has dropped)')
    if mig is not None:
        r = n.Ready_For_Migration
        print(f'Migration   : {int((r == 1).sum()):,} ready, '
              f'{int((r == 0).sum()):,} not ready, {int(r.isna().sum()):,} in '
              f'no readiness table; '
              f'{int((n.Ready_For_Migration_From.notna() & (n.Ready_For_Migration_From != n.Entity_Type.map(MIGRATION_TABLES))).sum()):,} '
              f'from another type\'s table; '
              f'{int(n.Ready_Tables_Disagree.sum()):,} whose tables disagree')
    rows = checks(counts, ent, n, edges)
    print_checks(rows)
    print(f'Wrote {prefix}_hierarchy_nodes.csv  (+ _edges, _contradictions, '
          f'_zeus_links_replaced, _zeus_links_dropped, _resolution)')

    wbp = workbook_path(prefix, 'Zeus_Entity_Hierarchy')
    inputs = [('Accuracy run', os.path.basename(a.accuracy)),
              ('Coverage run', os.path.basename(a.coverage)),
              ('Definitive hierarchy', src or 'queried live'),
              ('Zeus links', a.zeus_links or 'queried live')]
    if mig is not None:
        inputs.append(('Migration readiness',
                       a.migration_from or 'queried live'))
    build_workbook(wbp, os.path.basename(prefix), n, contra, repl, dropped,
                   n_self, pniz, remaps, ent, counts, rows, inputs)
    print(f'Wrote {wbp}')


if __name__ == '__main__':
    main()
