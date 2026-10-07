# Decision Record — one row of the decisions journal

The decisions journal `<vault>/03-ADR/decisions-log.md` is the chronological list of CTO decisions that do not need
an Architectural Decision Record: the operating profile, efficiency limits, accepted usage-audit proposals,
deferrals, glossary terms and wording, scope and priority calls. One decision is one row, appended at the bottom
by the coordinator. `init-project` creates the file; the dashboard links it as `[[decisions-log]]`.

---

## 1. Journal Row or ADR?

| The decision … | Record it as |
| :--- | :--- |
| changes the architecture, a service boundary or an integration contract | ADR — [`adr-record.md`](./adr-record.md) in `<vault>/03-ADR/` |
| changes the data schema, a migration or the rollback strategy | ADR |
| touches security: authentication, authorization, secrets, personal or regulated data | ADR |
| needed a debate of two turns (proposal and counter-proposal) before the CTO ruled | ADR |
| overrides the team's advice (Stubborn Donkey gate) | `ADR-OVERRIDE` ([`deep-reasoning-and-override.md`](../workflows/deep-reasoning-and-override.md)) |
| anything else — operating profile, R1–R5 limits, usage-audit proposals, deferrals, glossary terms, disputed wording, priorities and scope, tool defaults, an "experiment in prod" that changed product behavior | journal row |

An ADR replaces the row; it is not repeated in the journal (the dashboard lists ADRs next to the journal). When a
journal topic later grows into a trade-off that needs an ADR, the ADR cites the row (`D-NNN`) and the row stays.

---

## 2. Row Format

```markdown
| ID | Date | Topic | Decision | Decided by | Context | Follow-up / review date |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| D-{NNN} | {YYYY-MM-DD} | {Topic} | {What was decided, with the numbers that make it checkable} | {CTO / User / Virtual CTO} | {[[note with the evidence]]} | {date, trigger or —} |
```

| Column | Rule |
| :--- | :--- |
| **ID** | `D-` plus three digits, sequential per project, never reused or renumbered. |
| **Date** | The day the decision was made (`YYYY-MM-DD`), not the day it was written down. |
| **Topic** | One to four stable words so rows of a topic can be found together: `Operating profile`, `Efficiency R2`, `Deferral BUG-112`, `Glossary`, `Scope ATM-031`. |
| **Decision** | The outcome, not the discussion: limits, versions, dates, who is affected. Superseding rows say `supersedes D-NNN`. A `\|` inside a cell is escaped. |
| **Decided by** | The decision owner ([`agents/cto.md`](../agents/cto.md)): in `cto_mode: "USER"` the user as CTO; the Virtual CTO only within `delegated_authorities`. |
| **Context** | A wikilink to the note that holds the evidence — task, bug, usage audit, content review, QA report, ADR — or the session path. |
| **Follow-up / review date** | When the decision is looked at again: a date, a trigger ("at 50 active users", "next usage audit") or `—`. |

---

## 3. Rules

1.  **Single writer.** The coordinator writes the journal; other roles propose decisions in their reports and
    the CTO decides.
2.  **Append only.** A changed decision is a new row that names the row it supersedes; the old row stays (the
    vault never deletes).
3.  **Always a row:** confirming or switching the operating profile, changing an R1–R5 limit, approving or
    rejecting a usage-audit proposal (its `Decision` column cites the row id), signing a `Minor` deferral,
    approving a glossary term.
4.  **Same session.** The row is written in the session that received the decision, before the work that
    depends on it starts.

---

## 4. Examples

| ID | Date | Topic | Decision | Decided by | Context | Follow-up / review date |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| D-001 | 2026-10-07 | Operating profile | Project runs in the pilot profile: 5 active users, no live payments, no SLA, no regulated data. | CTO | [[00-Dashboard]] | review at 50 active users or when payments go live |
| D-002 | 2026-10-09 | Efficiency R2 | Screenshot budget 14 per scenario for the onboarding flow until ATM-031 ships; 10 everywhere else. | CTO | [[usage-audit-2026-10-08]] | next usage audit |
| D-003 | 2026-10-10 | Deferral BUG-112 | Minor content defect BUG-112 (secondary screen wording) deferred to the next release. | CTO | [[content-review-2026-10-10-ab12cd3]] | release after v0.4.0 |
| D-004 | 2026-11-02 | Operating profile | Production profile from 2026-11-03: Payme payments go live; supersedes D-001. | CTO | [[ADR-006-payments-payme\|ADR-006]] | — |
