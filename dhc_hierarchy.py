#!/usr/bin/env python3
"""Definitive Healthcare ownership hierarchy, one row per record.

Built for comparison with the destination system data produced by the
migration team. Hospital Overview only, by rule (2026-09-30); the parent rule
- SfParentAccountId, else IdNetwork, else HospitalId (a root) - is defined in
`Definitive Hospital Hierarchy.sql` and nowhere else. This script walks each
record's ParentId up to its root and reports level, root and path.

Every record carries two parents, labelled, because the tree is up to three
levels deep (system > division or region > hospital) and the destination
system may model either grain:
  Immediate_Parent*  the direct owner, full tree (e.g. HCA North Texas Division)
  Ultimate_Parent*   the top-level owner, tree flattened to two levels (HCA)
They differ only for records with an intermediate owner. A root is its own
immediate and ultimate parent.

  py dhc_hierarchy.py --config sources.yaml
      [--accuracy "Results Output/<accuracy run>/<run>_scored.csv"]
      [--definitive-from "Results Output/<earlier hierarchy run>"]
      [--label <suffix>]

Writes into its own folder, "Results Output/dhc_hierarchy_<YYYY_MM_DD_HHMM>/":
  <run>_hierarchy.csv                       every record, both parents, path
  <run>_hierarchy_immediate.csv             edge list: record -> direct owner
  <run>_hierarchy_ultimate.csv              edge list: record -> top-level owner
  <run>_dhc_hospitalhierarchy.parquet/.sql  the Definitive snapshot and its SQL
  Definitive_Hospital_Hierarchy_<run date and time>.xlsx

`--accuracy` adds the Zeus EntityIds that carry each id, read from a scored
accuracy run, so the output can be compared by either key.
"""
import argparse
import os

import pandas as pd
from openpyxl import Workbook

from dhc_match_v2 import RESULTS_DIR, load_config, materialise_tables, \
    new_run_prefix, resolve_prefix
from build_audit_workbook import FILL_NAVY, FILL_PURPLE, H1, H2, SECTION, \
    NOTE, WRAP, _put, _table, build_methodology, sheet_data, workbook_path

SEP = ' > '


def load_hierarchy(cfg, prefix, definitive_from=None):
    """The hierarchy snapshot for this run, queried live or replayed."""
    b = dict(cfg['hierarchy'])
    one = {'databricks': cfg.get('databricks'), 'definitive': [b]}
    if definitive_from:
        materialise_tables({'definitive': [dict(b)]}, definitive_from,
                           replay=True, copy_to=prefix)
        b['path'] = f'{prefix}_dhc_{b["snapshot"]}.parquet'
    else:
        materialise_tables(one, prefix)
    df = pd.read_parquet(b['path'])
    for c in ('HospitalId', 'ParentId', 'SfParentAccountId', 'IdNetwork'):
        df[c] = pd.to_numeric(df[c]).astype('Int64')
    if df.HospitalId.duplicated().any():
        raise SystemExit(f'{df.HospitalId.duplicated().sum()} duplicate '
                         f'HospitalId rows in the hierarchy source.')
    return df


def walk(df):
    """Level, root and path for every record, following ParentId upward.

    A record whose parent is itself is a root (level 0). A parent absent from
    the view ends the walk there: that id becomes the root, named from the
    child's SfParentAccountName / NameNetwork, and the row is flagged. A cycle
    would also end the walk and be flagged; none existed on 2026-09-30.
    """
    parent = dict(zip(df.HospitalId, df.ParentId))
    name = dict(zip(df.HospitalId, df.HospitalName))
    ext_name = {}
    for r in df.itertuples():
        if r.ParentId not in parent:
            ext_name[r.ParentId] = (r.SfParentAccountName
                                    if r.Parent_Rule == 'SfParentAccountId'
                                    else r.NameNetwork)
    out = {}
    for start in df.HospitalId:
        chain, seen, issue = [start], {start}, ''
        while True:
            p = parent[chain[-1]]
            if p == chain[-1]:
                break
            if p not in parent:
                chain.append(p)
                issue = 'Parent_Not_In_Definitive'
                break
            if p in seen:
                issue = 'Cycle'
                break
            chain.append(p)
            seen.add(p)
        path = chain[::-1]                       # root first
        out[start] = (len(path) - 1, path[0],
                      name.get(path[0], ext_name.get(path[0])),
                      SEP.join(str(x) for x in path),
                      SEP.join(str(name.get(x, ext_name.get(x))) for x in path),
                      issue)
    w = pd.DataFrame.from_dict(
        out, orient='index',
        columns=['Level', 'RootId', 'RootName', 'Path_Ids', 'Path_Names',
                 'Hierarchy_Issue'])
    h = df.merge(w, left_on='HospitalId', right_index=True)
    h['RootId'] = h.RootId.astype('Int64')
    h['ParentName'] = h.ParentId.map(name).fillna(h.ParentId.map(ext_name))
    h['Is_Root'] = h.ParentId == h.HospitalId
    h['Parent_In_Definitive'] = h.ParentId.isin(parent)
    kids = h[~h.Is_Root].groupby('ParentId').size()
    h['Child_Count'] = h.HospitalId.map(kids).fillna(0).astype(int)
    # Descendants: every record whose path passes through this one, itself
    # excluded. Paths are root-first id strings, so each ancestor is counted
    # once per descendant.
    desc = pd.Series(
        [int(x) for p in h.Path_Ids for x in p.split(SEP)[:-1]]).value_counts()
    h['Descendant_Count'] = h.HospitalId.map(desc).fillna(0).astype(int)
    tf = dict(zip(h.HospitalId, h.TypeFirm))
    h['Parent_TypeFirm'] = h.ParentId.map(tf)
    h['Root_TypeFirm'] = h.RootId.map(tf)
    h['Ultimate_Level'] = (~h.Is_Root).astype(int)
    h['Has_Intermediate_Parent'] = h.ParentId != h.RootId
    return h


