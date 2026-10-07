# Implementation spec: adaptive process, session protocol, dashboard automation, definitions, vault lint

Date: 2026-10-07 · Base: `master` @ `b4a5fdf` · Branch: `feature/adaptive-process-dashboard`
Status: approved by the CTO in conversation; this document is the contract for the implementing agents.

## 0. Goals and non-goals

Goals (from the CTO):
1. The dashboard is generated, not hand-edited, and **every ID, report and document in it is clickable**.
2. **Token optimization and audit results are visible on the dashboard** (last audit, delta, R1–R5, pending CTO decisions, next audit).
3. The process **adapts to the real situation** instead of behaving like a production-with-SLA bureaucracy for a product with five users: an explicit operating profile (`prototype` / `pilot` / `production`) sets the depth of every gate; in early profiles "back up the DB and work directly in prod" is a legitimate, documented path.
4. Concurrent sessions (a Cowork orchestrator plus local CLI sessions) do not corrupt the vault: a **session protocol** workflow with a tiny lock-file convention, no new runtime.
5. Things the skill already references but never defines exist: **Definition of Ready / Done**, a **decisions journal**, a **QA report template**.
6. A **vault lint** catches structural drift (frontmatter, status vs folder, links, severity consistency) and dashboard staleness.

Non-goals: security checkpoint, release-notes generator, brownfield `--detect`, skill evals, Claude Code agent generation (later iterations).

