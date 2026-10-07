"""Unit tests for scripts/apply_transitions.py (stdlib unittest).

Run from the scripts directory:  python -m unittest discover -s tests -v
"""
import contextlib
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
import apply_transitions as at  # noqa: E402
import dashboard_sync as ds  # noqa: E402

TODAY = datetime.date(2026, 10, 7)
ARROW = '\N{RIGHTWARDS ARROW}'
PLACEHOLDER = '- {YYYY-MM-DDTHH:MM:SSZ} In-Analysis %s Ready-For-Dev by coordinator (evidence: \N{HORIZONTAL ELLIPSIS})' % ARROW
SESSIONS = os.path.join('.it-department', 'sessions')


def task_note(tid, status, qa='pending', intake='approved', review='required', log=True):
    lines = ['---', 'id: %s' % tid, 'title: "Task %s"' % tid,
             'status: %s # In-Analysis (default for Full route) | Ready-For-Dev (for Lightweight route)' % status,
             'route: full # full | lightweight', 'priority: high # critical | high | medium | low',
             'assigned_agent: dev-backend # dev-backend | dev-frontend | dev-mobile',
             'branch: "feature/%s/07.10.2026/dev-backend"' % tid, 'date_created: "2026-10-05"', 'date_updated: "2026-10-06"',
             'pr_link: ""', 'docs: [] # related documents outside the vault', 'qa_status: %s # pending | testing | passed | failed' % qa,
             'content_review: %s # required | not-applicable' % review,
             'content_review_intake: %s # pending | approved | changes-requested | not-applicable' % intake,
             'cto_approved: true', 'tags:', '  - task', '---', '', '# [Shop] %s: Task %s' % (tid, tid), '',
             '## 9. Dependencies & Blockers', '- Depends on: None', '']
    if log:
        lines += ['## 10. Transition Log', PLACEHOLDER, '']
    return '\n'.join(lines)


BUG_NOTE = '\n'.join(['---', 'id: BUG-001', 'parent_task: "[[DEMO-001]]"', 'title: "[BUG] Wrong total"',
                      'status: Open # Open | In-Development | Code-Review | Retesting | Closed | Archived',
                      'severity: Major # Critical | Major | Minor | Trivial', 'release_blocking: true', '---', '',
                      '# [BUG-001] Wrong total', '', '## Defect Summary', '- **Affected Feature:** [[DEMO-001]]', ''])


def write(path, text, newline='\n'):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w', encoding='utf-8', newline=newline) as fh:
        fh.write(text)


def read(path):
    with open(path, encoding='utf-8') as fh:
        return fh.read()


def snapshot(root):
    files = {}
    for dp, _dn, fn in os.walk(root):
        for f in fn:
            p = os.path.join(dp, f)
            with open(p, 'rb') as fh:
                files[os.path.relpath(p, root)] = fh.read()
    return files


class TransitionCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix='apply-transitions-')
        self.root = os.path.join(self.tmp, 'project')
        self.vault = os.path.join(self.root, 'vault')
        for sub in ds.TASK_STATUSES:
            os.makedirs(os.path.join(self.vault, '01-Tasks', sub))
        for sub in ('02-Bugs', '03-ADR', '04-Archive/Completed-Tasks', '04-Archive/Resolved-Bugs', '05-Reports'):
            os.makedirs(os.path.join(self.vault, sub))
        write(os.path.join(self.root, '.it-department', 'config.json'), json.dumps({
            'project_name': 'Demo', 'operating_profile': 'pilot',
            'paths': {'vault_relative_path': 'vault', 'sessions_relative_path': '.it-department/sessions'}}))
        write(os.path.join(self.vault, ds.DASHBOARD), ds.skeleton())
        for name in ('06-Content/glossary.md', '06-Content/style-guide.md', '03-ADR/decisions-log.md'):
            write(os.path.join(self.vault, name), '# %s\n' % name)
        write(self.task('In-Development', 'DEMO-001'), task_note('DEMO-001', 'In-Development'))
        write(self.task('In-Analysis', 'DEMO-002'), task_note('DEMO-002', 'In-Analysis', intake='pending', log=False))
        write(self.task('QA-Testing', 'DEMO-003'), task_note('DEMO-003', 'QA-Testing', qa='testing'))
        write(self.task('Ready-For-Release', 'DEMO-004'), task_note('DEMO-004', 'Ready-For-Release', qa='passed'))
        write(os.path.join(self.vault, '02-Bugs', 'BUG-001.md'), BUG_NOTE)
        write(os.path.join(self.vault, '04-Archive', 'Completed-Tasks', 'DEMO-000.md'), task_note('DEMO-000', 'Archived'))

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def task(self, folder, tid):
        return os.path.join(self.vault, '01-Tasks', folder, tid + '.md')

    def request(self, tid, frm, to, role='backend-dev', session='s1', ts='2026-10-07T10:00:00Z', evidence=True, **extra):
        folder = os.path.join(self.root, SESSIONS, tid, role, session)
        req = {'task_id': tid, 'from_status': frm, 'to_status': to, 'agent_role': role, 'evidence_file': 'handoff.md',
               'timestamp': ts}
        req.update(extra)
        write(os.path.join(folder, 'transition-request.json'), json.dumps(req, indent=2))
        if evidence:
            write(os.path.join(folder, 'handoff.md'), '# hand-off\n')
        return os.path.join(folder, 'transition-request.json')

    def run_main(self, *args):
        buf = io.StringIO()
        with mock.patch.object(at, '_today', return_value=TODAY), contextlib.redirect_stdout(buf):
            rc = at.main(['--root', self.root] + list(args))
        return rc, buf.getvalue()

    def fm(self, path):
        return at.parse_frontmatter(read(path))[0]


