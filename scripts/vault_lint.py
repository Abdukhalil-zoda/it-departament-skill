#!/usr/bin/env python3
"""vault_lint.py - structural lint of the project vault: frontmatter, status vs folder, links, severities.

Part of the IT Department skill (references/definition-of-ready-done.md). Checks the mechanical parts of the
task, bug, ADR and report contracts (references/contracts-and-lifecycle.md) so that drift is caught before it
reaches the dashboard, a transition or the release gate. Read-only: it never changes a file.
validate-project runs it with --no-dashboard-check and fails on errors.

Usage:
  python3 vault_lint.py [--root PROJECT_ROOT] [--format text|json] [--no-dashboard-check] [--strict]

Defaults:
  --root    current directory; reads <root>/.it-department/config.json (paths.vault_relative_path, documents)
            when present, otherwise the vault is <root>/vault
  --format  text: one line per finding "<code> <severity> <path>: <message>", then a summary line;
            json: {"summary": {...}, "findings": [{"code", "severity", "path", "line", "message"}]}

Note types by location: 01-Tasks/** and 04-Archive/Completed-Tasks/ = tasks; 02-Bugs/ and 04-Archive/Resolved-Bugs/
= bugs; 03-ADR/ (except decisions-log.md) = ADRs; 04-Archive/Deprecated-Proposals/ = tasks (ADR-* files: ADRs);
content-review*.md and qa-report*.md anywhere in the vault = reports. Every other note is only link-checked.

Checks:
  VL001 error    task, bug, ADR or report without parseable frontmatter (missing or unclosed --- block, a line
                 that is not "key: value", a duplicate key, a tab used for indentation)
  VL002 error    required field missing or empty - task: id, title, status, route, priority, assigned_agent,
                 branch, date_created, content_review, content_review_intake (assigned_agent and branch may be
                 empty in Backlog, In-Analysis and Deprecated-Proposals); bug: id, parent_task, title, status,
                 severity, category, release_blocking; ADR: id, title, status, date; content review report:
                 checkpoint, scope, verdict, date; QA report: scope, verdict, date
  VL003 error    id does not match the file name (ATM-029.md <-> id: ATM-029; an ADR file name starts with its id)
  VL004 error    the same id in more than one note
  VL005 error    task status differs from its folder (archived tasks: Archived); bug status outside the bug
                 lifecycle, or Archived vs 02-Bugs / 04-Archive/Resolved-Bugs mismatch
  VL006 error    [[wikilink]] target not found in the vault (by file name, case-insensitive; #heading and
                 |alias ignored; code spans, code blocks and comments ignored)
  VL007 error    bug severity Critical/Major with release_blocking: false, Minor/Trivial with release_blocking:
                 true and no deferral_signoff, a severity outside Critical/Major/Minor/Trivial, or a
                 release_blocking value that is not true/false
  VL008 error    task past In-Analysis with content_review: required and content_review_intake pending or
                 changes-requested
  VL009 warning  bug with category: content and no locale
  VL010 warning  docs: entry of a note or documents[].path of config.json does not exist (relative to the root)
  VL011 warning  date field (date, date_*, *_date) not YYYY-MM-DD; timestamp field (*_at, timestamp) not ISO 8601
  VL012 warning  dashboard out of date (dashboard_sync.py --check exits 1); not run with --no-dashboard-check;
                 reported as skipped when dashboard_sync.py is not next to this script
  VL013 warning  <vault>/03-ADR/decisions-log.md missing
  VL014 warning  .it-department/lock.json present but expired (or without a readable expires_at)

--strict reports every warning as an error; the notice that dashboard_sync.py is missing stays a warning.
Exit codes: 0 no errors, 1 errors found, 2 bad arguments (project root or vault not found).
Requires Python 3.8+, standard library only.
"""
import argparse
import collections
import datetime
import json
import os
import re
import subprocess
import sys

DEFAULT_VAULT = 'vault'
TASK_STATUSES = ('Backlog', 'In-Analysis', 'Ready-For-Dev', 'In-Development', 'Code-Review', 'QA-Testing',
                 'Ready-For-Release', 'Archived')
