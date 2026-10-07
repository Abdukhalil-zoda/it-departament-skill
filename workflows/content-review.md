# Workflow Guide: Content & Localization Review (two checkpoints)

Text is the part of a product every user touches, and it is the part an engineering pipeline checks least:
tests pass with an untranslated button, screenshots look fine with a mistranslated label, and AI-generated
content ships in the wrong language without any build breaking. The first production project of this skill
showed exactly that: UI not switching to the second language, mixed-script screens, a localized bank name
shown in the wrong alphabet, and generated content whose "uz" variant contained Russian. The Content &
Localization Reviewer ([`agents/content-reviewer.md`](../agents/content-reviewer.md)) closes that gap at
two points of the pipeline and reports to the CTO.

```mermaid
flowchart LR
    SPEC["System Analyst: spec with<br/>User-Facing Content table"] --> A["Checkpoint A<br/>Intake content review"]
    A -->|approved| RFD["Ready-For-Dev"]
    A -->|changes-requested<br/>(max 1 cycle)| SPEC
    RFD --> DEV["Development: strings copied<br/>from the approved table"] --> QA["QA on candidate SHA"]
    DEV --> B["Checkpoint B<br/>Pre-release content review<br/>(same candidate SHA)"]
    QA --> GATE["CTO release gate"]
    B -->|approved / deferrals signed| GATE
    B -->|blocked: Critical/Major| BUG["Bug notes, category: content"] --> DEV
```

---

## 1. When a task needs content review

| Task touches… | `content_review` | Checkpoint A | Checkpoint B |
| :--- | :--- | :--- | :--- |
| Any user-visible text or localized resource (UI, messages, notifications, emails, store texts) | `required` | yes — strings table reviewed and finalized before `Ready-For-Dev` | yes — part of every candidate |
| Seeded / imported / AI-generated content that reaches users | `required` | yes — content rules and samples in the spec | yes — data sources scanned and sampled |
| Backend logic, schema, infra, internal tooling with no user-visible text | `not-applicable` (state why) | no | the candidate review still covers all texts of the release |

The System Analyst sets `content_review` and fills §6 of the task template; the coordinator refuses the
`Ready-For-Dev` transition while `content_review_intake` is `pending` or `changes-requested` for a required task.
Lightweight-route tasks are not exempt: a copy change is precisely a content change, reviewed in short form.

**Depth by operating profile** ([`operating-profiles.md`](./operating-profiles.md)):
*   `prototype` — Checkpoint A in short form; Checkpoint B only on the strings changed since the baseline.
*   `pilot` — both checkpoints; short form allowed for lightweight tasks.
*   `production` — both checkpoints as specified below.

*Short form* means the same checks on the strings in scope (every locale, placeholders, glossary), recorded as a
verdict and a findings list instead of the full report template.

---

## 2. Checkpoint A — intake review of the task

| | |
| :--- | :--- |
| **Input** | Task note (§1 context, §6 strings table, §7 acceptance criteria), glossary, style guide, existing resource keys. |
| **Work** | Completeness per locale, placeholders, length limits, plural forms; wording in each locale; the spec's own clarity; final text proposed in the table. |
| **Output** | `content-review-intake.md` in the reviewer's session directory; frontmatter `content_review_intake: approved` or `changes-requested` applied by the coordinator; glossary proposals. |
| **Limits** | One revision cycle with the System Analyst; unresolved disagreement → CTO decision (the CTO owns product wording). |

Developers then **copy user-facing strings from the approved table** into resource files for every locale.
They do not author UI text themselves; a string that is not in the table goes back to the reviewer.

---

## 3. Checkpoint B — pre-release review of the candidate

Runs on the frozen release candidate SHA, in parallel with QA
([`review-qa-and-release.md`](./review-qa-and-release.md) Step 3b), and is invalidated by the same rule as
QA evidence (new candidate SHA → new review, limited to what changed).

1.  **Inventory** — `scripts/content_inventory.py --root <project_root> --base <production_baseline_sha>` writes
    `<vault>/05-Reports/content-inventory-<date>-<sha7>.md` (+ `.json`): per resource group and locale the
    missing, extra, empty, identical-to-source, placeholder-mismatch, wrong-script, whitespace, punctuation
    and length findings; every string added, changed or removed since the baseline; hardcoded text
    candidates in markup; wrong-language strings inside content data sources.
2.  **Read** — every added or changed string in every locale, the primary flows even when unchanged, a sample
    of the rest, the content data sources by sample. Screenshots: QA's, within rule R2.
3.  **Log** — each Critical / Major / Minor finding as a bug note (`category: content`, `locale`, key, current and
    proposed text); Trivial findings stay in the report.
4.  **Report** — `<vault>/05-Reports/content-review-<date>-<sha7>.md` from
    [`templates/content-review-report.md`](../templates/content-review-report.md): locales and confidence,
    counts by severity, findings, deferrals requested, verdict (`approved`, `approved-with-deferrals`, `blocked`).
5.  **Record & send** — evidence attached to the candidate SHA and a ≤ 15-line message to the CTO with the verdict
    and the deferrals to sign. The dashboard row is generated from the report's frontmatter (`checkpoint`, `scope`,
    `locales_reviewed`, `findings`, `verdict`, `date`) by `scripts/dashboard_sync.py`, which the coordinator runs.

