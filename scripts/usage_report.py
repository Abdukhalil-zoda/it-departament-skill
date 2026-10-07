#!/usr/bin/env python3
"""usage_report.py - aggregate the usage ledger, job logs and vault into a markdown usage audit.

Part of the IT Department skill (workflows/efficiency-and-usage-audit.md). Produces deterministic
numbers; the auditing model adds its judgement on top (sections 6 and 7). The script never invents
numbers it cannot compute.

Usage:
  python3 usage_report.py [--root PROJECT_ROOT] [--since YYYY-MM-DD] [--out FILE] [--jobs DIR]
                          [--task-prefixes ATM,BUG] [--top N] [--no-json]

Inputs (all optional, skipped when missing; paths come from <root>/.it-department/config.json):
  <root>/<efficiency.ledger_path>/*.json           written by usage_ledger.py inside each session
  <root>/<efficiency.jobs_log_path>/*.log           job-runner logs, two marker lines per job:
                                                      [runner] job <name>.ps1 started <ISO-local-time>
                                                      [runner] exit=<code> elapsed=<seconds>s
  <root>/<efficiency.jobs_log_path>/jobs.jsonl      alternative machine-time feed, one JSON per line:
                                                      {"name","started","elapsed_seconds","exit_code",
                                                       "kind"?,"role"?,"task"?}
  <root>/<paths.sessions_relative_path>/**          screenshots per task folder (count only)
  <root>/<efficiency.reports_path>/usage-audit-*.json  totals of the previous audit (delta section)

Output: <efficiency.reports_path>/usage-audit-<date>.md plus a .json sidecar with the totals that the
next audit uses for its delta. --since defaults to the date of the previous audit report, or to
audit_interval_days + 1 days ago when there is none. Section 7 has a Decision column for the CTO's
verdict; when a previous report exists the sidecar also records its proposals_total / proposals_pending
(section 7 rows with a Change / of those, rows without a Decision).

Exit codes: 0 ok, 2 bad arguments. Requires Python 3.8+, standard library only.
"""
import argparse
import collections
import datetime
import glob
import json
import os
import re
import sys

DEFAULT_LEDGER_PATH = os.path.join('.it-department', 'sessions', '_usage', 'ledger')
DEFAULT_JOBS_PATH = os.path.join('.it-department', 'jobs')
DEFAULT_REPORTS_PATH = os.path.join('vault', '05-Reports')
DEFAULT_RULES = {
    'R1_builds_per_fix_round_max': 2,
    'R2_screenshots_per_scenario_max': 10,
    'R2_screenshot_scale': 0.5,
    'R4_log_tail_lines': 40,
    'R4_tool_result_tokens_max': 2000,
    'R5_queue_wait_minutes_max': 5,
}
IMAGE_EXT = ('.png', '.jpg', '.jpeg', '.webp', '.gif')


def utc_naive(ts):
    """Naive UTC datetime from a POSIX timestamp (replaces the deprecated utcfromtimestamp)."""
    return datetime.datetime.fromtimestamp(ts, datetime.timezone.utc).replace(tzinfo=None)


# --------------------------------------------------------------------------- project context
def load_config(root):
    path = os.path.join(root, '.it-department', 'config.json')
    try:
        with open(path, encoding='utf-8') as fh:
            return json.load(fh)
    except Exception:
        return {}


def discover_task_prefixes(root, cfg, override=None):
    if override:
        return sorted({p.strip().upper() for p in override.split(',') if p.strip()})
    prefixes = {'BUG', 'ADR'}
    vault = os.path.join(root, (cfg.get('paths') or {}).get('vault_relative_path', 'vault'))
    pat = re.compile(r'^([A-Z][A-Z0-9]{1,9})-\d{1,6}\b')
    for sub in ('01-Tasks', '02-Bugs', '03-ADR', '04-Archive'):
        for _dp, _dn, files in os.walk(os.path.join(vault, sub)):
            for f in files:
                m = pat.match(f)
                if m:
                    prefixes.add(m.group(1))
    return sorted(prefixes)


def previous_reports(reports_dir):
    """[(date, json_path or None)] of earlier audits, newest first."""
    found = {}
    for f in glob.glob(os.path.join(reports_dir, 'usage-audit-*.*')):
        m = re.match(r'usage-audit-(\d{4}-\d{2}-\d{2})\.(md|json)$', os.path.basename(f))
        if not m:
            continue
        entry = found.setdefault(m.group(1), {})
        entry[m.group(2)] = f
    return [(d, found[d].get('json')) for d in sorted(found, reverse=True)]


