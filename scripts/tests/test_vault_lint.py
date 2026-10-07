"""Unit tests for scripts/vault_lint.py (stdlib unittest, no network, temp directories only).

Run from the scripts directory:  python3 -m unittest discover -s tests -v
"""
import contextlib
import datetime
import io
import json
import os
import shutil
import sys
import tempfile
import textwrap
import unittest
from unittest import mock

SCRIPTS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SKILL_ROOT = os.path.dirname(SCRIPTS)
sys.path.insert(0, SCRIPTS)

import vault_lint  # noqa: E402

TEMPLATES = os.path.join(SKILL_ROOT, 'templates')
VAULT_TEMPLATE = os.path.join(SKILL_ROOT, 'assets', 'vault-template')

CONFIG = {
    'schema_version': '2.0.0',
    'project_name': 'Lint fixture',
    'paths': {'vault_relative_path': 'vault', 'sessions_relative_path': '.it-department/sessions',
              'worktrees_relative_path': '.it-department/worktrees'},
    'documents': [{'title': 'Product specification', 'path': 'docs/spec.md'}],
}

NOTES = {
    # one clean note per type, plus an archived task and a not-yet-dispatched backlog task
    'vault/01-Tasks/In-Development/T-001.md': '''\
        ---
        id: T-001
        title: "Clean task: \\"quoted\\" title"
        status: In-Development # In-Analysis | Ready-For-Dev
        route: full # full | lightweight
        type: feature
        priority: high
        assigned_agent: dev-backend
        branch: "feature/T-001/07.10.2026/dev-backend"
        date_created: "2026-10-01"
        date_updated: 2026-10-07
        pr_link: ""
        qa_status: pending
        content_review: required # required | not-applicable
        content_review_intake: approved # pending | approved | changes-requested | not-applicable
        cto_approved: false
        docs: ["docs/spec.md", "https://example.com/spec", "[[ADR-001-sample]]"]
        tags:
          - task
          - api
        ---

        # T-001: Clean task

        Decision: [[ADR-001-sample|ADR-001]], defect [[BUG-001#Steps to Reproduce]], journal [[decisions-log]].
        ''',
    'vault/01-Tasks/Backlog/T-002.md': '''\
        ---
        id: T-002
        title: "Backlog task, not dispatched yet"
        status: Backlog
        route: lightweight
        priority: low
        assigned_agent: ""
        branch: ""
        date_created: "2026-10-05"
        content_review: not-applicable
        content_review_intake: not-applicable
        tags: [task]
        ---
        # T-002
        ''',
    'vault/04-Archive/Completed-Tasks/T-000.md': '''\
        ---
        id: T-000
        title: Archived task
        status: Archived
        route: lightweight
        priority: medium
        assigned_agent: dev-frontend
        branch: feature/T-000/01.10.2026/dev-frontend
        date_created: "2026-09-30"
        content_review: required
        content_review_intake: approved
        release_version: "v0.1.0"
        release_commit: "abc1234"
        archived_at: "2026-10-02T17:30:00Z"
        ---
        # T-000
        ''',
    'vault/02-Bugs/BUG-001.md': '''\
        ---
        id: BUG-001
        parent_task: "[[T-001]]"
        title: "[BUG] Bank title in the wrong alphabet"
        status: Open # Open | In-Development | Code-Review | Retesting | Closed | Archived
        severity: Major # Critical | Major | Minor | Trivial
        category: content
        locale: uz
        assigned_agent: dev-frontend
        branch: "bug/BUG-001/07.10.2026/dev-frontend"
        date_created: "2026-10-07"
        date_resolved: ""
        release_blocking: true # true for Critical & Major
        deferral_signoff: ""
        tags:
          - bug
          - content-review # qa-reported | content-review
        ---
        # [BUG-001] Bank title in the wrong alphabet

        ## Steps to Reproduce
        1. Open [[T-001]].
        ''',
    'vault/03-ADR/ADR-001-sample.md': '''\
        ---
        id: ADR-001
        title: "Sample decision"
        status: Accepted
        decision_type: standard
        date: "2026-10-02"
        proposer: "Architect"
        approver: "CTO / User"
        tags:
          - adr
        ---
        # [ADR-001] Sample decision
        - [[T-001]]: implement it.
        ''',
    'vault/03-ADR/decisions-log.md': '''\
        # Decisions Journal

        | ID | Date | Topic | Decision | Decided by | Context | Follow-up / review date |
        | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
        | D-001 | 2026-10-01 | Operating profile | Project runs in pilot profile | CTO | [[00-Dashboard]] | review at 50 users |
        ''',
    'vault/05-Reports/content-review-2026-10-07-abc1234.md': '''\
        ---
        id: CR-2026-10-07-RC-abc1234        # scope = RC-{sha7} for a pre-release review
        checkpoint: pre-release            # task-creation | pre-release
        scope: "RC-abc1234"
        baseline: "def5678"
        locales_reviewed: ["ru", "uz"]
        reviewer_confidence:               # fluent | working | limited, per locale
          "ru": fluent
          "uz": limited
        findings: { critical: 0, major: 1, minor: 0, trivial: 0, needs_native_check: 0 }
        verdict: blocked                   # intake: approved | changes-requested
        cto_signoff: ""
        date: "2026-10-07"
        tags:
          - content-review
        ---
        # Content review — pre-release: RC-abc1234

        | 1 | Major | uz | `AppResources.uz.resx` / `BankTitle` | x | y | glossary | [[BUG-001]] |
        ''',
    'vault/05-Reports/qa-report-2026-10-07-abc1234.md': '''\
        ---
        id: QA-2026-10-07-RC-abc1234
        scope: "RC-abc1234"
        candidate_sha: "abc1234"
        baseline_sha: "def5678"
        operating_profile: pilot
        qa_scope: full
        environment: "test"
        verdict: passed-with-deferrals
        defects: { critical: 0, major: 0, minor: 1, trivial: 0 }
        screenshots: { count: 4, max_allowed: 10, scale: 0.5 }
        date: "2026-10-07"
        tags: [qa-report]
        ---
        # QA report RC-abc1234
        Defects: [[BUG-001]].
        ''',
    'vault/05-Reports/usage-audit-2026-10-06.md': '''\
        # Usage audit - 2026-10-06 (window since 2026-10-04)
        No frontmatter: usage audits are generated and only link-checked.
        ''',
    'vault/00-Dashboard.md': '''\
        # Dashboard

        | Task ID | Title |
        | :--- | :--- |
        | [[T-001]] | Clean task |
        | [[ADR-001-sample\\|ADR-001]] | escaped alias inside a table |

        Reports: [[content-review-2026-10-07-abc1234]], [[qa-report-2026-10-07-abc1234]], [[usage-audit-2026-10-06]],
        journal [[decisions-log]], same note [[#Dashboard]], path link [[03-ADR/ADR-001-sample]], attachment ![[shot.png|300]].

        Not links: `[[IN-INLINE-CODE]]` and ``[[DOUBLE-TICK]]`` <!-- [[IN-HTML-COMMENT]] --> %% [[IN-OBSIDIAN-COMMENT]] %%

        ```markdown
        [[IN-FENCED-BLOCK]]
        ```
        ''',
    'vault/05-Reports/shot.png': '',
    'docs/spec.md': '# Product specification\n',
}