class ApplyTest(TransitionCase):
    def test_legal_transition_moves_note_and_logs(self):
        req_path = self.request('DEMO-001', 'In-Development', 'Code-Review')
        rc, out = self.run_main('--no-sync')
        self.assertEqual(rc, 0, out)
        old, new = self.task('In-Development', 'DEMO-001'), self.task('Code-Review', 'DEMO-001')
        self.assertFalse(os.path.exists(old))
        text = read(new)
        self.assertIn('\nstatus: Code-Review # In-Analysis (default for Full route) | Ready-For-Dev (for Lightweight route)\n', text)
        self.assertIn('\ndate_updated: "2026-10-07"\n', text)
        line = ('- 2026-10-07T10:00:00Z In-Development %s Code-Review by backend-dev '
                '(evidence: .it-department/sessions/DEMO-001/backend-dev/s1/handoff.md)' % ARROW)
        self.assertTrue(text.endswith('## 10. Transition Log\n' + line + '\n'), text[-300:])
        self.assertNotIn('{YYYY-MM-DDTHH:MM:SSZ}', text)
        req = json.loads(read(req_path))
        self.assertRegex(req['applied_at'], r'^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$')
        self.assertEqual(req['to_status'], 'Code-Review')
        self.assertIn('applied      DEMO-001: In-Development %s Code-Review -> vault/01-Tasks/Code-Review/DEMO-001.md' % ARROW, out)
        self.assertIn('transitions: 1 applied, 0 refused', out)
        rc, out = self.run_main('--no-sync')
        self.assertEqual(rc, 0)
        self.assertIn('transitions: 0 applied, 0 refused (no pending requests under .it-department/sessions)', out)

    def test_illegal_transition_is_refused(self):
        req_path = self.request('DEMO-001', 'In-Development', 'QA-Testing')
        rc, out = self.run_main('--no-sync')
        self.assertEqual(rc, 1)
        self.assertIn('refused      DEMO-001: illegal transition: In-Development %s QA-Testing '
                      '(allowed from In-Development: Code-Review)' % ARROW, out)
        self.assertTrue(os.path.exists(self.task('In-Development', 'DEMO-001')))
        self.assertNotIn('applied_at', json.loads(read(req_path)))
        self.assertEqual(self.fm(self.task('In-Development', 'DEMO-001'))['status'], 'In-Development')

    def test_back_edge_is_legal(self):
        self.request('DEMO-003', 'QA-Testing', 'In-Development', role='qa-engineer')
        rc, out = self.run_main('--no-sync')
        self.assertEqual(rc, 0, out)
        self.assertEqual(self.fm(self.task('In-Development', 'DEMO-003'))['status'], 'In-Development')

    def test_stale_unknown_archived_and_missing_evidence(self):
        self.request('DEMO-001', 'Code-Review', 'QA-Testing', role='reviewer')
        self.request('DEMO-999', 'Backlog', 'In-Analysis', role='analyst')
        self.request('DEMO-000', 'Ready-For-Release', 'Archived', role='devops')
        self.request('DEMO-004', 'Ready-For-Release', 'Archived', role='devops', evidence=False,
                     release_version='v1.0.0', release_commit='abcdef1')
        rc, out = self.run_main('--no-sync')
        self.assertEqual(rc, 1)
        self.assertIn('refused      DEMO-001: stale: DEMO-001 is In-Development, the request is from Code-Review', out)
        self.assertIn('refused      DEMO-999: unknown note: no task under 01-Tasks/ and no bug under 02-Bugs/ named DEMO-999', out)
        self.assertIn('refused      DEMO-000: stale: DEMO-000 is already archived', out)
        self.assertIn('refused      DEMO-004: missing evidence: .it-department/sessions/DEMO-004/devops/s1/handoff.md', out)
        self.assertIn('transitions: 0 applied, 4 refused', out)

    def test_status_and_folder_must_agree(self):
        write(self.task('In-Development', 'DEMO-001'), task_note('DEMO-001', 'Code-Review'))
        self.request('DEMO-001', 'In-Development', 'Code-Review')
        rc, out = self.run_main('--no-sync')
        self.assertEqual(rc, 1)
        self.assertIn('stale: DEMO-001 has status "Code-Review" but lives in folder In-Development', out)

    def test_intake_verdict_gate(self):
        self.request('DEMO-002', 'In-Analysis', 'Ready-For-Dev', role='system-analyst')
        rc, out = self.run_main('--no-sync')
        self.assertEqual(rc, 1)
        self.assertIn('missing intake verdict: content_review_intake is pending (approved or not-applicable needed)', out)
        path = self.task('In-Analysis', 'DEMO-002')
        write(path, read(path).replace('content_review_intake: pending', 'content_review_intake: approved'))
        rc, out = self.run_main('--no-sync')
        self.assertEqual(rc, 0, out)
        text = read(self.task('Ready-For-Dev', 'DEMO-002'))
        self.assertTrue(text.endswith('\n- Depends on: None\n\n## Transition Log\n\n- 2026-10-07T10:00:00Z In-Analysis %s '
                                      'Ready-For-Dev by system-analyst (evidence: .it-department/sessions/DEMO-002/'
                                      'system-analyst/s1/handoff.md)\n' % ARROW), text[-250:])

    def test_ready_for_release_needs_qa_verdict_or_candidate(self):
        req_path = self.request('DEMO-003', 'QA-Testing', 'Ready-For-Release', role='qa-engineer')
        rc, out = self.run_main('--no-sync')
        self.assertEqual(rc, 1)
        self.assertIn('missing QA verdict: qa_status is testing and the request has no candidate_sha', out)
        req = json.loads(read(req_path))
        req['candidate_sha'] = 'abc1234def'
        write(req_path, json.dumps(req))
        rc, out = self.run_main('--no-sync')
        self.assertEqual(rc, 0, out)
        fm = self.fm(self.task('Ready-For-Release', 'DEMO-003'))
        self.assertEqual((fm['status'], fm['candidate_sha'], fm['qa_status']), ('Ready-For-Release', 'abc1234def', 'testing'))

    def test_qa_status_in_request_is_applied(self):
        self.request('DEMO-003', 'QA-Testing', 'Ready-For-Release', role='qa-engineer', qa_status='passed')
        rc, out = self.run_main('--no-sync')
        self.assertEqual(rc, 0, out)
        self.assertEqual(self.fm(self.task('Ready-For-Release', 'DEMO-003'))['qa_status'], 'passed')

    def test_archive_needs_release_data(self):
        req_path = self.request('DEMO-004', 'Ready-For-Release', 'Archived', role='devops')
        rc, out = self.run_main('--no-sync')
        self.assertEqual(rc, 1)
        self.assertIn('missing release data: release_version and release_commit required for Archived', out)
        req = json.loads(read(req_path))
        req.update(release_version='v1.0.0', release_commit='0123abc456')
        write(req_path, json.dumps(req))
        rc, out = self.run_main('--no-sync')
        self.assertEqual(rc, 0, out)
        self.assertFalse(os.path.exists(self.task('Ready-For-Release', 'DEMO-004')))
        archived = os.path.join(self.vault, '04-Archive', 'Completed-Tasks', 'DEMO-004.md')
        text = read(archived)
        for line in ('status: Archived #', 'release_version: "v1.0.0"', 'release_commit: "0123abc456"', 'archived_at: "2026-10-07"'):
            self.assertIn('\n' + line, text)
        self.assertEqual(self.fm(archived)['release_commit'], '0123abc456')

    def test_bug_transition_stays_in_bug_folder(self):
        self.request('BUG-001', 'Open', 'In-Development', role='frontend-dev')
        rc, out = self.run_main('--no-sync')
        self.assertEqual(rc, 0, out)
        path = os.path.join(self.vault, '02-Bugs', 'BUG-001.md')
        fm = self.fm(path)
        self.assertEqual((fm['status'], fm['date_updated']), ('In-Development', '2026-10-07'))
        self.assertIn('status: In-Development # Open | In-Development | Code-Review | Retesting | Closed | Archived', read(path))
        self.assertTrue(read(path).endswith('## Transition Log\n\n- 2026-10-07T10:00:00Z Open %s In-Development by frontend-dev '
                                            '(evidence: .it-department/sessions/BUG-001/frontend-dev/s1/handoff.md)\n' % ARROW))
        self.request('BUG-001', 'In-Development', 'Ready-For-Dev', role='frontend-dev', session='s2', ts='2026-10-07T11:00:00Z')
        rc, out = self.run_main('--no-sync')
        self.assertEqual(rc, 1)
        self.assertIn('illegal transition: In-Development %s Ready-For-Dev (allowed from In-Development: Code-Review)' % ARROW, out)

    def test_bug_archive_moves_to_resolved_bugs(self):
        path = os.path.join(self.vault, '02-Bugs', 'BUG-001.md')
        write(path, read(path).replace('status: Open', 'status: Closed'))
        self.request('BUG-001', 'Closed', 'Archived', role='devops', release_version='v1.0.1', release_commit='feed123')
        rc, out = self.run_main('--no-sync')
        self.assertEqual(rc, 0, out)
        self.assertEqual(self.fm(os.path.join(self.vault, '04-Archive', 'Resolved-Bugs', 'BUG-001.md'))['release_version'], 'v1.0.1')

    def test_valid_requests_apply_when_others_are_refused(self):
        self.request('DEMO-001', 'In-Development', 'Archived', role='devops', session='bad')
        self.request('DEMO-003', 'QA-Testing', 'In-Development', role='qa-engineer')
        rc, out = self.run_main('--no-sync')
        self.assertEqual(rc, 1)
        self.assertIn('transitions: 1 applied, 1 refused', out)
        self.assertTrue(os.path.exists(self.task('In-Development', 'DEMO-003')))

    def test_requests_apply_in_timestamp_order(self):
        second = self.request('DEMO-001', 'Code-Review', 'QA-Testing', role='a-reviewer', ts='2026-10-07T12:00:00+00:00')
        first = self.request('DEMO-001', 'In-Development', 'Code-Review', role='z-backend-dev', ts='2026-10-07T13:00:00+02:00')
        rc, out = self.run_main('--no-sync')
        self.assertEqual(rc, 0, out)
        text = read(self.task('QA-Testing', 'DEMO-001'))
        log = text.split('## 10. Transition Log\n')[1].strip().split('\n')
        self.assertEqual([re.sub(r' by .*', '', x) for x in log], [
            '- 2026-10-07T13:00:00+02:00 In-Development %s Code-Review' % ARROW,
            '- 2026-10-07T12:00:00+00:00 Code-Review %s QA-Testing' % ARROW])
        self.assertIn('applied_at', json.loads(read(first)))
        self.assertIn('applied_at', json.loads(read(second)))

    def test_dry_run_writes_nothing(self):
        self.request('DEMO-001', 'In-Development', 'Code-Review', ts='2026-10-07T10:00:00Z')
        self.request('DEMO-001', 'Code-Review', 'QA-Testing', role='reviewer', ts='2026-10-07T11:00:00Z')
        self.request('DEMO-002', 'In-Analysis', 'Ready-For-Dev', role='system-analyst')
        before = snapshot(self.root)
        rc, out = self.run_main('--dry-run')
        self.assertEqual(rc, 1)
        self.assertEqual(snapshot(self.root), before)
        self.assertIn('would apply  DEMO-001: In-Development %s Code-Review' % ARROW, out)
        self.assertIn('would apply  DEMO-001: Code-Review %s QA-Testing -> vault/01-Tasks/QA-Testing/DEMO-001.md' % ARROW, out)
        self.assertIn('refused      DEMO-002: missing intake verdict', out)
        self.assertIn('transitions (dry run): 2 would be applied, 1 refused; nothing written', out)
        self.assertTrue(out.rstrip().endswith('dashboard: sync skipped (--dry-run)'))

    def test_bad_requests(self):
        broken = os.path.join(self.root, SESSIONS, 'DEMO-001', 'dev', 's9', 'transition-request.json')
        write(broken, '{"task_id": "DEMO-001",')
        req_path = self.request('DEMO-001', 'In-Development', 'Code-Review', session='s2')
        req = json.loads(read(req_path))
        del req['agent_role']
        write(req_path, json.dumps(req))
        self.request('DEMO-003', 'QA-Testing', 'In-Development', role='qa-engineer', ts='yesterday')
        rc, out = self.run_main('--no-sync')
        self.assertEqual(rc, 1)
        self.assertIn('bad request: invalid JSON', out)
        self.assertIn('refused      DEMO-001: bad request: missing or empty field(s) agent_role', out)
        self.assertIn('refused      DEMO-003: bad request: timestamp "yesterday" is not ISO 8601', out)
        self.assertIn('transitions: 0 applied, 3 refused', out)

    def test_crlf_and_bom_notes_keep_their_style(self):
        path = self.task('In-Development', 'DEMO-001')
        write(path, '\N{ZERO WIDTH NO-BREAK SPACE}' + task_note('DEMO-001', 'In-Development'), newline='\r\n')
        self.request('DEMO-001', 'In-Development', 'Code-Review')
        rc, out = self.run_main('--no-sync')
        self.assertEqual(rc, 0, out)
        with open(self.task('Code-Review', 'DEMO-001'), 'rb') as fh:
            data = fh.read()
        self.assertTrue(data.startswith(b'\xef\xbb\xbf---\r\n'))
        self.assertEqual(data.count(b'\n'), data.count(b'\r\n'))
        self.assertIn(b'\r\nstatus: Code-Review #', data)

    def test_sync_runs_afterwards_unless_disabled(self):
        dashboard = os.path.join(self.vault, ds.DASHBOARD)
        self.request('DEMO-001', 'In-Development', 'Code-Review')
        rc, out = self.run_main()
        self.assertEqual(rc, 0, out)
        self.assertIn('dashboard: updated', out)
        tasks = ds.read_text(dashboard)
        span = ds.find_block(tasks, 'tasks')
        self.assertRegex(tasks[span[0]:span[1]], r'\| \[\[DEMO-001\]\] \| Task DEMO-001 \| high \| full \| dev-backend \| `[^`]+` \| Code-Review \|')
        before = snapshot(self.root)[os.path.join('vault', ds.DASHBOARD)]
        self.request('DEMO-001', 'Code-Review', 'QA-Testing', role='reviewer', session='s2', ts='2026-10-07T11:00:00Z')
        rc, out = self.run_main('--no-sync')
        self.assertEqual(rc, 0, out)
        self.assertTrue(out.rstrip().endswith('dashboard: sync skipped (--no-sync)'))
        self.assertEqual(snapshot(self.root)[os.path.join('vault', ds.DASHBOARD)], before)

    def test_missing_vault_is_a_bad_argument(self):
        with mock.patch('sys.stderr', new=io.StringIO()) as err:
            rc = at.main(['--root', os.path.join(self.tmp, 'nowhere')])
        self.assertEqual(rc, 2)
        self.assertIn('vault not found', err.getvalue())


