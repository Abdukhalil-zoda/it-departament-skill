"""Unit tests for scripts/dashboard_sync.py (stdlib unittest).

Run from the scripts directory:  python -m unittest discover -s tests -v
The fixture vault is copied from assets/vault-template when the skill root is reachable, otherwise it is
built from dashboard_sync.skeleton() (e.g. when only scripts/ is mounted into a container).
"""
import datetime
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

SCRIPTS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, SCRIPTS)
import dashboard_sync as ds  # noqa: E402

SKILL = os.path.dirname(SCRIPTS)
TEMPLATE_VAULT = os.path.join(SKILL, 'assets', 'vault-template')
TEMPLATES = os.path.join(SKILL, 'templates')
NOW = datetime.datetime(2026, 10, 7, 9, 30)
DASH, SEP, ARROW = ds.DASH, ds.SEP, '\N{RIGHTWARDS ARROW}'

TASK_1 = """---
id: DEMO-001
title: "Checkout: multi-currency | batch"
status: In-Development # In-Analysis (default for Full route) | Ready-For-Dev (for Lightweight route)
route: full # full | lightweight
type: feature # feature | bug | refactor | docs
priority: high # critical | high | medium | low
target_repository: "." # repository subdirectory or '.' for single-repo
assigned_agent: dev-backend # dev-backend | dev-frontend | dev-mobile
branch: "feature/DEMO-001/07.10.2026/dev-backend"
date_created: "2026-10-05"
date_updated: "2026-10-06"
pr_link: ""
docs: ["docs/requirements/spec.md", "vault/06-Content/glossary.md", "docs/missing.md"] # related documents
qa_status: pending # pending | testing | passed | failed
content_review: required # required | not-applicable
content_review_intake: approved # pending | approved | changes-requested | not-applicable
cto_approved: false
tags:
  - task
  - checkout
---

# [Checkout] DEMO-001: Multi-currency checkout

## 10. Transition Log
- {YYYY-MM-DDTHH:MM:SSZ} In-Analysis \N{RIGHTWARDS ARROW} Ready-For-Dev by coordinator (evidence: \N{HORIZONTAL ELLIPSIS})
"""
TASK_2 = """---
id: DEMO-002
status: Backlog
route: full
priority: critical
assigned_agent: dev-frontend
branch: ""
content_review: not-applicable # internal tooling only
content_review_intake: not-applicable
qa_status: pending
tags: [task, cart]
---

# Saved carts
"""
TASK_3 = """---
id: DEMO-003
title: 'Fix rounding in totals'
status: Code-Review
route: lightweight
priority: low
assigned_agent: dev-backend
branch: feature/DEMO-003/07.10.2026/dev-backend
content_review: required
content_review_intake: pending
qa_status: testing
---
"""
BUG_1 = """---
id: BUG-001
parent_task: "[[DEMO-001]]"
title: "[BUG] Bank title shown in Cyrillic in uz"
status: Open # Open | In-Development | Code-Review | Retesting | Closed | Archived
severity: Major # Critical | Major | Minor | Trivial
category: content # functional | content | security | performance | accessibility
locale: "uz" # for content defects: the locale code
assigned_agent: dev-frontend # dev-backend | dev-frontend
date_created: "2026-10-06"
release_blocking: true # true for Critical & Major, false for Minor & Trivial
tags:
  - bug
  - content-review # qa-reported | content-review
---
"""
BUG_2 = """---
id: BUG-002
parent_task: "[[DEMO-003]]"
title: "[BUG] Rounding differs by one cent"
status: Closed
severity: Minor
category: functional
locale: ""
assigned_agent: dev-backend
release_blocking: false
---
"""
ADR_1 = """---
id: ADR-001
title: "Use PostgreSQL"
status: Accepted # Proposed | Accepted | Rejected | Superseded
decision_type: standard
date: "2026-10-02"
approver: "CTO / User"
tags:
  - adr
---

# [ADR-001] Use PostgreSQL
"""
ARCHIVED_TASK = """---
id: DEMO-000
title: "Project skeleton"
status: Archived
release_version: "v0.1.0"
release_commit: "abc1234def5678"
archived_at: "2026-10-03"
---
"""
RESOLVED_BUG = """---
id: BUG-000
title: "[BUG] Crash on start"
status: Archived
severity: Critical
release_version: "v0.1.0"
release_commit: "abc1234def5678"
archived_at: "2026-10-02"
---
"""
QA_REPORT = """---
id: QA-2026-10-03-RC-abc1234
scope: RC-abc1234
candidate_sha: abc1234def5678
verdict: passed # passed | failed | passed-with-deferrals
defects: { critical: 0, major: 0, minor: 1, trivial: 0 }
date: "2026-10-03"
tags: [qa-report]
---
"""
CONTENT_REVIEW = """---
id: CR-2026-10-05-RC-abc1234        # scope = {TASK-ID} for an intake review, RC-{sha7} for a pre-release review
checkpoint: pre-release            # task-creation | pre-release
scope: "RC-abc1234"
baseline: "0123abc"
locales_reviewed: ["ru", "uz"]
reviewer_confidence:               # fluent | working | limited, per locale
  "ru": fluent
  "uz": limited
findings: { critical: 0, major: 1, minor: 2, trivial: 3, needs_native_check: 1 }
verdict: approved-with-deferrals   # intake: approved | changes-requested   pre-release: approved | blocked
cto_signoff: "CTO 2026-10-05"
inventory: "[[content-inventory-2026-10-05-abc1234]]"   # pre-release only
date: "2026-10-05"
tags:
  - content-review
---

# Content review
"""
AUDIT_NEW_MD = """# Usage audit - 2026-10-06 (window since 2026-10-04)

## 4. Rule indicators

| Rule | Indicator | Value | Limit | Status |
|---|---|---|---|---|
| R1 | task/day pairs with more build jobs than allowed per fix round | 0 | 2 | OK |
| R2 | session folders above the screenshot budget | 0 | 10 | OK |
| R2 | sessions that read more images than the budget | 1 (abc12345: 14) | 10 | CHECK |
| R3 | QA re-verification jobs / minutes | 2 / 30 | targeted only | review |
| R4 | tool results above the token limit (lower bound) | 2 | 2 000 | CHECK |
| R4 | context compactions in the window | 1 | 0 | CHECK |
| R5 | jobs that waited longer than the queue limit | 0 | 5 min | OK |
| R5 | dev/QA overlap minutes on the shared host | 0 | 0 | OK |

## 7. Proposals for the CTO (max 5, auditor fills in)

| # | Change | Evidence (numbers) | Expected saving | Where applied | Risk | Decision |
|---|---|---|---|---|---|---|
| 1 | Downscale screenshots before vision reads | 14 images | 20k tokens | QA brief | low | approved 2026-10-07 (D-002) |
| 2 | Batch fix rounds | 5 builds | 30 min | dev brief | low |  |
"""
AUDIT_NEW_JSON = {'date': '2026-10-06', 'since': '2026-10-04', 'ledger_sessions': 3, 'weighted_total': 1200000,
                  'output_tokens': 50000, 'images_read': 14, 'compactions': 1, 'tool_results_over_r4': 2, 'jobs': 12,
                  'jobs_hours': 3.46, 'build_jobs': 5, 'jobs_waited_over_max': 0, 'overlap_minutes': 0, 'screenshots_total': 30}