def count_proposals(md_path):
    """(total, pending) of the "Proposals" section of an audit report: rows with a non-empty Change; pending =
    of those, rows with an empty Decision (reports older than the Decision column count as pending).
    None when the report cannot be read."""
    try:
        with open(md_path, encoding='utf-8-sig', errors='replace') as fh:
            lines = fh.read().splitlines()
    except OSError:
        return None
    start = next((i for i, line in enumerate(lines) if line.startswith('#') and 'proposals' in line.lower()), None)
    rows = []
    for line in lines[start + 1:] if start is not None else []:
        s = line.strip()
        if line.startswith('#') or (rows and not s.startswith('|')):
            break
        if s.startswith('|'):
            rows.append([c.strip() for c in re.split(r'(?<!\\)\|', s.strip('|'))])
    if not rows:
        return 0, 0
    head = [c.lower() for c in rows[0]]
    ci = next((i for i, h in enumerate(head) if h.startswith('change')), None)
    di = next((i for i, h in enumerate(head) if h.startswith('decision')), None)
    total = pending = 0
    for r in rows[1:]:
        if ci is None or ci >= len(r) or not r[ci] or re.match(r'^:?-+:?$', r[ci]):
            continue
        total += 1
        if di is None or di >= len(r) or not r[di]:
            pending += 1
    return total, pending


# --------------------------------------------------------------------------- inputs
def load_ledger(ledger_dir, since):
    rows = []
    for f in glob.glob(os.path.join(ledger_dir, '*.json')):
        try:
            with open(f, encoding='utf-8') as fh:
                d = json.load(fh)
        except Exception:
            continue
        if not isinstance(d, dict) or 'weighted_total' not in d:
            continue
        if d.get('duplicate_of_resumed_session'):
            continue
        if since and (d.get('last_timestamp') or '') < since:
            continue
        d.setdefault('raw_tokens', {})
        d.setdefault('weighted_by_group', {})
        d.setdefault('by_side', {})
        d.setdefault('by_model', {})
        d.setdefault('tool_calls', {})
        d.setdefault('biggest_tool_results_est_tokens', [])
        d['role_label'] = d.get('role') or ('subagent' if (str(d.get('session_id', '')).startswith('agent-') or ('subagent' in d['by_side'] and 'main' not in d['by_side'])) else 'main')
        rows.append(d)
    return rows


def host_tz_offset(jobs_dir):
    """Seconds to add to this clock to get the job host's local time (runner.alive text vs its mtime)."""
    try:
        f = os.path.join(jobs_dir, 'runner.alive')
        with open(f, encoding='utf-8', errors='ignore') as fh:
            txt = fh.read().strip()
        m = re.search(r'(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})', txt)
        local = datetime.datetime.fromisoformat(m.group(1))
        mt = utc_naive(os.path.getmtime(f))
        return round((local - mt).total_seconds() / 900) * 900  # snap to 15-minute steps
    except Exception:
        return 0


def classify_kind(name):
    low = name.lower()
    if re.search(r'build|apk|aab|ipa|compile|publish|docker|image|bundle', low):
        return 'build'
    if re.search(r'test|unit|spec|coverage', low):
        return 'test'
    if re.search(r'emu|emulator|device|screen|shot|smoke|e2e|scen|vis|ui-|install|launch|cold|run', low):
        return 'device'
    if re.search(r'git|commit|merge|worktree|push|ledger', low):
        return 'git'
    return 'other'


def classify_role(name, prefixes):
    low = name.lower()
    if low.startswith('qa'):
        return 'qa'
    if low.startswith('dev') or any(low.startswith(p.lower()) for p in prefixes if p not in ('BUG', 'ADR')):
        return 'dev'
    if low.startswith('bug'):
        return 'dev'
    if re.match(r'(git|ops|usage|ledger|audit|env|sdk)', low):
        return 'ops'
    return 'other'


def task_from_name(name, prefixes):
    for p in prefixes:
        m = re.search(r'(?i)\b' + re.escape(p.lower()) + r'-?(\d{1,6})', name.lower())
        if m:
            return '%s-%s' % (p, m.group(1).zfill(3))
    return ''