Hard constraints (apply to every agent):
- Python scripts: Python 3.8+, **standard library only**, LF line endings, same header style as `scripts/usage_ledger.py` (module docstring = usage), `--root` defaults to cwd, read `<root>/.it-department/config.json`, exit codes `0` ok / `1` findings or refused / `2` bad arguments, print the output path(s) on the last lines.
- Markdown: English, relative links, tables where the existing docs use tables, no new top-level sections in `SKILL.md` beyond what this spec lists.
- Do not touch files outside your ownership (section 8). If you believe you must, write the needed change into your final report instead.
- Commit on your worktree branch with messages ending in `Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>` is **not** required — commit messages must end with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>` (the implementing model). One commit per logical unit is fine.
- Tests: Python is **not installed on the Windows host**; run Python through Docker: from PowerShell `docker run --rm -e PYTHONDONTWRITEBYTECODE=1 -v "<windows-path-to-worktree>\scripts:/skill/scripts:ro" -v "<windows-path-to-scratch>:/work" python:3.12-alpine python /skill/scripts/<script>.py ...`; from Git Bash set `MSYS_NO_PATHCONV=1` and use Windows-style paths in `-v`. `python:3.12-slim` has bash for the `.sh` scripts. Do not run `Remove-Item` in the same PowerShell command as a `docker run` (the harness blocks it); use separate commands or Git Bash `rm -rf` on scratch paths only. Node 24 and `pwsh` 7 are on the host for `.sh` (Node engine) and `.ps1` tests. Never write into `C:\Users\AAbdukhalil-zoda\Source\AT`; it may be mounted read-only for realistic input.

---

## 1. Operating profiles (owner: Agent A; validation: Agent C; dashboard header: Agent B)

### 1.1 Config

`assets/config-template.json` gains two top-level keys right after `cto_mode_options` and one after `security`:

```json
"operating_profile": "pilot",
"profile_review": {
  "active_users": 0,
  "payments_live": false,
  "sla_promised": false,
  "regulated_data": false,
  "reviewed_at": "{YYYY-MM-DD}",
  "note": "Why this profile; what would trigger the next one"
},
"documents": [
  { "title": "Product specification", "path": "docs/requirements/spec.md" }
]
```

Schema (`assets/project-config.schema.json`): `operating_profile` string enum `["prototype", "pilot", "production"]` (optional; absent = `production`, the current behavior); `profile_review` object, `additionalProperties: false`, properties `active_users` integer ≥ 0, `payments_live` boolean, `sla_promised` boolean, `regulated_data` boolean, `reviewed_at` string, `note` string — all optional; `documents` array of `{title: string minLength 1, path: string minLength 1}` with `additionalProperties: false`.

### 1.2 Profile matrix (normative; goes into `workflows/operating-profiles.md` and is summarized in `SKILL.md`)

| Gate / rule | `prototype` | `pilot` | `production` |
| :--- | :--- | :--- | :--- |
| Criteria (any of the later column's criteria moves the project up) | no real users; data can be thrown away | real users ≤ the CTO's pilot threshold (default 50 active), no live payments, no SLA, no regulated data | live payments **or** SLA promised **or** regulated data **or** users above the pilot threshold |
| Route sizing | everything lightweight unless schema or auth is touched | lightweight by default; full route for schema, auth, payments, data migration | as today (`lightweight-vs-full-routes.md`) |
| Definition of Ready depth | context + acceptance criteria + content table | full template, DB/API sections may be "Not applicable" with one sentence why | full template |
| Architect / ADR | on CTO request only | for schema, auth, payments, integrations | as today (non-trivial trade-offs) |
| Peer code review | optional; coordinator reads the diff | required for full-route tasks; lightweight = coordinator diff read | required |
| Test coverage gate | tests for the changed logic; threshold not enforced | threshold enforced on changed projects | threshold enforced on all |
| Staging / test environment | not required | not required; prod with backup may serve as test env | required |
| QA scope on a candidate | smoke path of the changed feature | fixed defects + one smoke path per feature, full suite once before the first wide release and after that once per candidate SHA that touches shared flows | full suite once per candidate SHA (R3) |
| Content review | Checkpoint B only on strings changed since baseline, Checkpoint A short form | both checkpoints, short form allowed for lightweight tasks | both checkpoints as specified |
| Deploy to production | directly from the integration branch after smoke, **DB backup first** | after QA smoke + content verdict, **DB backup first**, rollback = restore backup or redeploy previous artifact, 15-minute watch | immutable candidate SHA, CTO gate, full rollback plan |
| "Experiment in prod" | allowed: backup → change → smoke → watch 15 min → keep or restore | allowed for changes that are reversible by restore or redeploy; announce to users only if visible downtime > 5 min | not allowed; use staging |
| Hotfix | commit on integration, deploy, backfill task note | same + QA smoke | `review-qa-and-release.md` §3.2 |
| Usage audit | same cadence; proposals may be applied by the coordinator without a decision note when they only change tool defaults | same | as today |

**Floors that no profile relaxes:** secrets never in git (`secrets-and-incidents.md`); a verified backup before any destructive operation, migration or prod experiment; no force-push, no history rewrite on shared branches; archive instead of delete in the vault; `delegated_authorities` always apply (a profile never grants authority); the Stubborn Donkey gate stays; the usage ledger export stays.

### 1.3 Behavior rules
- The **CTO owns the profile**. The coordinator proposes it at project init and whenever `profile_review` facts change (e.g. payments go live) and asks for confirmation once; it never switches silently. The decision is logged in the decisions journal (§4.2).
- Every Task Assignment Contract and every release gate names the active profile and the gates it implies (`orchestration-and-worktrees.md` §2 gets a `Profile & Gates` field: `{operating_profile}: {route}, review {required|coordinator}, QA {smoke|targeted|full}, deploy {direct+backup|candidate gate}`).
- At each release gate the coordinator re-checks the criteria (`profile_review`) and proposes an upgrade when a criterion of the next column is met; downgrades only on explicit CTO decision.
- "Experiment in prod" procedure (prototype/pilot): 1) backup with a named, restorable artifact (DB dump, volume snapshot, export) and record its name in the session note; 2) apply the change; 3) smoke the changed flow; 4) watch logs/health for 15 minutes; 5) keep (backfill task note + transition) or restore the backup / redeploy the previous artifact; 6) note the outcome in the decisions journal when it changed product behavior.

### 1.4 Documentation changes (Agent A)
- `workflows/operating-profiles.md` (new): rationale (one paragraph, includes the "five users is not an SLA" argument), §1.2 matrix, floors, §1.3 rules, how to switch (config edit + decisions-log entry + dashboard shows it), examples: "pilot project ships a copy fix" (5 steps) vs "production project ships a payment change".
- `SKILL.md`: new section **"10. Operating Profiles: Right-Sizing the Process"** after section 9 with a 6-row summary of the matrix, the floors, and the rule that the profile appears in every brief; one sentence in section 7 before the mermaid: "Steps 7–11 scale with the operating profile (section 10); the diagram shows the production profile."; package tree: `workflows/` line mentions `operating-profiles.md`, `session-protocol.md`; `scripts/` line mentions `dashboard_sync.py`, `apply_transitions.py`, `vault_lint.py`; `vault/` tree gets `03-ADR/decisions-log.md`; Core Execution Guarantees gets two bullets: **Operating Profiles** and **Session Protocol & Dashboard Automation** (links). Section 2 Guarantees: mention `vault_lint.py` runs inside `validate-project`.
- `workflows/cto-and-authority.md` §3 Operational Rules: add "A profile never widens `delegated_authorities`; in `prototype`/`pilot` a direct production deploy still requires `allow_deploy_production: true` or the user's go-ahead in `USER` mode."
- `workflows/review-qa-and-release.md`: new §0 "Gate depth by operating profile" (3 bullets, link to the matrix) before §1; Step 5 adds "pilot/prototype: backup name recorded before deploy".
- `workflows/lightweight-vs-full-routes.md`: matrix row "Operating profile" (what each profile defaults to) + one sentence in §1.
- `workflows/orchestration-and-worktrees.md` §2: `Profile & Gates` field; §1: link to `session-protocol.md` for multi-session rules.
- `workflows/content-review.md` §1 table: add a column "Depth by profile" or a sentence per profile under the table.
- `workflows/efficiency-and-usage-audit.md` §4 step 4: dashboard token block is generated by `dashboard_sync.py`, the auditor only appends the "Usage Audits" row via the coordinator; §4 step 6: CTO decisions go to the decisions journal (`vault/03-ADR/decisions-log.md`) and are mirrored in the report's `Decision` column.
- `references/contracts-and-lifecycle.md`: §1.1 table "Required Verification Evidence" column gets "(depth per operating profile, `workflows/operating-profiles.md`)" in the header; §3 paths: `9. Lock & hand-off: .it-department/lock.json, .it-department/sessions/_handoff/`; `10. Decisions journal: <vault>/03-ADR/decisions-log.md`; §4 item 3: "regenerates `00-Dashboard.md` with `scripts/dashboard_sync.py`; transition requests are applied with `scripts/apply_transitions.py`".
- `references/mcp-integration.md` "Preventing Race Conditions": mention `dashboard_sync.py --check` and the lock file.
- `agents/cto.md`: new bullet under §3 "Operating profile owner" (propose/confirm/switch, decisions journal); `agents/qa-engineer.md` Step 2 preamble: scope per profile + "write `qa-report.md` from `templates/qa-report.md`" (Step 4.1); `agents/devops-engineer.md` Step 4: backup-first and restore procedure per profile; `agents/system-analyst.md` §2.3: DoR depth per profile, link `references/definition-of-ready-done.md`; `agents/content-reviewer.md` §3/§4: depth per profile (one line each); all seven role files + content-reviewer: no other changes.
- `README.md`: feature row "Operating profiles" and "Session protocol & dashboard automation"; layout lines for the new scripts/workflows/references.

---

## 2. Session protocol and lock (owner: Agent A; `.gitignore` entries: Agent C)

`workflows/session-protocol.md` (new) defines:

1. **Session start checklist** (coordinator or any role): read `config.json` (profile, authorities), read `00-Dashboard.md`, read `.it-department/sessions/_handoff/latest.md` if present, check the lock, export nothing yet.
2. **Lock convention** — `.it-department/lock.json`:
   ```json
   { "owner_role": "coordinator", "session_id": "<id or free text>", "host": "cowork | cli | <machine>",
     "started_at": "2026-10-07T09:00:00Z", "expires_at": "2026-10-07T13:00:00Z", "scope": "vault + dashboard", "note": "waves 3-4" }
   ```
   Rules: only the holder writes shared vault records and the dashboard (single-writer rule); the file is written by hand by the coordinator (no script); default TTL 4 hours, renew by rewriting `expires_at`; an expired lock may be taken over after writing a line into the hand-off note; a live lock held by someone else → the session works in **contributor mode**: its own session directory, transition requests, bug notes, its own report files — never task-note moves or the dashboard. The lock file is git-ignored (Agent C adds `.it-department/.gitignore`), shared through the project folder (mount or sync), never committed.
3. **Hand-off note** — `.it-department/sessions/_handoff/latest.md` (overwritten at session end; previous copy kept as `<YYYY-MM-DD>-<session_id>.md`): what was done, what is in flight (task ids + status + worktree), pending transition requests, open questions for the CTO, next steps, usage exported (yes/no).
4. **Session end checklist**: apply pending transition requests (`apply_transitions.py`), regenerate the dashboard (`dashboard_sync.py`), export usage (`usage_ledger.py`), write the hand-off note, release the lock (delete `lock.json`).
5. **Parallel work rules**: who may run concurrently (orchestrator + developers + QA + content reviewer in contributor mode), what to do on conflict (newer session writes a `CONFLICT` line into the hand-off note and stops touching shared records).
6. Dashboard shows the lock holder and age (Agent B reads `lock.json`).

Agent A also adds a 3-line "Session protocol" bullet to `SKILL.md` section 3 (after "Subagents vs. Sequential Fallback") and the Core Execution Guarantees bullet (see §1.4).

---

## 3. Dashboard automation (owner: Agent B)

### 3.1 `assets/vault-template/00-Dashboard.md` — generated blocks with markers

Every generated block is wrapped in HTML comment markers; the script replaces only the text between them and leaves everything else (manual notes, extra sections) untouched:

```
<!-- sync:header start --> … <!-- sync:header end -->
<!-- sync:tokens start --> … <!-- sync:tokens end -->
<!-- sync:kanban start --> … <!-- sync:kanban end -->
<!-- sync:tasks start --> … <!-- sync:tasks end -->
<!-- sync:bugs start --> … <!-- sync:bugs end -->
<!-- sync:adr start --> … <!-- sync:adr end -->
<!-- sync:usage-audits start --> … <!-- sync:usage-audits end -->
<!-- sync:content-reviews start --> … <!-- sync:content-reviews end -->
<!-- sync:releases start --> … <!-- sync:releases end -->
<!-- sync:documents start --> … <!-- sync:documents end -->
```

Template layout (top to bottom): title; header block (Project, Last Updated, Operating Profile with link `[[decisions-log]]`, CTO Decision Mode, Session lock, Vault Archival Policy); `## ⚡ Tokens & Machine Time` (tokens block); `## 📊 Live Task Kanban Overview` (kanban); `## 🚀 Active Sprint Tasks` (tasks); `## 🐛 Open Defects & Bugs` (bugs); `## 🏛️ Architectural Decision Records` (adr) + a line `Decisions journal: [[decisions-log]]`; `## 📈 Usage Audits` (usage-audits); `## ✍️ Content & Localization Reviews` (content-reviews); `## 📦 Recent Production Releases` (releases); `## 📚 Documents` (documents); the Obsidian tip. Keep the existing `{PROJECT_NAME}`, `{LAST_UPDATED}`, `{CTO_MODE}` placeholders inside the header block so `init-project` still works before the first sync.