AUDIT_OLD_MD = """# Usage audit - 2026-10-04 (window since 2026-10-02)

## 7. Proposals for the CTO (max 5, auditor fills in)

| # | Change | Evidence (numbers) | Expected saving | Where applied | Risk |
|---|---|---|---|---|---|
| 1 | Export the ledger in every session | 2 sessions missing | n/a | coordinator brief | none |
"""
AUDIT_OLD_JSON = {'date': '2026-10-04', 'since': '2026-10-02', 'ledger_sessions': 2, 'weighted_total': 1000000,
                  'output_tokens': 40000, 'images_read': 3, 'compactions': 0, 'tool_results_over_r4': 0, 'jobs': 0,
                  'jobs_hours': 0, 'build_jobs': 0, 'jobs_waited_over_max': 0, 'overlap_minutes': 0, 'screenshots_total': 0}
CONFIG = {
    'project_name': 'Demo', 'cto_mode': 'USER', 'operating_profile': 'pilot',
    'paths': {'vault_relative_path': 'vault', 'sessions_relative_path': '.it-department/sessions',
              'worktrees_relative_path': '.it-department/worktrees'},
    'efficiency': {'audit_interval_days': 2, 'reports_path': 'vault/05-Reports',
                   'rules': {'R1_builds_per_fix_round_max': 2, 'R2_screenshots_per_scenario_max': 10}},
    'content_review': {'enabled': True, 'reports_path': 'vault/05-Reports'},
    'documents': [{'title': 'Product specification', 'path': 'docs/requirements/spec.md'},
                  {'title': 'API notes', 'path': 'docs/api notes.md'},
                  {'title': 'Roadmap', 'path': 'docs/roadmap.md'}],
}
LOCK = {'owner_role': 'coordinator', 'session_id': 's-42', 'host': 'cowork', 'started_at': '2026-10-07T09:00:00Z',
        'expires_at': '2099-01-01T00:00:00Z', 'scope': 'vault + dashboard', 'note': 'waves 3-4'}
OLD_DASHBOARD = '\n'.join([
    '# \N{OFFICE BUILDING} Project Engineering Dashboard', '',
    '**Project:** Demo  ', '**Last Updated:** 2026-10-01 10:00 (manual)  ', '**CTO Decision Mode:** USER  ',
    '**Vault Archival Policy:** Active (Zero-Deletion Enforced)', '', '---', '',
    '## \N{BAR CHART} Live Task Kanban Overview', '',
    '| Backlog | In-Analysis | Ready-For-Dev | In-Development | Code-Review | QA-Testing | Ready-For-Release | Archived |',
    '| :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |', '| 9 | 9 | 9 | 9 | 9 | 9 | 9 | 9 |', '', '---', '',
    '## \N{ROCKET} Active Sprint Tasks', '', '| Task ID | Title |', '| :--- | :--- |', '| [[DEMO-001]] | hand-written row |', '',
    '> [!NOTE]', '> Manual wave note that must survive.', '',
    '## \N{BUG} Open Defects & Bugs (`vault/02-Bugs/`) - 3 open of 51', '', '| Bug ID | Title |', '| :--- | :--- |', '', '---', '',
    '## \N{CLASSICAL BUILDING}\N{VARIATION SELECTOR-16} Architectural Decision Records (`vault/03-ADR/`)', '',
    '| ADR ID | Decision Title |', '| :--- | :--- |', '', '---', '',
    '## \N{CHART WITH UPWARDS TREND} Usage audits (`vault/05-Reports/`)', '', '| Date | Report |', '| :--- | :--- |', '', '---', '',
    '## \N{PACKAGE} Recent Production Releases (`vault/04-Archive/Completed-Tasks/`)', '',
    '| Release Tag | Commit SHA |', '| :--- | :--- |', '| v0.0.1 | 1111111 |', '', '---', '',
    ds.TIP[0], ds.TIP[1], '', ''])


def write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w', encoding='utf-8', newline='\n') as fh:
        fh.write(text)


