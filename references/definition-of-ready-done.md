# Canonical Reference: Definition of Ready & Definition of Done

The lifecycle in [`contracts-and-lifecycle.md`](./contracts-and-lifecycle.md) says *when* a task may move; this
document says *what must be true* before it moves. The **Definition of Ready (DoR)** gates `Ready-For-Dev`; the
**Definition of Done (DoD)** gates every later transition. The depth of each item follows the project's operating
profile (`prototype`, `pilot`, `production`; matrix and floors in
[`workflows/operating-profiles.md`](../workflows/operating-profiles.md)). This page names per item what each
profile requires; it never relaxes a floor (backup before destructive work, secrets, the Stubborn Donkey gate,
`delegated_authorities`).

---

## 1. Who Checks What

The **System Analyst** proposes readiness: it fills the task note from
[`templates/task-specification.md`](../templates/task-specification.md) and states in its hand-off which DoR items
are covered and which sections are *"Not applicable."* and why. Every implementation role proves done-ness with
evidence files in its session directory (section 4). The **Coordinator** verifies both before it applies a
transition: it reads the evidence, rejects stale or incomplete requests and never fills a gap on the author's
behalf. **`scripts/vault_lint.py`** checks the mechanical parts on every `validate-project` run — required
frontmatter fields (VL002), id and file name (VL003, VL004), status versus folder (VL005), links (VL006),
severity versus release blocking (VL007), the content intake verdict past `In-Analysis` (VL008), dates (VL011) —
and `scripts/apply_transitions.py` refuses a request whose evidence file, intake verdict, QA status or release
fields are missing. Judgement items (testable criteria, verified facts, a sound feasibility score) stay with the
analyst, the reviewer and the CTO.

---

## 2. Definition of Ready (→ `Ready-For-Dev`)

Profile columns: **full** — as the template describes it; **short** — one to three lines, or *"Not applicable."*
with one sentence why; **optional** — may be left out. *"Not applicable."* is always the right content for a
section the task does not touch; the profile decides how much detail a touched section needs. **Lint** names the
`vault_lint.py` check that enforces the mechanical part.

### 2.1 Full route (12 items)

| # | Item | Template | prototype | pilot | production | Lint |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| 1 | **Context & motivation** — why, which user problem, which components and dependencies interact. | §1 | short | full | full | — |
| 2 | **Facts vs. assumptions** — artifacts verified in the repository, proposed artifacts, assumptions; open questions listed and none blocking. | §2 | optional | full | full | — |
| 3 | **Database & schema** — tables, columns, indexes, migration file, rollback or forward-fix — or *"Not applicable."* with why. | §3 | optional | short | full | — |
| 4 | **Endpoints** — method, route, permission key, behavior — or *"Not applicable."* with why. | §4 | optional | short | full | — |
| 5 | **Code locations** — exact files, classes and methods to touch. | §5 | optional | full | full | — |
| 6 | **User-facing content** — strings table complete in every configured locale and `content_review_intake: approved` (Checkpoint A), or `content_review: not-applicable` with why. | §6 | full | full | full | VL008 |
| 7 | **Acceptance criteria** — numbered, testable pass/fail sentences, including the localization criterion when §6 applies. | §7 | full | full | full | — |
| 8 | **JSON contracts** — request, response and error payloads — or *"Not applicable."* | §8 | optional | short | full | — |
| 9 | **Dependencies & blockers** — linked notes (`[[ID]]`) or *None*. | §9 | optional | full | full | VL006 |
| 10 | **Feasibility** — score ≥ 8/10 recorded, the advised alternative adopted, or an `ADR-OVERRIDE` linked. | task note / ADR | full | full | full | — |
| 11 | **Route & priority** — `route: full` and `priority` set; the brief names the profile's gates. | frontmatter | full | full | full | VL002 |
| 12 | **Assignee & branch** — `assigned_agent` set and `branch` from the formula `feature/{task-id}/{dd.mm.yyyy}/{agent}`. | frontmatter | full | full | full | VL002 |

A prototype task that changes the schema still meets the backup floor: the migration is applied only after a
named, restorable backup exists.

### 2.2 Lightweight route (6 items)