### 3.2 `scripts/dashboard_sync.py`

```
python3 dashboard_sync.py [--root PROJECT_ROOT] [--check] [--quiet]
```
- Reads: config (`project_name`, `cto_mode`, `operating_profile`, `efficiency.audit_interval_days`, `efficiency.reports_path`, `content_review.reports_path`, `documents`, `paths.vault_relative_path`), every `*.md` under `<vault>/01-Tasks/**`, `02-Bugs/`, `03-ADR/`, `04-Archive/**` (frontmatter), report sidecars `usage-audit-*.json`, report frontmatter `content-review-*.md`, `qa-report-*.md` (optional), `.it-department/lock.json`.
- **Frontmatter parser** (stdlib, no PyYAML): block between the first `---` line and the next `---`; `key: value` pairs; values: quoted strings (strip quotes, unescape `\"`), booleans `true|false`, integers, inline lists `[a, b]`, block lists (`- item` lines under a key), inline comments after ` #` removed outside quotes; unknown shapes kept as raw strings; nested maps not required. Title fallback: first `# ` heading when `title` is absent.
- **Link rules**: task/bug ids → `[[ID]]`; ADR → `[[<filename-without-.md>|ADR-NNN]]` (alias = `id` field or the `ADR-NNN` prefix of the file name); reports → `[[<filename-without-.md>]]`; decisions log → `[[decisions-log]]`; glossary/style guide → `[[glossary]]`, `[[style-guide]]`; `docs:` entries of a task and `documents` of the config → markdown link `[title](<relative path from the dashboard file>)` when the path is outside the vault, wikilink when inside; a path that does not exist → rendered as plain code with ` (missing)` and counted as a warning. Titles in tables are escaped for `|`.
- **Blocks**:
  - header: `**Project:** {name}`, `**Last Updated:** {YYYY-MM-DD HH:MM}` (local), `**Operating Profile:** {profile} ([[decisions-log]])`, `**CTO Decision Mode:** {mode}`, `**Session Lock:** {owner_role}@{host} since {started_at}, expires {expires_at}` or `free`, `**Vault Archival Policy:** Active (Zero-Deletion Enforced)`.
  - tokens: from the newest `usage-audit-*.json` (by date in file name): `Last audit {date} (window since {since}) · weighted tokens {n} ({delta% vs previous or "baseline"}) · output {n} · jobs {n}/{hours} h · screenshots {n}`; a line `R1 {OK|CHECK} · R2 … · R5 …` — derive statuses with the same rules as `usage_report.py` section 4 from the sidecar fields (`jobs_waited_over_max`, `overlap_minutes`, `tool_results_over_r4`, `compactions`, `images_read` vs `R2_screenshots_per_scenario_max`, `build_jobs`/`jobs`); `Proposals pending CTO decision: {n}` = rows of section 7 of the newest `usage-audit-*.md` whose "Change" cell is non-empty and whose "Decision" cell is empty (see §3.4); `Next audit due: {date + audit_interval_days}` with ` (overdue)` when in the past; when no audit exists: `No usage audit yet — run usage_report.py`.
  - kanban: counts per status folder of `01-Tasks` + Archived = files in `04-Archive/Completed-Tasks`.
  - tasks: all notes under `01-Tasks/**` sorted by status order (In-Development, Code-Review, QA-Testing, Ready-For-Release, Ready-For-Dev, In-Analysis, Backlog) then priority (critical, high, medium, low) then id; columns: Task ID (wikilink) | Title | Priority | Route | Assigned Agent | Branch (code) | Status | Content review (`intake: approved` etc. or `n/a`) | QA (`qa_status`) | Docs (links from `docs:`); empty table row `*(No active tasks)*` when none.
  - bugs: notes in `02-Bugs` with status ≠ Archived; columns Bug ID | Title | Severity | Category/Locale | Linked Task (wikilink from `parent_task`) | Assigned Agent | Status | Blocking; sorted severity then id.
  - adr: notes in `03-ADR` except `decisions-log.md`; columns ADR ID (wikilink with alias) | Decision Title | Status | Date | Approver.
  - usage-audits: one row per `usage-audit-*.json`: Date | Report (wikilink to the .md) | Window | Weighted tokens | Delta | Proposals (pending/total) | Rule flags (e.g. `R2 R4`); newest first, max 10.
  - content-reviews: one row per `content-review-*.md` with frontmatter (`checkpoint`, `scope`, `locales_reviewed`, `findings`, `verdict`, `date`): Date | Checkpoint | Scope | Locales | Findings C/M/m/T | Verdict | Report; newest first, max 10.
  - releases: group archived tasks and resolved bugs by `release_version`: Release Tag | Commit SHA (`release_commit`) | Date (`archived_at` max) | Tasks Included (wikilinks) | Verified By (QA report link if a `qa-report-*-<sha7>.md` exists, else `—`); newest first, max 10.
  - documents: list from config `documents` + auto entries: glossary, style guide, decisions log, latest usage audit, latest content review, latest QA report; each `- [title](link) — note`.