STUB_SCRIPT = '''\
import json, sys
with open(__file__ + '.argv.json', 'w') as fh:
    json.dump(sys.argv[1:], fh)
sys.exit({rc})
'''


def write(root, rel, content):
    path = os.path.join(root, *rel.split('/'))
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w', encoding='utf-8', newline='\n') as fh:
        fh.write(textwrap.dedent(content) if content else '')
    return path


def build_project(root, notes=None, config=CONFIG):
    os.makedirs(os.path.join(root, '.it-department'), exist_ok=True)
    if config is not None:
        with open(os.path.join(root, '.it-department', 'config.json'), 'w', encoding='utf-8') as fh:
            json.dump(config, fh, indent=2)
    for rel, content in (notes or NOTES).items():
        write(root, rel, content)


def codes(findings):
    return sorted({f['code'] for f in findings})


class LintCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix='vault-lint-')
        self.root = os.path.join(self.tmp, 'project')
        build_project(self.root)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def lint(self, **kwargs):
        kwargs.setdefault('dashboard_check', False)
        return vault_lint.lint(self.root, **kwargs)

    def put(self, rel, content):
        return write(self.root, rel, content)

    def remove(self, rel):
        os.remove(os.path.join(self.root, *rel.split('/')))

    def edit(self, rel, old, new):
        path = os.path.join(self.root, *rel.split('/'))
        with open(path, encoding='utf-8') as fh:
            text = fh.read()
        self.assertIn(old, text, 'fixture text to replace not found in %s' % rel)
        with open(path, 'w', encoding='utf-8', newline='\n') as fh:
            fh.write(text.replace(old, new, 1))

    def assertOnly(self, findings, code, *fragments):
        self.assertEqual(codes(findings), [code], '\n'.join(vault_lint.format_finding(f) for f in findings))
        text = '\n'.join(vault_lint.format_finding(f) for f in findings)
        for fragment in fragments:
            self.assertIn(fragment, text)


