#!/usr/bin/env python3
"""apply_transitions.py - apply the pending transition requests of agent sessions to the vault notes.

Part of the IT Department skill (references/contracts-and-lifecycle.md sections 1 and 4,
workflows/session-protocol.md). Agents never move notes themselves: each one writes
<sessions>/<task-id>/<agent-role>/<session-id>/transition-request.json next to its evidence. The
coordinator (the lock holder) runs this script; every request without an "applied_at" field is checked
against its note and the canonical state machine and then applied: the note is moved to its status
folder, its frontmatter is updated, a line is appended to its "## Transition Log" section, "applied_at" is
written into the request, and finally the dashboard is regenerated with dashboard_sync.py.

Usage:
  python3 apply_transitions.py [--root PROJECT_ROOT] [--dry-run] [--no-sync]

  --root      project root holding .it-department/config.json (default: current directory)
  --dry-run   validate and report only; nothing is written (the dashboard sync is skipped as well)
  --no-sync   do not run dashboard_sync.py afterwards

Request fields: task_id, from_status, to_status, agent_role, evidence_file (relative to the request's
directory), timestamp (ISO 8601) - all required; candidate_sha, qa_status, release_version,
release_commit (and archived_at) when they apply.
Checks, in this order: JSON shape; the note exists (task under 01-Tasks/**, bug under 02-Bugs/); from_status
equals the note's status - and, for tasks, its folder (else "stale"); to_status is a legal next status
(tasks: Backlog > In-Analysis > Ready-For-Dev > In-Development > Code-Review > QA-Testing > Ready-For-Release
> Archived, plus Code-Review > In-Development and QA-Testing > In-Development; bugs: Open > In-Development >
Code-Review > Retesting > Closed > Archived, plus Retesting > In-Development); the evidence file exists;
Ready-For-Dev needs content_review_intake approved or not-applicable when content_review is required;
Ready-For-Release needs qa_status passed or a candidate_sha in the request; Archived needs release_version
and release_commit in the request.
Applied: task notes move to 01-Tasks/<to_status>/ (Archived: 04-Archive/Completed-Tasks/), bug notes stay
in 02-Bugs/ (Archived: 04-Archive/Resolved-Bugs/); frontmatter status and date_updated (today) are
rewritten, plus release_version, release_commit, archived_at for Archived and candidate_sha / qa_status
when the request carries them; the log line is
  - {timestamp} {from} -> {to} by {agent_role} (evidence: {path relative to the project root})
Requests are processed in timestamp order, so consecutive requests for one note apply in one run. A
refused request keeps no "applied_at" and is listed with its reason; the valid ones are still applied.

Exit codes: 0 ok (or nothing pending), 1 at least one request refused, 2 bad arguments (no vault at the
resolved path). Requires Python 3.8+, standard library only.
"""
import argparse
import datetime
import json
import os
import re
import stat
import sys
import tempfile

ARROW = '\N{RIGHTWARDS ARROW}'
REQUEST_NAME = 'transition-request.json'
DEFAULT_SESSIONS_PATH = os.path.join('.it-department', 'sessions')
REQUIRED = ('task_id', 'from_status', 'to_status', 'agent_role', 'evidence_file', 'timestamp')
TASK_FLOW = {
    'Backlog': ('In-Analysis',),
    'In-Analysis': ('Ready-For-Dev',),
    'Ready-For-Dev': ('In-Development',),
    'In-Development': ('Code-Review',),
    'Code-Review': ('QA-Testing', 'In-Development'),
    'QA-Testing': ('Ready-For-Release', 'In-Development'),
    'Ready-For-Release': ('Archived',),
    'Archived': (),
}
BUG_FLOW = {
    'Open': ('In-Development',),
    'In-Development': ('Code-Review',),
    'Code-Review': ('Retesting',),
    'Retesting': ('Closed', 'In-Development'),
    'Closed': ('Archived',),
    'Archived': (),
}
TASK_FOLDERS = tuple(s for s in TASK_FLOW if s != 'Archived')
SKIP_DIRS = {'.git', 'node_modules', 'bin', 'obj', '.store', '__pycache__'}
QUOTED_KEYS = ('date_updated', 'archived_at', 'release_version', 'release_commit', 'candidate_sha')
LOG_HEADING_RE = re.compile(r'^##[ \t]+(?:\d+(?:\.\d+)*\.?[ \t]+)?Transition Log[ \t]*$', re.I)
LOG_PLACEHOLDER = '{YYYY-MM-DDTHH:MM:SSZ}'