TASK_FOLDERS = TASK_STATUSES[:-1]           # 01-Tasks/<status>/; archived tasks live in 04-Archive/
PRE_DISPATCH = ('Backlog', 'In-Analysis')   # assigned_agent / branch may still be empty
PAST_ANALYSIS = TASK_STATUSES[2:]           # Ready-For-Dev ... Archived: content intake verdict required
BUG_STATUSES = ('Open', 'In-Development', 'Code-Review', 'Retesting', 'Closed', 'Archived')
SEVERITIES = ('Critical', 'Major', 'Minor', 'Trivial')
REQUIRED = {
    'task': ('id', 'title', 'status', 'route', 'priority', 'assigned_agent', 'branch', 'date_created',
             'content_review', 'content_review_intake'),
    'bug': ('id', 'parent_task', 'title', 'status', 'severity', 'category', 'release_blocking'),
    'adr': ('id', 'title', 'status', 'date'),
    'content-review': ('checkpoint', 'scope', 'verdict', 'date'),
    'qa-report': ('scope', 'verdict', 'date'),
}
TYPE_LABEL = {'task': 'task', 'bug': 'bug', 'adr': 'ADR', 'content-review': 'content review report',
              'qa-report': 'QA report'}
CONTENT_REVIEW_RE = re.compile(r'^content-review(?:-.*)?\.md$', re.I)
QA_REPORT_RE = re.compile(r'^qa-report(?:-.*)?\.md$', re.I)
KEY_RE = re.compile(r'(.*?):(?=\s|$)')
BLOCK_SCALAR_RE = re.compile(r'^[|>][-+]?[1-9]?[-+]?(?:\s+#.*)?$')
INT_RE = re.compile(r'^[-+]?(?:0|[1-9][0-9]*)$')
WIKILINK_RE = re.compile(r'\[\[([^\[\]\n]+?)\]\]')
FENCE_RE = re.compile(r'^ {0,3}(`{3,}|~{3,})')
INLINE_CODE_RE = re.compile(r'(`+)[^\n]*?\1')
DATE_RE = re.compile(r'^(\d{4})-(\d{2})-(\d{2})$')
TIMESTAMP_RE = re.compile(r'^(\d{4})-(\d{2})-(\d{2})'
                          r'(?:T(\d{2}):(\d{2})(?::(\d{2})(?:\.\d+)?)?(Z|[+-](\d{2}):?(\d{2}))?)?$')
URL_RE = re.compile(r'^[A-Za-z][A-Za-z0-9+.-]*://')
SKIP_DIRS = {'node_modules'}                # plus every hidden directory (.obsidian, .trash, .git)
DASHBOARD_SYNC = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'dashboard_sync.py')
DASHBOARD_TIMEOUT_SECONDS = 300


class SetupError(Exception):
    """The lint cannot run (exit code 2)."""


# --------------------------------------------------------------------------- frontmatter parser
def read_quoted(text):
    """Leading quoted scalar of text -> (value, rest); (None, text) when the quote is not closed."""
    quote, out, i = text[0], [], 1
    while i < len(text):
        ch = text[i]
        if quote == '"' and ch == '\\' and i + 1 < len(text):
            nxt = text[i + 1]
            out.append({'"': '"', '\\': '\\', '/': '/', 'n': '\n', 't': '\t'}.get(nxt, '\\' + nxt))
            i += 2
            continue
        if ch == quote:
            if quote == "'" and text[i + 1:i + 2] == "'":
                out.append("'")
                i += 2
                continue
            return ''.join(out), text[i + 1:]
        out.append(ch)
        i += 1
    return None, text


def strip_comment(text):
    """Remove an inline comment (' #' outside quotes) from an unquoted value."""
    m = re.search(r'\s#', text)
    return (text[:m.start()] if m else text).strip()


def parse_inline_list(text):
    """'[a, "b, c", 3]' -> ['a', 'b, c', 3]; None when the list is not closed on this line."""
    items, cur, depth, quote, i = [], '', 0, None, 1
    while i < len(text):
        ch = text[i]
        if quote:
            cur += ch
            if quote == '"' and ch == '\\' and i + 1 < len(text):
                cur += text[i + 1]
                i += 2
                continue
            if ch == quote:
                quote = None
        elif ch in '"\'':
            quote = ch
            cur += ch
        elif ch in '[{':
            depth += 1
            cur += ch
        elif ch in ']}':
            if depth == 0:
                rest = text[i + 1:].strip()
                if rest and not rest.startswith('#'):
                    return None
                items.append(cur)
                return [parse_scalar(x) for x in items if x.strip()]
            depth -= 1
            cur += ch
        elif ch == ',' and depth == 0:
            items.append(cur)
            cur = ''
        else:
            cur += ch
        i += 1
    return None