class CleanVaultTest(LintCase):
    def test_clean_vault_has_no_findings(self):
        findings, summary = self.lint()
        self.assertEqual(findings, [], '\n'.join(vault_lint.format_finding(f) for f in findings))
        self.assertEqual((summary['tasks'], summary['bugs'], summary['adrs'], summary['reports']), (3, 1, 1, 2))
        self.assertEqual(summary['notes'], 10)
        self.assertEqual(summary['dashboard_check'], 'disabled')

    def test_crlf_and_bom_notes_parse(self):
        path = os.path.join(self.root, 'vault', '02-Bugs', 'BUG-001.md')
        with open(path, encoding='utf-8') as fh:
            text = fh.read()
        with open(path, 'wb') as fh:
            fh.write(b'\xef\xbb\xbf' + text.replace('\n', '\r\n').encode('utf-8'))
        findings, _ = self.lint()
        self.assertEqual(findings, [])

    def test_hidden_directories_are_skipped(self):
        self.put('vault/.obsidian/broken.md', 'links to [[NOWHERE]]\n')
        self.put('vault/.trash/01-Tasks/Backlog/X-1.md', 'no frontmatter\n')
        findings, summary = self.lint()
        self.assertEqual(findings, [])
        self.assertEqual(summary['notes'], 10)


class FrontmatterParserTest(unittest.TestCase):
    def parse(self, body):
        return vault_lint.read_frontmatter('---\n' + textwrap.dedent(body) + '---\n# body\n')

    def test_scalars_lists_maps_and_comments(self):
        meta, problems = self.parse('''\
            title: "A \\"quoted\\" title: with colon" # comment
            single: 'it''s'
            plain: value with # a comment
            hash_in_word: C# basics
            flag: true
            off: False
            count: 42
            neg: -3
            sha: 0012
            empty:
            nothing: null
            date: 2026-10-07
            inline: [a, "b, c", 'd', 7]
            nested_inline: [[spec]]
            flow_map: { critical: 0, major: 1 }
            block:
              - one
              - "two" # comment
              -
            compact:
            - x
            - y
            nested:
              "ru": fluent
              uz: limited
            folded: >
              line one
              line two
            literal: |-
              keep
              lines
            url: https://example.com/a:b
            multi: first part
              second part
            ''')
        self.assertEqual(problems, [])
        self.assertEqual(meta['title'], 'A "quoted" title: with colon')
        self.assertEqual(meta['single'], "it's")
        self.assertEqual(meta['plain'], 'value with')
        self.assertEqual(meta['hash_in_word'], 'C# basics')
        self.assertIs(meta['flag'], True)
        self.assertIs(meta['off'], False)
        self.assertEqual((meta['count'], meta['neg']), (42, -3))
        self.assertEqual(meta['sha'], '0012')
        self.assertIsNone(meta['empty'])
        self.assertIsNone(meta['nothing'])
        self.assertEqual(meta['date'], '2026-10-07')
        self.assertEqual(meta['inline'], ['a', 'b, c', 'd', 7])
        self.assertEqual(meta['nested_inline'], [['spec']])
        self.assertEqual(meta['flow_map'], '{ critical: 0, major: 1 }')
        self.assertEqual(meta['block'], ['one', 'two', None])
        self.assertEqual(meta['compact'], ['x', 'y'])
        self.assertEqual(meta['nested'], {'ru': 'fluent', 'uz': 'limited'})
        self.assertEqual(meta['folded'], 'line one line two')
        self.assertEqual(meta['literal'], 'keep\nlines')
        self.assertEqual(meta['url'], 'https://example.com/a:b')
        self.assertEqual(meta['multi'], 'first part second part')

    def test_no_frontmatter_and_unclosed(self):
        self.assertEqual(vault_lint.read_frontmatter('# just a note\n'), (None, []))
        self.assertEqual(vault_lint.read_frontmatter('\n---\nid: X\n---\n'), (None, []))
        meta, problems = vault_lint.read_frontmatter('---\nid: X\nstatus: Open\n')
        self.assertIsNone(meta)
        self.assertIn('never closed', problems[0][1])

    def test_problem_lines(self):
        meta, problems = self.parse('''\
            id: X-1
            status In-Development
            - orphan item
            id: X-2
            \tindented: with a tab
            ''')
        messages = [m for _, m in problems]
        self.assertTrue(any('not a "key: value" line' in m for m in messages), messages)
        self.assertTrue(any('list item without a key' in m for m in messages), messages)
        self.assertTrue(any('duplicate key id' in m for m in messages), messages)
        self.assertTrue(any('tab used for indentation' in m for m in messages), messages)
        self.assertEqual([n for n, _ in problems], [3, 4, 5, 6])
        self.assertEqual(meta['id'], 'X-2')

    def test_crlf_text(self):
        meta, problems = vault_lint.read_frontmatter('---\r\nid: X-1\r\ntags:\r\n  - a\r\n---\r\nbody\r\n')
        self.assertEqual(problems, [])
        self.assertEqual(meta, {'id': 'X-1', 'tags': ['a']})

    @unittest.skipUnless(os.path.isdir(TEMPLATES), 'templates/ not available (only scripts/ mounted)')
    def test_skill_templates_parse_with_required_fields(self):
        expected = {'task-specification.md': 'task', 'bug-defect-task.md': 'bug', 'adr-record.md': 'adr',
                    'content-review-report.md': 'content-review', 'qa-report.md': 'qa-report'}
        for name, kind in expected.items():
            path = os.path.join(TEMPLATES, name)
            if not os.path.isfile(path):
                self.fail('template missing: %s' % name)
            meta, problems = vault_lint.read_frontmatter(vault_lint.read_text(path))
            self.assertIsNotNone(meta, name)
            self.assertEqual(problems, [], name)
            missing = [k for k in vault_lint.REQUIRED[kind] if k not in meta]
            self.assertEqual(missing, [], name)


