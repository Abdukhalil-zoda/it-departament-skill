#!/usr/bin/env python3
"""content_inventory.py - inventory and sanity checks of user-facing text for the Content Reviewer.

Part of the IT Department skill (workflows/content-review.md). Collects every localized string of the
project, compares each locale with the source locale and reports what a reviewer should look at first.
It is deterministic and language-agnostic: it finds missing, empty, untranslated and malformed strings;
judging naturalness, tone and meaning stays with the Content Reviewer.

Usage:
  python3 content_inventory.py [--root PROJECT_ROOT] [--out FILE] [--base GIT_REF]
                               [--max-examples N] [--no-json]

Sources (from the content_review block of <root>/.it-department/config.json):
  text_sources           globs of resource files: .resx (Name.<locale>.resx), Android res/values-<locale>/strings.xml,
                         JSON i18n (<locale>.json, <name>.<locale>.json or one file keyed by locale), iOS <locale>.lproj/*.strings
  inline_tables          [{"path": "...", "locales": ["ru", "uz"]}] - code tables such as ["Key"] = ("ru text", "uz text")
  markup_sources         globs of markup files scanned for hardcoded user-facing text candidates
  content_data_sources   globs of JSON data files whose objects carry per-locale subtrees (e.g. "variants": {"ru": .., "uz": ..})
  exclude                globs never scanned (bin, obj, node_modules, vault, .it-department by default)

Checks per locale against the source locale: missing keys, extra keys, empty values, values identical to the
source (untranslated?), placeholder mismatches ({0}, {name}, %s, %1$d, {{var}}, ${var}, %@), wrong writing
system for the locale (e.g. Cyrillic text in a Latin-script locale), leading/trailing/double whitespace,
trailing punctuation mismatch, extreme length ratios. With --base, strings added/changed/removed since that
git ref are listed (the pre-release scope).

Output: markdown (+ .json sidecar) under <content_review.reports_path or efficiency.reports_path>, default
content-inventory-<date>.md. Exit codes: 0 ok, 2 bad arguments. Python 3.8+, standard library only.
"""
import argparse
import collections
import datetime
import json
import os
import re
import subprocess
import sys
import unicodedata
import xml.etree.ElementTree as ET

DEFAULT_TEXT_SOURCES = ['**/*.resx', '**/i18n/**/*.json', '**/locales/**/*.json', '**/res/values*/strings.xml', '**/*.lproj/*.strings']
DEFAULT_MARKUP_SOURCES = ['**/*.xaml', '**/*.razor', '**/*.cshtml', '**/*.html', '**/*.vue', '**/*.tsx', '**/*.jsx']
DEFAULT_EXCLUDE = ['**/bin/**', '**/obj/**', '**/node_modules/**', '**/dist/**', '**/build/**', '**/.git/**',
                   '**/.it-department/**', '**/vault/**', '**/*.Designer.cs']
DEFAULT_REPORTS_PATH = os.path.join('vault', '05-Reports')
CYRILLIC_LOCALES = {'ru', 'uk', 'be', 'bg', 'sr', 'mk', 'kk', 'ky', 'mn', 'tg'}
ARABIC_LOCALES = {'ar', 'fa', 'ur', 'ps'}
GREEK_LOCALES = {'el'}
HEBREW_LOCALES = {'he'}
LATIN_LOCALES = {'en', 'uz', 'de', 'fr', 'es', 'it', 'pt', 'tr', 'pl', 'nl', 'sv', 'da', 'no', 'fi', 'cs', 'sk', 'hu', 'ro',
                 'hr', 'sl', 'lt', 'lv', 'et', 'id', 'ms', 'vi', 'tk', 'az', 'sw', 'tl'}
PLACEHOLDER_RE = re.compile(r'\{\{\s*[^{}]+?\s*\}\}|\$\{[^}]+\}|\{\d+(?::[^}]*)?\}|\{[A-Za-z_][A-Za-z0-9_.]*\}|%\d+\$[sdif@]|%[sdif@]|%%')
LOCALE_TOKEN_RE = re.compile(r'^[a-z]{2,3}(?:[-_][A-Za-z0-9]{2,8})*$')
MARKUP_ATTR_RE = re.compile(r'\b(?:Text|Title|Placeholder|Content|Header|Label|ToolTip|Hint|Caption|Description|SemanticProperties\.Description|'
                            r'aria-label|alt|placeholder|title|label)\s*=\s*"([^"{@<>]{3,})"')