def job_rows(jobs_dir, since, prefixes):
    rows = []
    if not os.path.isdir(jobs_dir):
        return rows
    off = host_tz_offset(jobs_dir)
    for f in glob.glob(os.path.join(jobs_dir, '*.log')):
        try:
            with open(f, encoding='utf-8', errors='ignore') as fh:
                t = fh.read()
        except Exception:
            continue
        m = re.search(r'\[runner\] exit=(\d+) elapsed=(\d+)s', t)
        if not m:
            continue
        st = re.search(r'\[runner\] job \S+ started (\S+)', t)
        started = st.group(1) if st else ''
        if since and started and started[:10] < since:
            continue
        name = os.path.basename(f)[:-4]
        wait = None
        try:
            ps1 = f[:-4] + '.ps1'
            if started and os.path.exists(ps1):
                sub = utc_naive(os.path.getmtime(ps1)) + datetime.timedelta(seconds=off)
                wait = max(0, int((datetime.datetime.fromisoformat(started) - sub).total_seconds()))
        except Exception:
            wait = None
        rows.append({'name': name, 'exit': int(m.group(1)), 'elapsed': int(m.group(2)), 'started': started,
                     'kind': classify_kind(name), 'role': classify_role(name, prefixes),
                     'task': task_from_name(name, prefixes), 'wait': wait})
    feed = os.path.join(jobs_dir, 'jobs.jsonl')
    if os.path.isfile(feed):
        with open(feed, encoding='utf-8', errors='ignore') as fh:
            for line in fh:
                try:
                    j = json.loads(line)
                except Exception:
                    continue
                if not isinstance(j, dict) or not j.get('name'):
                    continue
                started = str(j.get('started') or '')
                if since and started and started[:10] < since:
                    continue
                name = str(j['name'])
                rows.append({'name': name, 'exit': int(j.get('exit_code') or 0), 'elapsed': int(j.get('elapsed_seconds') or 0),
                             'started': started, 'kind': j.get('kind') or classify_kind(name),
                             'role': j.get('role') or classify_role(name, prefixes),
                             'task': j.get('task') or task_from_name(name, prefixes),
                             'wait': int(j['wait_seconds']) if j.get('wait_seconds') is not None else None})
    return rows


def overlap_minutes(rows):
    """Minutes during which a dev job and a qa job ran at the same time (shared build host)."""
    iv = []
    for r in rows:
        if not r['started']:
            continue
        try:
            s = datetime.datetime.fromisoformat(r['started'])
        except Exception:
            continue
        iv.append((s, s + datetime.timedelta(seconds=r['elapsed']), r['role']))
    total = datetime.timedelta()
    for i, (s1, e1, r1) in enumerate(iv):
        for s2, e2, r2 in iv[i + 1:]:
            if {r1, r2} == {'dev', 'qa'}:
                lo, hi = max(s1, s2), min(e1, e2)
                if hi > lo:
                    total += hi - lo
    return int(total.total_seconds() / 60)


def screenshots(sessions_dir):
    c = collections.Counter()
    if not os.path.isdir(sessions_dir):
        return {}
    for dp, dn, fn in os.walk(sessions_dir):
        dn[:] = [d for d in dn if d not in ('_usage', 'bin', 'obj', 'node_modules', '.git')]
        rel = os.path.relpath(dp, sessions_dir).split(os.sep)
        top = rel[0] if rel and rel[0] != '.' else '(root)'
        if top.upper().startswith('QA') and len(rel) > 1:
            top = top + '/' + rel[1]
        c[top] += sum(1 for f in fn if f.lower().endswith(IMAGE_EXT))
    return {k: v for k, v in c.items() if v}


# --------------------------------------------------------------------------- formatting
def fmt(n):
    return '{:,}'.format(int(n)).replace(',', ' ')


def pct(part, whole):
    return '%.0f%%' % (part / whole * 100) if whole else '-'


def delta_str(prev, cur):
    if prev is None:
        return 'n/a'
    if prev == 0:
        return '+inf' if cur else '0%'
    return '%+.0f%%' % ((cur - prev) / prev * 100)