def parse_scalar(text):
    """One YAML value: quoted string, true/false, null, integer, inline list; anything else stays a string."""
    text = text.strip()
    if not text or text.startswith('#'):
        return None
    if text[0] in '"\'':
        value, rest = read_quoted(text)
        if value is not None and (not rest.strip() or rest.strip().startswith('#')):
            return value
        return strip_comment(text)
    if text[0] == '[':
        items = parse_inline_list(text)
        if items is not None:
            return items
    text = strip_comment(text)
    if not text:
        return None
    low = text.lower()
    if low in ('true', 'false'):
        return low == 'true'
    if low in ('null', '~'):
        return None
    if INT_RE.match(text):
        return int(text)
    return text


def split_key(line):
    """'key: value' -> (key, raw value); None when the line is not a mapping entry."""
    if line[0] in '"\'':
        key, rest = read_quoted(line)
        if key is None:
            return None
        rest = rest.lstrip()
        if not rest.startswith(':') or (len(rest) > 1 and not rest[1].isspace()):
            return None
        return key, rest[1:].strip()
    m = KEY_RE.match(line)
    if not m:
        return None
    key = m.group(1).strip()
    if not key or key[0] in '-[]{}&*!|>%@`#?,':
        return None
    return key, line[m.end():].strip()


def short(text, limit=60):
    text = str(text)
    return text if len(text) <= limit else text[:limit - 1] + '…'


def finish_block(meta, block):
    lines = block['lines']
    while lines and not lines[-1].strip():
        lines.pop()
    indent = min((len(x) - len(x.lstrip(' ')) for x in lines if x.strip()), default=0)
    meta[block['key']] = ('\n' if block['style'] == '|' else ' ').join(x[indent:] for x in lines)


def parse_frontmatter_lines(lines, first_line_no):
    """Parse the lines between the --- markers. Returns (meta, problems[(line, message)])."""
    meta, problems, seen, raw = {}, [], {}, {}
    key, mode, block, map_indent = None, None, None, None
    for offset, line in enumerate(lines):
        n = first_line_no + offset
        line = line.rstrip()
        stripped = line.strip()
        if mode == 'block':
            if not stripped or line[0] in ' \t':
                block['lines'].append(line)
                continue
            finish_block(meta, block)
            mode = None
        if not stripped or stripped.startswith('#'):
            continue
        if line[0] == '\t':
            problems.append((n, 'tab used for indentation: %s' % short(stripped)))
            continue
        indent = len(line) - len(line.lstrip(' '))
        is_item = stripped == '-' or stripped.startswith('- ')
        if indent == 0 and not is_item:
            kv = split_key(stripped)
            if kv is None:
                problems.append((n, 'not a "key: value" line: %s' % short(stripped)))
                key, mode = None, None
                continue
            key, value = kv
            if key in seen:
                problems.append((n, 'duplicate key %s (first on line %d)' % (key, seen[key])))
            seen[key] = n
            raw.pop(key, None)
            if not value or value.startswith('#'):
                meta[key], mode = None, 'open'
            elif BLOCK_SCALAR_RE.match(value):
                meta[key], mode, block = '', 'block', {'key': key, 'style': value[0], 'lines': []}
            else:
                raw[key] = value
                meta[key], mode = parse_scalar(value), 'value'
            continue
        if is_item:
            if mode in ('open', 'list'):
                if mode == 'open':
                    meta[key], mode = [], 'list'
                item = stripped[1:].strip()
                meta[key].append(parse_scalar(item) if item else None)
            elif indent == 0:
                problems.append((n, 'list item without a key: %s' % short(stripped)))
            continue
        # indented line: nested map, multi-line scalar or the content of a list item
        if mode == 'open':
            kv = split_key(stripped)
            if kv is not None:
                meta[key], mode, map_indent = {kv[0]: parse_scalar(kv[1]) if kv[1] else None}, 'map', indent
            else:
                raw[key] = stripped
                meta[key], mode = parse_scalar(stripped), 'value'
        elif mode == 'map' and indent == map_indent:
            kv = split_key(stripped)
            if kv is not None:
                meta[key][kv[0]] = parse_scalar(kv[1]) if kv[1] else None
        elif mode == 'value' and key in raw:
            raw[key] += ' ' + stripped
            meta[key] = parse_scalar(raw[key])
    if mode == 'block':
        finish_block(meta, block)
    return meta, problems