MARKUP_TEXT_RE = re.compile(r'>([^<>{}@\n]*?[^\W\d_]{3,}[^<>{}@\n]*?)<')
TRAILING_PUNCT = '.:!?…;'


# --------------------------------------------------------------------------- config & files
def load_config(root):
    path = os.path.join(root, '.it-department', 'config.json')
    try:
        with open(path, encoding='utf-8') as fh:
            return json.load(fh)
    except Exception:
        return {}


def norm(path):
    return path.replace('\\', '/')


def glob_to_regex(pattern):
    """Glob with '**' (any depth), '*' (within a path segment) and '?' -> compiled regex on '/'-separated paths."""
    p = norm(pattern).lstrip('/')
    i, out = 0, ''
    while i < len(p):
        if p.startswith('**/', i):
            out += '(?:.*/)?'
            i += 3
        elif p.startswith('**', i):
            out += '.*'
            i += 2
        elif p[i] == '*':
            out += '[^/]*'
            i += 1
        elif p[i] == '?':
            out += '[^/]'
            i += 1
        else:
            out += re.escape(p[i])
            i += 1
    return re.compile('^' + out + '$')


def compile_globs(patterns):
    return [glob_to_regex(p) for p in patterns if str(p).strip()]


def glob_match(rel, regexes):
    rel = norm(rel)
    return any(rx.match(rel) for rx in regexes)


def walk_files(root, include, exclude):
    inc, exc = compile_globs(include), compile_globs(exclude)
    out = []
    for dp, dn, fn in os.walk(root):
        rel_dir = norm(os.path.relpath(dp, root))
        rel_dir = '' if rel_dir == '.' else rel_dir
        prefix = rel_dir + '/' if rel_dir else ''
        dn[:] = [d for d in dn if d != '.git' and not glob_match(prefix + d + '/', exc)]
        for f in fn:
            rel = prefix + f
            if glob_match(rel, exc):
                continue
            if glob_match(rel, inc):
                out.append(rel)
    return sorted(out)


def identifier_like(value):
    """ASCII-only token without whitespace: hashes, enum values, URLs, codes - not natural-language text."""
    return bool(value) and not re.search(r'\s', value) and all(ord(ch) < 128 for ch in value)


def read_text(path):
    with open(path, encoding='utf-8-sig', errors='replace') as fh:
        return fh.read()


# --------------------------------------------------------------------------- parsers
def parse_resx(text):
    out = {}
    try:
        root = ET.fromstring(text.encode('utf-8'))
    except ET.ParseError:
        return None
    for data in root.iter('data'):
        name = data.get('name')
        if not name or data.get('type') or data.get('mimetype'):
            continue
        val = data.find('value')
        out[name] = (val.text or '') if val is not None else ''
    return out


def parse_android(text):
    out = {}
    try:
        root = ET.fromstring(text.encode('utf-8'))
    except ET.ParseError:
        return None
    for s in root.iter('string'):
        name = s.get('name')
        if name and s.get('translatable', 'true') != 'false':
            out[name] = ''.join(s.itertext()).strip()
    for arr in root.iter('string-array'):
        name = arr.get('name')
        if name:
            for i, item in enumerate(arr.findall('item')):
                out['%s[%d]' % (name, i)] = ''.join(item.itertext()).strip()
    return out


def flatten_json(obj, prefix=''):
    out = {}
    if isinstance(obj, dict):
        for k, v in obj.items():
            out.update(flatten_json(v, prefix + ('.' if prefix else '') + str(k)))
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            out.update(flatten_json(v, '%s[%d]' % (prefix, i)))
    elif isinstance(obj, str):
        out[prefix] = obj
    return out