def build_project(root, use_template=True):
    """Project with 3 tasks, 2 bugs, 1 ADR, 2 usage audits, 1 content review, 1 QA report, documents and a lock."""
    vault = os.path.join(root, 'vault')
    if use_template and os.path.isdir(TEMPLATE_VAULT):
        shutil.copytree(TEMPLATE_VAULT, vault)
        dash = os.path.join(vault, ds.DASHBOARD)
        text = ds.read_text(dash).replace('{PROJECT_NAME}', 'Demo').replace('{LAST_UPDATED}', '2026-10-01').replace('{CTO_MODE}', 'USER')
        write(dash, text)
    else:
        for sub in ds.TASK_STATUSES:
            os.makedirs(os.path.join(vault, '01-Tasks', sub))
        for sub in ('02-Bugs', '03-ADR', '04-Archive/Completed-Tasks', '04-Archive/Resolved-Bugs', '05-Reports'):
            os.makedirs(os.path.join(vault, sub))
        write(os.path.join(vault, ds.DASHBOARD), ds.skeleton())
    for name in ('glossary.md', 'style-guide.md'):
        path = os.path.join(vault, '06-Content', name)
        if not os.path.exists(path):
            write(path, '# %s\n' % name)
    if not os.path.exists(os.path.join(vault, '03-ADR', 'decisions-log.md')):
        write(os.path.join(vault, '03-ADR', 'decisions-log.md'), '# Decisions journal\n')
    write(os.path.join(root, '.it-department', 'config.json'), json.dumps(CONFIG, indent=2))
    write(os.path.join(root, '.it-department', 'lock.json'), json.dumps(LOCK))
    write(os.path.join(root, 'docs', 'requirements', 'spec.md'), '# Spec\n')
    write(os.path.join(root, 'docs', 'api notes.md'), '# API\n')
    write(os.path.join(vault, '01-Tasks', 'In-Development', 'DEMO-001.md'), TASK_1)
    write(os.path.join(vault, '01-Tasks', 'Backlog', 'DEMO-002.md'), TASK_2)
    write(os.path.join(vault, '01-Tasks', 'Code-Review', 'DEMO-003.md'), TASK_3)
    write(os.path.join(vault, '02-Bugs', 'BUG-001.md'), BUG_1)
    write(os.path.join(vault, '02-Bugs', 'BUG-002.md'), BUG_2)
    write(os.path.join(vault, '03-ADR', 'ADR-001-use-postgres.md'), ADR_1)
    write(os.path.join(vault, '04-Archive', 'Completed-Tasks', 'DEMO-000.md'), ARCHIVED_TASK)
    write(os.path.join(vault, '04-Archive', 'Resolved-Bugs', 'BUG-000.md'), RESOLVED_BUG)
    reports = os.path.join(vault, '05-Reports')
    write(os.path.join(reports, 'usage-audit-2026-10-06.md'), AUDIT_NEW_MD)
    write(os.path.join(reports, 'usage-audit-2026-10-06.json'), json.dumps(AUDIT_NEW_JSON))
    write(os.path.join(reports, 'usage-audit-2026-10-04.md'), AUDIT_OLD_MD)
    write(os.path.join(reports, 'usage-audit-2026-10-04.json'), json.dumps(AUDIT_OLD_JSON))
    write(os.path.join(reports, 'content-review-2026-10-05-abc1234.md'), CONTENT_REVIEW)
    write(os.path.join(reports, 'qa-report-2026-10-03-abc1234.md'), QA_REPORT)
    return vault


def block(text, name):
    span = ds.find_block(text, name)
    assert isinstance(span, tuple), 'block %s not found or broken' % name
    return text[span[0]:span[1]].strip('\n')


def without_blocks(text):
    """The dashboard with every generated block emptied: what must stay byte-identical across syncs."""
    for name in ds.BLOCKS:
        span = ds.find_block(text, name)
        if isinstance(span, tuple):
            text = text[:span[0]] + text[span[1]:]
    return text


def generated(text):
    return '\n'.join(block(text, name) for name in ds.BLOCKS)


def unresolved_links(vault, text):
    """Wikilinks of text whose target is no file of the vault: an independent copy of the vault_lint VL006 rule
    (file names case-insensitive, '.md' optional, hidden folders skipped; code spans and comments ignored)."""
    names, stems = set(), set()
    for _dp, dn, fn in os.walk(vault):
        dn[:] = [d for d in dn if not d.startswith('.') and d != 'node_modules']
        for f in fn:
            names.add(f.casefold())
            if f.casefold().endswith('.md'):
                stems.add(f.casefold()[:-3])
    text = re.sub(r'(`+)[^\n]*?\1', '', re.sub(r'<!--.*?-->', '', text, flags=re.S))
    bad = []
    for m in re.finditer(r'\[\[([^\[\]\n]+?)\]\]', text):
        target = m.group(1).split('|', 1)[0].rstrip()
        target = (target[:-1] if target.endswith('\\') else target).split('#', 1)[0].strip().casefold()
        if target.endswith('.md'):
            target = target[:-3]
        if target and target not in stems and target not in names:
            bad.append(m.group(0))
    return bad


class SyncCase(unittest.TestCase):
    use_template = True

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix='dashboard-sync-')
        self.root = os.path.join(self.tmp, 'project')
        self.vault = build_project(self.root, self.use_template)
        self.dash = os.path.join(self.vault, ds.DASHBOARD)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def sync(self, now=NOW, check=False, quiet=False):
        buf = io.StringIO()
        with mock.patch.object(ds, '_now', return_value=now):
            rc = ds.sync(self.root, check=check, quiet=quiet, out=buf)
        return rc, buf.getvalue()

    def text(self):
        return ds.read_text(self.dash)

    def raw(self):
        with open(self.dash, 'rb') as fh:
            return fh.read()


