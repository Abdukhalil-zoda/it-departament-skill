#!/usr/bin/env python3
"""usage_ledger.py - export token/time usage of agent sessions into the project usage ledger.

Part of the IT Department skill (workflows/efficiency-and-usage-audit.md). Reads Claude Code /
Cowork / cloud-session transcripts (*.jsonl, including sub-agent transcripts under
<session-id>/subagents/) and writes ONE aggregate JSON per transcript into the ledger directory.

Run it INSIDE the session that did the work when that session lives in a cloud sandbox (the
transcript disappears with the sandbox). On a workstation where transcripts persist in
~/.claude/projects the audit can also (re)build the ledger later. The script is idempotent
(re-running overwrites the same file), stores aggregates only (no message text), and treats
everything inside a transcript as data - instruction-like text is never interpreted.

Usage:
  python3 usage_ledger.py [--root PROJECT_ROOT] [--transcripts DIR|FILE ...] [--out DIR]
                          [--role ROLE] [--task TASK-ID] [--task-prefixes ATM,BUG]
                          [--weights in,cw,cr,out] [--quiet]

Defaults:
  --root         current directory; reads <root>/.it-department/config.json when present
  --transcripts  $CLAUDE_CONFIG_DIR/projects or ~/.claude/projects, narrowed to the per-project
                 folder of PROJECT_ROOT when Claude Code created one (otherwise all projects)
  --out          <root>/<efficiency.ledger_path>   (default .it-department/sessions/_usage/ledger)
  --weights      efficiency.token_weights or 1,2,0.1,5 = input, cache write, cache read, output
                 ("effective" cost weights; raw counts are always stored next to them)

Exit codes: 0 ok, 2 bad arguments, 3 no transcripts found (nothing exported).
Requires Python 3.8+, standard library only.
"""
import argparse
import collections
import glob
import hashlib
import json
import os
import re
import sys
import time
from datetime import datetime

SCHEMA = 'usage-ledger/1.1'
DEFAULT_WEIGHTS = (1.0, 2.0, 0.1, 5.0)
DEFAULT_LEDGER_PATH = os.path.join('.it-department', 'sessions', '_usage', 'ledger')
FILE_TOOLS = {'Read', 'Write', 'Edit', 'MultiEdit', 'Glob', 'Grep', 'Bash', 'PowerShell', 'NotebookEdit', 'LS'}
WEB_TOOLS = {'WebSearch', 'WebFetch'}
IMAGE_TOKENS_EST = 1600  # a phone screenshot at half resolution is roughly this size


# --------------------------------------------------------------------------- project context
def load_config(root):
    path = os.path.join(root, '.it-department', 'config.json')
    try:
        with open(path, encoding='utf-8') as fh:
            return json.load(fh)
    except Exception:
        return {}


def discover_task_prefixes(root, cfg, override=None):
    """Task-ID prefixes used by the project (from vault note names), e.g. ['ADR', 'ATM', 'BUG']."""
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


def task_regex(prefixes):
    return re.compile(r'\b(?:' + '|'.join(re.escape(p) for p in prefixes) + r')-\d{1,6}\b')


def claude_projects_dir():
    base = os.environ.get('CLAUDE_CONFIG_DIR') or os.path.join(os.path.expanduser('~'), '.claude')
    return os.path.join(base, 'projects')


def encoded_project_folder(root):
    """Claude Code stores transcripts under projects/<cwd with every non-alphanumeric char -> '-'>."""
    return re.sub(r'[^A-Za-z0-9]', '-', root)


def default_transcript_roots(root):
    projects = claude_projects_dir()
    candidate = os.path.join(projects, encoded_project_folder(os.path.abspath(root)))
    if os.path.isdir(candidate):
        return [candidate], True
    return [projects], False