def attach_zeus(h, scored):
    """Zeus entities carrying each Definitive id, from a scored accuracy run."""
    z = pd.read_csv(scored, dtype=str, usecols=['EntityId', 'DHC_Id',
                                                'Zeus_Sources', 'Verdict'])
    z['DHC_Id'] = pd.to_numeric(z.DHC_Id, errors='coerce').astype('Int64')
    z = z.dropna(subset=['DHC_Id'])
    g = z.groupby('DHC_Id').agg(
        Zeus_Entity_Count=('EntityId', 'nunique'),
        Zeus_EntityIds=('EntityId', lambda v: '|'.join(sorted(set(v), key=int))),
        Zeus_Sources=('Zeus_Sources', lambda v: '|'.join(sorted(
            {x for s in v.dropna() for x in s.split('|')}))),
        Zeus_Verdicts=('Verdict', lambda v: '|'.join(sorted(set(v.dropna())))))
    h = h.merge(g, left_on='HospitalId', right_index=True, how='left')
    h['Zeus_Entity_Count'] = h.Zeus_Entity_Count.fillna(0).astype(int)
    tree = h.groupby('RootId').Zeus_Entity_Count.sum()
    h['Tree_Zeus_Entity_Count'] = h.RootId.map(tree).fillna(0).astype(int)
    return h, len(z), int(z.DHC_Id.isin(h.HospitalId).sum())


# Internal name -> output label. The walk keeps the short internal names; every
# file and sheet shows the labels, so "parent" is never ambiguous.
LABELS = {
    'ParentId': 'Immediate_ParentId',
    'ParentName': 'Immediate_ParentName',
    'Parent_TypeFirm': 'Immediate_Parent_TypeFirm',
    'Parent_Rule': 'Immediate_Parent_Rule',
    'Parent_In_Definitive': 'Immediate_Parent_In_Definitive',
    'Level': 'Immediate_Level',
    'Child_Count': 'Immediate_Child_Count',
    'RootId': 'Ultimate_ParentId',
    'RootName': 'Ultimate_ParentName',
    'Root_TypeFirm': 'Ultimate_Parent_TypeFirm',
}
COLUMNS = ['HospitalId', 'HospitalName', 'TypeFirm', 'TypeHospital',
           'CompanyStatus', 'HqCity', 'HqState', 'Is_Root',
           'ParentId', 'ParentName', 'Parent_TypeFirm', 'Parent_Rule',
           'Parent_In_Definitive', 'Level', 'Child_Count',
           'RootId', 'RootName', 'Root_TypeFirm', 'Ultimate_Level',
           'Has_Intermediate_Parent', 'Descendant_Count',
           'Path_Ids', 'Path_Names', 'Hierarchy_Issue',
           'SfParentAccountId', 'SfParentAccountName', 'IdNetwork',
           'NameNetwork']
IMMEDIATE = ['HospitalId', 'HospitalName', 'TypeFirm', 'ParentId',
             'ParentName', 'Parent_TypeFirm', 'Level', 'Is_Root',
             'Parent_Rule']
ULTIMATE = ['HospitalId', 'HospitalName', 'TypeFirm', 'RootId', 'RootName',
            'Root_TypeFirm', 'Ultimate_Level', 'Is_Root',
            'Has_Intermediate_Parent']


