# Environment

What a Windows 11 machine needs to **run** this project and to **keep developing
it**, written for a developer taking it over. Day-to-day commands are in
[Usage.md](Usage.md). The design decisions, and why they must not be reversed
casually, are in [CLAUDE.md](CLAUDE.md). Read that before changing any scoring
logic.

Last verified against the original owner's machine on 2026-09-29.

## 1. Access you need first

Software alone isn't enough. Ask for these before you start, because each has
an owner and a lead time.

| Access | What for | Ask |
|---|---|---|
| GitHub: collaborator on the **private** repo `GrantJCLT/Zeus-DHC-Ids-to-Definitive-Source-Fuzzy-Matching` | Source code | Repo owner (Grant). Consider moving it to an org-owned repo or Azure DevOps `jclt/BI` at handover |
| Zeus SQL login `JCBIReportUser` password | Reading Zeus (Azure SQL, failover replica, read-only) | Zeus DBA / BI engineering |
| Network path to `prd-jcl-zeus-failover.ff2d73e4c70e.database.windows.net:1433` | Same | Corporate network or VPN; the Azure SQL firewall may need your IP |
| Azure Databricks workspace `adb-8032826808193104.4.azuredatabricks.net`, signed in with your Entra ID account | Reading Definitive | Databricks workspace admin |
| **CAN USE** on SQL warehouse `qat-eus-jcl-Databricks-W-M` (id `5941bfd954019dc3`) | Running the Definitive queries | Databricks workspace admin |
| **SELECT** on the four views in `prd_silver.definitive` (`hospitaloverview`, `physiciangroupsoverview`, `grouppurchasingorganizationoverview`, `physicianspracticelocations`) | Same | Unity Catalog owner of `prd_silver` |
| Governed archive location (SharePoint / blob) | Keeping run folders; see Usage.md, "What to keep" | Team lead |

Definitive Healthcare data is **licensed**. Don't copy the `Definitive_*.xlsx`
exports or any `*_dhc_*.parquet` snapshot off managed storage without
confirming terms with the licence owner.

## 2. Software to install