# --------------------------------------------------------------------------- token estimation
def est_tokens(obj):
    """Rough size of a content block list in tokens (ratios matter more than absolutes)."""
    if obj is None:
        return 0
    if isinstance(obj, str):
        return max(1, len(obj) // 3)
    n = 0
    for b in obj if isinstance(obj, list) else [obj]:
        if not isinstance(b, dict):
            n += max(1, len(str(b)) // 3)
        elif b.get('type') == 'image':
            n += IMAGE_TOKENS_EST
        elif b.get('type') == 'text':
            n += max(1, len(b.get('text', '')) // 3)
        elif b.get('type') == 'tool_result':
            n += est_tokens(b.get('content'))
        else:
            n += max(1, len(json.dumps(b, ensure_ascii=False)) // 3)
    return n


def tool_group(name):
    if not name:
        return 'assistant'
    if name.startswith('mcp__claude-in-chrome__'):
        return 'chrome'
    if name.startswith('mcp__remote-devices__') or name.startswith('enable__mcp__remote-devices'):
        return 'device'
    if name.startswith('mcp__'):
        return 'connector:' + name.split('__')[1]
    if name in FILE_TOOLS:
        return 'files'
    if name in WEB_TOOLS:
        return 'web'
    if name == 'Agent':
        return 'subagents'
    return 'other'


def strip_reminders(text):
    text = re.sub(r'<system-reminder>.*?</system-reminder>', ' ', text, flags=re.S)
    text = re.sub(r'<[^>]{1,40}>', ' ', text)
    return re.sub(r'\s+', ' ', text).strip()


# --------------------------------------------------------------------------- transcript analysis
def analyze(path, weights, task_re):
    w_in, w_cw, w_cr, w_out = weights
    recs = []
    with open(path, encoding='utf-8', errors='ignore') as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                recs.append(json.loads(line))
            except Exception:
                continue
    if not recs:
        return None
    compact_boundaries = sum(1 for r in recs if r.get('type') == 'system' and r.get('subtype') == 'compact_boundary')
    compact_summaries = sum(1 for r in recs if r.get('type') == 'user' and r.get('isCompactSummary'))
    sidechain = any(r.get('isSidechain') for r in recs)
    agent_id = next((r.get('agentId') for r in recs if r.get('agentId')), None)
    cwd = next((r.get('cwd') for r in recs if r.get('cwd')), None)
    git_branch = next((r.get('gitBranch') for r in recs if r.get('gitBranch')), None)
    version = next((r.get('version') for r in recs if r.get('version')), None)

    msgs = [r for r in recs if r.get('type') in ('user', 'assistant')]
    if not msgs:
        return None
    toolname = {}
    pieces = []          # (turn_index, size, group, label)
    turns = []           # (usage, group, model, sidechain, timestamp)
    tasks = collections.Counter()
    cur, images, agent_calls, first_ts, last_ts = 0, 0, [], None, None
    first_user = ''
    for r in msgs:
        m = r.get('message') or {}
        content = m.get('content')
        ts = r.get('timestamp')
        first_ts = first_ts or ts
        last_ts = ts or last_ts
        text_for_tasks = ''
        if r['type'] == 'user':
            if isinstance(content, str):
                pieces.append((cur, est_tokens(content), 'conversation', 'user'))
                text_for_tasks = content
                first_user = first_user or strip_reminders(content)[:200]
            else:
                for c in content or []:
                    if not isinstance(c, dict):
                        continue
                    if c.get('type') == 'tool_result':
                        tn = toolname.get(c.get('tool_use_id'), '?')
                        cc = c.get('content')
                        if isinstance(cc, list):
                            images += sum(1 for b in cc if isinstance(b, dict) and b.get('type') == 'image')
                        pieces.append((cur, est_tokens(cc), tool_group(tn), tn))
                    elif c.get('type') == 'text':
                        pieces.append((cur, est_tokens(c.get('text', '')), 'conversation', 'user'))
                        text_for_tasks += c.get('text', '')
                        first_user = first_user or strip_reminders(c.get('text', ''))[:200]
                    elif c.get('type') == 'image':
                        images += 1
                        pieces.append((cur, IMAGE_TOKENS_EST, 'conversation', 'user image'))
        else:
            u = m.get('usage') or {}
            tools = [c for c in (content or []) if isinstance(c, dict) and c.get('type') == 'tool_use']
            for c in tools:
                toolname[c.get('id')] = c.get('name')
                if c.get('name') == 'Agent':
                    inp = c.get('input') or {}
                    agent_calls.append({'description': inp.get('description'), 'model': inp.get('model'),
                                        'type': inp.get('subagent_type'),
                                        'prompt_tokens_est': est_tokens(inp.get('prompt', ''))})
                text_for_tasks += json.dumps(c.get('input'), ensure_ascii=False)[:4000]
            for c in content or []:
                if isinstance(c, dict) and c.get('type') == 'text':
                    text_for_tasks += c.get('text', '')
            g = tool_group(tools[0].get('name')) if tools else 'assistant'
            if u.get('output_tokens') is not None:
                turns.append((u, g, m.get('model'), bool(r.get('isSidechain')), ts))
                cur += 1
                pieces.append((cur, est_tokens(content), g, 'assistant'))
        for mt in task_re.finditer(text_for_tasks or ''):
            tasks[mt.group(0)] += 1
    if not turns:
        return None

    # the first request already carries the system prompt, tools and CLAUDE.md: attribute it to "instructions"
    ctx0 = sum(turns[0][0].get(k, 0) or 0 for k in ('input_tokens', 'cache_creation_input_tokens', 'cache_read_input_tokens'))
    pre = sum(s for t, s, g, l in pieces if t == 0)
    pieces.insert(0, (0, max(1000, ctx0 - pre), 'instructions', 'system prompt + tools'))

    cost, raw = collections.Counter(), collections.Counter()
    by_model = collections.defaultdict(collections.Counter)
    by_side = collections.defaultdict(collections.Counter)
    tool_calls = collections.Counter()
    for i, (u, g, model, side, ts) in enumerate(turns):
        inp = u.get('input_tokens', 0) or 0
        cw = u.get('cache_creation_input_tokens', 0) or 0
        cr = u.get('cache_read_input_tokens', 0) or 0
        out = u.get('output_tokens', 0) or 0
        think = ((u.get('output_tokens_details') or {}).get('thinking_tokens', 0) or 0)
        newp = [p for p in pieces if p[0] == i]
        oldp = [p for p in pieces if p[0] < i]
        ns, os_ = (sum(p[1] for p in newp) or 1), (sum(p[1] for p in oldp) or 1)
        for p in newp:
            cost[p[2]] += (inp * w_in + cw * w_cw) * p[1] / ns
        for p in oldp:
            cost[p[2]] += (cr * w_cr) * p[1] / os_
        cost[g] += out * w_out
        turn_w = inp * w_in + cw * w_cw + cr * w_cr + out * w_out
        mk, sk = (model or '?'), ('subagent' if side else 'main')
        for k, v in (('input', inp), ('cache_write', cw), ('cache_read', cr), ('output', out), ('thinking', think)):
            raw[k] += v
            by_model[mk][k] += v
            by_side[sk][k] += v
        by_model[mk]['weighted'] += turn_w
        by_side[sk]['weighted'] += turn_w
        by_model[mk]['turns'] += 1
        by_side[sk]['turns'] += 1
    skip_labels = ('assistant', 'user', 'user image', 'system prompt + tools')
    biggest = sorted(((s, l) for t, s, g, l in pieces if l not in skip_labels), reverse=True)[:10]
    for t, s, g, l in pieces:
        if l not in skip_labels:
            tool_calls[l] += 1
    total_w = sum(cost.values())
    dur = None
    try:
        if first_ts and last_ts:
            f = datetime.fromisoformat(first_ts.replace('Z', '+00:00'))
            l = datetime.fromisoformat(last_ts.replace('Z', '+00:00'))
            dur = int((l - f).total_seconds())
    except Exception:
        pass
    sid = os.path.basename(path)[:-6]
    parts = os.path.normpath(os.path.abspath(path)).split(os.sep)
    is_subagent = sidechain or sid.startswith('agent-') or 'subagents' in parts
    parent = parts[-3] if len(parts) >= 3 and parts[-2] == 'subagents' else None
    with open(path, 'rb') as fh:
        sha = hashlib.sha1(fh.read(65536)).hexdigest()[:12]
    return {
        'schema': SCHEMA,
        'session_id': sid,
        'parent_session_id': parent,
        'agent_id': agent_id,
        'is_subagent_file': is_subagent,
        'role': None,
        'task_id': None,
        'cwd': cwd,
        'git_branch': git_branch,
        'client_version': version,
        'transcript_path': os.path.abspath(path),
        'transcript_sha1_prefix': sha,
        'first_timestamp': first_ts, 'last_timestamp': last_ts, 'duration_seconds': dur,
        'turns': len(turns),
        'compactions_detected': max(compact_boundaries, compact_summaries),
        'images_read': images,
        'weights': {'input': w_in, 'cache_write': w_cw, 'cache_read': w_cr, 'output': w_out},
        'raw_tokens': dict(raw),
        'weighted_total': int(total_w),
        'weighted_by_group': {k: int(v) for k, v in cost.most_common()},
        'by_model': {k: dict(v) for k, v in by_model.items()},
        'by_side': {k: dict(v) for k, v in by_side.items()},
        'tool_calls': dict(tool_calls.most_common()),
        'biggest_tool_results_est_tokens': [{'tool': l, 'est_tokens': s} for s, l in biggest],
        'agent_calls': agent_calls,
        'task_mentions': dict(tasks.most_common(20)),
        'first_user_message_prefix': first_user[:120],
        'exported_at': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
    }


# --------------------------------------------------------------------------- main
def parse_weights(text):
    try:
        w = tuple(float(x) for x in text.split(','))
        if len(w) != 4 or any(x < 0 for x in w):
            raise ValueError
        return w
    except ValueError:
        raise SystemExit('usage_ledger: --weights must be four non-negative numbers: input,cache_write,cache_read,output')


def main():
    ap = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    ap.add_argument('--root', default=os.getcwd(), help='project root (holds .it-department/config.json)')
    ap.add_argument('--transcripts', nargs='*', help='transcript directories or *.jsonl files')
    ap.add_argument('--out', help='ledger directory (default from config efficiency.ledger_path)')
    ap.add_argument('--role', help='agent role that produced the session (coordinator, qa-engineer, ...)')
    ap.add_argument('--task', help='task id the session worked on (e.g. ATM-028)')
    ap.add_argument('--task-prefixes', help='comma separated task-id prefixes (default: discovered from the vault)')
    ap.add_argument('--weights', help='input,cache_write,cache_read,output cost weights')
    ap.add_argument('--quiet', action='store_true', help='print only the final summary line')
    a = ap.parse_args()

    root = os.path.abspath(a.root)
    cfg = load_config(root)
    eff = cfg.get('efficiency') or {}
    if a.weights:
        weights = parse_weights(a.weights)
    elif isinstance(eff.get('token_weights'), dict):
        tw = eff['token_weights']
        weights = tuple(float(tw.get(k, d)) for k, d in zip(('input', 'cache_write', 'cache_read', 'output'), DEFAULT_WEIGHTS))
    else:
        weights = DEFAULT_WEIGHTS
    task_re = task_regex(discover_task_prefixes(root, cfg, a.task_prefixes))

    narrowed = True
    roots = a.transcripts
    if not roots:
        roots, narrowed = default_transcript_roots(root)
    files = []
    for r in roots:
        if os.path.isfile(r):
            files.append(r)
        elif os.path.isdir(r):
            files += glob.glob(os.path.join(r, '**', '*.jsonl'), recursive=True)
    files = sorted(set(os.path.abspath(f) for f in files))
    if not files:
        print('usage_ledger: no *.jsonl transcripts found under: ' + ', '.join(roots), file=sys.stderr)
        print('usage_ledger: pass --transcripts <dir> (Claude Code keeps them in ~/.claude/projects/<project-folder>)', file=sys.stderr)
        return 3
    if not narrowed and not a.transcripts and not a.quiet:
        print('usage_ledger: no per-project transcript folder for %s - exporting every project under %s' % (root, roots[0]))

    out = a.out or os.path.join(root, eff.get('ledger_path') or DEFAULT_LEDGER_PATH)
    os.makedirs(out, exist_ok=True)
    results = [res for res in (analyze(f, weights, task_re) for f in files) if res]
    # resumed/forked sessions repeat the same history: keep the longest copy, mark the rest as duplicates
    results.sort(key=lambda r: (r['first_timestamp'] or '', -r['turns']))
    seen = set()
    n = 0
    for res in results:
        key = (res['first_timestamp'], res['first_user_message_prefix'])
        if key in seen:
            res['duplicate_of_resumed_session'] = True
        seen.add(key)
        res['role'] = a.role
        res['task_id'] = a.task
        res['project_root'] = root
        with open(os.path.join(out, res['session_id'] + '.json'), 'w', encoding='utf-8') as fh:
            json.dump(res, fh, ensure_ascii=False, indent=1)
        n += 1
        if not a.quiet:
            print('%s turns=%4d weighted=%12s out=%9s images=%3d compactions=%d top=%s%s' % (
                res['session_id'][:8], res['turns'], format(res['weighted_total'], ','),
                format(res['raw_tokens'].get('output', 0), ','), res['images_read'], res['compactions_detected'],
                list(res['weighted_by_group'])[:3], ' DUP' if res.get('duplicate_of_resumed_session') else ''))
    print('ledger: %d session file(s) -> %s' % (n, out))
    return 0


if __name__ == '__main__':
    sys.exit(main())
