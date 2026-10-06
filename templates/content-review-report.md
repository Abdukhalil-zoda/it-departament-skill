---
id: CR-{YYYY-MM-DD}-{scope}        # scope = {TASK-ID} for an intake review, RC-{sha7} for a pre-release review
checkpoint: pre-release            # task-creation | pre-release
scope: "{TASK-ID or candidate SHA}"
baseline: "{production baseline SHA, pre-release only}"
locales_reviewed: ["{locale}", "{locale}"]
reviewer_confidence:               # fluent | working | limited, per locale
  "{locale}": fluent
  "{locale}": limited
findings: { critical: 0, major: 0, minor: 0, trivial: 0, needs_native_check: 0 }
verdict: approved                  # intake: approved | changes-requested   pre-release: approved | approved-with-deferrals | blocked
cto_signoff: ""                    # who signed the deferrals and when (pre-release only)
inventory: "[[content-inventory-{date}-{sha7}]]"   # pre-release only
date: "{YYYY-MM-DD}"
tags:
  - content-review
---

# Content review — {checkpoint}: {scope}

## 1. Scope & method
- **What was reviewed:** {task strings table and spec text | all strings added or changed since `{baseline}` in every locale, primary flows, content data sources}
- **Sources:** {resource files / inline tables / data files, from the inventory}
- **Locales & confidence:** {locale}: fluent · {locale}: limited (mechanical checks only, native check requested)
- **Screenshots used:** {QA set for candidate `{sha7}` — none taken by the reviewer | n/a}
- **Glossary / style guide version:** {date of last change}

## 2. Inventory summary (pre-release) / Strings table status (intake)
{Pre-release: copy the one-line totals of the inventory: strings, findings by check, changed since baseline, markup candidates, data findings.}
{Intake: strings in the table: N; locales complete: yes/no; placeholders consistent: yes/no; length limits given: yes/no.}

## 3. Findings
| # | Severity | Locale | Location (file / key / screen / data path) | Current text | Proposed text | Reason (glossary, meaning, script, placeholder, tone, truncation…) | Bug |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| 1 | Major | uz | `AppResources.uz.resx` / `BankTitle` | ПДД Узбекистана | O‘zbekiston YHQ | Cyrillic text in Latin-script locale; glossary term "YHQ" | [[BUG-{id}]] |
| 2 | Minor | ru | `Study.xaml` / `FabStart` | Начать сессию | Начать занятие | glossary: "занятие", not "сессия" | [[BUG-{id}]] |

Trivial findings (report only): {list or "none"}.
Items marked `needs native check`: {locale: keys…}.

## 4. Decisions requested from the CTO
- **Deferrals (Minor):** {#2 — reason; proposed fix task or next release}
- **Glossary / style-guide changes:** {new term, locale variants, definition}
- **Disputed wording:** {item, options, recommendation}

## 5. Verdict
**{approved | approved-with-deferrals | blocked | changes-requested}** — {one sentence: what blocks, or what was signed}.
{Pre-release: evidence attached to candidate `{sha7}`; dashboard row requested from the coordinator.}

---

### Message to the CTO (≤ 15 lines, sent separately)
```text
Content review {checkpoint} {scope}: {verdict}.
Locales: {ru fluent, uz limited}. Findings: {C 0 / M 1 / m 2 / T 3}, native check needed: {n}.
1. {top finding, one line}
2. {…}
Deferrals to sign: {#2, #3}. Glossary proposals: {term}.
Report: {vault path}.
```