def _today():
    """Local date (patched by the tests)."""
    return datetime.date.today()


def _utcnow():
    return datetime.datetime.now(datetime.timezone.utc)


# --------------------------------------------------------------------------- frontmatter (stdlib, no PyYAML)
KEY_RE = re.compile(r'^([A-Za-z0-9_][A-Za-z0-9_.-]*)[ \t]*:(?:[ \t]+(.*)|[ \t]*)$')
NESTED_RE = re.compile(r'^("(?:[^"\\]|\\.)*"|\'(?:[^\']|\'\')*\'|[^:#\s][^:]*?)[ \t]*:(?:[ \t]+(.*)|[ \t]*)$')
INT_RE = re.compile(r'^[-+]?(?:0|[1-9][0-9]*)$')


def comment_start(raw):
    """Index of a YAML comment (' #' outside quotes) in a value, or -1."""
    quote, i, n = None, 0, len(raw)
    while i < n:
        ch = raw[i]
        if quote:
            if quote == '"' and ch == '\\':
                i += 2
                continue
            if ch == quote:
                if quote == "'" and i + 1 < n and raw[i + 1] == "'":
                    i += 2
                    continue
                quote = None
        elif ch in '"\'':
            before = raw[:i].rstrip()
            if not before or before[-1] in '[{,:':
                quote = ch
        elif ch == '#' and (i == 0 or raw[i - 1] in ' \t'):
            return i
        i += 1
    return -1


def strip_comment(raw):
    i = comment_start(raw)
    return (raw if i < 0 else raw[:i]).strip()


def split_items(inner):
    """Split the inside of an inline list or map on top-level commas (quotes and brackets respected)."""
    items, buf, depth, quote, i = [], '', 0, None, 0
    while i < len(inner):
        ch = inner[i]
        if quote:
            buf += ch
            if quote == '"' and ch == '\\' and i + 1 < len(inner):
                buf += inner[i + 1]
                i += 2
                continue
            if ch == quote:
                quote = None
        elif ch in '"\'' and (not buf.strip() or buf.rstrip().endswith(':')):
            quote = ch
            buf += ch
        elif ch in '[{':
            depth += 1
            buf += ch
        elif ch in ']}':
            depth -= 1
            buf += ch
        elif ch == ',' and depth == 0:
            items.append(buf.strip())
            buf = ''
        else:
            buf += ch
        i += 1
    items.append(buf.strip())
    return [x for x in items if x]


def unquote(v):
    if len(v) >= 2 and v[0] == v[-1] == '"':
        return re.sub(r'\\(["\\])', r'\1', v[1:-1])
    if len(v) >= 2 and v[0] == v[-1] == "'":
        return v[1:-1].replace("''", "'")
    return v


def parse_scalar(v):
    """Quoted string, true/false, null, integer, inline list [a, b]; anything else stays a raw string."""
    v = v.strip()
    if not v:
        return ''
    if len(v) >= 2 and v[0] == v[-1] and v[0] in '"\'':
        return unquote(v)
    if v in ('true', 'True', 'TRUE'):
        return True
    if v in ('false', 'False', 'FALSE'):
        return False
    if v in ('null', 'Null', 'NULL', '~'):
        return None
    if INT_RE.match(v):
        return int(v)
    if v[0] == '[' and v[-1] == ']':
        return [parse_scalar(x) for x in split_items(v[1:-1])]
    return v


def frontmatter_end(lines):
    if not lines or lines[0].strip() != '---':
        return None
    return next((i for i in range(1, len(lines)) if lines[i].rstrip() == '---'), None)