| # | Item | Template | prototype | pilot | production | Lint |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| 1 | **Context** — one or two sentences: what changes, where, why; feasibility in one line (anything below 8/10 is not lightweight). | §1 | short | short | short | — |
| 2 | **Code locations** — the files to touch, verified in the repository. | §5 | optional | full | full | — |
| 3 | **Route fit** — §3 Database, §4 Endpoints and §8 JSON contracts are *"Not applicable."*; otherwise re-route the task to the full route. | §3, §4, §8 | full | full | full | — |
| 4 | **User-facing content** — strings table in every locale with a short-form intake verdict whenever text changes, or `content_review: not-applicable` with why. | §6 | full | full | full | VL008 |
| 5 | **Acceptance criteria** — at least one testable criterion plus what must stay unchanged (screen, endpoint, file). | §7 | full | full | full | — |
| 6 | **Frontmatter** — `route: lightweight`, `priority`, `assigned_agent`, `branch` set; `status: Ready-For-Dev` in `01-Tasks/Ready-For-Dev/`. | frontmatter | full | full | full | VL002, VL005 |

---

## 3. Definition of Done per Transition

Each transition is requested with `transition-request.json` in the requesting role's session directory
(`<sessions>/<task-id>/<agent-role>/<session-id>/`, contract in
[`contracts-and-lifecycle.md`](./contracts-and-lifecycle.md) §4) and applied by the coordinator. Every DoD ends
with the same two items: **usage ledger exported** (`scripts/usage_ledger.py --role <role> --task <task-id>`)
and **transition request written**, its `evidence_file` naming the evidence file of the table. Profile-dependent
depth (review, coverage, test environment, QA scope, deploy) follows the matrix in
[`workflows/operating-profiles.md`](../workflows/operating-profiles.md).

### 3.1 `In-Development` → `Code-Review` (developer)

| # | Done when | Evidence |
| :--- | :--- | :--- |
| 1 | Work is committed on the task branch in the task's worktree; the PR targets the integration branch. | `handoff.md`: branch, commit SHAs, PR link |
| 2 | Pre-deploy checks pass in the worktree: lint, typecheck/compile, tests; coverage gate per profile (`quality_gates.test_coverage_threshold_percent`). | `handoff.md`: commands, pass/fail counts, coverage; log tails within R4 |
| 3 | User-facing strings are copied verbatim from the approved §6 table into every locale; `scripts/content_inventory.py` shows no missing, empty, placeholder or wrong-script finding for the task's keys (tasks with `content_review: required`). | `handoff.md`: inventory summary line |
| 4 | Diff summary, known limitations and follow-ups are written; builds per fix round stayed within R1. | `handoff.md` |
| 5 | Usage ledger exported; transition request `In-Development → Code-Review`. | `transition-request.json` (`evidence_file: handoff.md`) |

### 3.2 `Code-Review` → `QA-Testing` (reviewer, coordinator)

| # | Done when | Evidence |
| :--- | :--- | :--- |
| 1 | The review verdict on the diff is recorded: approved, or changes requested (at most 2 revision cycles, then CTO escalation). A peer review where the profile requires one; a coordinator diff read where the profile allows it. | `code-review.md` in the reviewer's session directory |
| 2 | The branch is merged into the integration branch; the merge commit SHA is recorded. | `code-review.md` |
| 3 | The integration build is deployed to the test environment the profile requires (in `pilot`, production after a verified backup may serve as the test environment). | deploy log tail and backup name in `code-review.md` |
| 4 | Usage ledger exported; transition request `Code-Review → QA-Testing`. | `transition-request.json` (`evidence_file: code-review.md`) |

### 3.3 `QA-Testing` → `Ready-For-Release` (QA engineer)