class EditingHelpersTest(unittest.TestCase):
    def test_set_frontmatter_keeps_comments_and_adds_keys(self):
        text = '---\nid: X-1\nstatus: Open # Open | Closed\ntitle: "a # b"\n---\nbody\n'
        new = at.set_frontmatter(text, [('status', 'Closed'), ('date_updated', '2026-10-07'), ('title', 'Say "hi"')])
        self.assertEqual(new, '---\nid: X-1\nstatus: Closed # Open | Closed\ntitle: "Say \\"hi\\""\n'
                              'date_updated: "2026-10-07"\n---\nbody\n')
        self.assertEqual(at.parse_frontmatter(new)[0]['title'], 'Say "hi"')

    def test_append_log_section_variants(self):
        line = '- t A %s B by r (evidence: e)' % ARROW
        self.assertEqual(at.append_log('# T\n\n## Transition Log\n\n- old\n\n## Next\ntext\n', line),
                         '# T\n\n## Transition Log\n\n- old\n%s\n\n## Next\ntext\n' % line)
        self.assertEqual(at.append_log('# T\n\n## Transition Log\n## Next\n', line),
                         '# T\n\n## Transition Log\n\n%s\n\n## Next\n' % line)
        self.assertEqual(at.append_log('# T\nbody\n\n\n', line), '# T\nbody\n\n## Transition Log\n\n%s\n' % line)
        self.assertEqual(at.append_log('```\n## Transition Log\n```\n', line),
                         '```\n## Transition Log\n```\n\n## Transition Log\n\n%s\n' % line)


class CliTest(TransitionCase):
    def test_script_runs_standalone(self):
        self.request('DEMO-001', 'In-Development', 'Code-Review')
        env = dict(os.environ, PYTHONIOENCODING='utf-8')
        res = subprocess.run([sys.executable, os.path.join(SCRIPTS, 'apply_transitions.py'), '--root', self.root, '--dry-run'],
                             stdout=subprocess.PIPE, stderr=subprocess.PIPE, encoding='utf-8', env=env)
        self.assertEqual(res.returncode, 0, res.stdout + res.stderr)
        self.assertIn('would apply  DEMO-001', res.stdout)
        res = subprocess.run([sys.executable, os.path.join(SCRIPTS, 'apply_transitions.py'), '--root', self.root],
                             stdout=subprocess.PIPE, stderr=subprocess.PIPE, encoding='utf-8', env=env)
        self.assertEqual(res.returncode, 0, res.stdout + res.stderr)
        self.assertEqual(res.stdout.strip().split('\n')[-2:], [os.path.join(self.vault, ds.DASHBOARD),
                                                                'dashboard: updated (4 tasks, 1 bugs, 0 warnings)'])


if __name__ == '__main__':
    unittest.main()