class BlockContentTest(SyncCase):
    def setUp(self):
        super(BlockContentTest, self).setUp()
        self.rc, self.out = self.sync()
        self.assertEqual(self.rc, 0, self.out)
        self.dashboard = self.text()

    def test_summary_line_and_path_are_printed_last(self):
        lines = self.out.strip().split('\n')
        self.assertEqual(lines[-2], self.dash)
        self.assertEqual(lines[-1], 'dashboard: updated (3 tasks, 2 bugs, 2 warnings)')
        self.assertIn('warning: missing document: docs/missing.md (DEMO-001 docs)', self.out)
        self.assertIn('warning: missing document: docs/roadmap.md (config documents)', self.out)

    def test_header(self):
        self.assertEqual(block(self.dashboard, 'header').split('\n'), [
            '**Project:** Demo  ',
            '**Last Updated:** 2026-10-07 09:30  ',
            '**Operating Profile:** pilot ([[decisions-log]])  ',
            '**CTO Decision Mode:** USER  ',
            '**Session Lock:** coordinator@cowork since 2026-10-07T09:00:00Z, expires 2099-01-01T00:00:00Z  ',
            '**Vault Archival Policy:** Active (Zero-Deletion Enforced)'])
        self.assertNotIn('{PROJECT_NAME}', self.dashboard)

    def test_kanban_counts(self):
        rows = block(self.dashboard, 'kanban').split('\n')
        self.assertEqual(rows[0], '| Backlog | In-Analysis | Ready-For-Dev | In-Development | Code-Review | QA-Testing | Ready-For-Release | Archived |')
        self.assertEqual(rows[2], '| 1 | 0 | 0 | 1 | 1 | 0 | 0 | 1 |')

    def test_task_rows_links_and_order(self):
        rows = block(self.dashboard, 'tasks').split('\n')
        self.assertEqual(rows[0], '| Task ID | Title | Priority | Route | Assigned Agent | Branch | Status | Content review | QA | Docs |')
        self.assertEqual([r.split(' | ')[0] for r in rows[2:]], ['| [[DEMO-001]]', '| [[DEMO-003]]', '| [[DEMO-002]]'])
        self.assertEqual(rows[2], '| [[DEMO-001]] | Checkout: multi-currency \\| batch | high | full | dev-backend | '
                                  '`feature/DEMO-001/07.10.2026/dev-backend` | In-Development | intake: approved | pending | '
                                  '[spec.md](../docs/requirements/spec.md), [[glossary]], `docs/missing.md` (missing) |')
        self.assertEqual(rows[3], '| [[DEMO-003]] | Fix rounding in totals | low | lightweight | dev-backend | '
                                  '`feature/DEMO-003/07.10.2026/dev-backend` | Code-Review | intake: pending | testing | %s |' % DASH)
        self.assertEqual(rows[4], '| [[DEMO-002]] | Saved carts | critical | full | dev-frontend | %s | Backlog | n/a | pending | %s |' % (DASH, DASH))

    def test_bug_rows(self):
        rows = block(self.dashboard, 'bugs').split('\n')
        self.assertEqual(rows[0], '| Bug ID | Title | Severity | Category/Locale | Linked Task | Assigned Agent | Status | Blocking |')
        self.assertEqual(rows[2:], [
            '| [[BUG-001]] | [BUG] Bank title shown in Cyrillic in uz | Major | content/uz | [[DEMO-001]] | dev-frontend | Open | yes |',
            '| [[BUG-002]] | [BUG] Rounding differs by one cent | Minor | functional | [[DEMO-003]] | dev-backend | Closed | no |'])

    def test_adr_row_uses_file_name_with_alias(self):
        rows = block(self.dashboard, 'adr').split('\n')
        self.assertEqual(rows[2:], ['| [[ADR-001-use-postgres\\|ADR-001]] | Use PostgreSQL | Accepted | 2026-10-02 | CTO / User |'])
        self.assertNotIn('decisions-log', block(self.dashboard, 'adr'))

    def test_token_block(self):
        self.assertEqual(block(self.dashboard, 'tokens').split('  \n'), [
            SEP.join(['Last audit [[usage-audit-2026-10-06|2026-10-06]] (window since 2026-10-04)',
                      'weighted tokens 1 200 000 (+20% vs previous)', 'output 50 000', 'jobs 12/3.5 h', 'screenshots 30']),
            SEP.join(['R1 OK', 'R2 CHECK', 'R3 CHECK', 'R4 CHECK', 'R5 OK']),
            'Proposals pending CTO decision: 1',
            'Next audit due: 2026-10-08'])

    def test_usage_audit_rows(self):
        rows = block(self.dashboard, 'usage-audits').split('\n')
        self.assertEqual(rows[0], '| Date | Report | Window | Weighted tokens | Delta | Proposals (pending/total) | Rule flags |')
        self.assertEqual(rows[2:], [
            '| 2026-10-06 | [[usage-audit-2026-10-06]] | since 2026-10-04 | 1 200 000 | +20% | 1/2 | R2 R3 R4 |',
            '| 2026-10-04 | [[usage-audit-2026-10-04]] | since 2026-10-02 | 1 000 000 | baseline | 1/1 | %s |' % DASH])

    def test_content_review_row(self):
        rows = block(self.dashboard, 'content-reviews').split('\n')
        self.assertEqual(rows[2:], ['| 2026-10-05 | pre-release | RC-abc1234 | ru, uz | 0/1/2/3 | approved-with-deferrals | '
                                    '[[content-review-2026-10-05-abc1234]] |'])

    def test_release_row_groups_tasks_and_bugs(self):
        rows = block(self.dashboard, 'releases').split('\n')
        self.assertEqual(rows[2:], ['| v0.1.0 | `abc1234def5678` | 2026-10-03 | [[BUG-000]], [[DEMO-000]] | '
                                    '[[qa-report-2026-10-03-abc1234]] |'])

    def test_documents(self):
        self.assertEqual(block(self.dashboard, 'documents').split('\n'), [
            '- [Product specification](../docs/requirements/spec.md) %s `docs/requirements/spec.md`' % DASH,
            '- [API notes](../docs/api%%20notes.md) %s `docs/api notes.md`' % DASH,
            '- Roadmap %s `docs/roadmap.md` (missing)' % DASH,
            '- [[glossary|Glossary]] %s product terms per locale' % DASH,
            '- [[style-guide|Style guide]] %s writing rules per locale' % DASH,
            '- [[decisions-log|Decisions journal]] %s CTO decisions (D-NNN)' % DASH,
            '- [[usage-audit-2026-10-06|Latest usage audit]] %s 2026-10-06, window since 2026-10-04' % DASH,
            '- [[content-review-2026-10-05-abc1234|Latest content review]] %s 2026-10-05 pre-release RC-abc1234: '
            'approved-with-deferrals' % DASH,
            '- [[qa-report-2026-10-03-abc1234|Latest QA report]] %s 2026-10-03 RC-abc1234: passed' % DASH])

    def test_every_marker_pair_once_and_static_text_kept(self):
        for name in ds.BLOCKS:
            self.assertEqual(self.dashboard.count(ds.marker(name, 'start')), 1, name)
            self.assertEqual(self.dashboard.count(ds.marker(name, 'end')), 1, name)
        self.assertIn('Decisions journal: [[decisions-log]]', self.dashboard)
        self.assertTrue(self.dashboard.rstrip('\n').endswith(ds.TIP[1]))
        self.assertNotIn('\r', self.raw().decode('utf-8'))

    def test_every_wikilink_resolves_in_the_vault(self):
        self.assertGreater(len(re.findall(r'\[\[', self.dashboard)), 20)
        self.assertEqual(unresolved_links(self.vault, self.dashboard), [])