| # | Done when | Evidence |
| :--- | :--- | :--- |
| 1 | The QA report is written from [`templates/qa-report.md`](../templates/qa-report.md) with `verdict: passed` or `passed-with-deferrals` and the profile's `qa_scope` (`smoke`, `targeted`, `full`). | `qa-report.md` |
| 2 | Every acceptance criterion of §7 has a scenario row with a result and evidence. | `qa-report.md` §2 |
| 3 | No open `Critical`/`Major` defect is linked to the task; every deferred `Minor` carries the CTO's `deferral_signoff` and a decisions journal row; `Trivial` defects are in the backlog. | bug notes (VL007), `qa-report.md` §3 |
| 4 | Re-verification after fix rounds was targeted (R3) and screenshots stayed within the R2 budget. | `qa-report.md` §4–5 |
| 5 | The pre-release content review verdict (`approved` or `approved-with-deferrals`) is attached to the same candidate SHA. | `<vault>/05-Reports/content-review-<date>-<sha7>.md` |
| 6 | Usage ledger exported; transition request `QA-Testing → Ready-For-Release` with `qa_status: passed` and `candidate_sha`. | `transition-request.json` (`evidence_file: qa-report.md`) |

### 3.4 `Ready-For-Release` → `Archived` (DevOps engineer, coordinator)

| # | Done when | Evidence |
| :--- | :--- | :--- |
| 1 | The CTO release gate passed for the candidate SHA within `delegated_authorities` (a profile never grants authority). | gate decision in `deploy.md`; decisions journal row for deferrals |
| 2 | The release-level QA report and content review exist for the deployed SHA. | `<vault>/05-Reports/qa-report-<date>-<sha7>.md`, `content-review-<date>-<sha7>.md` |
| 3 | A named, restorable backup (DB dump, volume snapshot, export) was taken before the deploy wherever the profile or a migration requires it; the rollback path is written down. | `deploy.md`: backup name, rollback step |
| 4 | The deployed artifact is the candidate SHA; the production branch is fast-forwarded and tagged; health and logs were watched for 15 minutes. | `deploy.md`: deploy log tail, tag, watch result |
| 5 | The note carries `status: Archived`, `release_version`, `release_commit`, `archived_at`, sits in `04-Archive/Completed-Tasks/`, and the dashboard is regenerated with `scripts/dashboard_sync.py`. | task note (VL005, VL011) |
| 6 | Usage ledger exported; transition request `Ready-For-Release → Archived` with `release_version` and `release_commit`. | `transition-request.json` (`evidence_file: deploy.md`) |

### 3.5 Bug: `Retesting` → `Closed` (QA engineer)

| # | Done when | Evidence |
| :--- | :--- | :--- |
| 1 | The reproduction steps of the bug note pass on the test environment, plus one smoke path of the affected feature (R3). | `qa-report.md` (task level) |
| 2 | The fix PR contains a test that covers the defect (checked when the bug was in `Code-Review`). | PR link in the bug note |
| 3 | Content defects: the approved text is in every affected locale and the inventory is clean for the key. | inventory summary line in `qa-report.md` |
| 4 | The bug note has `date_resolved` set and a consistent `severity` / `release_blocking` pair. | bug note (VL007, VL011) |
| 5 | Usage ledger exported; transition request `Retesting → Closed`. | `transition-request.json` (`evidence_file: qa-report.md`) |

A closed bug is archived with its release: section 3.4 items 4–6 apply, and the note moves to
`04-Archive/Resolved-Bugs/` with `status: Archived`.

---

## 4. Evidence Files

| File | Written by | Location |
| :--- | :--- | :--- |
| `handoff.md` | developer | `<sessions>/<task-id>/<dev-role>/<session-id>/` |
| `code-review.md` | reviewer (peer developer, architect or coordinator) | `<sessions>/<task-id>/<reviewer-role>/<session-id>/` |
| `qa-report.md` | QA engineer | task level: `<sessions>/<task-id>/qa-engineer/<session-id>/`; release level: `<vault>/05-Reports/qa-report-<date>-<sha7>.md` |
| `content-review-intake.md` | Content Reviewer | `<sessions>/<task-id>/content-reviewer/<session-id>/` |
| `content-review-<date>-<sha7>.md` | Content Reviewer | `<vault>/05-Reports/` |
| `deploy.md` | DevOps engineer | `<sessions>/<task-id or RC-sha7>/devops-engineer/<session-id>/` |
| `transition-request.json` | every role | its session directory, next to the evidence file |
| usage ledger JSON | every session | `<project_root>/{efficiency.ledger_path}/` |
| decisions journal row | coordinator | `<vault>/03-ADR/decisions-log.md` ([`templates/decision-record.md`](../templates/decision-record.md)) |
