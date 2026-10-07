#!/usr/bin/env python3
"""Run the whole audit in one go: both runs, every workbook, the hierarchy.

  1. dhc_match_v2.py run          - the accuracy audit
  2. dhc_gap_match.py             - the coverage audit, cross-checked against 1
                                    (--claimed) and scored against 1's Definitive
                                    snapshots (--definitive-from), so both audits
                                    see the same Definitive data
  3. build_audit_workbook.py      - accuracy workbook
  4. build_coverage_workbook.py   - coverage workbook
     only if --population is given: steps 3 and 4 again, limited to that
     population, as EXTRA workbooks beside the full ones
  5. dhc_hierarchy.py             - the Definitive ownership hierarchy
  6. zeus_hierarchy.py            - the Zeus HealthSystem > Client >
                                    WorkLocation hierarchy, from 1, 2 and 5
  Steps 5 and 6 need both audits, so --accuracy-only skips them, and
  --no-hierarchy skips them on purpose.

Both runs always score all six Zeus populations and the full workbooks are
always built; --population never narrows or removes anything.

Each step is the existing script, run unchanged with this same Python, so its
console output is exactly what Usage.md describes. The first step that fails
stops the run. The end is a summary of the checks Usage.md asks for.

  py run_all.py                                    # everything: 4 workbooks
  py run_all.py --population WorkLocation          # the same, plus 2 Work Location workbooks
  py run_all.py --population all                   # the same, plus 2 per population (16)
  py run_all.py --limit 200 --label smoke          # quick end-to-end test
"""
import argparse
import os
import re
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))


class StepFailed(Exception):
    pass


def step(title, args, log):
    """Run one script with this Python, stream its output, and keep it."""
    print(f'\n{"=" * 78}\n{title}\n  {" ".join(args)}\n{"=" * 78}', flush=True)
    env = dict(os.environ, PYTHONUNBUFFERED='1')
    t0 = time.time()
    p = subprocess.Popen([sys.executable] + args, cwd=HERE, env=env,
                         stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                         text=True, encoding='utf-8', errors='replace')
    lines = []
    for line in p.stdout:
        sys.stdout.write(line)
        sys.stdout.flush()      # live even when redirected to a log file
        lines.append(line.rstrip('\n'))
    p.wait()
    log.append((title, lines, time.time() - t0))
    if p.returncode:
        raise StepFailed(f'{title} failed (exit code {p.returncode}); nothing '
                         f'after it was run.')
    return lines


def run_folder(lines, title):
    for l in lines:
        m = re.match(r'Run folder\s*:\s*(.+)$', l)
        if m:
            return m.group(1).strip()
    raise StepFailed(f'{title} did not report its run folder.')


def prefix_of(folder):
    return os.path.join(folder, os.path.basename(folder))


def population_labels(config):
    """Every zeus.sources label in the config, for --population all, so the
    list is never hard-coded here. Checked before anything runs."""
    import yaml
    with open(os.path.join(HERE, config), encoding='utf-8') as f:
        cfg = yaml.safe_load(f)
    labels = [s['label'] for s in cfg.get('zeus', {}).get('sources', [])
              if s.get('label')]
    if not labels:
        raise SystemExit(f'--population all: no zeus.sources labels in {config}')
    return labels


def summarise(log, limit):
    """The checks from Usage.md, read back from everything the steps printed."""
    problems, notes, books = [], [], []
    for title, lines, _ in log:
        for l in lines:
            s = l.strip()
            if s.startswith('connected to a '):
                ok = 'READ_ONLY' in s
                notes.append(f'{"OK  " if ok else "FAIL"} {title}: {s}')
                if not ok:
                    problems.append(f'{title}: {s}')
            elif s.startswith('NOTE:'):
                notes.append(f'NOTE {title}: {s}')
            elif s.startswith('WARNING'):
                notes.append(f'WARN {title}: {s}')
                problems.append(f'{title}: {s}')
            elif s.startswith('Wrote ') and s.endswith('.xlsx'):
                books.append(s[len('Wrote '):])
            elif s.endswith(('OK', 'FAIL')) and '==' in s:
                # With --limit only N entities are scored but the extract holds
                # everyone, so this one identity cannot hold on a smoke test.
                expected = (limit and s.endswith('FAIL')
                            and s.startswith('extract entities'))
                tag = 'OK  ' if s.endswith('OK') else (
                    'n/a ' if expected else 'FAIL')
                notes.append(f'{tag} {title}: {s}'
                             + ('  (expected with --limit)' if expected else ''))
                if tag == 'FAIL':
                    problems.append(f'{title}: {s}')
    return problems, notes, books