class LinkResolutionTest(SyncCase):
    """Wikilinks are written only when vault_lint's VL006 would resolve them."""

    def test_missing_targets_become_text_with_warnings(self):
        os.remove(os.path.join(self.vault, '03-ADR', 'decisions-log.md'))
        write(os.path.join(self.vault, '02-Bugs', 'BUG-003.md'),
              BUG_2.replace('BUG-002', 'BUG-003').replace('[[DEMO-003]]', '[[DEMO-999]]'))
        write(os.path.join(self.vault, '01-Tasks', 'Code-Review', 'DEMO-003.md'),
              TASK_3.replace("'Fix rounding in totals'", '"Fix rounding, see [[DEMO-001]] and [[NOPE-7|old spec]]"'))
        rc, out = self.sync()
        self.assertEqual(rc, 0, out)
        text = self.text()
        self.assertIn('**Operating Profile:** pilot (decisions-log (missing))  ', block(text, 'header'))
        self.assertEqual(out.count('warning: missing document: vault/03-ADR/decisions-log.md (decisions journal)'), 1)
        self.assertIn('- Decisions journal %s `vault/03-ADR/decisions-log.md` (missing)' % DASH, block(text, 'documents'))
        self.assertIn('| [[BUG-003]] | [BUG] Rounding differs by one cent | Minor | functional | DEMO-999 (missing) |', block(text, 'bugs'))
        self.assertIn('warning: unresolved link: DEMO-999 (BUG-003 linked task)', out)
        self.assertIn('| [[DEMO-003]] | Fix rounding, see [[DEMO-001]] and old spec |', block(text, 'tasks'))
        self.assertIn('warning: unresolved wikilink [[NOPE-7|old spec]] shown as text (tasks block)', out)
        self.assertEqual(unresolved_links(self.vault, generated(text)), [])
        self.assertEqual(self.sync(check=True)[0], 0)

    def test_new_sections_and_new_dashboards_skip_the_journal_line(self):
        os.remove(os.path.join(self.vault, '03-ADR', 'decisions-log.md'))
        write(self.dash, '# Dashboard\n\nFree text.\n')
        self.sync()
        self.assertNotIn('decisions-log]]', self.text())
        self.assertEqual(unresolved_links(self.vault, self.text()), [])
        os.remove(self.dash)
        rc, out = self.sync()
        self.assertEqual(rc, 0, out)
        self.assertNotIn(ds.JOURNAL_LINE, self.text())
        self.assertIn(ds.marker('adr', 'end') + '\n\n---\n', self.text())
        self.assertEqual(unresolved_links(self.vault, self.text()), [])

    def test_existing_but_unlinkable_files_get_markdown_links(self):
        write(os.path.join(self.vault, '.private', 'notes.md'), '# private\n')
        write(os.path.join(self.vault, '01-Tasks', 'Backlog', 'DEMO-005 #1.md'),
              TASK_2.replace('id: DEMO-002', 'id: DEMO-005').replace('tags: [task, cart]', 'docs: ["vault/.private/notes.md"]'))
        self.sync()
        tasks = block(self.text(), 'tasks')
        self.assertIn('| [DEMO-005](01-Tasks/Backlog/DEMO-005%20%231.md) | Saved carts |', tasks)
        self.assertIn('| [notes.md](.private/notes.md) |', tasks)
        self.assertEqual(unresolved_links(self.vault, self.text()), [])


class TokenVariantsTest(SyncCase):
    def reports(self, name):
        return os.path.join(self.vault, '05-Reports', name)

    def test_sidecar_only_derives_rule_status(self):
        os.remove(self.reports('usage-audit-2026-10-06.md'))
        self.sync()
        lines = block(self.text(), 'tokens').split('  \n')
        self.assertTrue(lines[0].startswith('Last audit 2026-10-06 (window since 2026-10-04)' + SEP), lines[0])
        self.assertEqual(lines[1], SEP.join(['R1 CHECK', 'R2 CHECK', 'R3 n/a', 'R4 CHECK', 'R5 OK']))
        self.assertEqual(lines[2], 'Proposals pending CTO decision: n/a')

    def test_report_without_sidecar(self):
        os.remove(self.reports('usage-audit-2026-10-06.json'))
        self.sync()
        lines = block(self.text(), 'tokens').split('  \n')
        self.assertEqual(lines[0], 'Last audit [[usage-audit-2026-10-06|2026-10-06]] (window since 2026-10-04)%s'
                                   'numbers n/a (no .json sidecar; re-run usage_report.py)' % SEP)
        self.assertEqual(lines[1], SEP.join(['R1 OK', 'R2 CHECK', 'R3 CHECK', 'R4 CHECK', 'R5 OK']))
        self.assertIn('| 2026-10-06 | [[usage-audit-2026-10-06]] | since 2026-10-04 | n/a | n/a | 1/2 | R2 R3 R4 |',
                      block(self.text(), 'usage-audits'))

    def test_overdue_audit(self):
        self.sync(now=datetime.datetime(2026, 10, 9, 8, 0))
        self.assertTrue(block(self.text(), 'tokens').endswith('Next audit due: 2026-10-08 (overdue)'))

    def test_no_audit_yet(self):
        for f in os.listdir(os.path.join(self.vault, '05-Reports')):
            if f.startswith('usage-audit-'):
                os.remove(self.reports(f))
        self.sync()
        self.assertEqual(block(self.text(), 'tokens'), 'No usage audit yet %s run usage_report.py' % DASH)
        self.assertEqual(block(self.text(), 'usage-audits').split('\n')[2],
                         '| *(No usage audit yet %s the first one becomes the baseline)* | | | | | | |' % DASH)
        self.assertIn('- Latest usage audit %s none yet' % DASH, block(self.text(), 'documents'))