def parse_frontmatter(text):
    """(dict, body) for text that starts with a '---' block, (None, text) otherwise."""
    lines = text.split('\n')
    end = frontmatter_end(lines)
    if end is None:
        return None, text
    fm, i = {}, 1
    while i < end:
        m = KEY_RE.match(lines[i])
        i += 1
        if not m:
            continue
        key, raw = m.group(1), strip_comment(m.group(2) or '')
        if raw:
            fm[key] = parse_scalar(raw)
            continue
        items, nested = [], {}
        while i < end:
            line = lines[i]
            s = line.strip()
            if s and not s.startswith('#'):
                if s == '-' or s.startswith('- '):
                    items.append(parse_scalar(strip_comment(s[1:])))
                elif line[:1] in ' \t':
                    nm = NESTED_RE.match(s)
                    if nm:
                        nested[unquote(nm.group(1).strip())] = parse_scalar(strip_comment(nm.group(2) or ''))
                else:
                    break
            i += 1
        fm[key] = items if items else (nested if nested else '')
    return fm, '\n'.join(lines[end + 1:])


# --------------------------------------------------------------------------- note editing
def yaml_value(key, value):
    s = str(value)
    if key in QUOTED_KEYS or not re.match(r'^[A-Za-z0-9][A-Za-z0-9._/-]*$', s) or \
            s.lower() in ('true', 'false', 'null', 'yes', 'no', 'on', 'off'):
        return '"%s"' % s.replace('\\', '\\\\').replace('"', '\\"')
    return s


def set_frontmatter(text, updates):
    """Rewrite (or add) top-level frontmatter keys, keeping every other line and the inline comments."""
    lines = text.split('\n')
    end = frontmatter_end(lines)
    if end is None:
        return '\n'.join(['---'] + ['%s: %s' % (k, yaml_value(k, v)) for k, v in updates] + ['---'] + lines)
    for key, value in updates:
        rx = re.compile(r'^%s[ \t]*:(.*)$' % re.escape(key))
        for i in range(1, end):
            m = rx.match(lines[i])
            if m:
                c = comment_start(m.group(1))
                lines[i] = '%s: %s%s' % (key, yaml_value(key, value), (' ' + m.group(1)[c:].strip()) if c >= 0 else '')
                break
        else:
            lines.insert(end, '%s: %s' % (key, yaml_value(key, value)))
            end += 1
    return '\n'.join(lines)


def append_log(text, line):
    """Append a line to the '## Transition Log' section (created at the end when missing); a template
    placeholder line ('- {YYYY-MM-DDTHH:MM:SSZ} ...') is replaced instead."""
    lines = text.split('\n')
    end = frontmatter_end(lines)
    first = end + 1 if end is not None else 0
    heading, fence = None, False
    for i in range(first, len(lines)):
        if lines[i].lstrip().startswith(('```', '~~~')):
            fence = not fence
        elif not fence and LOG_HEADING_RE.match(lines[i].rstrip()):
            heading = i
            break
    if heading is None:
        body = list(lines)
        while body and not body[-1].strip():
            body.pop()
        return '\n'.join(body + ['', '## Transition Log', '', line]) + '\n'
    stop, fence = len(lines), False
    for i in range(heading + 1, len(lines)):
        if lines[i].lstrip().startswith(('```', '~~~')):
            fence = not fence
        elif not fence and re.match(r'^#{1,2}[ \t]', lines[i]):
            stop = i
            break
    for i in range(heading + 1, stop):
        if lines[i].lstrip().startswith('- ') and LOG_PLACEHOLDER in lines[i]:
            lines[i] = line
            return '\n'.join(lines)
    k = stop
    while k - 1 > heading and not lines[k - 1].strip():
        k -= 1
    new = ([''] if k == heading + 1 else []) + [line]
    if stop < len(lines) and k == stop:
        new.append('')
    lines[k:k] = new
    return '\n'.join(lines)


# --------------------------------------------------------------------------- files
def load_config(root):
    try:
        with open(os.path.join(root, '.it-department', 'config.json'), encoding='utf-8-sig') as fh:
            cfg = json.load(fh)
        return cfg if isinstance(cfg, dict) else {}
    except Exception:
        return {}


def read_note(path):
    """-> (text with LF endings and no BOM, style to restore on write)."""
    with open(path, 'rb') as fh:
        text = fh.read().decode('utf-8', errors='replace')
    bom = text.startswith('\N{ZERO WIDTH NO-BREAK SPACE}')
    if bom:
        text = text[1:]
    return text.replace('\r\n', '\n'), {'bom': bom, 'crlf': '\r\n' in text}