- `--check`: compute the new dashboard, compare with the file; exit `0` if identical, `1` if it differs (print a unified diff limited to 60 lines), never write. Without `--check`: write only when changed, print `dashboard: updated|unchanged (<n> tasks, <n> bugs, <n> warnings)`; warnings listed (missing docs, notes without frontmatter, unknown status folder).
- Missing markers (old dashboards): insert the block after the matching `## ` heading when found, else append at the end before the Obsidian tip; print `inserted block <name>`.
- Idempotent; LF output; UTF-8; never touches text outside markers; placeholders `{PROJECT_NAME}` etc. are replaced within the header block only.

### 3.3 `scripts/apply_transitions.py`

```
python3 apply_transitions.py [--root PROJECT_ROOT] [--dry-run] [--no-sync]
```
- Finds every `transition-request.json` under `<sessions>/**` that has no `applied_at` field.
- Validates: JSON shape (`task_id`, `from_status`, `to_status`, `agent_role`, `evidence_file`, `timestamp`); the note exists (task under `01-Tasks/**`, bug under `02-Bugs/`); `from_status` equals the note's `status` frontmatter **and** its folder (tasks); `to_status` is a legal next status per `references/contracts-and-lifecycle.md` §1.1/§1.2 (tasks: Backlog→In-Analysis→Ready-For-Dev→In-Development→Code-Review→QA-Testing→Ready-For-Release→Archived, with the back-edges Code-Review→In-Development and QA-Testing→In-Development; bugs: Open→In-Development→Code-Review→Retesting→Closed→Archived, back-edge Retesting→In-Development); `evidence_file` exists next to the request; `Ready-For-Dev` requires `content_review_intake` ∈ {approved, not-applicable} when `content_review: required`; `Ready-For-Release` requires `qa_status: passed` or `candidate_sha` in the request; `Archived` requires `release_version` and `release_commit` in the request.
- Applies (unless `--dry-run`): moves the task note to `01-Tasks/<to_status>/` (Archived → `04-Archive/Completed-Tasks/`; bugs: Archived → `04-Archive/Resolved-Bugs/`, otherwise stays in `02-Bugs/`), rewrites frontmatter `status`, `date_updated` (today), plus `release_version`/`release_commit`/`archived_at` for Archived, `candidate_sha`/`qa_status` when provided; appends a line to the note's `## Transition Log` section (created at the end when missing): `- {timestamp} {from} → {to} by {agent_role} (evidence: {relative path})`; writes `applied_at` into the request file.
- Refuses with a reason per request (stale, unknown note, illegal transition, missing evidence, missing intake verdict) — listed, exit `1`; valid requests are still applied.
- Runs `dashboard_sync.py` afterwards unless `--no-sync` (import by path, same directory).