def labelled(df, cols=None):
    """Rows in tree order, output labels; `cols` picks internal columns."""
    df = df.sort_values(['RootId', 'Path_Ids'])
    return (df[cols] if cols else df).rename(columns=LABELS)


def immediate_edges(h):
    """Record -> direct owner: the full tree as a child/parent edge list."""
    return labelled(h, IMMEDIATE)


def ultimate_edges(h):
    """Record -> top-level owner: the tree flattened to two levels. The
    immediate parent is kept only where it differs, as Intermediate_*, so the
    flattened view still shows the tier it skipped."""
    u = labelled(h, ULTIMATE)
    mid = h.sort_values(['RootId', 'Path_Ids'])
    u['Intermediate_ParentId'] = mid.ParentId.where(
        mid.Has_Intermediate_Parent).astype('Int64')
    u['Intermediate_ParentName'] = mid.ParentName.where(
        mid.Has_Intermediate_Parent)
    return u
ZEUS_COLUMNS = ['Zeus_Entity_Count', 'Zeus_EntityIds', 'Zeus_Sources',
                'Zeus_Verdicts', 'Tree_Zeus_Entity_Count']


def checks(h):
    """Identities that must hold; printed and written to the Summary."""
    roots = h[h.Is_Root]
    # Records under a root that is not itself a Definitive record (its id is
    # a parent missing from the view) belong to no root's Descendant_Count.
    orphaned = int((~h.RootId.isin(roots.HospitalId)).sum())
    return [
        ('Every record has exactly one parent', h.ParentId.notna().all()),
        ('Level 0 records are exactly the self-parented roots',
         ((h.Level == 0) == h.Is_Root).all()),
        ('Roots + their descendants + records under missing parents = all',
         len(roots) + roots.Descendant_Count.sum() + orphaned == len(h)),
        ('No cycles', (h.Hierarchy_Issue != 'Cycle').all()),
    ]


def _xl(df):
    """Nullable Int64 columns hold pd.NA, which openpyxl cannot write."""
    return df.astype(object).where(df.notna(), None)