def atomic_write(path, data):
    """Write bytes through a temp file + rename, keeping the mode of an existing file."""
    fd, tmp = tempfile.mkstemp(prefix='.transition-', suffix='.tmp', dir=os.path.dirname(path) or '.')
    try:
        with os.fdopen(fd, 'wb') as fh:
            fh.write(data)
        if os.path.exists(path):
            os.chmod(tmp, stat.S_IMODE(os.stat(path).st_mode))
        else:
            mask = os.umask(0)
            os.umask(mask)
            os.chmod(tmp, 0o666 & ~mask)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.remove(tmp)
        except OSError:
            pass
        raise


def write_note(path, text, style):
    if style.get('crlf'):
        text = text.replace('\n', '\r\n')
    atomic_write(path, (('\N{ZERO WIDTH NO-BREAK SPACE}' if style.get('bom') else '') + text).encode('utf-8'))


def walk_md(top):
    out = []
    if not os.path.isdir(top):
        return out
    for dp, dn, fn in os.walk(top):
        dn[:] = sorted(d for d in dn if not d.startswith('.'))
        out += [os.path.join(dp, f) for f in sorted(fn) if f.lower().endswith('.md') and not f.startswith('.')]
    return out


def fwd(path, base):
    try:
        r = os.path.relpath(path, base)
    except ValueError:
        r = os.path.abspath(path)
    return r.replace(os.sep, '/')


def text_of(value):
    if value is None:
        return ''
    if isinstance(value, bool):
        return 'true' if value else 'false'
    return str(value).strip()


def canon(value, choices):
    s = text_of(value).lower()
    return next((c for c in choices if c.lower() == s), None)


def parse_ts(value):
    if not isinstance(value, str) or not value.strip():
        return None
    s = value.strip()
    if s[-1:] in ('Z', 'z'):
        s = s[:-1] + '+00:00'
    try:
        dt = datetime.datetime.fromisoformat(s)
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=datetime.timezone.utc)


# --------------------------------------------------------------------------- requests and notes
def collect(sessions):
    """-> (pending [(sort key, path, request)], invalid [(path, reason)])."""
    pending, invalid = [], []
    for dp, dn, fn in os.walk(sessions) if os.path.isdir(sessions) else []:
        dn[:] = sorted(d for d in dn if d not in SKIP_DIRS)
        for f in sorted(fn):
            if f.lower() != REQUEST_NAME:
                continue
            path = os.path.join(dp, f)
            try:
                with open(path, encoding='utf-8-sig') as fh:
                    req = json.load(fh)
            except (OSError, ValueError) as e:
                invalid.append((path, 'bad request: invalid JSON (%s)' % e))
                continue
            if not isinstance(req, dict):
                invalid.append((path, 'bad request: not a JSON object'))
                continue
            if 'applied_at' in req:
                continue
            ts = parse_ts(req.get('timestamp'))
            pending.append(((0, ts.timestamp()) if ts else (1, 0.0), path, req))
    pending.sort(key=lambda x: (x[0], x[1]))
    return pending, invalid


def load_notes(vault):
    """Active task and bug notes (with their parsed frontmatter) plus the stems of archived notes."""
    notes = []
    for kind, top in (('task', os.path.join(vault, '01-Tasks')), ('bug', os.path.join(vault, '02-Bugs'))):
        for path in walk_md(top):
            try:
                fm = parse_frontmatter(read_note(path)[0])[0] or {}
            except OSError:
                fm = {}
            stem = os.path.splitext(os.path.basename(path))[0]
            parts = fwd(path, top).split('/')
            notes.append({'kind': kind, 'path': path, 'stem': stem, 'id': text_of(fm.get('id')) or stem, 'fm': fm,
                          'folder': canon(parts[0], TASK_FOLDERS) if kind == 'task' and len(parts) > 1 else None})
    archived = {os.path.splitext(os.path.basename(p))[0].lower() for p in walk_md(os.path.join(vault, '04-Archive'))}
    return notes, archived


def find_note(notes, task_id):
    low = task_id.lower()
    for match in (lambda n: n['stem'] == task_id, lambda n: n['stem'].lower() == low, lambda n: n['id'].lower() == low):
        hits = [n for n in notes if match(n)]
        if hits:
            return hits[0]
    return None