def read_frontmatter(text):
    """Frontmatter of a note -> (meta, problems). meta is None when there is no closed --- block on line 1."""
    lines = text.split('\n')
    if not lines or lines[0].rstrip() != '---':
        return None, []
    for end in range(1, len(lines)):
        if lines[end].rstrip() == '---':
            return parse_frontmatter_lines(lines[1:end], 2)
    return None, [(1, 'frontmatter opened on line 1 is never closed with a --- line')]


# --------------------------------------------------------------------------- vault helpers
def load_config(root):
    path = os.path.join(root, '.it-department', 'config.json')
    if not os.path.isfile(path):
        return {}, None
    try:
        with open(path, encoding='utf-8-sig') as fh:
            cfg = json.load(fh)
    except Exception as exc:  # reported, then the defaults apply
        return {}, str(exc)
    return (cfg if isinstance(cfg, dict) else {}), None


def read_text(path):
    with open(path, encoding='utf-8-sig', errors='replace') as fh:
        return fh.read()


def walk_vault(vault):
    files = []
    for dp, dn, fn in os.walk(vault):
        dn[:] = sorted(d for d in dn if not d.startswith('.') and d not in SKIP_DIRS)
        files += [os.path.join(dp, f) for f in sorted(fn)]
    return files


def classify(parts):
    """Note type from its path parts relative to the vault, e.g. ['01-Tasks', 'Backlog', 'ATM-1.md']."""
    name, top = parts[-1], (parts[0] if len(parts) > 1 else '')
    if top == '01-Tasks':
        return 'task'
    if top == '02-Bugs':
        return 'bug'
    if top == '03-ADR':
        return None if name.lower() == 'decisions-log.md' else 'adr'
    if top == '04-Archive' and len(parts) > 2:
        if parts[1] == 'Completed-Tasks':
            return 'task'
        if parts[1] == 'Resolved-Bugs':
            return 'bug'
        if parts[1] == 'Deprecated-Proposals':
            return 'adr' if name.upper().startswith('ADR-') else 'task'
    if CONTENT_REVIEW_RE.match(name):
        return 'content-review'
    if QA_REPORT_RE.match(name):
        return 'qa-report'
    return None


def task_location(parts):
    """(folder status or None, location problem or None, deprecated) of a task note."""
    if parts[0] == '04-Archive':
        return 'Archived', None, parts[1] == 'Deprecated-Proposals'
    if len(parts) == 2:
        return None, 'task note is directly in 01-Tasks/, not in a status folder', False
    if parts[1] not in TASK_FOLDERS:
        return None, 'folder %s is not a task status folder (%s; archived tasks go to 04-Archive/Completed-Tasks)' % (
            parts[1], ', '.join(TASK_FOLDERS)), False
    return parts[1], None, False


def build_index(vault, files):
    stems, names, paths = set(), set(), set()
    for f in files:
        rel = os.path.relpath(f, vault).replace(os.sep, '/').casefold()
        name = os.path.basename(f).casefold()
        names.add(name)
        paths.add(rel)
        if name.endswith('.md'):
            stems.add(name[:-3])
            paths.add(rel[:-3])
    return stems, names, paths


def link_target(inner):
    """'Target#heading|alias' (table-escaped 'Target\\|alias' too) -> 'Target'."""
    target = inner.split('|', 1)[0].rstrip()
    if target.endswith('\\'):
        target = target[:-1]
    return target.split('#', 1)[0].strip()


def resolve_link(target, index):
    stems, names, paths = index
    t = target.replace('\\', '/').casefold()
    while t.startswith('./'):
        t = t[2:]
    t = t.lstrip('/')
    if t.endswith('.md'):
        t = t[:-3]
    if not t:
        return True
    if '/' in t:
        return t in paths or any(p.endswith('/' + t) for p in paths)
    return t in stems or t in names


def strip_code(text):
    """Blank out fenced code blocks, inline code spans and comments; line numbers stay the same."""
    out, fence = [], None
    for line in text.split('\n'):
        m = FENCE_RE.match(line)
        if fence:
            if m and m.group(1)[0] == fence[0] and len(m.group(1)) >= len(fence) and not line.strip()[len(m.group(1)):].strip():
                fence = None
            out.append('')
        elif m:
            fence = m.group(1)
            out.append('')
        else:
            out.append(line)

    def blank(mo):
        return re.sub(r'[^\n]', ' ', mo.group(0))
    text = '\n'.join(out)
    text = re.sub(r'<!--.*?-->', blank, text, flags=re.S)
    text = re.sub(r'%%.*?%%', blank, text, flags=re.S)
    return INLINE_CODE_RE.sub(blank, text)