### 3.4 `scripts/usage_report.py` (small change)
Section 7 table gets a `Decision` column: `| # | Change | Evidence (numbers) | Expected saving | Where applied | Risk | Decision |` with the empty row `| 1 |  |  |  |  |  |  |`; the sidecar gets `"proposals_total"`, `"proposals_pending"` when a previous report exists in the window (count rows with non-empty Change). Nothing else changes; the existing tests in this spec's §7 must still pass.

### 3.5 `templates/task-specification.md` (small change)
Frontmatter: add `docs: [] # related documents outside the vault, e.g. ["docs/requirements/spec.md"]` after `pr_link`; add `## 10. Transition Log` at the end with one placeholder line `- {YYYY-MM-DDTHH:MM:SSZ} In-Analysis → Ready-For-Dev by coordinator (evidence: …)`.

### 3.6 Tests (Agent B): `scripts/tests/test_dashboard_sync.py`, `scripts/tests/test_apply_transitions.py` (unittest, stdlib) building a temp vault from the template with 3 tasks, 2 bugs, 1 ADR, 1 usage-audit sidecar + report, 1 content-review report, config with profile and documents, a lock file; assert links, counts, ordering, token block lines, idempotency, `--check` exit codes, marker insertion into a marker-less dashboard, a legal and an illegal transition, Transition Log line, `applied_at`. Run via Docker.