# --------------------------------------------------------------------------- main
def main():
    ap = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    ap.add_argument('--root', default=os.getcwd())
    ap.add_argument('--since', default=None, help='YYYY-MM-DD; default = previous audit date or interval+1 days ago')
    ap.add_argument('--out', default=None, help='markdown output path (default <reports_path>/usage-audit-<date>.md)')
    ap.add_argument('--jobs', default=None, help='job log directory (default efficiency.jobs_log_path)')
    ap.add_argument('--task-prefixes', default=None)
    ap.add_argument('--top', type=int, default=10)
    ap.add_argument('--no-json', action='store_true', help='do not write the .json sidecar')
    a = ap.parse_args()

    root = os.path.abspath(a.root)
    cfg = load_config(root)
    eff = cfg.get('efficiency') or {}
    rules = dict(DEFAULT_RULES)
    rules.update({k: v for k, v in (eff.get('rules') or {}).items() if isinstance(v, (int, float))})
    interval = int(eff.get('audit_interval_days') or 2)
    ledger_dir = os.path.join(root, eff.get('ledger_path') or DEFAULT_LEDGER_PATH)
    jobs_dir = os.path.abspath(a.jobs) if a.jobs else os.path.join(root, eff.get('jobs_log_path') or DEFAULT_JOBS_PATH)
    reports_dir = os.path.join(root, eff.get('reports_path') or DEFAULT_REPORTS_PATH)
    sessions_dir = os.path.join(root, (cfg.get('paths') or {}).get('sessions_relative_path') or os.path.join('.it-department', 'sessions'))
    prefixes = discover_task_prefixes(root, cfg, a.task_prefixes)
    today = datetime.date.today()

    if a.since and not re.match(r'^\d{4}-\d{2}-\d{2}$', a.since):
        print('usage_report: --since must be YYYY-MM-DD', file=sys.stderr)
        return 2
    earlier = [(d, j) for d, j in previous_reports(reports_dir) if d < today.isoformat()]
    prev_date, prev_json = (earlier[0] if earlier else (None, None))
    since = a.since or prev_date or (today - datetime.timedelta(days=interval + 1)).isoformat()
    prev = None
    if prev_json:
        try:
            with open(prev_json, encoding='utf-8') as fh:
                prev = json.load(fh)
        except Exception:
            prev = None

    out = a.out or os.path.join(reports_dir, 'usage-audit-%s.md' % today.isoformat())
    L = load_ledger(ledger_dir, since)
    J = job_rows(jobs_dir, since, prefixes)
    S = screenshots(sessions_dir)
    w = L[0]['weights'] if L and L[0].get('weights') else {'input': 1, 'cache_write': 2, 'cache_read': 0.1, 'output': 5}

    lines = ['# Usage audit - %s (window since %s)' % (today.isoformat(), since), '',
             'Numbers below are computed by `usage_report.py` of the IT Department skill; weights: input x%g, cache write x%g, '
             'cache read x%g, output x%g.' % (w['input'], w['cache_write'], w['cache_read'], w['output']),
             'Sources: ledger sessions = %d (`%s`), jobs = %d (`%s`), previous audit = %s.' % (
                 len(L), os.path.relpath(ledger_dir, root), len(J), os.path.relpath(jobs_dir, root), prev_date or 'none'),
             'Task-id prefixes: %s.' % ', '.join(prefixes), '']
    totals = {'date': today.isoformat(), 'since': since, 'ledger_sessions': len(L)}

    # --- 1. tokens
    lines += ['## 1. Tokens (weighted) - by session', '']
    if L:
        tot = sum(d['weighted_total'] for d in L)
        lines += ['| Session | Role | Model | Start | Turns | Output | Images | Compactions | Weighted | Top groups | Tasks |',
                  '|---|---|---|---|---|---|---|---|---|---|---|']
        for d in sorted(L, key=lambda x: -x['weighted_total']):
            g = ', '.join('%s %s' % (k, pct(v, d['weighted_total'])) for k, v in list(d['weighted_by_group'].items())[:3])
            tasks = ', '.join(list(d.get('task_mentions') or {})[:4])
            model = ', '.join(sorted(k for k in d['by_model'] if k and not k.startswith('<')))[:40]
            lines.append('| %s | %s | %s | %s | %d | %s | %d | %d | %s | %s | %s |' % (
                d['session_id'][:8], d['role_label'], model, (d.get('first_timestamp') or '')[:16], d.get('turns', 0),
                fmt(d['raw_tokens'].get('output', 0)), d.get('images_read', 0), d.get('compactions_detected', 0),
                fmt(d['weighted_total']), g, tasks))
        role, model, group, tools = collections.Counter(), collections.Counter(), collections.Counter(), collections.Counter()
        out_tokens = think = images = compactions = 0
        for d in L:
            role[d['role_label']] += d['weighted_total']
            for k, v in d['by_model'].items():
                if str(k).startswith('<'):
                    continue
                model[k] += v.get('weighted', 0)
            for k, v in d['weighted_by_group'].items():
                group[k] += v
            for k, v in d['tool_calls'].items():
                tools[k] += v
            out_tokens += d['raw_tokens'].get('output', 0)
            think += d['raw_tokens'].get('thinking', 0)
            images += d.get('images_read', 0)
            compactions += d.get('compactions_detected', 0)
        lines += ['', '**Total weighted: %s** (output tokens %s, of which thinking %s; images read %d; compactions %d)' % (
            fmt(tot), fmt(out_tokens), fmt(think), images, compactions), '',
            '| By role | Weighted | % |', '|---|---|---|'] + ['| %s | %s | %s |' % (k, fmt(v), pct(v, tot)) for k, v in role.most_common()]
        lines += ['', '| By model | Weighted | % |', '|---|---|---|'] + ['| %s | %s | %s |' % (k, fmt(v), pct(v, tot)) for k, v in model.most_common()]
        lines += ['', '| By content group | Weighted | % |', '|---|---|---|'] + ['| %s | %s | %s |' % (k, fmt(v), pct(v, tot)) for k, v in group.most_common(a.top)]
        lines += ['', 'Most called tools: ' + ', '.join('%s x%d' % (k, v) for k, v in tools.most_common(a.top)), '']
        big = sorted(((b['est_tokens'], b['tool'], d['session_id'][:8]) for d in L for b in d['biggest_tool_results_est_tokens']), reverse=True)
        over = [b for b in big if b[0] > rules['R4_tool_result_tokens_max']]
        lines += ['Largest single tool results (est. tokens, re-read on every later turn): ' +
                  '; '.join('%s %s (%s)' % (fmt(s), t, sid) for s, t, sid in big[:a.top]), '',
                  'Tool results above R4 limit (%s tokens): %d of the %d largest recorded.' % (fmt(rules['R4_tool_result_tokens_max']), len(over), len(big)), '']
        totals.update({'weighted_total': int(tot), 'output_tokens': int(out_tokens), 'thinking_tokens': int(think), 'images_read': images,
                       'compactions': compactions, 'tool_results_over_r4': len(over),
                       'by_role': {k: int(v) for k, v in role.items()}, 'by_group': {k: int(v) for k, v in group.most_common(a.top)}})
    else:
        lines += ['_No ledger files in the window. Each working session must run `usage_ledger.py` before it ends '
                  '(workflows/efficiency-and-usage-audit.md), or the audit must rebuild the ledger from the host transcripts._', '']
        totals.update({'weighted_total': 0, 'output_tokens': 0, 'thinking_tokens': 0, 'images_read': 0, 'compactions': 0, 'tool_results_over_r4': 0})

    # --- 2. machine time
    lines += ['## 2. Machine time (build / test / device jobs)', '']
    builds = [j for j in J if j['kind'] == 'build']
    waited = [j for j in J if (j['wait'] or 0) > rules['R5_queue_wait_minutes_max'] * 60]
    reverify = [j for j in J if j['role'] == 'qa' and re.search(r'(^|[-_])re|recheck|retest|verify', j['name'].lower())]
    if J:
        th = sum(j['elapsed'] for j in J) / 3600
        by = collections.defaultdict(lambda: [0, 0, 0])
        for j in J:
            k = '%s/%s' % (j['role'], j['kind'])
            by[k][0] += 1
            by[k][1] += j['elapsed']
            by[k][2] += (j['exit'] != 0)
        lines += ['Jobs: %d, total %.1f h, failed: %d.' % (len(J), th, sum(1 for j in J if j['exit'])), '',
                  '| Role/kind | Jobs | Hours | Failed |', '|---|---|---|---|']
        lines += ['| %s | %d | %.2f | %d |' % (k, v[0], v[1] / 3600, v[2]) for k, v in sorted(by.items(), key=lambda x: -x[1][1])]
        bt = collections.defaultdict(lambda: [0, 0, 0])
        for j in J:
            if j['task']:
                bt[j['task']][0] += 1
                bt[j['task']][1] += j['elapsed']
                bt[j['task']][2] += (j['kind'] == 'build')
        lines += ['', '| Task | Jobs | Hours | Build jobs |', '|---|---|---|---|'] + [
            '| %s | %d | %.2f | %d |' % (k, v[0], v[1] / 3600, v[2]) for k, v in sorted(bt.items(), key=lambda x: -x[1][1])[:12]]
        longest = sorted(J, key=lambda j: -j['elapsed'])[:8]
        lines += ['', 'Longest jobs: ' + '; '.join('%s %ds exit=%d' % (j['name'], j['elapsed'], j['exit']) for j in longest), '',
                  'Build jobs: %d, %.0f min total. QA re-verification jobs: %d, %.0f min. Queue wait total: %.0f min; '
                  'jobs that waited > %g min: %d. Dev/QA overlap on the shared host: %d min.' % (
                      len(builds), sum(j['elapsed'] for j in builds) / 60, len(reverify), sum(j['elapsed'] for j in reverify) / 60,
                      sum((j['wait'] or 0) for j in J) / 60, rules['R5_queue_wait_minutes_max'], len(waited), overlap_minutes(J)), '']
    else:
        lines += ['_No job logs found in `%s` (optional: see the machine-time log contract in the workflow guide)._' % os.path.relpath(jobs_dir, root), '']
    totals.update({'jobs': len(J), 'jobs_hours': round(sum(j['elapsed'] for j in J) / 3600, 2), 'jobs_failed': sum(1 for j in J if j['exit']),
                   'build_jobs': len(builds), 'build_minutes': round(sum(j['elapsed'] for j in builds) / 60),
                   'queue_wait_minutes': round(sum((j['wait'] or 0) for j in J) / 60), 'jobs_waited_over_max': len(waited),
                   'overlap_minutes': overlap_minutes(J) if J else 0})

    # --- 3. screenshots
    lines += ['## 3. Screenshots per session folder (R2: <= %d per scenario, %.0f%% scale before vision reads)' % (
        rules['R2_screenshots_per_scenario_max'], rules['R2_screenshot_scale'] * 100), '']
    if S:
        lines += ['| Folder | Screenshots |', '|---|---|'] + ['| %s | %d |' % (k, v) for k, v in sorted(S.items(), key=lambda x: -x[1])[:12]] + ['']
    else:
        lines += ['_No screenshots under `%s`._' % os.path.relpath(sessions_dir, root), '']
    totals['screenshots_total'] = sum(S.values())

    # --- 4. rule indicators
    builds_per_task_day = collections.Counter((j['task'], j['started'][:10]) for j in builds if j['task'])
    r1_over = sorted(((k, v) for k, v in builds_per_task_day.items() if v > rules['R1_builds_per_fix_round_max']), key=lambda x: -x[1])
    r2_folders = [(k, v) for k, v in S.items() if v > rules['R2_screenshots_per_scenario_max']]
    r2_sessions = [d for d in L if d.get('images_read', 0) > rules['R2_screenshots_per_scenario_max']]
    r4_over = totals.get('tool_results_over_r4', 0)

    def status(flag, available=True):
        return 'CHECK' if (available and flag) else ('OK' if available else 'n/a')

    lines += ['## 4. Rule indicators', '',
              '| Rule | Indicator | Value | Limit | Status |', '|---|---|---|---|---|',
              '| R1 | task/day pairs with more build jobs than allowed per fix round | %d%s | %g | %s |' % (
                  len(r1_over), (' (' + ', '.join('%s %s: %d' % (k[0], k[1], v) for k, v in r1_over[:5]) + ')') if r1_over else '',
                  rules['R1_builds_per_fix_round_max'], status(bool(r1_over), bool(J))),
              '| R2 | session folders above the screenshot budget | %d%s | %g | %s |' % (
                  len(r2_folders), (' (' + ', '.join('%s: %d' % kv for kv in r2_folders[:5]) + ')') if r2_folders else '',
                  rules['R2_screenshots_per_scenario_max'], status(bool(r2_folders), bool(S))),
              '| R2 | sessions that read more images than the budget | %d%s | %g | %s |' % (
                  len(r2_sessions), (' (' + ', '.join('%s: %d' % (d['session_id'][:8], d['images_read']) for d in r2_sessions[:5]) + ')') if r2_sessions else '',
                  rules['R2_screenshots_per_scenario_max'], status(bool(r2_sessions), bool(L))),
              '| R3 | QA re-verification jobs / minutes | %d / %.0f | targeted only | %s |' % (
                  len(reverify), sum(j['elapsed'] for j in reverify) / 60, 'review' if reverify else status(False, bool(J))),
              '| R4 | tool results above the token limit (lower bound) | %d | %s | %s |' % (
                  r4_over, fmt(rules['R4_tool_result_tokens_max']), status(r4_over > 0, bool(L))),
              '| R4 | context compactions in the window | %d | 0 | %s |' % (totals['compactions'], status(totals['compactions'] > 0, bool(L))),
              '| R5 | jobs that waited longer than the queue limit | %d | %g min | %s |' % (
                  len(waited), rules['R5_queue_wait_minutes_max'], status(bool(waited), bool(J))),
              '| R5 | dev/QA overlap minutes on the shared host | %d | 0 | %s |' % (totals['overlap_minutes'], status(totals['overlap_minutes'] > 0, bool(J))),
              '']

    # --- 5. delta
    lines += ['## 5. Delta vs previous audit (%s)' % (prev_date or 'none'), '']
    if prev:
        lines += ['| Metric | Previous | Current | Delta |', '|---|---|---|---|']
        for key, label in (('weighted_total', 'Weighted tokens'), ('output_tokens', 'Output tokens'), ('ledger_sessions', 'Ledger sessions'),
                           ('images_read', 'Images read'), ('compactions', 'Compactions'), ('tool_results_over_r4', 'Tool results over R4'),
                           ('jobs', 'Jobs'), ('jobs_hours', 'Job hours'), ('jobs_failed', 'Failed jobs'), ('build_jobs', 'Build jobs'),
                           ('queue_wait_minutes', 'Queue wait minutes'), ('screenshots_total', 'Screenshots on disk')):
            p, c = prev.get(key), totals.get(key, 0)
            lines.append('| %s | %s | %s | %s |' % (label, fmt(p) if isinstance(p, (int, float)) else 'n/a', fmt(c) if isinstance(c, (int, float)) else c,
                                                   delta_str(p if isinstance(p, (int, float)) else None, c if isinstance(c, (int, float)) else 0)))
        lines.append('')
    else:
        lines += ['_No previous audit sidecar (`usage-audit-<date>.json`) found - this report becomes the baseline._', '']

    # --- 6/7. auditor sections
    lines += ['## 6. Checks for the auditor (fill in)', '',
              '- R1 Builds per fix round - which tasks rebuilt the artifact more than once per round? Name the jobs.',
              '- R2 Screenshots - folders/sessions above budget; were images downscaled before vision reads?',
              '- R3 Targeted re-verification - did QA re-run full scenarios after fix rounds instead of fixed defects + one smoke path?',
              '- R4 Log discipline - sessions whose `files`/`device` groups dominate: which tool results were largest, which logs were pasted?',
              '- R5 Shared host scheduling - name the colliding dev/QA jobs and the jobs that waited.',
              '- Top-3 token sources and top-3 time consumers, with numbers from sections 1-3.',
              '- Delta vs previous audit: better / worse / same, with numbers from section 5.', '',
              '## 7. Proposals for the CTO (max 5, auditor fills in)', '',
              '| # | Change | Evidence (numbers) | Expected saving | Where applied | Risk | Decision |', '|---|---|---|---|---|---|---|',
              '| 1 |  |  |  |  |  |  |', '']
    if not L:
        lines += ['> First proposal must name the sessions that did not export their usage (no ledger files in the window).', '']
    if prev_date:  # proposals of the previous report still waiting for a CTO decision (Decision column empty)
        counts = count_proposals(os.path.join(reports_dir, 'usage-audit-%s.md' % prev_date))
        if counts is not None:
            totals['proposals_total'], totals['proposals_pending'] = counts

    os.makedirs(os.path.dirname(out) or '.', exist_ok=True)
    with open(out, 'w', encoding='utf-8') as fh:
        fh.write('\n'.join(lines) + '\n')
    if not a.no_json:
        sidecar = os.path.splitext(out)[0] + '.json'
        with open(sidecar, 'w', encoding='utf-8') as fh:
            json.dump(totals, fh, ensure_ascii=False, indent=1)
    print(out)
    print('sessions=%d weighted=%s jobs=%d hours=%.1f screenshots=%d since=%s' % (
        len(L), fmt(totals['weighted_total']), len(J), totals['jobs_hours'], totals['screenshots_total'], since))
    return 0


if __name__ == '__main__':
    sys.exit(main())