def parse_strings(text):
    out = {}
    for m in re.finditer(r'^\s*"((?:[^"\\]|\\.)*)"\s*=\s*"((?:[^"\\]|\\.)*)"\s*;', text, re.M):
        out[m.group(1)] = m.group(2).replace('\\"', '"').replace('\\n', '\n')
    return out


def parse_inline_table(text, locales):
    out = {loc: {} for loc in locales}
    for m in re.finditer(r'\[\s*"((?:[^"\\]|\\.)*)"\s*\]\s*=\s*\(([^\n]*?)\)\s*,?\s*(?://.*)?$', text, re.M):
        key = m.group(1)
        vals = [v.replace('\\"', '"') for v in re.findall(r'"((?:[^"\\]|\\.)*)"', m.group(2))]
        for loc, val in zip(locales, vals):
            out[loc][key] = val
    return out


def locale_of(token, locales, source_locale):
    t = token.replace('_', '-')
    if t in ('values', 'Base', 'base', 'neutral', 'default'):
        return source_locale
    if locales and t not in locales and t != source_locale and t.split('-')[0] not in locales:
        return None
    return t if LOCALE_TOKEN_RE.match(t) else None


def classify_text_file(rel, locales, source_locale):
    """-> (group, locale, kind) or None."""
    relp = norm(rel)
    base = os.path.basename(relp)
    low = base.lower()
    if low.endswith('.resx'):
        stem = base[:-5]
        parts = stem.split('.')
        if len(parts) >= 2 and locale_of(parts[-1], locales, source_locale):
            return (os.path.dirname(relp) + '/' + '.'.join(parts[:-1]), locale_of(parts[-1], locales, source_locale), 'resx')
        return (os.path.dirname(relp) + '/' + stem, source_locale, 'resx')
    if low == 'strings.xml' and '/values' in relp:
        d = os.path.basename(os.path.dirname(relp))
        loc = source_locale if d == 'values' else locale_of(d[len('values-'):].replace('-r', '-'), locales, source_locale)
        return (os.path.dirname(os.path.dirname(relp)) + '/strings', loc, 'android') if loc else None
    if low.endswith('.strings'):
        d = os.path.basename(os.path.dirname(relp))
        if d.endswith('.lproj'):
            loc = locale_of(d[:-6], locales, source_locale)
            return (os.path.dirname(os.path.dirname(relp)) + '/' + base[:-8], loc, 'strings') if loc else None
        return None
    if low.endswith('.json'):
        stem = base[:-5]
        parts = stem.split('.')
        if locale_of(parts[-1], locales, source_locale) and (len(parts) >= 2 or LOCALE_TOKEN_RE.match(parts[-1])):
            group = os.path.dirname(relp) + '/' + ('.'.join(parts[:-1]) if len(parts) >= 2 else 'messages')
            return (group, locale_of(parts[-1], locales, source_locale), 'json')
        return (os.path.dirname(relp) + '/' + stem, None, 'json-multi')
    return None


def parse_text_file(kind, text, locales, source_locale):
    """-> {locale: {key: value}} (locale None means 'as classified')."""
    if kind == 'resx':
        d = parse_resx(text)
        return {None: d} if d is not None else None
    if kind == 'android':
        d = parse_android(text)
        return {None: d} if d is not None else None
    if kind == 'strings':
        return {None: parse_strings(text)}
    try:
        obj = json.loads(text)
    except Exception:
        return None
    if kind == 'json':
        return {None: flatten_json(obj)}
    if isinstance(obj, dict) and obj and all(locale_of(k, locales, source_locale) for k in obj):
        return {locale_of(k, locales, source_locale): flatten_json(v) for k, v in obj.items()}
    return None


# --------------------------------------------------------------------------- checks
def script_counts(text):
    c = collections.Counter()
    for ch in text:
        if not ch.isalpha():
            continue
        o = ord(ch)
        if 0x0400 <= o <= 0x052F:
            c['Cyrillic'] += 1
        elif 0x0600 <= o <= 0x06FF or 0x0750 <= o <= 0x077F:
            c['Arabic'] += 1
        elif 0x0370 <= o <= 0x03FF:
            c['Greek'] += 1
        elif 0x0590 <= o <= 0x05FF:
            c['Hebrew'] += 1
        elif 0x3040 <= o <= 0x30FF or 0x4E00 <= o <= 0x9FFF or 0xAC00 <= o <= 0xD7AF:
            c['CJK'] += 1
        elif o < 0x0250 or 0x1E00 <= o <= 0x1EFF:
            c['Latin'] += 1
        else:
            c['Other'] += 1
    return c