def wikilinks(text):
    """[(line number, inner text, target)] of every wikilink outside code and comments."""
    found = []
    for n, line in enumerate(strip_code(text).split('\n'), 1):
        for m in WIKILINK_RE.finditer(line):
            found.append((n, m.group(1), link_target(m.group(1))))
    return found


def is_empty(value):
    return value is None or (isinstance(value, str) and not value.strip()) or (isinstance(value, (list, dict)) and not value)


def text_of(value):
    """Scalar frontmatter value as stripped text ('' for empty or non-scalar values)."""
    if isinstance(value, bool):
        return 'true' if value else 'false'
    if isinstance(value, (str, int)):
        return str(value).strip()
    return ''


def as_bool(value):
    if isinstance(value, bool):
        return value
    if isinstance(value, str) and value.strip().lower() in ('true', 'false'):
        return value.strip().lower() == 'true'
    return None


def valid_date(text):
    m = DATE_RE.match(text)
    if not m:
        return False
    try:
        datetime.date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    except ValueError:
        return False
    return True


def parse_timestamp(text):
    """ISO 8601 date or date-time -> aware datetime (UTC when no offset is given); None when invalid."""
    m = TIMESTAMP_RE.match(text.strip())
    if not m:
        return None
    y, mo, d, hh, mm, ss, zone, oh, om = m.groups()
    try:
        tz = datetime.timezone.utc
        if zone and zone != 'Z':
            sign = -1 if zone[0] == '-' else 1
            tz = datetime.timezone(sign * datetime.timedelta(hours=int(oh), minutes=int(om)))
        return datetime.datetime(int(y), int(mo), int(d), int(hh or 0), int(mm or 0), int(ss or 0), tzinfo=tz)
    except ValueError:
        return None


def display(root, path):
    return os.path.relpath(path, root).replace(os.sep, '/')


def run_dashboard_check(script, root):
    """(exit code, first output line) of dashboard_sync.py --check; exit code None when it could not run."""
    env = dict(os.environ, PYTHONIOENCODING='utf-8')
    try:
        proc = subprocess.run([sys.executable, script, '--root', root, '--check'], capture_output=True,
                              encoding='utf-8', errors='replace', timeout=DASHBOARD_TIMEOUT_SECONDS, env=env)
    except Exception as exc:
        return None, str(exc)
    lines = [x for x in (proc.stderr or '').splitlines() + (proc.stdout or '').splitlines() if x.strip()]
    return proc.returncode, (lines[0].strip() if lines else '')