The CTO release gate requires the content verdict next to the QA verdict: `blocked` stops the release like a
`Critical`/`Major` functional defect; `approved-with-deferrals` needs the CTO's explicit sign-off on each
deferred `Minor`, recorded in the report and the bug notes.

---

## 4. The inventory script

```bash
python3 <skill_root>/scripts/content_inventory.py --root <project_root>                       # full inventory
python3 <skill_root>/scripts/content_inventory.py --root <project_root> --base v1.4.0          # + strings changed since the last release
python3 <skill_root>/scripts/content_inventory.py --root <project_root> --out <file.md> --max-examples 50
```

Supported sources (globs in `content_review.text_sources`): .NET `.resx` (`Name.resx` = source locale,
`Name.<locale>.resx`), Android `res/values[-<locale>]/strings.xml`, JSON i18n (`<locale>.json`,
`<name>.<locale>.json`, or one file keyed by locale), iOS `<locale>.lproj/*.strings`, and **inline code
tables** such as `["Key"] = ("ru text", "uz text")` declared in `content_review.inline_tables`. Markup files
(`markup_sources`) are scanned for literal text in text-bearing attributes and element bodies — candidates
for strings that bypass localization. JSON content data (`content_data_sources`) is scanned for per-locale
subtrees (`{"ru": …, "uz": …}`) whose strings use the wrong writing system for that locale.

The script finds what can be found mechanically; it does not judge wording. Developers run it before
hand-off when they touched strings (`findings` for their keys must be zero); the reviewer runs it on the
candidate.

---

## 5. Glossary and style guide

`<vault>/06-Content/glossary.md` holds the product terms per locale (term, locale variants, definition,
do-not-use list) and `<vault>/06-Content/style-guide.md` the writing rules (tone, person, capitalization,
punctuation, numbers and dates, placeholders, plural forms, length limits, per-locale notes). Both are
created by `init-project` from the vault template and maintained by the Content Reviewer; a change to a
product term is a CTO decision recorded in the decisions journal or an ADR. Every intake review checks the
spec against them; every pre-release review checks the candidate against them.

---

## 6. Severity, blocking and waivers

Content defects use the canonical severity scale of
[`references/contracts-and-lifecycle.md`](../references/contracts-and-lifecycle.md); the examples per level
are in the reviewer's role file (section 5). `content_review.block_release_on` (default `Critical`, `Major`)
lists the severities that block; `Minor` can be deferred only with an explicit CTO sign-off recorded in the
review report and in the bug note (`release_blocking: false`, deferral reason).

---

## 7. Configuration (`content_review` block of `config.json`)

```json
"content_review": {
  "enabled": true,
  "source_locale": "en",
  "locales": ["en"],
  "locale_scripts": {},
  "checkpoints": ["task-creation", "pre-release"],
  "block_release_on": ["Critical", "Major"],
  "glossary_path": "vault/06-Content/glossary.md",
  "style_guide_path": "vault/06-Content/style-guide.md",
  "text_sources": ["**/*.resx", "**/i18n/**/*.json", "**/locales/**/*.json", "**/res/values*/strings.xml", "**/*.lproj/*.strings"],
  "inline_tables": [],
  "markup_sources": ["**/*.xaml", "**/*.razor", "**/*.cshtml", "**/*.html", "**/*.vue", "**/*.tsx", "**/*.jsx"],
  "content_data_sources": [],
  "exclude": ["**/bin/**", "**/obj/**", "**/node_modules/**", "**/dist/**", "**/build/**", "**/.git/**", "**/.it-department/**", "**/vault/**"]
}
```

*   `locales` — every locale the product ships; `source_locale` is the one authors write first.
*   `locale_scripts` — override the expected writing system per locale when the default inference is wrong
    (e.g. `{"uz": "Latin", "sr": "Cyrillic"}`); unknown locales skip the script check.
*   `inline_tables` — `[{"path": "src/App/Localization/UiText.cs", "locales": ["ru", "uz"]}]` for code-defined tables.
*   `content_data_sources` — JSON files with per-locale subtrees that ship to users (seeded banks, catalogs).
*   `checkpoints` — remove `task-creation` only for projects without user-facing text in their tasks; the
    pre-release checkpoint stays as long as `enabled` is true.

---

## 8. Interaction with the other roles

| Role | Gives the reviewer | Gets from the reviewer |
| :--- | :--- | :--- |
| System Analyst | spec with §6 strings table, `content_review` flag | intake verdict, final wording, glossary proposals |
| Developers | strings copied verbatim from the table into every locale, inventory run before hand-off | content bug notes with proposed text |
| QA Engineer | screenshots of the candidate; content defects it notices logged with `category: content` | confirmation or re-classification of those defects |
| Coordinator | candidate SHA, baseline SHA, dispatch at both checkpoints | verdicts and evidence files (dashboard rows are generated from the report frontmatter by `scripts/dashboard_sync.py`) |
| CTO | decisions on deferrals, glossary terms, disputed wording | the ≤ 15-line pre-release report, the review file |

Single-writer rule: the reviewer writes only its own session directory, new bug notes, the review and
inventory files under `05-Reports/`, and the content reference files under `06-Content/`. Task notes and the
dashboard are updated by the coordinator from the reviewer's evidence.