class CheckCodesTest(LintCase):
    def test_vl001_no_frontmatter(self):
        self.put('vault/01-Tasks/Backlog/T-010.md', '# T-010 without frontmatter\n')
        findings, _ = self.lint()
        self.assertOnly(findings, 'VL001', 'vault/01-Tasks/Backlog/T-010.md: no frontmatter')

    def test_vl001_unparseable_line_and_unclosed_block(self):
        self.edit('vault/03-ADR/ADR-001-sample.md', 'decision_type: standard', 'decision_type standard')
        self.put('vault/02-Bugs/BUG-009.md', '---\nid: BUG-009\nstatus: Open\n')
        findings, _ = self.lint()
        self.assertOnly(findings, 'VL001', 'vault/03-ADR/ADR-001-sample.md: line 5: not a "key: value" line',
                        'vault/02-Bugs/BUG-009.md: frontmatter opened on line 1 is never closed')

    def test_vl002_required_fields(self):
        self.edit('vault/01-Tasks/In-Development/T-001.md', 'route: full # full | lightweight\n', '')
        self.edit('vault/01-Tasks/In-Development/T-001.md', 'branch: "feature/T-001/07.10.2026/dev-backend"', 'branch: ""')
        self.edit('vault/05-Reports/qa-report-2026-10-07-abc1234.md', 'verdict: passed-with-deferrals\n', '')
        self.edit('vault/05-Reports/content-review-2026-10-07-abc1234.md', 'checkpoint: pre-release ', 'checkpoint: ')
        findings, _ = self.lint()
        self.assertOnly(findings, 'VL002',
                        'T-001.md: missing required field: route; required field empty: branch',
                        'qa-report-2026-10-07-abc1234.md: missing required field: verdict',
                        'content-review-2026-10-07-abc1234.md: required field empty: checkpoint')

    def test_vl002_backlog_may_have_empty_branch_but_not_missing(self):
        self.edit('vault/01-Tasks/Backlog/T-002.md', 'branch: ""\n', '')
        findings, _ = self.lint()
        self.assertOnly(findings, 'VL002', 'T-002.md: missing required field: branch')

    def test_vl003_id_vs_file_name(self):
        self.edit('vault/01-Tasks/Backlog/T-002.md', 'id: T-002', 'id: T-003')
        self.put('vault/03-ADR/ADR-0010-other.md', '---\nid: ADR-001\ntitle: x\nstatus: Proposed\ndate: "2026-10-03"\n---\n')
        self.edit('vault/03-ADR/ADR-001-sample.md', 'id: ADR-001', 'id: ADR-002')
        findings, _ = self.lint()
        self.assertOnly(findings, 'VL003', 'T-002.md: id T-003 does not match the file name T-002.md',
                        'ADR-0010-other.md: file name ADR-0010-other.md does not start with the id ADR-001',
                        'ADR-001-sample.md: file name ADR-001-sample.md does not start with the id ADR-002')

    def test_vl004_duplicate_ids(self):
        self.put('vault/04-Archive/Deprecated-Proposals/T-002.md', NOTES['vault/01-Tasks/Backlog/T-002.md'].replace(
            'status: Backlog', 'status: Archived'))
        findings, _ = self.lint()
        self.assertOnly(findings, 'VL004',
                        'vault/01-Tasks/Backlog/T-002.md: id T-002 is also used by vault/04-Archive/Deprecated-Proposals/T-002.md',
                        'vault/04-Archive/Deprecated-Proposals/T-002.md: id T-002 is also used by vault/01-Tasks/Backlog/T-002.md')

    def test_vl005_task_status_vs_folder(self):
        self.edit('vault/01-Tasks/Backlog/T-002.md', 'status: Backlog', 'status: In-Development')
        self.edit('vault/04-Archive/Completed-Tasks/T-000.md', 'status: Archived', 'status: Completed')
        self.put('vault/01-Tasks/On-Hold/T-020.md', NOTES['vault/01-Tasks/Backlog/T-002.md'].replace('T-002', 'T-020'))
        findings, _ = self.lint()
        self.assertOnly(findings, 'VL005',
                        'VL005 error vault/01-Tasks/Backlog/T-002.md: status In-Development but folder Backlog',
                        'T-000.md: status Completed but archived tasks must have status Archived',
                        'T-020.md: folder On-Hold is not a task status folder')

    def test_vl005_bug_lifecycle(self):
        self.edit('vault/02-Bugs/BUG-001.md', 'status: Open', 'status: Verified')
        bug = NOTES['vault/02-Bugs/BUG-001.md']
        self.put('vault/02-Bugs/BUG-002.md', bug.replace('BUG-001', 'BUG-002').replace('status: Open', 'status: Archived'))
        self.put('vault/04-Archive/Resolved-Bugs/BUG-003.md', bug.replace('BUG-001', 'BUG-003').replace('status: Open', 'status: Closed'))
        findings, _ = self.lint()
        self.assertOnly(findings, 'VL005', 'BUG-001.md: status Verified is not a bug status',
                        'BUG-002.md: status Archived but the note is in 02-Bugs',
                        'BUG-003.md: status Closed but folder Resolved-Bugs expects Archived')

    def test_vl006_broken_wikilinks(self):
        self.edit('vault/00-Dashboard.md', '| [[T-001]] | Clean task |', '| [[T-404]] | Missing task |')
        self.edit('vault/02-Bugs/BUG-001.md', 'parent_task: "[[T-001]]"', 'parent_task: "[[{TASK-ID}]]"')
        findings, _ = self.lint()
        self.assertOnly(findings, 'VL006', 'vault/00-Dashboard.md: line 5: wikilink [[T-404]] target not found',
                        'vault/02-Bugs/BUG-001.md: line 3: wikilink [[{TASK-ID}]] target not found')
        self.assertEqual(len(findings), 2)

    def test_vl007_severity_and_release_blocking(self):
        bug = NOTES['vault/02-Bugs/BUG-001.md'].replace('category: content', 'category: functional')
        self.put('vault/02-Bugs/BUG-002.md', bug.replace('BUG-001', 'BUG-002').replace('release_blocking: true', 'release_blocking: false'))
        self.put('vault/02-Bugs/BUG-003.md', bug.replace('BUG-001', 'BUG-003').replace('severity: Major', 'severity: Minor'))
        self.put('vault/02-Bugs/BUG-004.md', bug.replace('BUG-001', 'BUG-004').replace('severity: Major', 'severity: Trivial')
                 .replace('deferral_signoff: ""', 'deferral_signoff: "CTO 2026-10-07: blocks the demo"'))
        self.put('vault/02-Bugs/BUG-005.md', bug.replace('BUG-001', 'BUG-005').replace('severity: Major', 'severity: medium'))
        self.put('vault/02-Bugs/BUG-006.md', bug.replace('BUG-001', 'BUG-006').replace('release_blocking: true', 'release_blocking: maybe'))
        self.put('vault/02-Bugs/BUG-007.md', bug.replace('BUG-001', 'BUG-007').replace('severity: Major', 'severity: minor')
                 .replace('release_blocking: true', 'release_blocking: false'))
        findings, _ = self.lint()
        self.assertOnly(findings, 'VL007', 'BUG-002.md: severity Major with release_blocking: false',
                        'BUG-003.md: severity Minor with release_blocking: true and no deferral_signoff',
                        'BUG-005.md: severity medium is not one of Critical, Major, Minor, Trivial',
                        'BUG-006.md: release_blocking maybe is not true or false')
        flagged = {f['path'].rsplit('/', 1)[1] for f in findings}
        self.assertEqual(flagged, {'BUG-002.md', 'BUG-003.md', 'BUG-005.md', 'BUG-006.md'})

    def test_vl008_content_intake_before_ready_for_dev(self):
        self.put('vault/01-Tasks/Ready-For-Dev/T-030.md', NOTES['vault/01-Tasks/In-Development/T-001.md']
                 .replace('T-001', 'T-030').replace('status: In-Development', 'status: Ready-For-Dev')
                 .replace('content_review_intake: approved', 'content_review_intake: pending'))
        self.edit('vault/01-Tasks/Backlog/T-002.md', 'content_review: not-applicable\ncontent_review_intake: not-applicable',
                  'content_review: required\ncontent_review_intake: changes-requested')
        findings, _ = self.lint()
        self.assertOnly(findings, 'VL008', 'T-030.md: content_review: required but content_review_intake is pending at Ready-For-Dev')
        self.assertEqual(len(findings), 1)

    def test_vl009_content_bug_without_locale(self):
        self.edit('vault/02-Bugs/BUG-001.md', 'locale: uz', 'locale: ""')
        findings, _ = self.lint()
        self.assertOnly(findings, 'VL009', 'BUG-001.md: category content without locale')
        self.assertEqual(findings[0]['severity'], 'warning')

    def test_vl010_missing_documents(self):
        self.remove('docs/spec.md')
        findings, summary = self.lint()
        self.assertOnly(findings, 'VL010', 'T-001.md: docs path docs/spec.md does not exist',
                        '.it-department/config.json: documents[0] (Product specification): path docs/spec.md does not exist')
        self.assertEqual(summary['errors'], 0)

    def test_vl011_dates_and_timestamps(self):
        self.edit('vault/01-Tasks/In-Development/T-001.md', 'date_created: "2026-10-01"', 'date_created: "01.10.2026"')
        self.edit('vault/04-Archive/Completed-Tasks/T-000.md', 'archived_at: "2026-10-02T17:30:00Z"', 'archived_at: "yesterday"')
        self.edit('vault/03-ADR/ADR-001-sample.md', 'date: "2026-10-02"', 'date: "2026-02-30"')
        findings, _ = self.lint()
        self.assertOnly(findings, 'VL011', 'T-001.md: date_created 01.10.2026 is not a YYYY-MM-DD date',
                        'T-000.md: archived_at yesterday is not an ISO 8601 timestamp',
                        'ADR-001-sample.md: date 2026-02-30 is not a YYYY-MM-DD date')

    def test_vl013_decisions_log_missing(self):
        self.remove('vault/03-ADR/decisions-log.md')
        self.edit('vault/01-Tasks/In-Development/T-001.md', ', journal [[decisions-log]]', '')
        self.edit('vault/00-Dashboard.md', 'journal [[decisions-log]], ', '')
        findings, _ = self.lint()
        self.assertOnly(findings, 'VL013', 'vault/03-ADR/decisions-log.md: decisions journal missing')

    def test_vl014_expired_lock(self):
        lock = {'owner_role': 'coordinator', 'session_id': 's1', 'host': 'cowork',
                'started_at': '2026-10-07T09:00:00Z', 'expires_at': '2026-10-07T13:00:00Z'}
        self.put('.it-department/lock.json', json.dumps(lock))
        before = datetime.datetime(2026, 10, 7, 12, 0, tzinfo=datetime.timezone.utc)
        after = datetime.datetime(2026, 10, 7, 13, 0, 1, tzinfo=datetime.timezone.utc)
        self.assertEqual(self.lint(now=before)[0], [])
        findings, _ = self.lint(now=after)
        self.assertOnly(findings, 'VL014', '.it-department/lock.json: lock held by coordinator@cowork expired at 2026-10-07T13:00:00Z')
        self.put('.it-department/lock.json', '{"expires_at": "soon"}')
        self.assertOnly(self.lint(now=before)[0], 'VL014', 'no valid expires_at')
        self.put('.it-department/lock.json', 'not json')
        self.assertOnly(self.lint(now=before)[0], 'VL014', 'not valid JSON')

    def test_vl014_offset_timestamps(self):
        self.put('.it-department/lock.json', '{"expires_at": "2026-10-07T18:00:00+05:00"}')
        self.assertEqual(self.lint(now=datetime.datetime(2026, 10, 7, 12, 59, tzinfo=datetime.timezone.utc))[0], [])
        self.assertOnly(self.lint(now=datetime.datetime(2026, 10, 7, 13, 1, tzinfo=datetime.timezone.utc))[0], 'VL014')