# --------------------------------------------------------------------------- lint
def lint(root, dashboard_check=True, strict=False, dashboard_script=None, now=None):
    """Lint the vault of a project. Returns (findings, summary); raises SetupError when it cannot run."""
    root = os.path.abspath(root)
    if not os.path.isdir(root):
        raise SetupError('project root not found: %s' % root)
    cfg, cfg_error = load_config(root)
    paths_cfg = cfg.get('paths') if isinstance(cfg.get('paths'), dict) else {}
    vault_rel = paths_cfg.get('vault_relative_path')
    if not isinstance(vault_rel, str) or not vault_rel.strip():
        vault_rel = DEFAULT_VAULT
    vault = os.path.normpath(os.path.join(root, vault_rel))
    if not os.path.isdir(vault):
        raise SetupError('vault not found: %s (%s)' % (vault, 'config.json is not readable: %s' % cfg_error
                                                          if cfg_error else 'run init-project first'))

    findings = []

    def add(code, severity, path, message, line=None, sticky=False):
        findings.append({'code': code, 'severity': severity, 'path': path, 'line': line, 'message': message,
                         'sticky': sticky})

    files = walk_vault(vault)
    index = build_index(vault, files)
    counts = collections.Counter()
    ids = collections.OrderedDict()
    for path in (f for f in files if f.lower().endswith('.md')):
        parts = os.path.relpath(path, vault).split(os.sep)
        kind = classify(parts)
        shown = display(root, path)
        counts['notes'] += 1
        if kind:
            counts[kind] += 1
        try:
            text = read_text(path)
        except OSError as exc:
            add('VL001', 'error', shown, 'cannot read the note: %s' % exc)
            continue
        meta, problems = read_frontmatter(text)

        # VL001 - parseable frontmatter (typed notes only)
        if kind:
            if meta is None:
                add('VL001', 'error', shown, problems[0][1] if problems else
                    'no frontmatter: a %s starts with a --- block of "key: value" lines' % TYPE_LABEL[kind])
            else:
                for line_no, message in problems:
                    add('VL001', 'error', shown, message, line_no)

        if meta is not None:
            nid = text_of(meta.get('id'))
            if nid:
                ids.setdefault(nid.casefold(), []).append((shown, nid))
            if kind:
                lint_typed(add, kind, parts, shown, meta, nid)
            lint_docs(add, root, shown, meta)
            lint_dates(add, shown, meta)

        # VL006 - wikilinks resolve inside the vault
        reported = set()
        for line_no, inner, target in wikilinks(text):
            if target and target.casefold() not in reported and not resolve_link(target, index):
                reported.add(target.casefold())
                add('VL006', 'error', shown, 'wikilink [[%s]] target not found in the vault' % short(inner, 80), line_no)

    # VL004 - duplicate ids
    for occurrences in ids.values():
        if len(occurrences) > 1:
            for shown, nid in occurrences:
                others = [o for o, _ in occurrences if o != shown] or [shown]
                add('VL004', 'error', shown, 'id %s is also used by %s' % (nid, ', '.join(others)))

    # VL010 - documents of the config
    documents = cfg.get('documents')
    if isinstance(documents, list):
        for i, doc in enumerate(documents):
            if isinstance(doc, dict) and isinstance(doc.get('path'), str) and doc['path'].strip():
                if not path_exists(root, doc['path']):
                    add('VL010', 'warning', '.it-department/config.json', 'documents[%d] (%s): path %s does not exist' % (
                        i, short(doc.get('title') or 'untitled', 40), doc['path'].strip()))

    # VL013 - decisions journal
    decisions_log = os.path.join(vault, '03-ADR', 'decisions-log.md')
    if not os.path.isfile(decisions_log):
        add('VL013', 'warning', display(root, decisions_log),
            'decisions journal missing (re-run init-project; row format: templates/decision-record.md)')

    # VL014 - expired lock
    lint_lock(add, root, now)

    # VL012 - dashboard freshness
    dashboard_state = 'disabled'
    if dashboard_check:
        script = dashboard_script or DASHBOARD_SYNC
        dashboard = display(root, os.path.join(vault, '00-Dashboard.md'))
        if not os.path.isfile(script):
            dashboard_state = 'skipped'
            add('VL012', 'warning', None, 'dashboard check skipped: dashboard_sync.py not found', sticky=True)
        else:
            rc, detail = run_dashboard_check(script, root)
            if rc == 0:
                dashboard_state = 'ok'
            elif rc == 1:
                dashboard_state = 'outdated'
                add('VL012', 'warning', dashboard, 'dashboard out of date (dashboard_sync.py --check exit 1); '
                    'regenerate it with dashboard_sync.py --root <project_root>')
            else:
                dashboard_state = 'failed'
                add('VL012', 'warning', dashboard, 'dashboard check failed (dashboard_sync.py --check exit %s)%s' % (
                    rc, (': ' + short(detail, 120)) if detail else ''))

    if strict:
        for f in findings:
            if f['severity'] == 'warning' and not f['sticky']:
                f['severity'] = 'error'
    for f in findings:
        del f['sticky']
    findings.sort(key=lambda f: (f['path'] is None, f['path'] or '', f['line'] or 0, f['code'], f['message']))
    summary = {
        'errors': sum(1 for f in findings if f['severity'] == 'error'),
        'warnings': sum(1 for f in findings if f['severity'] == 'warning'),
        'notes': counts['notes'], 'tasks': counts['task'], 'bugs': counts['bug'], 'adrs': counts['adr'],
        'reports': counts['content-review'] + counts['qa-report'],
        'by_code': dict(sorted(collections.Counter(f['code'] for f in findings).items())),
        'vault': display(root, vault), 'strict': strict, 'dashboard_check': dashboard_state,
        'config_error': cfg_error,
    }
    return findings, summary