class IdempotencyAndCheckTest(SyncCase):
    def test_check_never_writes_and_reports_differences(self):
        before = self.raw()
        rc, out = self.sync(check=True)
        self.assertEqual(rc, 1)
        self.assertEqual(self.raw(), before)
        self.assertIn('dashboard: out of date (3 tasks, 2 bugs, 2 warnings)', out)
        self.assertIn('+| [[DEMO-001]]', out)
        diff_lines = [line for line in out.split('\n') if line[:1] in ('+', '-', ' ', '@')]
        self.assertLessEqual(len(diff_lines), ds.DIFF_LIMIT + 1)

    def test_second_run_is_identical(self):
        self.assertEqual(self.sync()[0], 0)
        first = self.raw()
        rc, out = self.sync(now=NOW + datetime.timedelta(hours=5))
        self.assertEqual(rc, 0)
        self.assertIn('dashboard: unchanged (3 tasks, 2 bugs, 2 warnings)', out)
        self.assertEqual(self.raw(), first)
        self.assertIn('**Last Updated:** 2026-10-07 09:30  ', self.text())
        rc, out = self.sync(now=NOW + datetime.timedelta(hours=6), check=True)
        self.assertEqual(rc, 0, out)
        self.assertIn('dashboard: up to date', out)

    def test_change_is_detected_and_stamps_last_updated(self):
        self.sync()
        path = os.path.join(self.vault, '01-Tasks', 'Backlog', 'DEMO-002.md')
        write(path, TASK_2.replace('priority: critical', 'priority: medium'))
        before = self.raw()
        rc, out = self.sync(now=NOW + datetime.timedelta(minutes=10), check=True)
        self.assertEqual(rc, 1)
        self.assertIn('-| [[DEMO-002]] | Saved carts | critical', out)
        self.assertEqual(self.raw(), before)
        rc, out = self.sync(now=NOW + datetime.timedelta(minutes=10))
        self.assertEqual(rc, 0)
        self.assertIn('dashboard: updated', out)
        self.assertIn('**Last Updated:** 2026-10-07 09:40  ', self.text())
        self.assertIn('| [[DEMO-002]] | Saved carts | medium |', self.text())

    def test_text_outside_markers_is_untouched(self):
        self.sync()
        text = self.text()
        text = text.replace(ds.marker('kanban', 'end'), ds.marker('kanban', 'end') + '\n\nManual paragraph kept as is.')
        text = text.replace(ds.TIP[0], '## Team notes\n\n- hand-written item\n\n' + ds.TIP[0])
        text = text.replace('| [[DEMO-003]] |', '| [[DEMO-003]] edited by hand |')
        write(self.dash, text)
        outside = without_blocks(text)
        rc, out = self.sync()
        self.assertEqual(rc, 0, out)
        new = self.text()
        self.assertEqual(without_blocks(new), outside)
        self.assertNotIn('edited by hand', new)
        self.assertIn('Manual paragraph kept as is.', new)
        self.assertIn('## Team notes\n\n- hand-written item', new)

    def test_crlf_and_bom_dashboard(self):
        self.sync()
        windows_style = b'\xef\xbb\xbf' + self.text().replace('\n', '\r\n').encode('utf-8')
        with open(self.dash, 'wb') as fh:
            fh.write(windows_style)
        before = self.raw()
        self.assertEqual(self.sync(check=True)[0], 0)
        rc, out = self.sync()
        self.assertIn('dashboard: unchanged', out)
        self.assertEqual(self.raw(), before)
        write(os.path.join(self.vault, '01-Tasks', 'Backlog', 'DEMO-004.md'), TASK_2.replace('DEMO-002', 'DEMO-004'))
        self.sync()
        data = self.raw()
        self.assertFalse(data.startswith(b'\xef\xbb\xbf'))
        self.assertNotIn(b'\r\n', data)

    def test_quiet_prints_only_path_and_summary(self):
        rc, out = self.sync(check=True, quiet=True)
        self.assertEqual(rc, 1)
        self.assertEqual(out.strip().split('\n'), [self.dash, 'dashboard: out of date (3 tasks, 2 bugs, 2 warnings)'])

    def test_broken_markers_are_reported_and_left_alone(self):
        self.sync()
        text = self.text().replace(ds.marker('bugs', 'end'), '')
        write(self.dash, text)
        write(os.path.join(self.vault, '01-Tasks', 'Backlog', 'DEMO-004.md'), TASK_2.replace('DEMO-002', 'DEMO-004'))
        rc, out = self.sync()
        self.assertEqual(rc, 1)
        self.assertIn('warning: block bugs has unbalanced or duplicate sync markers - left unchanged', out)
        new = self.text()
        self.assertIn('[[DEMO-004]]', block(new, 'tasks'))
        self.assertEqual(new.count(ds.marker('bugs', 'start')), 1)
        self.assertEqual(self.sync(check=True)[0], 1)

    def test_missing_dashboard_is_created(self):
        os.remove(self.dash)
        rc, out = self.sync(check=True)
        self.assertEqual(rc, 1)
        self.assertIn('would create vault/00-Dashboard.md', out)
        self.assertFalse(os.path.exists(self.dash))
        rc, out = self.sync()
        self.assertEqual(rc, 0, out)
        for name in ds.BLOCKS:
            self.assertIn(ds.marker(name, 'start'), self.text())
        self.assertEqual(self.sync(check=True)[0], 0)