class DashboardCheckTest(LintCase):
    """VL012 with a stub dashboard_sync.py (the real script is owned by another work package)."""

    def stub(self, rc):
        path = os.path.join(self.tmp, 'stub_rc%d' % rc, 'dashboard_sync.py')
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, 'w', encoding='utf-8') as fh:
            fh.write(STUB_SCRIPT.format(rc=rc))
        return path

    def test_up_to_date_dashboard(self):
        script = self.stub(0)
        findings, summary = self.lint(dashboard_check=True, dashboard_script=script)
        self.assertEqual(findings, [])
        self.assertEqual(summary['dashboard_check'], 'ok')
        with open(script + '.argv.json', encoding='utf-8') as fh:
            argv = json.load(fh)
        self.assertEqual(argv, ['--root', os.path.abspath(self.root), '--check'])

    def test_outdated_dashboard_is_a_warning_and_an_error_when_strict(self):
        script = self.stub(1)
        findings, summary = self.lint(dashboard_check=True, dashboard_script=script)
        self.assertOnly(findings, 'VL012', 'VL012 warning vault/00-Dashboard.md: dashboard out of date')
        self.assertEqual((summary['errors'], summary['warnings'], summary['dashboard_check']), (0, 1, 'outdated'))
        findings, summary = self.lint(dashboard_check=True, dashboard_script=script, strict=True)
        self.assertEqual(findings[0]['severity'], 'error')
        self.assertEqual(summary['errors'], 1)

    def test_failing_dashboard_script(self):
        findings, summary = self.lint(dashboard_check=True, dashboard_script=self.stub(2))
        self.assertOnly(findings, 'VL012', 'dashboard check failed (dashboard_sync.py --check exit 2)')
        self.assertEqual(summary['dashboard_check'], 'failed')

    def test_missing_script_is_reported_as_skipped_and_never_fails(self):
        missing = os.path.join(self.tmp, 'nowhere', 'dashboard_sync.py')
        for strict in (False, True):
            findings, summary = self.lint(dashboard_check=True, dashboard_script=missing, strict=strict)
            self.assertEqual(len(findings), 1)
            self.assertEqual(vault_lint.format_finding(findings[0]),
                             'VL012 warning dashboard check skipped: dashboard_sync.py not found')
            self.assertEqual((summary['errors'], summary['dashboard_check']), (0, 'skipped'))

    def test_no_dashboard_check_never_runs_the_script(self):
        script = self.stub(1)
        findings, summary = self.lint(dashboard_check=False, dashboard_script=script)
        self.assertEqual(findings, [])
        self.assertFalse(os.path.exists(script + '.argv.json'))
        self.assertEqual(summary['dashboard_check'], 'disabled')