def expected_script(locale, locale_scripts):
    if not locale:
        return None
    if locale in locale_scripts:
        return locale_scripts[locale]
    parts = locale.replace('_', '-').split('-')
    for p in parts[1:]:
        if p in ('Cyrl',):
            return 'Cyrillic'
        if p in ('Latn',):
            return 'Latin'
        if p in ('Arab',):
            return 'Arabic'
    lang = parts[0]
    if lang in locale_scripts:
        return locale_scripts[lang]
    if lang in CYRILLIC_LOCALES:
        return 'Cyrillic'
    if lang in ARABIC_LOCALES:
        return 'Arabic'
    if lang in GREEK_LOCALES:
        return 'Greek'
    if lang in HEBREW_LOCALES:
        return 'Hebrew'
    if lang in LATIN_LOCALES:
        return 'Latin'
    return None


def wrong_script(value, expected):
    if not expected:
        return None
    c = script_counts(value)
    letters = sum(c.values())
    if letters < 3:
        return None
    bad = letters - c.get(expected, 0) - c.get('Other', 0)
    if bad >= 3 and bad / letters >= 0.5:
        return max((k for k in c if k != expected), key=lambda k: c[k])
    return None


def letters(value):
    return sum(1 for ch in value if ch.isalpha())


def placeholders(value):
    return sorted(PLACEHOLDER_RE.findall(value))


def check_locale(src, tgt, locale, source_locale, locale_scripts):
    """Compare one locale table with the source table -> list of findings (dicts)."""
    findings = []
    exp = expected_script(locale, locale_scripts)
    for key in sorted(src):
        if key not in tgt:
            findings.append({'check': 'missing', 'key': key, 'value': '', 'source': src[key]})
    for key in sorted(tgt):
        val = tgt[key]
        if key not in src:
            findings.append({'check': 'extra', 'key': key, 'value': val, 'source': ''})
            s = None
        else:
            s = src[key]
        if val.strip() == '':
            findings.append({'check': 'empty', 'key': key, 'value': val, 'source': s or ''})
            continue
        if val != val.strip() or '  ' in val:
            findings.append({'check': 'whitespace', 'key': key, 'value': val, 'source': s or ''})
        # writing-system check: skipped for identifier-like tokens (brands, codes) and for values identical to
        # the source, which are reported once as 'identical' instead
        ws = None if (identifier_like(val) or (s is not None and val == s and locale != source_locale)) else wrong_script(val, exp)
        if ws:
            findings.append({'check': 'script', 'key': key, 'value': val, 'source': s or '', 'detail': '%s text in %s locale (expected %s)' % (ws, locale, exp)})
        if s is None or locale == source_locale:
            continue
        if val == s and letters(s) >= 3:
            findings.append({'check': 'identical', 'key': key, 'value': val, 'source': s})
        if placeholders(val) != placeholders(s):
            findings.append({'check': 'placeholder', 'key': key, 'value': val, 'source': s,
                             'detail': 'source %s vs locale %s' % (placeholders(s) or '-', placeholders(val) or '-')})
        if s and val and (s.rstrip()[-1:] in TRAILING_PUNCT) != (val.rstrip()[-1:] in TRAILING_PUNCT):
            findings.append({'check': 'punctuation', 'key': key, 'value': val, 'source': s})
        if letters(s) >= 10:
            ratio = len(val) / max(1, len(s))
            if ratio > 2.5 or ratio < 0.3:
                findings.append({'check': 'length', 'key': key, 'value': val, 'source': s, 'detail': 'ratio %.1f' % ratio})
    return findings