class MarkerInsertionTest(SyncCase):
    def test_old_dashboard_gets_every_block(self):
        write(self.dash, OLD_DASHBOARD)
        rc, out = self.sync()
        self.assertEqual(rc, 0, out)
        for name in ds.BLOCKS:
            self.assertIn('inserted block %s' % name, out)
        text = self.text()
        for name in ds.BLOCKS:
            self.assertEqual(text.count(ds.marker(name, 'start')), 1, name)
            self.assertEqual(text.count(ds.marker(name, 'end')), 1, name)
        lines = text.split('\n')
        self.assertEqual(lines[0], '# \N{OFFICE BUILDING} Project Engineering Dashboard')
        self.assertEqual(lines[2], ds.marker('header', 'start'))
        self.assertLess(text.index(ds.marker('header', 'end')), text.index('**Last Updated:** 2026-10-01 10:00 (manual)'))
        kanban_heading = text.index('## \N{BAR CHART} Live Task Kanban Overview')
        self.assertLess(kanban_heading, text.index(ds.marker('kanban', 'start')))
        self.assertLess(text.index(ds.marker('kanban', 'end')), text.index('| 9 | 9 | 9 |'))
        self.assertLess(text.index('## \N{BUG} Open Defects & Bugs'), text.index(ds.marker('bugs', 'start')))
        self.assertLess(text.index('## \N{CHART WITH UPWARDS TREND} Usage audits'), text.index(ds.marker('usage-audits', 'start')))
        self.assertIn('> Manual wave note that must survive.', text)
        self.assertIn('| [[DEMO-001]] | hand-written row |', text)
        releases = text.index(ds.marker('releases', 'end'))
        tokens, reviews, docs = (text.index(ds.SECTION[n][1]) for n in ('tokens', 'content-reviews', 'documents'))
        self.assertTrue(releases < tokens < reviews < docs < text.index(ds.TIP[0]))
        self.assertTrue(text.rstrip('\n').endswith(ds.TIP[1]))
        rc, out = self.sync(now=NOW + datetime.timedelta(minutes=1))
        self.assertIn('dashboard: unchanged', out)
        self.assertNotIn('inserted block', out)

    def test_check_on_old_dashboard_shows_inserted_blocks(self):
        write(self.dash, OLD_DASHBOARD)
        rc, out = self.sync(check=True)
        self.assertEqual(rc, 1)
        self.assertIn('would insert block kanban', out)
        self.assertIn('+' + ds.marker('header', 'start'), out)
        self.assertEqual(self.text(), OLD_DASHBOARD)

    def test_dashboard_without_tip_appends_at_end(self):
        write(self.dash, '# Dashboard\n\nFree text.\n')
        self.sync()
        text = self.text()
        self.assertTrue(text.startswith('# Dashboard\n\n' + ds.marker('header', 'start')))
        self.assertIn('Free text.', text)
        self.assertTrue(text.endswith(ds.marker('documents', 'end') + '\n'))
        self.assertIn('\n---\n\n' + ds.SECTION['kanban'][1] + '\n\n' + ds.marker('kanban', 'start'), text)


class WarningsTest(SyncCase):
    def test_unknown_folder_missing_frontmatter_and_status_mismatch(self):
        write(os.path.join(self.vault, '01-Tasks', 'On-Hold', 'DEMO-009.md'), TASK_2.replace('DEMO-002', 'DEMO-009'))
        write(os.path.join(self.vault, '02-Bugs', 'BUG-009.md'), '# BUG-009 without frontmatter\n')
        write(os.path.join(self.vault, '01-Tasks', 'In-Development', 'DEMO-001.md'),
              TASK_1.replace('status: In-Development #', 'status: Backlog #'))
        rc, out = self.sync()
        self.assertEqual(rc, 0)
        self.assertIn('warning: unknown status folder: vault/01-Tasks/On-Hold (1 note)', out)
        self.assertIn('warning: no frontmatter: vault/02-Bugs/BUG-009.md', out)
        self.assertIn('warning: status "Backlog" differs from its folder In-Development: vault/01-Tasks/In-Development/DEMO-001.md', out)
        self.assertIn('| [[BUG-009]] | BUG-009 without frontmatter |', block(self.text(), 'bugs'))

    def test_lock_variants(self):
        lock = os.path.join(self.root, '.it-department', 'lock.json')
        write(lock, json.dumps(dict(LOCK, started_at='2026-10-06T09:00:00Z', expires_at='2026-10-06T13:00:00Z')))
        self.sync()
        self.assertIn('since 2026-10-06T09:00:00Z, expires 2026-10-06T13:00:00Z (expired)  ', block(self.text(), 'header'))
        os.remove(lock)
        self.sync()
        self.assertIn('**Session Lock:** free  ', block(self.text(), 'header'))
        write(lock, '{not json')
        rc, out = self.sync()
        self.assertIn('warning: unreadable lock file: .it-department/lock.json', out)
        self.assertIn('**Session Lock:** unreadable `.it-department/lock.json`  ', block(self.text(), 'header'))

    def test_profile_default_and_priority_order(self):
        cfg = dict(CONFIG)
        del cfg['operating_profile']
        write(os.path.join(self.root, '.it-department', 'config.json'), json.dumps(cfg))
        write(os.path.join(self.vault, '01-Tasks', 'In-Development', 'DEMO-010.md'),
              TASK_3.replace('DEMO-003', 'DEMO-010').replace('Code-Review', 'In-Development').replace('priority: low', 'priority: critical'))
        write(os.path.join(self.vault, '01-Tasks', 'In-Development', 'DEMO-011.md'),
              TASK_3.replace('DEMO-003', 'DEMO-011').replace('Code-Review', 'In-Development').replace('priority: low', 'priority: medium'))
        self.sync()
        text = self.text()
        self.assertIn('**Operating Profile:** production (default) ([[decisions-log]])  ', text)
        ids = re.findall(r'^\| \[\[(DEMO-\d+)\]\]', block(text, 'tasks'), re.M)
        self.assertEqual(ids, ['DEMO-010', 'DEMO-001', 'DEMO-011', 'DEMO-003', 'DEMO-002'])

    def test_vault_missing_is_a_bad_argument(self):
        with mock.patch('sys.stderr', new=io.StringIO()) as err:
            rc = ds.sync(os.path.join(self.tmp, 'nowhere'), out=io.StringIO())
        self.assertEqual(rc, 2)
        self.assertIn('vault not found', err.getvalue())