Every item has a `winget` command. Run them in a PowerShell terminal (admin
isn't needed for most; the ODBC driver needs elevation). If an ID doesn't
resolve, find the current one with `winget search <name>`.

| Software | Version in use | Install |
|---|---|---|
| Python | **3.14.6** (3.10+ works; 3.12 and 3.14 are both known-good) | `winget install Python.Python.3.14`. Tick "Add to PATH" and keep the `py` launcher |
| Microsoft ODBC Driver for SQL Server | **18** (17 also works; set `driver:` in `sources.yaml` to match) | `winget install Microsoft.msodbcsql.18` |
| Databricks CLI | v1.7.0 | `winget install Databricks.DatabricksCLI` |
| Git for Windows | 2.55 | `winget install Git.Git` |
| GitHub CLI (optional) | — | `winget install GitHub.cli` |
| VS Code (recommended) | — | `winget install Microsoft.VisualStudioCode`, plus the Python and Databricks extensions |
| uv (optional) | 0.10.11 | `winget install astral-sh.uv`. Only needed to manage the `.venv` described in section 4 |
| Excel | — | To open the deliverable workbooks |

Check the install:

```powershell
py --version
databricks --version
git --version
py -c "import pyodbc; print(pyodbc.drivers())"   # after section 3; must list 'ODBC Driver 18 for SQL Server'
```

## 3. Python packages

The tools need these packages, and nothing else outside the standard library:

| Package | Used by | Version in use |
|---|---|---|
| `pandas` | everything | 3.0.5 |
| `numpy` | everything | 2.5.1 |
| `rapidfuzz` | name and address scoring | 3.14.5 |
| `openpyxl` | reading xlsx exports, writing the workbooks | 3.1.5 |
| `pyyaml` | reading `sources.yaml` | 6.0.3 |
| `pyodbc` | reading Zeus | 5.3.0 |
| `databricks-sql-connector` | reading Definitive from the SQL warehouse | 4.6.0 |
| `databricks-sdk` | Databricks OAuth via the CLI profile | 0.143.0 |
| `pyarrow` | writing and reading the parquet snapshots | 25.0.1 |

Install into the Python you'll run the tools with:

```powershell
py -m pip install pandas numpy rapidfuzz openpyxl pyyaml pyodbc `
    databricks-sql-connector databricks-sdk pyarrow
```

The repo doesn't yet pin these anywhere. `pyproject.toml` declares only
`databricks-connect`, a dev dependency the tools don't import. A
`requirements.txt` (or a `[project] dependencies` list) with the versions above
would be a worthwhile first commit for a new owner.

## 4. Which Python

There are two candidate interpreters on the original machine. Only one of
them works.

- **System Python 3.14**, `%LOCALAPPDATA%\Programs\Python\Python314\python.exe`.
  It has every package in section 3, and it's what the 2026-09-29 runs used.
- **The project `.venv`** (Python 3.12, managed by uv). It was created by
  `databricks environments setup-local` for Databricks Connect, and
  `pyproject.toml`'s `[tool.uv]` block belongs to that command. **It currently
  lacks `rapidfuzz`, `openpyxl`, `pyyaml`, `pyodbc` and
  `databricks-sql-connector`**, so the tools fail inside it.

The trap: VS Code activates `.venv` automatically in its integrated terminal,
and once a venv is active **`py` runs the venv's Python, not the system one**.
The symptom is `ModuleNotFoundError: No module named 'rapidfuzz'`.

Pick one approach:

- **Complete the venv** (recommended; it keeps the project self-contained):
  ```powershell
  uv pip install --python .venv\Scripts\python.exe rapidfuzz openpyxl pyyaml pyodbc databricks-sql-connector
  ```
  `pandas`, `numpy`, `pyarrow` and `databricks-sdk` are already there. Don't
  hand-edit the `[tool.uv]` block in `pyproject.toml`; it's regenerated by
  `databricks environments setup-local`.
- **Use the system Python.** Run `deactivate` in the terminal, or select the
  3.14 interpreter with VS Code's *Python: Select Interpreter*.

On a fresh machine without a `.venv` (it's not in git), a plain
`py -m venv .venv` followed by the section 3 `pip install` works too.

## 5. Configuration and secrets

### Zeus password

It's read from an environment variable and never stored in a file. Set it
once, at User scope:

```powershell
[Environment]::SetEnvironmentVariable('ZEUS_SQL_PASSWORD', '<password>', 'User')
```

Then **close and reopen** every terminal and VS Code window. Running processes
don't see new User variables. Check with `[bool]$env:ZEUS_SQL_PASSWORD`.

Don't put the password in `sources.yaml`, a `.env` committed to git, or an
MCP config. `.env` and `*.local.yaml` are git-ignored as a backstop.

### Databricks login

OAuth, held by the Databricks CLI. No token is stored in the project.

```powershell
databricks auth login --host https://adb-8032826808193104.4.azuredatabricks.net --profile jcl
databricks auth profiles        # jcl should show Valid YES
```

The profile **must be named `jcl`**, because `sources.yaml` refers to it by name.
It's written to `%USERPROFILE%\.databrickscfg`, with the token in the Windows
credential store (`auth_storage = secure`). Logins expire. When a run fails to
authenticate, repeat the `auth login`.

### `sources.yaml`

This holds the connection details and column-role mappings, and needs no
per-machine edits. Two settings must not change:

- `application_intent: ReadOnly`. The Zeus host is a failover-group listener;
  without the declared intent the connection is routed read-write. The run
  prints and checks `connected to a READ_ONLY database`.
- `driver:`. It must name an ODBC driver that `pyodbc.drivers()` lists.

## 6. Getting the code

```powershell
cd C:\Code
git clone https://github.com/GrantJCLT/Zeus-DHC-Ids-to-Definitive-Source-Fuzzy-Matching.git "Zeus DHC Ids to Definitive Source Fuzzy Matching"
```

Any folder works. Run the tools from the repo root, because the config uses
relative paths.

**Not everything is in git yet.** As of 2026-09-29 these are in the working
directory but untracked, and must be committed before handover or a clone
cannot run:

- the four `Definitive *.sql` query files (**required**: `sources.yaml` points
  at them);
- `pyproject.toml`, `uv.lock` and `databricks.yml` (the Databricks
  local-environment and bundle stubs);
- uncommitted edits to the Python files, `sources.yaml`, `.gitignore` and
  `CLAUDE.md`.

Deliberately **not** in git (see `.gitignore` and CLAUDE.md, "Version control"):

| Item | Where to get it |
|---|---|
| `Results Output\` (all past runs, extracts, snapshots, workbooks) | The governed archive, or the previous owner's machine. You only need it to replay or compare old runs |
| `Definitive_*.xlsx` | No longer read since 2026-09-29; Definitive comes live from Databricks. Needed only to rebuild pre-2026-09-29 runs |
| `Zeus_DHC_ID_Accuracy_Audit.xlsx` | The reporting-format template (ignored by the `Zeus_DHC_ID_*.xlsx` rule). The builders don't read it; it's a design reference. Copy it from the previous owner |

A **history-rewrite is pending**: the root commit `f7f0e4e` still contains
~100 MB of licensed Definitive data and Zeus client records (CLAUDE.md, open
work #5). Keep the repo private until that's done.

## 7. First-run smoke test

With sections 1–6 done, the following confirms every connection in a few
minutes, without a full run:

```powershell
py -c "import rapidfuzz, pyodbc, openpyxl, yaml, databricks.sql; print('packages ok')"
databricks auth profiles
py dhc_gap_match.py --config sources.yaml --limit 200 --label smoketest
```

Look for `connected to a READ_ONLY database`, four Definitive row counts, six Zeus
population counts, and `Wrote ..._gap_candidates.csv`. Delete the
`Results Output\dhc_gap_match_*_smoketest` folder afterwards. Then do a full
accuracy run as described in Usage.md.

## 8. Development notes

- **Layout.** `dhc_match_v2.py` holds all normalisation and scoring;
  `dhc_gap_match.py` imports it (`import dhc_match_v2 as M`), and
  `build_coverage_workbook.py` imports styling from `build_audit_workbook.py`.
  Change shared behaviour in one place only.
- **No test suite exists.** Regression checking is done by replaying an
  archived run offline (`--zeus` plus `--definitive-from`, Usage.md) and
  diffing the new `_scored.csv` / `_gap_candidates.csv` against the old one.
  The identity checks the builders print are the second line of defence. Any
  scoring change should report how many verdicts or tiers moved, and in which
  direction. CLAUDE.md records every past change that way.
- **Offline development.** A replay needs neither the Zeus password nor a
  Databricks login. With a copy of one archived run folder you can develop the
  scoring and the workbooks entirely offline.
- **Baselines.** `ZEUS_BASELINE_ENTITIES` (`dhc_match_v2.py`) and
  `GAP_BASELINE_ENTITIES` (`dhc_gap_match.py`) drive the population-drift
  `NOTE`. Update them only after explaining a population change.
- **Documentation.** `CLAUDE.md` is the project's working memory: decisions,
  results, known quirks and open work. It's also read automatically by Claude
  Code if you use it. Keep it current after each run or change.
  `Zeus_DHC_ID_Audit_Business_Overview.md` is for business readers and has
  hand-copied figures.
- **Databricks bundle.** `databricks.yml` is an empty bundle stub (dev target
  only) created by the VS Code Databricks extension. Nothing is deployed from
  it. It's a starting point if the project moves to a Databricks job (CLAUDE.md,
  open work #4).
- **Paths.** File names contain spaces. Quote them in
  PowerShell, and in `sources.yaml` if you add new ones.