def scan_markup(root, rel):
    cands = []
    try:
        text = read_text(os.path.join(root, rel))
    except Exception:
        return cands
    for i, line in enumerate(text.splitlines(), 1):
        if 'x:Uid' in line or 'Binding' in line and '{' in line and MARKUP_ATTR_RE.search(line) is None:
            pass
        for m in MARKUP_ATTR_RE.finditer(line):
            v = m.group(1).strip()
            if letters(v) >= 3 and not v.startswith(('{', '@', '$')):
                cands.append((i, v))
        if rel.lower().endswith(('.razor', '.cshtml', '.html', '.vue', '.tsx', '.jsx')):
            for m in MARKUP_TEXT_RE.finditer(line):
                v = m.group(1).strip()
                if letters(v) >= 3 and ' ' in v and not v.startswith(('{', '@', '$', '<')):
                    cands.append((i, v))
    return cands


def scan_data(obj, locales, locale_scripts, path='', out=None):
    """Find per-locale subtrees and check the writing system of every string inside them."""
    if out is None:
        out = {'strings': collections.Counter(), 'findings': []}
    if isinstance(obj, dict):
        loc_keys = [k for k in obj if isinstance(k, str) and (k in locales or (len(k) <= 3 and LOCALE_TOKEN_RE.match(k) and locales == []))]
        if len(loc_keys) >= 2:
            for k in loc_keys:
                exp = expected_script(k, locale_scripts)
                for p, v in flatten_json(obj[k], path + '.' + k).items():
                    out['strings'][k] += 1
                    ws = None if identifier_like(v) else wrong_script(v, exp)
                    if ws:
                        out['findings'].append({'check': 'script', 'key': p, 'value': v, 'locale': k,
                                                'detail': '%s text in %s subtree (expected %s)' % (ws, k, exp)})
            rest = {k: v for k, v in obj.items() if k not in loc_keys}
        else:
            rest = obj
        for k, v in rest.items():
            scan_data(v, locales, locale_scripts, path + '.' + str(k) if path else str(k), out)
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            scan_data(v, locales, locale_scripts, '%s[%d]' % (path, i), out)
    return out


def git_show(root, ref, rel):
    try:
        res = subprocess.run(['git', '-C', root, 'show', '%s:%s' % (ref, norm(rel))], capture_output=True, text=True,
                             encoding='utf-8', errors='replace', timeout=30)
    except Exception:
        return None
    return res.stdout if res.returncode == 0 else None


# --------------------------------------------------------------------------- formatting
def short(v, n=70):
    v = (v or '').replace('\n', '\\n').replace('|', '\\|')
    return v if len(v) <= n else v[:n - 1] + '…'