class SkeletonTest(SyncCase):
    use_template = False

    def test_skeleton_vault_syncs(self):
        rc, out = self.sync()
        self.assertEqual(rc, 0, out)
        self.assertIn('| [[DEMO-001]] |', block(self.text(), 'tasks'))
        self.assertEqual(self.sync(check=True)[0], 0)

    @unittest.skipUnless(os.path.isfile(os.path.join(TEMPLATE_VAULT, ds.DASHBOARD)), 'vault template not reachable')
    def test_template_and_skeleton_render_identically(self):
        self.sync()
        other = os.path.join(self.tmp, 'from-template')
        build_project(other, use_template=True)
        with mock.patch.object(ds, '_now', return_value=NOW):
            ds.sync(other, out=io.StringIO())
        self.assertEqual(ds.read_text(os.path.join(other, 'vault', ds.DASHBOARD)), self.text())


class FrontmatterTest(unittest.TestCase):
    def test_value_shapes(self):
        text = '\n'.join([
            '---', 'a: "x # y" # comment', 'b: plain # comment', 'c: true', 'd: 12', 'e: [a, "b, c", 3]',
            'f:', '  - one', '  - "two" # c', 'g:', '  "k": v', '  k2: 2', 'h: { critical: 0, major: 1 }',
            "i: It's ok # trailing", "j: 'single ''quoted'''", 'k: 0123', 'l: ~', 'm:', 'n: "say \\"hi\\""',
            'o:', '- flush', 'p: docs/a.md#anchor', '---', '', '# Title line', 'Body'])
        fm, body = ds.parse_frontmatter(text)
        self.assertEqual(fm['a'], 'x # y')
        self.assertEqual(fm['b'], 'plain')
        self.assertIs(fm['c'], True)
        self.assertEqual(fm['d'], 12)
        self.assertEqual(fm['e'], ['a', 'b, c', 3])
        self.assertEqual(fm['f'], ['one', 'two'])
        self.assertEqual(fm['g'], {'k': 'v', 'k2': 2})
        self.assertEqual(fm['h'], '{ critical: 0, major: 1 }')
        self.assertEqual(ds.inline_map(fm['h']), {'critical': 0, 'major': 1})
        self.assertEqual(fm['i'], "It's ok")
        self.assertEqual(fm['j'], "single 'quoted'")
        self.assertEqual(fm['k'], '0123')
        self.assertIsNone(fm['l'])
        self.assertEqual(fm['m'], '')
        self.assertEqual(fm['n'], 'say "hi"')
        self.assertEqual(fm['o'], ['flush'])
        self.assertEqual(fm['p'], 'docs/a.md#anchor')
        self.assertEqual(ds.first_heading(body), 'Title line')

    def test_no_or_unterminated_frontmatter(self):
        self.assertIsNone(ds.parse_frontmatter('# Note\n\n---\na: 1\n---\n')[0])
        self.assertIsNone(ds.parse_frontmatter('---\na: 1\n')[0])
        self.assertEqual(ds.parse_frontmatter('---\n---\nbody')[0], {})

    @unittest.skipUnless(os.path.isdir(TEMPLATES), 'skill templates not reachable')
    def test_real_templates_parse(self):
        def fm(name):
            return ds.parse_frontmatter(ds.read_text(os.path.join(TEMPLATES, name)))[0]
        task = fm('task-specification.md')
        self.assertEqual(task['status'], 'In-Analysis')
        self.assertEqual(task['content_review'], 'required')
        self.assertEqual(task['tags'], ['task', '{service-name}', 'in-analysis'])
        self.assertIs(task['cto_approved'], False)
        self.assertEqual(task['docs'], [])
        bug = fm('bug-defect-task.md')
        self.assertEqual((bug['severity'], bug['release_blocking'], bug['parent_task'], bug['locale']),
                         ('Major', True, '[[{TASK-ID}]]', ''))
        self.assertEqual(fm('adr-record.md')['status'], 'Proposed')
        review = fm('content-review-report.md')
        self.assertEqual(review['checkpoint'], 'pre-release')
        self.assertEqual(review['locales_reviewed'], ['{locale}', '{locale}'])
        self.assertIsInstance(review['reviewer_confidence'], dict)
        self.assertEqual(ds.inline_map(review['findings'])['needs_native_check'], 0)
        self.assertEqual(review['inventory'], '[[content-inventory-{date}-{sha7}]]')


class CliTest(SyncCase):
    def run_cli(self, *args):
        res = subprocess.run([sys.executable, os.path.join(SCRIPTS, 'dashboard_sync.py')] + list(args),
                             stdout=subprocess.PIPE, stderr=subprocess.PIPE, encoding='utf-8',
                             env=dict(os.environ, PYTHONIOENCODING='utf-8'))
        return res.returncode, res.stdout, res.stderr

    def test_exit_codes(self):
        rc, out, _err = self.run_cli('--root', self.root, '--check')
        self.assertEqual(rc, 1, out)
        rc, out, _err = self.run_cli('--root', self.root)
        self.assertEqual(rc, 0, out)
        self.assertEqual(out.strip().split('\n')[-2:], [self.dash, 'dashboard: updated (3 tasks, 2 bugs, 2 warnings)'])
        rc, out, _err = self.run_cli('--root', self.root, '--check', '--quiet')
        self.assertEqual((rc, len(out.strip().split('\n'))), (0, 2), out)
        rc, _out, err = self.run_cli('--root', os.path.join(self.tmp, 'nowhere'))
        self.assertEqual(rc, 2)
        self.assertIn('vault not found', err)
        rc, _out, _err = self.run_cli('--bogus')
        self.assertEqual(rc, 2)


if __name__ == '__main__':
    unittest.main()