def main():
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--config', default='sources.yaml')
    ap.add_argument('--population', action='append', default=[], metavar='LABEL',
                    help='ALSO build workbooks limited to one Zeus population, '
                         'in addition to the full ones (never instead of '
                         'them); repeatable; labels: Client, WorkLocation, '
                         'HealthSystem, GPO, Agency, VMS, or "all" for every '
                         'label under zeus.sources in the config')
    ap.add_argument('--label', help='suffix for both run folders')
    ap.add_argument('--accuracy-only', action='store_true',
                    help='stop after the accuracy run and its workbook(s)')
    ap.add_argument('--limit', type=int,
                    help='coverage run scores only the first N entities '
                         '(quick end-to-end test)')
    ap.add_argument('--no-reverse', action='store_true',
                    help='accuracy run skips the reverse lookup')
    ap.add_argument('--no-hierarchy', action='store_true',
                    help='skip the Definitive and Zeus hierarchy steps')
    a = ap.parse_args()
    if any(p.lower() == 'all' for p in a.population):
        a.population = population_labels(a.config)

    t_start = time.time()
    log = []
    label = ['--label', a.label] if a.label else []
    try:
        lines = step('1. Accuracy run',
                     ['dhc_match_v2.py', 'run', '--config', a.config] + label +
                     (['--no-reverse'] if a.no_reverse else []), log)
        acc = run_folder(lines, '1. Accuracy run')
        scored = prefix_of(acc) + '_scored.csv'

        cand = None
        if not a.accuracy_only:
            lines = step('2. Coverage run',
                         ['dhc_gap_match.py', '--config', a.config,
                          '--claimed', scored, '--definitive-from', acc] + label +
                         (['--limit', str(a.limit)] if a.limit else []), log)
            gap = run_folder(lines, '2. Coverage run')
            cand = prefix_of(gap) + '_gap_candidates.csv'

        for pop in [None] + a.population:
            scope = ['--population', pop] if pop else []
            name = f' ({pop})' if pop else ''
            step(f'3. Accuracy workbook{name}',
                 ['build_audit_workbook.py', '--scored', scored,
                  '--config', a.config] + scope, log)
            if cand:
                step(f'4. Coverage workbook{name}',
                     ['build_coverage_workbook.py', '--candidates', cand,
                      '--accuracy', scored, '--config', a.config] + scope, log)

        if cand and not a.no_hierarchy:
            lines = step('5. Definitive hierarchy',
                         ['dhc_hierarchy.py', '--config', a.config,
                          '--accuracy', scored] + label, log)
            hier = run_folder(lines, '5. Definitive hierarchy')
            step('6. Zeus hierarchy',
                 ['zeus_hierarchy.py', '--config', a.config,
                  '--accuracy', scored, '--coverage', cand,
                  '--definitive-hierarchy', hier] + label, log)
        failed = None
    except StepFailed as e:
        failed = str(e)

    problems, notes, books = summarise(log, a.limit)
    print(f'\n{"=" * 78}\nSummary  ({(time.time() - t_start) / 60:.1f} min)\n'
          f'{"=" * 78}')
    for title, _, secs in log:
        print(f'  {secs / 60:5.1f} min  {title}')
    print('\nChecks:')
    for n in notes:
        print(f'  {n}')
    if books:
        print('\nWorkbooks:')
        for b in books:
            print(f'  {b}')
    if failed:
        print(f'\nSTOPPED: {failed}')
    if problems:
        print('\nNeeds attention before circulating:')
        for p in problems:
            print(f'  {p}')
    if not failed and not problems:
        print('\nAll steps finished and every check passed.')
    return 1 if (failed or problems) else 0


if __name__ == '__main__':
    sys.exit(main())