def main():
    ap = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    ap.add_argument('--root', default=os.getcwd())
    ap.add_argument('--out', default=None)
    ap.add_argument('--base', default=None, help='git ref of the previous release; lists strings added/changed/removed since then')
    ap.add_argument('--max-examples', type=int, default=25)
    ap.add_argument('--no-json', action='store_true')
    a = ap.parse_args()

    root = os.path.abspath(a.root)
    cfg = load_config(root)
    cr = cfg.get('content_review') or {}
    source_locale = str(cr.get('source_locale') or 'en')
    locales = [str(x) for x in (cr.get('locales') or [])]
    locale_scripts = {str(k): str(v) for k, v in (cr.get('locale_scripts') or {}).items()}
    text_sources = cr.get('text_sources') or DEFAULT_TEXT_SOURCES
    markup_sources = cr.get('markup_sources') or DEFAULT_MARKUP_SOURCES
    data_sources = cr.get('content_data_sources') or []
    inline_tables = cr.get('inline_tables') or []
    exclude = (cr.get('exclude') or DEFAULT_EXCLUDE)
    reports_dir = os.path.join(root, cr.get('reports_path') or (cfg.get('efficiency') or {}).get('reports_path') or DEFAULT_REPORTS_PATH)
    today = datetime.date.today().isoformat()
    out = a.out or os.path.join(reports_dir, 'content-inventory-%s.md' % today)
    N = a.max_examples

    # --- collect tables: group -> locale -> {key: value}
    groups = collections.defaultdict(dict)
    file_of = {}
    unsupported = []
    for rel in walk_files(root, text_sources, exclude):
        cls = classify_text_file(rel, locales, source_locale)
        if not cls:
            unsupported.append(rel + ' (unrecognised locale naming)')
            continue
        group, loc, kind = cls
        parsed = parse_text_file(kind, read_text(os.path.join(root, rel)), locales, source_locale)
        if parsed is None:
            unsupported.append(rel + ' (could not parse)')
            continue
        for ploc, table in parsed.items():
            eff_loc = ploc or loc
            if not eff_loc:
                continue
            groups[group].setdefault(eff_loc, {}).update(table)
            file_of[(group, eff_loc)] = rel
    declared = {}  # inline tables declare their own locales; configured locales they lack are not "absent"
    for it in inline_tables:
        rel, locs = norm(str(it.get('path', ''))), [str(x) for x in (it.get('locales') or [])]
        full = os.path.join(root, rel)
        if not rel or not locs or not os.path.isfile(full):
            unsupported.append(rel + ' (inline table missing or without locales)')
            continue
        declared[rel] = set(locs)
        for loc, table in parse_inline_table(read_text(full), locs).items():
            groups[rel].setdefault(loc, {}).update(table)
            file_of[(rel, loc)] = rel
    all_locales = sorted({loc for g in groups.values() for loc in g})

    # --- checks
    summary_rows, findings = [], []
    for group in sorted(groups):
        tables = groups[group]
        src_loc = source_locale if source_locale in tables else (sorted(tables)[0] if tables else None)
        src = tables.get(src_loc, {})
        for loc in sorted(tables):
            f = check_locale(src, tables[loc], loc, src_loc, locale_scripts) if loc != src_loc else \
                [x for x in check_locale({}, tables[loc], loc, src_loc, locale_scripts) if x['check'] in ('empty', 'whitespace', 'script')]
            for x in f:
                x.update({'group': group, 'locale': loc, 'file': file_of.get((group, loc), '')})
            findings += f
            counts = collections.Counter(x['check'] for x in f)
            summary_rows.append({'group': group, 'locale': loc, 'keys': len(tables[loc]), 'is_source': loc == src_loc,
                                 **{c: counts.get(c, 0) for c in ('missing', 'extra', 'empty', 'identical', 'placeholder', 'script', 'whitespace', 'punctuation', 'length')}})
        for loc in (locales or []):
            if loc not in tables and loc != src_loc and group not in declared:
                summary_rows.append({'group': group, 'locale': loc, 'keys': 0, 'is_source': False, 'missing': len(src), 'extra': 0, 'empty': 0,
                                     'identical': 0, 'placeholder': 0, 'script': 0, 'whitespace': 0, 'punctuation': 0, 'length': 0, 'absent': True})
                findings.append({'check': 'missing-locale', 'group': group, 'locale': loc, 'key': '*', 'value': '', 'source': '', 'file': ''})

    # --- changes since base
    changes = []
    base_note = ''
    if a.base:
        seen_files = sorted({f for f in file_of.values()})
        for rel in seen_files:
            cls = classify_text_file(rel, locales, source_locale)
            kind = cls[2] if cls else None
            old_text = git_show(root, a.base, rel)
            inline = next((it for it in inline_tables if norm(str(it.get('path', ''))) == rel), None)
            if inline:
                new_tables = parse_inline_table(read_text(os.path.join(root, rel)), [str(x) for x in inline['locales']])
                old_tables = parse_inline_table(old_text, [str(x) for x in inline['locales']]) if old_text else {}
            elif kind:
                new_p = parse_text_file(kind, read_text(os.path.join(root, rel)), locales, source_locale) or {}
                old_p = (parse_text_file(kind, old_text, locales, source_locale) or {}) if old_text else {}
                new_tables = {(k or cls[1]): v for k, v in new_p.items()}
                old_tables = {(k or cls[1]): v for k, v in old_p.items()}
            else:
                continue
            for loc in sorted(set(new_tables) | set(old_tables)):
                new_t, old_t = new_tables.get(loc, {}), old_tables.get(loc, {})
                for k in sorted(set(new_t) | set(old_t)):
                    if k not in old_t:
                        changes.append({'file': rel, 'locale': loc, 'key': k, 'change': 'added', 'old': '', 'new': new_t[k]})
                    elif k not in new_t:
                        changes.append({'file': rel, 'locale': loc, 'key': k, 'change': 'removed', 'old': old_t[k], 'new': ''})
                    elif new_t[k] != old_t[k]:
                        changes.append({'file': rel, 'locale': loc, 'key': k, 'change': 'changed', 'old': old_t[k], 'new': new_t[k]})
        probe = subprocess.run(['git', '-C', root, 'rev-parse', '--verify', a.base], capture_output=True, text=True)
        base_note = '' if probe.returncode == 0 else ' (git ref `%s` not found - files treated as new)' % a.base

    # --- markup candidates and data sources
    markup = {}
    for rel in walk_files(root, markup_sources, exclude):
        c = scan_markup(root, rel)
        if c:
            markup[rel] = c
    data_results = {}
    for rel in walk_files(root, data_sources, exclude) if data_sources else []:
        try:
            obj = json.loads(read_text(os.path.join(root, rel)))
        except Exception:
            unsupported.append(rel + ' (data source is not valid JSON)')
            continue
        data_results[rel] = scan_data(obj, locales, locale_scripts)

    # --- markdown
    by_check = collections.Counter(x['check'] for x in findings)
    lines = ['# Content inventory - %s' % today, '',
             'Computed by `content_inventory.py` of the IT Department skill. Source locale `%s`; configured locales: %s; locales found: %s.' % (
                 source_locale, ', '.join(locales) or '(any)', ', '.join(all_locales) or 'none'),
             'Resource groups: %d, strings: %d, findings: %d (%s). Markup files with hardcoded text candidates: %d. Data files scanned: %d.' % (
                 len(groups), sum(len(t) for g in groups.values() for t in g.values()), len(findings),
                 ', '.join('%s %d' % kv for kv in by_check.most_common()) or 'none', len(markup), len(data_results)), '',
             'The checks are mechanical. The Content Reviewer reads the texts themselves (meaning, naturalness, glossary, tone) and decides; '
             'see workflows/content-review.md.', '',
             '## 1. Summary by resource group and locale', '',
             '| Group | Locale | Keys | Missing | Extra | Empty | Identical | Placeholder | Script | Whitespace | Punct. | Length |',
             '|---|---|---|---|---|---|---|---|---|---|---|---|']
    for r in summary_rows:
        lines.append('| %s | %s%s | %d | %d | %d | %d | %d | %d | %d | %d | %d | %d |' % (
            short(r['group'], 60), r['locale'], ' (source)' if r.get('is_source') else (' (ABSENT)' if r.get('absent') else ''), r['keys'],
            r['missing'], r['extra'], r['empty'], r['identical'], r['placeholder'], r['script'], r['whitespace'], r['punctuation'], r['length']))
    if not summary_rows:
        lines.append('| (no resource files matched `text_sources`) | | | | | | | | | | | |')
    lines.append('')
    labels = [('missing-locale', 'Locales without a resource file'), ('missing', 'Keys missing in a locale'), ('empty', 'Empty values'),
              ('placeholder', 'Placeholder mismatches'), ('script', 'Wrong writing system for the locale'), ('identical', 'Values identical to the source (untranslated?)'),
              ('extra', 'Keys only in a locale (orphans)'), ('whitespace', 'Whitespace problems'), ('punctuation', 'Trailing punctuation differs from source'),
              ('length', 'Extreme length ratio vs source')]
    lines += ['## 2. Findings by check (first %d each)' % N, '']
    for check, label in labels:
        items = [x for x in findings if x['check'] == check]
        if not items:
            continue
        lines += ['### %s - %d' % (label, len(items)), '', '| Group | Locale | Key | Value | Source / detail |', '|---|---|---|---|---|']
        for x in items[:N]:
            lines.append('| %s | %s | `%s` | %s | %s |' % (short(x['group'], 40), x['locale'], short(x['key'], 50), short(x['value']), short(x.get('detail') or x.get('source', ''))))
        lines.append('')
    lines += ['## 3. Strings changed since `%s`%s' % (a.base, base_note) if a.base else '## 3. Strings changed since the previous release', '']
    if a.base:
        cc = collections.Counter(c['change'] for c in changes)
        lines += ['Added %d, changed %d, removed %d. Review every added and changed string in every locale; this is the pre-release scope.' % (
            cc.get('added', 0), cc.get('changed', 0), cc.get('removed', 0)), '']
        if changes:
            lines += ['| File | Locale | Key | Change | Old | New |', '|---|---|---|---|---|---|']
            for c in changes[:N * 4]:
                lines.append('| %s | %s | `%s` | %s | %s | %s |' % (short(c['file'], 40), c['locale'], short(c['key'], 50), c['change'], short(c['old'], 50), short(c['new'], 50)))
            if len(changes) > N * 4:
                lines.append('| … | | | %d more in the JSON sidecar | | |' % (len(changes) - N * 4))
            lines.append('')
    else:
        lines += ['_Pass `--base <production-sha>` to list the strings added, changed or removed since the last release._', '']
    lines += ['## 4. Hardcoded text candidates in markup (first %d files)' % N, '']
    if markup:
        lines += ['Literal text in markup that bypasses the resource files. Each candidate is either an untranslatable string (a defect when the product is localized) or a false positive to ignore.', '',
                  '| File | Candidates | Examples |', '|---|---|---|']
        for rel, c in sorted(markup.items(), key=lambda kv: -len(kv[1]))[:N]:
            lines.append('| %s | %d | %s |' % (short(rel, 60), len(c), '; '.join('L%d: %s' % (i, short(v, 40)) for i, v in c[:3])))
        lines.append('')
    else:
        lines += ['_No candidates found in `markup_sources`._', '']
    lines += ['## 5. Content data sources (per-locale subtrees)', '']
    if data_results:
        lines += ['| File | Strings per locale | Wrong-script findings |', '|---|---|---|']
        for rel, r in sorted(data_results.items()):
            lines.append('| %s | %s | %d |' % (short(rel, 60), ', '.join('%s %d' % kv for kv in sorted(r['strings'].items())) or '-', len(r['findings'])))
        lines.append('')
        ex = [(rel, x) for rel, r in sorted(data_results.items()) for x in r['findings']][:N]
        if ex:
            lines += ['| File | Path | Locale | Value | Detail |', '|---|---|---|---|---|']
            for rel, x in ex:
                lines.append('| %s | `%s` | %s | %s | %s |' % (short(rel, 30), short(x['key'], 45), x['locale'], short(x['value'], 50), x['detail']))
            lines.append('')
    else:
        lines += ['_No `content_data_sources` configured or matched._', '']
    if unsupported:
        lines += ['## 6. Skipped files', ''] + ['- %s' % u for u in unsupported[:N]] + ['']

    os.makedirs(os.path.dirname(out) or '.', exist_ok=True)
    with open(out, 'w', encoding='utf-8') as fh:
        fh.write('\n'.join(lines) + '\n')
    if not a.no_json:
        with open(os.path.splitext(out)[0] + '.json', 'w', encoding='utf-8') as fh:
            json.dump({'date': today, 'source_locale': source_locale, 'locales': all_locales, 'summary': summary_rows, 'findings': findings,
                       'changes': changes, 'markup_candidates': {k: [{'line': i, 'text': v} for i, v in c] for k, c in markup.items()},
                       'data_sources': {k: {'strings': dict(r['strings']), 'findings': r['findings']} for k, r in data_results.items()},
                       'skipped': unsupported}, fh, ensure_ascii=False, indent=1)
    print(out)
    print('groups=%d strings=%d findings=%d markup_files=%d data_files=%d%s' % (
        len(groups), sum(len(t) for g in groups.values() for t in g.values()), len(findings), len(markup), len(data_results),
        (' changes=%d' % len(changes)) if a.base else ''))
    return 0


if __name__ == '__main__':
    sys.exit(main())