---

## 4. Definitions, decisions journal, QA report (owner: Agent C)

### 4.1 `references/definition-of-ready-done.md` (new)
- **DoR** checklists: full route (12 items: context, verified facts vs assumptions, DB section or "n/a + why", endpoints, code locations, content table complete in every locale with intake verdict, acceptance criteria testable, JSON contracts, dependencies, feasibility score ≥ 8 or ADR-OVERRIDE, route and priority set, assignee and branch formula) and lightweight (6 items); a column or note "required in profile prototype / pilot / production" per item (reference the matrix in `workflows/operating-profiles.md`; do not duplicate it).
- **DoD** per transition: → Code-Review, → QA-Testing, → Ready-For-Release, → Archived, bug → Closed; each a checklist with evidence file names (`handoff.md`, `qa-report.md`, content review verdict, usage ledger exported, transition request written).
- One paragraph on who checks what (analyst proposes, coordinator verifies, `vault_lint.py` checks the mechanical parts).

### 4.2 Decisions journal
- `templates/decision-record.md` (new): the format of one journal row and the rule when an ADR is required instead (architecture, schema, security, anything with a 2-turn debate or an override; everything else is a journal row): columns `ID (D-NNN) | Date | Topic | Decision | Decided by | Context (link) | Follow-up / review date`.
- `assets/vault-template/03-ADR/decisions-log.md` (new): title, two-sentence intro, the table header with one example row (`D-001 | {DATE} | Operating profile | Project runs in pilot profile … | CTO | [[00-Dashboard]] | review at 50 users`) — placeholders `{PROJECT_NAME}` and `{DATE}` replaced by `init-project` (Agent C changes both init scripts: the `03-ADR/decisions-log.md` file gets the same placeholder treatment as `06-Content/*`).
- `validate-project.*`: warn (not fail) when `03-ADR/decisions-log.md` is missing.

### 4.3 `templates/qa-report.md` (new)
Frontmatter: `id: QA-{YYYY-MM-DD}-{scope}`, `scope` (task id or `RC-<sha7>`), `candidate_sha`, `baseline_sha`, `operating_profile`, `qa_scope` (`smoke | targeted | full`), `environment`, `verdict` (`passed | failed | passed-with-deferrals`), `defects: { critical, major, minor, trivial }`, `screenshots: { count, max_allowed, scale }`, `date`, `tags: [qa-report]`. Body: 1 Scope & environment (commands run, versions), 2 Scenario table (`# | Scenario | Steps ref | Result | Evidence`), 3 Defects table (`Bug | Severity | Category | Status`), 4 Regression & re-verification (what was re-run after fix rounds, R3), 5 Screenshots (list, within the R2 budget), 6 Verdict + transition request reference. Release-level copies live at `<vault>/05-Reports/qa-report-<date>-<sha7>.md`; task-level at the session directory as `qa-report.md`.