def build_workbook(h, path, run, zeus_info):
    wb = Workbook()
    wb.remove(wb.active)
    ws = wb.create_sheet('Summary')
    for col, w in zip('ABCDE', (4, 46, 16, 16, 60)):
        ws.column_dimensions[col].width = w
    ws.merge_cells('A1:E1')
    _put(ws, 'A1', 'Jackson and Coker Locum Tenens - Definitive Hospital '
                   'Ownership Hierarchy', H1, FILL_NAVY)
    ws.merge_cells('A2:E2')
    _put(ws, 'A2', f'Run {run} - Definitive Hospital Overview, one row per '
                   f'record', H2, FILL_PURPLE)

    roots = h[h.Is_Root]
    ext = h[h.Hierarchy_Issue == 'Parent_Not_In_Definitive']
    trees = h.groupby('RootId').size()
    multi = int((trees > 1).sum())
    _put(ws, 'B4', 'Headline', SECTION)
    ws.merge_cells('B5:E8')
    _put(ws, 'B5',
         f'Definitive Hospital Overview holds {len(h):,} records '
         f'({(h.TypeFirm == "Hospital").sum():,} hospitals and '
         f'{(h.TypeFirm == "Health System").sum():,} health systems). Each '
         f'record\'s immediate parent is its SfParentAccountId, else its '
         f'IdNetwork, else the record itself. That arranges them into '
         f'{trees.size:,} trees: {multi:,} with more than one member and '
         f'{trees.size - multi:,} standalone records, at most '
         f'{h.Level.max()} levels deep. Each record is given two parents: its '
         f'immediate parent (direct owner) and its ultimate parent (top-level '
         f'owner). They differ for the {int(h.Has_Intermediate_Parent.sum()):,} '
         f'records owned through a division or region. {len(ext):,} '
         f'record(s) name a parent that is not in Hospital Overview. They are '
         f'kept, and flagged on Hierarchy_Issues.', align=WRAP)

    r = _table(ws, 10, ['Immediate_Level', 'Records', 'Hospitals',
                        'Health systems'],
               [[int(lv), len(g), int((g.TypeFirm == 'Hospital').sum()),
                 int((g.TypeFirm == 'Health System').sum())]
                for lv, g in h.groupby('Level')])
    mid, n_root = int(h.Has_Intermediate_Parent.sum()), int(h.Is_Root.sum())
    _put(ws, f'B{r}', 'Immediate versus ultimate parent', SECTION)
    r = _table(ws, r + 1, ['Records', 'Count', 'Meaning'], [
        ['Roots: their own immediate and ultimate parent', n_root,
         'Top-level systems and standalone hospitals'],
        ['Immediate parent = ultimate parent', len(h) - mid - n_root,
         'Owned directly by a top-level system'],
        ['Immediate parent differs from ultimate', mid,
         'Owned through a division or region, e.g. HCA Healthcare > HCA '
         'Medical City Healthcare > Medical City Denton. Immediate_* names the '
         'division, Ultimate_* the top-level system']], notes_col=2)
    r = _table(ws, r, ['Parent decided by', 'Records', 'Of which roots'],
               [[k, len(g), int(g.Is_Root.sum())]
                for k, g in h.groupby('Parent_Rule')])
    big = (h.groupby(['RootId', 'RootName'], dropna=False)
           .agg(n=('HospitalId', 'size'), d=('Level', 'max'))
           .sort_values('n', ascending=False).head(15).reset_index())
    _put(ws, f'B{r}', 'Largest ultimate parents', SECTION)
    r = _table(ws, r + 1, ['Ultimate parent', 'Ultimate_ParentId',
                           'Records in tree', 'Depth'],
               [[x.RootName, int(x.RootId), int(x.n), int(x.d)]
                for x in big.itertuples()])
    if zeus_info:
        n_scored, n_in = zeus_info
        linked = h[h.Zeus_Entity_Count > 0]
        _put(ws, f'B{r}', 'Zeus linkage', SECTION)
        r = _table(ws, r + 1, ['Measure', 'Count'], [
            ['Zeus entities in the accuracy run with a Definitive id',
             n_scored],
            ['... whose id is a Hospital Overview record', n_in],
            ['Hospital Overview records carried by a Zeus entity',
             len(linked)],
            ['Trees with at least one Zeus-linked record',
             int(linked.RootId.nunique())]])
    _put(ws, f'B{r}', 'Identity checks', SECTION)
    r = _table(ws, r + 1, ['Check', 'Result'],
               [[k, 'OK' if v else 'FAIL'] for k, v in checks(h)])

    build_methodology(wb, [
        ('Source', 'prd_silver.definitive.hospitaloverview only, per the rule '
                   'set on 2026-09-30. It holds hospitals and health systems, '
                   'so health systems appear as ordinary records and as the '
                   'parents of hospitals. Physician groups, GPOs and practice '
                   'locations are not in this hierarchy.'),
        ('Parent rule', 'Immediate_ParentId = SfParentAccountId if present; '
                        'otherwise IdNetwork; otherwise the record\'s own '
                        'HospitalId, which makes it a root. '
                        'Immediate_Parent_Rule says which step decided. The '
                        'rule is defined in "Definitive Hospital '
                        'Hierarchy.sql", and the SQL that ran is saved beside '
                        'the snapshot.'),
        ('Immediate parent', 'The direct owner in the full tree. It can be a '
                             'division or regional system, e.g. HCA Medical '
                             'City Healthcare or VISN 1. Immediate_Level 0 is '
                             'a root, and each step up counts as one level. '
                             'Sheet Immediate_Parent is this view as a '
                             'child/parent list.'),
        ('Ultimate parent', 'The top-level owner, e.g. HCA Healthcare or '
                            'Department of Veterans Affairs: the tree '
                            'flattened to two levels. Ultimate_Level is 0 for '
                            'a root, otherwise 1. Where a division sits in '
                            'between, Has_Intermediate_Parent is True, and '
                            'sheet Ultimate_Parent names that division as '
                            'Intermediate_*.'),
        ('Which to compare', 'Both are given, because the destination system '
                             'may or may not model divisions as their own '
                             'accounts. The two differ only for records with '
                             'an intermediate owner. A root is its own '
                             'immediate and ultimate parent.'),
        ('Path', 'Path_Ids / Path_Names list the chain root first, separated '
                 'by " > ", ending at the record itself.'),
        ('Child and descendant counts', 'Immediate_Child_Count is the number '
                                        'of records whose immediate parent is '
                                        'this one. Descendant_Count is every '
                                        'record below it at any depth. For a '
                                        'root, that is the size of its tree, '
                                        'less itself.'),
        ('Parents not in Definitive', 'A parent id missing from Hospital '
                                      'Overview ends the walk. That id becomes '
                                      'the root, named from the child\'s '
                                      'SfParentAccountName or NameNetwork, and '
                                      'Parent_In_Definitive is False. These '
                                      'rows are kept, not dropped.'),
        ('Zeus columns', 'Present only when the run was given --accuracy. '
                         'Zeus_EntityIds lists the Zeus entities whose '
                         'Definitive id is this record, taken from that scored '
                         'accuracy run. Tree_Zeus_Entity_Count adds them up '
                         'across the ultimate parent\'s whole tree.'),
        ('Reproducibility', 'Definitive views are refreshed in place. This '
                            'workbook describes the snapshot saved in its own '
                            'run folder. Pass --definitive-from with that '
                            'folder to regenerate it exactly.'),
    ])
    sheet_data(wb, 'Immediate_Parent', _xl(immediate_edges(h)))
    sheet_data(wb, 'Ultimate_Parent', _xl(ultimate_edges(h)))
    sheet_data(wb, 'Hierarchy', _xl(labelled(h)))
    sheet_data(wb, 'Roots', _xl(roots.sort_values('Descendant_Count',
                                                  ascending=False)
                                .rename(columns=LABELS)))
    sheet_data(wb, 'Hierarchy_Issues',
               _xl(labelled(h[h.Hierarchy_Issue != ''])))
    if zeus_info:
        sheet_data(wb, 'Zeus_Linked', _xl(labelled(h[h.Zeus_Entity_Count > 0])))
    wb.save(path)


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--config', required=True)
    ap.add_argument('--accuracy', metavar='SCORED_CSV',
                    help='a scored accuracy run; adds the Zeus EntityIds that '
                         'carry each Definitive id')
    ap.add_argument('--definitive-from', metavar='PREFIX',
                    help='replay the hierarchy snapshot of an earlier '
                         'dhc_hierarchy run (its folder or prefix)')
    ap.add_argument('--label', help='optional suffix for the run folder name')
    ap.add_argument('--results-dir', default=RESULTS_DIR)
    a = ap.parse_args()

    cfg = load_config(a.config)
    if not cfg.get('hierarchy'):
        raise SystemExit('No `hierarchy:` block in the config.')
    src = a.definitive_from
    if src and os.path.isdir(src):
        hits = [f for f in os.listdir(src) if f.endswith(
            f'_dhc_{cfg["hierarchy"]["snapshot"]}.parquet')]
        src = (os.path.join(src, hits[0][:-len(
            f'_dhc_{cfg["hierarchy"]["snapshot"]}.parquet')])
            if len(hits) == 1 else resolve_prefix(src))
    prefix = new_run_prefix('dhc_hierarchy', a.label, a.results_dir)
    h = walk(load_hierarchy(cfg, prefix, src))

    cols = list(COLUMNS)
    zeus_info = None
    if a.accuracy:
        h, n_scored, n_in = attach_zeus(h, a.accuracy)
        cols += ZEUS_COLUMNS
        zeus_info = (n_scored, n_in)
    h = h[cols]

    out = f'{prefix}_hierarchy.csv'
    labelled(h).to_csv(out, index=False)
    immediate_edges(h).to_csv(f'{prefix}_hierarchy_immediate.csv', index=False)
    ultimate_edges(h).to_csv(f'{prefix}_hierarchy_ultimate.csv', index=False)
    trees = h.groupby('RootId').size()
    print(f'Records     : {len(h):,}  ({(h.TypeFirm == "Hospital").sum():,} '
          f'hospitals, {(h.TypeFirm == "Health System").sum():,} health systems)')
    print(f'Trees       : {trees.size:,}  ({(trees > 1).sum():,} with more than '
          f'one member), max depth {h.Level.max()}')
    print(f'Parents     : {h.Has_Intermediate_Parent.sum():,} records have an '
          f'immediate parent different from their ultimate parent')
    for k, n in h.Parent_Rule.value_counts().items():
        print(f'  parent from {k:<18}: {n:,}')
    print(f'Issues      : {(h.Hierarchy_Issue != "").sum():,} '
          f'{h.Hierarchy_Issue[h.Hierarchy_Issue != ""].value_counts().to_dict()}')
    if zeus_info:
        print(f'Zeus        : {zeus_info[1]:,} of {zeus_info[0]:,} scored '
              f'entities carry a Hospital Overview id; '
              f'{(h.Zeus_Entity_Count > 0).sum():,} records are Zeus-linked')
    for k, v in checks(h):
        print(f'  {"OK  " if v else "FAIL"} {k}')
    print(f'Wrote       : {out}  (+ _immediate.csv, _ultimate.csv)')
    wbp = workbook_path(prefix, 'Definitive_Hospital_Hierarchy')
    build_workbook(h, wbp, os.path.basename(prefix), zeus_info)
    print(f'Wrote       : {wbp}')


if __name__ == '__main__':
    main()