def lint_typed(add, kind, parts, shown, meta, nid):
    """VL002, VL003, VL005, VL007, VL008, VL009 for one task, bug, ADR or report."""
    folder_status, location_problem, deprecated = task_location(parts) if kind == 'task' else (None, None, False)
    status = text_of(meta.get('status'))
    effective = folder_status or (status if status in TASK_STATUSES else None)

    # VL002 - required fields
    missing, empty = [], []
    for field in REQUIRED[kind]:
        if field not in meta:
            missing.append(field)
        elif is_empty(meta[field]):
            if kind == 'task' and field in ('assigned_agent', 'branch') and (deprecated or effective in PRE_DISPATCH):
                continue
            empty.append(field)
    if missing or empty:
        parts_msg = []
        if missing:
            parts_msg.append('missing required field%s: %s' % ('s' if len(missing) > 1 else '', ', '.join(missing)))
        if empty:
            parts_msg.append('required field%s empty: %s' % ('s' if len(empty) > 1 else '', ', '.join(empty)))
        add('VL002', 'error', shown, '; '.join(parts_msg))

    # VL003 - id matches the file name
    stem = parts[-1][:-3]
    if nid and kind in ('task', 'bug'):
        if stem != nid:
            add('VL003', 'error', shown, 'id %s does not match the file name %s' % (nid, parts[-1]))
    elif nid and kind == 'adr':
        if not (stem == nid or (stem.startswith(nid) and stem[len(nid)] in '-_ .')):
            add('VL003', 'error', shown, 'file name %s does not start with the id %s' % (parts[-1], nid))

    if kind == 'task':
        # VL005 - status vs folder
        if location_problem:
            add('VL005', 'error', shown, location_problem)
        elif status and folder_status == 'Archived' and status != 'Archived':
            add('VL005', 'error', shown, 'status %s but archived tasks must have status Archived' % status)
        elif status and folder_status and status != folder_status:
            add('VL005', 'error', shown, 'status %s but folder %s' % (status, folder_status))
        # VL008 - content intake verdict before Ready-For-Dev
        intake = text_of(meta.get('content_review_intake')).lower()
        if (text_of(meta.get('content_review')).lower() == 'required' and not deprecated and effective in PAST_ANALYSIS
                and intake in ('pending', 'changes-requested')):
            add('VL008', 'error', shown, 'content_review: required but content_review_intake is %s at %s '
                '(the Checkpoint A verdict must be approved before Ready-For-Dev)' % (intake, effective))

    if kind == 'bug':
        archived_folder = parts[0] == '04-Archive'
        # VL005 - bug lifecycle
        if status and status not in BUG_STATUSES:
            add('VL005', 'error', shown, 'status %s is not a bug status (%s)' % (status, ', '.join(BUG_STATUSES)))
        elif status and archived_folder and status != 'Archived':
            add('VL005', 'error', shown, 'status %s but folder Resolved-Bugs expects Archived' % status)
        elif status == 'Archived' and not archived_folder:
            add('VL005', 'error', shown, 'status Archived but the note is in 02-Bugs (archived bugs move to 04-Archive/Resolved-Bugs)')
        # VL007 - severity vs release_blocking
        raw_severity = text_of(meta.get('severity'))
        severity = next((s for s in SEVERITIES if s.lower() == raw_severity.lower()), None)
        if raw_severity and severity is None:
            add('VL007', 'error', shown, 'severity %s is not one of %s' % (raw_severity, ', '.join(SEVERITIES)))
        blocking = as_bool(meta.get('release_blocking'))
        if not is_empty(meta.get('release_blocking')) and blocking is None:
            add('VL007', 'error', shown, 'release_blocking %s is not true or false' % short(meta.get('release_blocking')))
        if severity in ('Critical', 'Major') and blocking is False:
            add('VL007', 'error', shown, 'severity %s with release_blocking: false (Critical and Major always block the release)' % severity)
        if severity in ('Minor', 'Trivial') and blocking is True and is_empty(meta.get('deferral_signoff')):
            add('VL007', 'error', shown, 'severity %s with release_blocking: true and no deferral_signoff '
                '(record who decided and when, or set release_blocking: false)' % severity)
        # VL009 - content defects carry the locale
        if text_of(meta.get('category')).lower() == 'content' and is_empty(meta.get('locale')):
            add('VL009', 'warning', shown, 'category content without locale (set the locale code of the defect)')


def path_exists(root, path):
    path = path.strip()
    if URL_RE.match(path):
        return True
    path = path.split('#', 1)[0].strip().replace('\\', '/')
    if not path:
        return True
    return os.path.exists(path if os.path.isabs(path) else os.path.join(root, path))