---

## 5. Vault lint (owner: Agent C)

### 5.1 `scripts/vault_lint.py`
```
python3 vault_lint.py [--root PROJECT_ROOT] [--format text|json] [--no-dashboard-check] [--strict]
```
Checks (code, severity `error|warning`):
- `VL001 error` note has no parseable frontmatter (tasks, bugs, ADRs, reports with required frontmatter).
- `VL002 error` required fields missing — task: `id,title,status,route,priority,assigned_agent,branch,date_created,content_review,content_review_intake`; bug: `id,parent_task,title,status,severity,category,release_blocking`; ADR: `id,title,status,date`; content review report: `checkpoint,scope,verdict,date`; QA report: `scope,verdict,date`.
- `VL003 error` `id` does not match the file name (`ATM-029.md` ↔ `id: ATM-029`; ADR file name starts with the id).
- `VL004 error` duplicate ids across the vault.
- `VL005 error` task `status` differs from its folder; archived task not `Archived`; bug status not in the bug lifecycle.
- `VL006 error` wikilink target not found in the vault (`[[Target]]` / `[[Target|alias]]`; targets resolved by file name without extension anywhere in the vault; `#heading` suffix ignored).
- `VL007 error` bug severity Critical/Major with `release_blocking: false`, or Minor/Trivial with `true` and no `deferral_signoff`.
- `VL008 error` task with `content_review: required` beyond `Backlog`/`In-Analysis` with `content_review_intake: pending|changes-requested`.
- `VL009 warning` bug `category: content` without `locale`.
- `VL010 warning` `docs:` path (task) or `documents[].path` (config) does not exist.
- `VL011 warning` dates not `YYYY-MM-DD` / timestamps not ISO.
- `VL012 warning` dashboard out of date (`dashboard_sync.py --check` exit 1) unless `--no-dashboard-check`; `error` with `--strict`.
- `VL013 warning` `03-ADR/decisions-log.md` missing; `VL014 warning` lock file expired but present.
- Uses the same frontmatter parser rules as §3.2 (copy the function; keep each script standalone).
- Output text: one line per finding `VL005 error vault/01-Tasks/Backlog/ATM-029.md: status In-Development but folder Backlog`, then a summary line; exit `1` on any error, `0` otherwise (`--strict`: warnings count as errors). JSON format: `{summary, findings[]}`.
- Tests: `scripts/tests/test_vault_lint.py` (unittest) with a temp vault containing one clean note per type and one violation per code.

### 5.2 `validate-project.ps1` / `.sh`
- After the existing checks: if `python3`/`python` ≥ 3.8 is available, run `vault_lint.py --root <project> --no-dashboard-check` and fail validation on lint errors (print its output); otherwise print `[WARN] Python not available: vault lint skipped`. (On the .sh side reuse the engine detection; on Windows detect `python`/`py -3`, skip the Microsoft Store stub by checking `python --version` exit code.)
- Validate `operating_profile` (enum), `profile_review` (types), `documents` (array of {title, path}; relative paths) when present; warn when `operating_profile` is absent ("defaults to production").
- `03-ADR/decisions-log.md` missing → warning.

### 5.3 `init-project.ps1` / `.sh`
- Create `.it-department/.gitignore` when absent with: `lock.json`, `worktrees/`, `sessions/_usage/raw/`, `sessions/_usage/audit-runs/`, `sessions/_usage/audit-prompt.generated.md`, `sessions/_handoff/*.md` except `latest.md` is **kept** (so write `sessions/_handoff/` + `!sessions/_handoff/latest.md`).
- Placeholder replacement for `03-ADR/decisions-log.md` (`{PROJECT_NAME}`, `{DATE}`).
- Print the active profile at the end: `Profile:   pilot (workflows/operating-profiles.md)`.

---

## 6. Dashboard ↔ vault ↔ scripts contract summary (all agents)