def current_status(note, root):
    """-> (canonical status, None) or (None, why the note cannot be transitioned)."""
    if note.get('archived'):
        return None, '%s is already archived' % note['stem']
    flow = TASK_FLOW if note['kind'] == 'task' else BUG_FLOW
    raw = note['fm'].get('status')
    status = canon(raw, tuple(flow))
    if note['kind'] == 'task':
        if note['folder'] is None:
            return None, '%s is not in a status folder of 01-Tasks/' % fwd(note['path'], root)
        if text_of(raw) and status != note['folder']:
            return None, '%s has status "%s" but lives in folder %s' % (note['stem'], text_of(raw), note['folder'])
        return note['folder'], None
    if status is None:
        return None, '%s has no valid bug status ("%s")' % (note['stem'], text_of(raw))
    return status, None


def check(req, req_path, notes, archived, root, vault):
    """-> (True, plan) or (False, reason)."""
    bad = [k for k in REQUIRED if not isinstance(req.get(k), str) or not req[k].strip()]
    if bad:
        return False, 'bad request: missing or empty field(s) %s' % ', '.join(bad)
    if parse_ts(req['timestamp']) is None:
        return False, 'bad request: timestamp "%s" is not ISO 8601' % req['timestamp'].strip()
    tid = req['task_id'].strip()
    note = find_note(notes, tid)
    if note is None:
        if tid.lower() in archived:
            return False, 'stale: %s is already archived' % tid
        return False, 'unknown note: no task under 01-Tasks/ and no bug under 02-Bugs/ named %s' % tid
    flow = TASK_FLOW if note['kind'] == 'task' else BUG_FLOW
    current, problem = current_status(note, root)
    if problem:
        return False, 'stale: ' + problem
    frm, to = canon(req['from_status'], tuple(flow)), canon(req['to_status'], tuple(flow))
    if frm is None:
        return False, 'illegal transition: "%s" is not a %s status' % (req['from_status'].strip(), note['kind'])
    if frm != current:
        return False, 'stale: %s is %s, the request is from %s' % (tid, current, frm)
    if to is None or to not in flow[frm]:
        return False, 'illegal transition: %s %s %s (allowed from %s: %s)' % (
            frm, ARROW, req['to_status'].strip(), frm, ', '.join(flow[frm]) or 'none')
    evidence = os.path.normpath(os.path.join(os.path.dirname(req_path), req['evidence_file'].strip()))
    if not os.path.exists(evidence):
        return False, 'missing evidence: %s' % fwd(evidence, root)
    fm = note['fm']
    if note['kind'] == 'task' and to == 'Ready-For-Dev' and text_of(fm.get('content_review')).lower() == 'required':
        intake = text_of(fm.get('content_review_intake')).lower()
        if intake not in ('approved', 'not-applicable'):
            return False, 'missing intake verdict: content_review_intake is %s (approved or not-applicable needed)' % (intake or 'empty')
    if note['kind'] == 'task' and to == 'Ready-For-Release':
        qa = text_of(req.get('qa_status') or fm.get('qa_status')).lower()
        if qa != 'passed' and not text_of(req.get('candidate_sha')):
            return False, 'missing QA verdict: qa_status is %s and the request has no candidate_sha' % (qa or 'empty')
    if to == 'Archived':
        miss = [k for k in ('release_version', 'release_commit') if not text_of(req.get(k))]
        if miss:
            return False, 'missing release data: %s required for Archived' % ' and '.join(miss)
    name = os.path.basename(note['path'])
    if to == 'Archived':
        dest = os.path.join(vault, '04-Archive', 'Completed-Tasks' if note['kind'] == 'task' else 'Resolved-Bugs', name)
    else:
        dest = os.path.join(vault, '01-Tasks', to, name) if note['kind'] == 'task' else note['path']
    if os.path.normcase(dest) != os.path.normcase(note['path']) and os.path.exists(dest):
        return False, 'target exists: %s' % fwd(dest, root)
    return True, {'note': note, 'from': frm, 'to': to, 'dest': dest, 'evidence': fwd(evidence, root)}


def changes(plan, req, today):
    """-> (frontmatter updates, Transition Log line)."""
    updates = [('status', plan['to']), ('date_updated', today)]
    if plan['to'] == 'Archived':
        updates += [('release_version', text_of(req['release_version'])), ('release_commit', text_of(req['release_commit'])),
                    ('archived_at', text_of(req.get('archived_at')) or today)]
    updates += [(k, text_of(req[k])) for k in ('candidate_sha', 'qa_status') if text_of(req.get(k))]
    line = '- %s %s %s %s by %s (evidence: %s)' % (req['timestamp'].strip(), plan['from'], ARROW, plan['to'],
                                                    req['agent_role'].strip(), plan['evidence'])
    return updates, line