class CliTest(LintCase):
    def run_main(self, *args):
        out, err = io.StringIO(), io.StringIO()
        with mock.patch.object(vault_lint, 'DASHBOARD_SYNC', os.path.join(self.tmp, 'absent', 'dashboard_sync.py')):
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                rc = vault_lint.main(list(args))
        return rc, out.getvalue(), err.getvalue()

    def test_clean_project_exits_zero(self):
        rc, out, _ = self.run_main('--root', self.root, '--no-dashboard-check')
        self.assertEqual(rc, 0)
        lines = out.strip().split('\n')
        self.assertEqual(len(lines), 1)
        self.assertTrue(lines[0].startswith('vault_lint: 0 error(s), 0 warning(s) in 10 note(s)'), lines[0])

    def test_text_output_format_and_exit_one(self):
        self.edit('vault/01-Tasks/Backlog/T-002.md', 'status: Backlog', 'status: In-Development')
        rc, out, _ = self.run_main('--root', self.root)
        self.assertEqual(rc, 1)
        lines = out.strip().split('\n')
        self.assertEqual(lines[0], 'VL005 error vault/01-Tasks/Backlog/T-002.md: status In-Development but folder Backlog')
        self.assertEqual(lines[1], 'VL012 warning dashboard check skipped: dashboard_sync.py not found')
        self.assertTrue(lines[-1].startswith('vault_lint: 1 error(s), 1 warning(s)'), lines[-1])

    def test_warnings_only_exit_zero_and_strict_exit_one(self):
        self.remove('docs/spec.md')
        self.assertEqual(self.run_main('--root', self.root, '--no-dashboard-check')[0], 0)
        rc, out, _ = self.run_main('--root', self.root, '--no-dashboard-check', '--strict')
        self.assertEqual(rc, 1)
        self.assertIn('VL010 error', out)
        self.assertIn('[strict]', out)

    def test_json_format(self):
        self.edit('vault/02-Bugs/BUG-001.md', 'locale: uz', 'locale: ""')
        rc, out, _ = self.run_main('--root', self.root, '--format', 'json', '--no-dashboard-check')
        self.assertEqual(rc, 0)
        data = json.loads(out)
        self.assertEqual(sorted(data), ['findings', 'summary'])
        self.assertEqual(data['summary']['warnings'], 1)
        self.assertEqual(data['summary']['by_code'], {'VL009': 1})
        self.assertEqual(data['findings'][0]['path'], 'vault/02-Bugs/BUG-001.md')
        self.assertEqual(sorted(data['findings'][0]), ['code', 'line', 'message', 'path', 'severity'])

    def test_bad_arguments_exit_two(self):
        rc, _, err = self.run_main('--root', os.path.join(self.tmp, 'does-not-exist'))
        self.assertEqual(rc, 2)
        self.assertIn('project root not found', err)
        shutil.rmtree(os.path.join(self.root, 'vault'))
        rc, _, err = self.run_main('--root', self.root)
        self.assertEqual(rc, 2)
        self.assertIn('vault not found', err)
        with contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit) as ctx:
                vault_lint.main(['--format', 'xml'])
        self.assertEqual(ctx.exception.code, 2)

    def test_configured_vault_path_and_unreadable_config(self):
        os.rename(os.path.join(self.root, 'vault'), os.path.join(self.root, 'notes'))
        config = dict(CONFIG, paths=dict(CONFIG['paths'], vault_relative_path='notes'))
        with open(os.path.join(self.root, '.it-department', 'config.json'), 'w', encoding='utf-8') as fh:
            json.dump(config, fh)
        rc, out, _ = self.run_main('--root', self.root, '--no-dashboard-check')
        self.assertEqual(rc, 0, out)
        self.assertIn('under notes', out)
        with open(os.path.join(self.root, '.it-department', 'config.json'), 'w', encoding='utf-8') as fh:
            fh.write('{ broken')
        rc, _, err = self.run_main('--root', self.root, '--no-dashboard-check')
        self.assertEqual(rc, 2)
        self.assertIn('config.json is not readable', err)


@unittest.skipUnless(os.path.isdir(VAULT_TEMPLATE), 'assets/vault-template not available (only scripts/ mounted)')
class VaultTemplateTest(unittest.TestCase):
    def test_fresh_vault_from_template_has_no_errors(self):
        tmp = tempfile.mkdtemp(prefix='vault-lint-template-')
        try:
            root = os.path.join(tmp, 'project')
            shutil.copytree(VAULT_TEMPLATE, os.path.join(root, 'vault'))
            findings, summary = vault_lint.lint(root, dashboard_check=False)
            self.assertEqual(summary['errors'], 0, '\n'.join(vault_lint.format_finding(f) for f in findings))
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


if __name__ == '__main__':
    unittest.main()