| Item | Value |
| :--- | :--- |
| Dashboard markers | `<!-- sync:<name> start -->` … `<!-- sync:<name> end -->`, names in §3.1 |
| Dashboard sync CLI | `python3 <skill_root>/scripts/dashboard_sync.py --root <project_root> [--check]`, exit 0/1/2 |
| Transitions CLI | `python3 <skill_root>/scripts/apply_transitions.py --root <project_root> [--dry-run] [--no-sync]` |
| Vault lint CLI | `python3 <skill_root>/scripts/vault_lint.py --root <project_root> [--strict] [--format json]` |
| Lock file | `.it-department/lock.json` (§2) |
| Hand-off | `.it-department/sessions/_handoff/latest.md` + dated copies |
| Decisions journal | `<vault>/03-ADR/decisions-log.md`, rows `D-NNN`, template `templates/decision-record.md` |
| QA report | `templates/qa-report.md`; release copies `<vault>/05-Reports/qa-report-<date>-<sha7>.md` |
| DoR / DoD | `references/definition-of-ready-done.md` |
| Profiles | config `operating_profile`, matrix in `workflows/operating-profiles.md` |
| Task frontmatter additions | `docs: []`; `## 10. Transition Log` section |

---

## 7. Test and acceptance commands (run by each agent before reporting; re-run by the integrator)

```bash
# Python syntax + unit tests (Docker, from Git Bash with MSYS_NO_PATHCONV=1)
docker run --rm -e PYTHONDONTWRITEBYTECODE=1 -v "<worktree>\scripts:/skill/scripts:ro" python:3.12-alpine \
  sh -c "cd /skill/scripts && python -m unittest discover -s tests -v"
# existing scripts must keep passing their earlier checks (ast parse of all scripts/*.py)
# bash syntax
bash -n scripts/init-project.sh scripts/validate-project.sh scripts/schedule-usage-audit.sh
# PowerShell parse
pwsh -NoProfile -c "[System.Management.Automation.Language.Parser]::ParseFile('scripts/validate-project.ps1',[ref]$null,[ref]$e)|Out-Null; $e.Count"
# init + validate round trip on a scratch project (ps1 and sh; sh under Node on the host and under Python in python:3.12-slim)
# markdown relative links resolve (script used in this repo's history):
for f in $(git ls-files '*.md'); do d=$(dirname "$f"); for l in $(grep -oE '\]\((\./|\.\./)[^)#]+' "$f" | sed 's/^](//' | sort -u); do [ -e "$d/$l" ] || echo "MISSING: $f -> $l"; done; done
```

Acceptance: all of the above green; `dashboard_sync.py` run twice on the fixture produces identical output; `validate-project` passes on a freshly initialised project and fails on the fixture with a VL005 violation; no file outside the agent's ownership modified (check `git diff --name-only`).

---

## 8. Ownership and branches

| Agent | Worktree branch | Owns (may modify or create) | Must not touch |
| :--- | :--- | :--- | :--- |
| **A — process** | `wt/agent-a-process` | `SKILL.md`, `README.md`, `assets/config-template.json`, `assets/project-config.schema.json`, `workflows/operating-profiles.md`, `workflows/session-protocol.md`, `workflows/cto-and-authority.md`, `workflows/review-qa-and-release.md`, `workflows/lightweight-vs-full-routes.md`, `workflows/orchestration-and-worktrees.md`, `workflows/content-review.md`, `workflows/efficiency-and-usage-audit.md`, `references/contracts-and-lifecycle.md`, `references/mcp-integration.md`, `agents/*.md` | everything under `scripts/`, `templates/`, `assets/vault-template/`, `references/definition-of-ready-done.md` |
| **B — dashboard** | `wt/agent-b-dashboard` | `scripts/dashboard_sync.py`, `scripts/apply_transitions.py`, `scripts/usage_report.py` (§3.4 only), `scripts/tests/test_dashboard_sync.py`, `scripts/tests/test_apply_transitions.py`, `assets/vault-template/00-Dashboard.md`, `templates/task-specification.md` (§3.5 only) | all docs (`SKILL.md`, `README.md`, `workflows/`, `references/`, `agents/`), other scripts, config/schema |
| **C — definitions & lint** | `wt/agent-c-definitions` | `references/definition-of-ready-done.md`, `templates/decision-record.md`, `templates/qa-report.md`, `assets/vault-template/03-ADR/decisions-log.md`, `scripts/vault_lint.py`, `scripts/tests/test_vault_lint.py`, `scripts/validate-project.ps1`, `scripts/validate-project.sh`, `scripts/init-project.ps1`, `scripts/init-project.sh` | `SKILL.md`, `README.md`, `workflows/`, `agents/`, `assets/config-template.json`, schema, dashboard template, other scripts |

Shared test helper: if two agents need the same frontmatter parser, each keeps its own copy (standalone scripts); the integrator may unify later.

Final report of each agent (max 40 lines): files changed, commits, test commands run with results, deviations from this spec with reasons, and the list of changes needed in files outside its ownership (the integrator applies them).