def lint_docs(add, root, shown, meta):
    """VL010 for the docs: entries of a note (wikilink entries are checked by VL006)."""
    docs = meta.get('docs')
    entries = docs if isinstance(docs, list) else ([docs] if isinstance(docs, str) else [])
    for entry in entries:
        if isinstance(entry, str) and entry.strip() and not entry.strip().startswith('[['):
            if not path_exists(root, entry):
                add('VL010', 'warning', shown, 'docs path %s does not exist (paths are relative to the project root)' % entry.strip())


def lint_dates(add, shown, meta):
    """VL011 for date (date, date_*, *_date) and timestamp (*_at, timestamp) fields."""
    for key, value in meta.items():
        low = key.lower()
        is_date = low == 'date' or low.startswith('date_') or low.endswith('_date')
        is_timestamp = not is_date and (low.endswith('_at') or low == 'timestamp')
        if not (is_date or is_timestamp) or is_empty(value):
            continue
        text = value.strip() if isinstance(value, str) else None
        if is_date and not (text and valid_date(text)):
            add('VL011', 'warning', shown, '%s %s is not a YYYY-MM-DD date' % (key, short(value, 40)))
        elif is_timestamp and not (text and parse_timestamp(text)):
            add('VL011', 'warning', shown, '%s %s is not an ISO 8601 timestamp' % (key, short(value, 40)))


def lint_lock(add, root, now):
    """VL014 for an expired (or unreadable) .it-department/lock.json."""
    lock = os.path.join(root, '.it-department', 'lock.json')
    if not os.path.isfile(lock):
        return
    shown = display(root, lock)
    try:
        with open(lock, encoding='utf-8-sig') as fh:
            data = json.load(fh)
    except Exception:
        add('VL014', 'warning', shown, 'lock file is not valid JSON (fix it, or delete it after a line in the hand-off note)')
        return
    expires = data.get('expires_at') if isinstance(data, dict) else None
    expires_at = parse_timestamp(expires) if isinstance(expires, str) else None
    if expires_at is None:
        add('VL014', 'warning', shown, 'lock file has no valid expires_at (ISO 8601 timestamp)')
        return
    now = now or datetime.datetime.now(datetime.timezone.utc)
    if expires_at < now:
        holder = '%s@%s' % (text_of(data.get('owner_role')) or '?', text_of(data.get('host')) or '?')
        add('VL014', 'warning', shown, 'lock held by %s expired at %s (take it over after a line in the hand-off note, '
            'or delete it)' % (holder, expires.strip()))


# --------------------------------------------------------------------------- output
def format_finding(f):
    message = ('line %d: %s' % (f['line'], f['message'])) if f['line'] else f['message']
    if f['path']:
        return '%s %s %s: %s' % (f['code'], f['severity'], f['path'], message)
    return '%s %s %s' % (f['code'], f['severity'], message)


def summary_line(s):
    return ('vault_lint: %d error(s), %d warning(s) in %d note(s) (%d tasks, %d bugs, %d ADRs, %d reports) under %s%s; '
            'dashboard check %s' % (s['errors'], s['warnings'], s['notes'], s['tasks'], s['bugs'], s['adrs'], s['reports'],
                                    s['vault'], ' [strict]' if s['strict'] else '', s['dashboard_check']))


def main(argv=None):
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(errors='backslashreplace')
        except Exception:
            pass
    ap = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    ap.add_argument('--root', default=os.getcwd(), help='project root (holds .it-department/config.json)')
    ap.add_argument('--format', choices=('text', 'json'), default='text', help='output format (default text)')
    ap.add_argument('--no-dashboard-check', action='store_true', help='do not run dashboard_sync.py --check (VL012)')
    ap.add_argument('--strict', action='store_true', help='report warnings as errors')
    a = ap.parse_args(argv)
    try:
        findings, summary = lint(a.root, dashboard_check=not a.no_dashboard_check, strict=a.strict)
    except SetupError as exc:
        print('vault_lint: %s' % exc, file=sys.stderr)
        return 2
    if summary['config_error']:
        print('vault_lint: .it-department/config.json is not readable (%s) - using the default vault path' % summary['config_error'],
              file=sys.stderr)
    if a.format == 'json':
        print(json.dumps({'summary': summary, 'findings': findings}, ensure_ascii=False, indent=1))
    else:
        for f in findings:
            print(format_finding(f))
        print(summary_line(summary))
    return 1 if summary['errors'] else 0


if __name__ == '__main__':
    sys.exit(main())