def apply(plan, req, req_path, updates, line):
    note = plan['note']
    text, style = read_note(note['path'])
    write_note(note['path'], append_log(set_frontmatter(text, updates), line), style)
    if os.path.normcase(plan['dest']) != os.path.normcase(note['path']):
        os.makedirs(os.path.dirname(plan['dest']), exist_ok=True)
        os.replace(note['path'], plan['dest'])
    done = dict(req)
    done['applied_at'] = _utcnow().strftime('%Y-%m-%dT%H:%M:%SZ')
    atomic_write(req_path, (json.dumps(done, ensure_ascii=False, indent=2) + '\n').encode('utf-8'))


def run_sync(root):
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    try:
        import dashboard_sync
    except ImportError as e:
        print('apply_transitions: cannot import dashboard_sync.py from %s (%s); dashboard not regenerated' % (
            os.path.dirname(os.path.abspath(__file__)), e), file=sys.stderr)
        return 1
    return dashboard_sync.sync(root)


# --------------------------------------------------------------------------- main
def main(argv=None):
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(errors='replace')
        except Exception:
            pass
    ap = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    ap.add_argument('--root', default=os.getcwd(), help='project root (holds .it-department/config.json)')
    ap.add_argument('--dry-run', action='store_true', help='validate and report only; write nothing')
    ap.add_argument('--no-sync', action='store_true', help='do not regenerate the dashboard afterwards')
    a = ap.parse_args(argv)

    root = os.path.abspath(a.root)
    cfg = load_config(root)
    paths = cfg.get('paths') if isinstance(cfg.get('paths'), dict) else {}
    vault = os.path.join(root, str(paths.get('vault_relative_path') or 'vault'))
    sessions = os.path.join(root, str(paths.get('sessions_relative_path') or DEFAULT_SESSIONS_PATH))
    if not os.path.isdir(vault):
        print('apply_transitions: vault not found: %s (check --root and paths.vault_relative_path)' % vault, file=sys.stderr)
        return 2
    pending, invalid = collect(sessions)
    notes, archived = load_notes(vault)
    today = _today().isoformat()
    applied, refused = 0, 0
    for path, reason in invalid:
        refused += 1
        print('refused      %s  [%s]' % (reason, fwd(path, root)))
    for _key, path, req in pending:
        tid = text_of(req.get('task_id')) or '?'
        ok, plan = check(req, path, notes, archived, root, vault)
        if not ok:
            refused += 1
            print('refused      %s: %s  [%s]' % (tid, plan, fwd(path, root)))
            continue
        updates, line = changes(plan, req, today)
        if not a.dry_run:
            try:
                apply(plan, req, path, updates, line)
            except OSError as e:
                refused += 1
                print('refused      %s: write failed (%s)  [%s]' % (tid, e, fwd(path, root)))
                continue
        note = plan['note']
        note['fm'].update(dict(updates))
        note['path'] = plan['dest']
        if note['kind'] == 'task':
            note['folder'] = plan['to'] if plan['to'] != 'Archived' else None
        note['archived'] = plan['to'] == 'Archived'
        applied += 1
        print('%s %s: %s %s %s -> %s  [%s]' % ('would apply ' if a.dry_run else 'applied     ', tid, plan['from'], ARROW,
                                               plan['to'], fwd(plan['dest'], root), fwd(path, root)))
    if a.dry_run:
        print('transitions (dry run): %d would be applied, %d refused; nothing written' % (applied, refused))
    else:
        print('transitions: %d applied, %d refused%s' % (applied, refused, '' if pending or invalid else
                                                          ' (no pending requests under %s)' % fwd(sessions, root)))
    rc = 1 if refused else 0
    if a.dry_run or a.no_sync:
        print('dashboard: sync skipped (%s)' % ('--dry-run' if a.dry_run else '--no-sync'))
        return rc
    return max(rc, 1 if run_sync(root) else 0)


if __name__ == '__main__':
    sys.exit(main())
