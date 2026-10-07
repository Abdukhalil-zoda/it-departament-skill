# IT Department Skill

A reusable skill package that turns an AI coding host (Claude Code, Cowork, Codex, Antigravity or any
host that can read `SKILL.md`) into a coordinated software engineering department: CTO, System Analyst,
Architect, Backend / Frontend developers, QA and DevOps roles with explicit boundaries, a delivery pipeline
with real verification gates, git worktree isolation, a project-local Obsidian vault for telemetry, and a
**token optimizer** that measures what the department costs and proposes savings every few days.

The entry point for the host is [`SKILL.md`](./SKILL.md). This file is the human overview.

## What you get

| Area | Highlights |
| :--- | :--- |
| **Deep reasoning, not blind execution** | Feasibility scoring (1–10), constructive pushback with alternatives, "Ask Why" context discovery, and the Stubborn Donkey Override gate with an `ADR-OVERRIDE` record. |
| **Roles** | `agents/*.md` — one system prompt per role (CTO, System Analyst, Architect, Backend / Frontend developers, QA, DevOps, Content & Localization Reviewer) with step-by-step SOPs and session-output contracts. |
| **Content & localization review** | Two checkpoints: every user-facing string finalized in every locale before development, and all texts of the release candidate reviewed before the CTO gate, with an inventory script, glossary, style guide and a report to the CTO. |
| **Delivery pipeline** | Ready-For-Dev → worktree → tests (≥ 80 % coverage) → CI → peer review → integration merge → QA on an immutable candidate SHA → CTO release gate → production → archive. |
| **Operating profiles** | `prototype` / `pilot` / `production` in `config.json` sets the depth of every gate (route, Definition of Ready, review, coverage, QA scope, staging, deploy), so a product with five users is not run like one with an SLA; in early profiles "back up the database and work directly in production" is a documented path. Floors never move: secrets out of git, verified backups, no force-push, delegated authorities. |
| **Safety rails** | Delegated authorities in `config.json`, mock vs real secrets rules, non-destructive rollback (redeploy, never force-push), incident triage classes. |
| **Vault** | Project-local Obsidian vault (`vault/`) with kanban folders, bugs, ADRs, a decisions journal, usage-audit, content and QA reports, and a zero-deletion archive. |
| **Session protocol & dashboard automation** | A hand-written lock file and hand-off notes let a Cowork orchestrator, local CLI sessions and scheduled routines share one vault. The dashboard is generated (every ID, report and document clickable; token and audit status on top), transition requests are applied by a script, and a vault lint catches structural drift. |
| **Token optimizer** | Efficiency rules R1–R5, a per-session usage ledger, a scheduled usage audit with ≤ 5 proposals for the CTO. |

## Package layout

```text
SKILL.md                      host entry point: routing, modes, guarantees
README.md                     this overview
agents/                       role prompts (cto, system-analyst, architect, backend-dev, frontend-dev, qa-engineer,
                              devops-engineer, content-reviewer)
workflows/                    runbooks: orchestration & worktrees, git branching, review/QA/release, CTO authority,
                              deep reasoning & override, lightweight vs full routes, secrets & incidents,
                              efficiency & usage audit (token optimizer), content review (two checkpoints),
                              operating profiles, session protocol (lock & hand-off)
templates/                    task specification, bug/defect, ADR, decision record, QA report, usage-audit prompt,
                              content-review report
references/                   canonical contracts & lifecycle, Definition of Ready / Done, MCP integration,
                              worked example (SHOP-102)
assets/                       config-template.json, project-config.schema.json, vault-template/
scripts/                      init-project.{ps1,sh}, validate-project.{ps1,sh},
                              usage_ledger.py, usage_report.py, schedule-usage-audit.{ps1,sh}, content_inventory.py,
                              dashboard_sync.py, apply_transitions.py, vault_lint.py (unit tests in scripts/tests/)
```

The package is stateless. All project data lives in the target project:

```text
<project_root>/
├── vault/                    00-Dashboard.md (generated), 01-Tasks/<status>/, 02-Bugs/, 03-ADR/ (+ decisions-log.md),
│                             04-Archive/, 05-Reports/, 06-Content/ (glossary, style guide)
└── .it-department/
    ├── config.json           modes, operating profile, delegated authorities, git policy, quality gates, paths,
    │                         documents, efficiency rules, content review
    ├── lock.json             session lock while a writer is active (written by hand, git-ignored)
    ├── sessions/             <task-id>/<role>/<session-id>/ work records; _handoff/ hand-off notes;
    │                         _usage/ledger/ usage ledger
    ├── worktrees/            isolated git worktrees per task
    └── jobs/                 optional machine-time feed (job logs or jobs.jsonl)
```

## Quick start

1.  **Install the package** where your host looks for skills, for example
    `<project_root>/.agents/skills/it-departament-skill/` (project-scoped, Codex / Claude Code) or
    `~/.claude/skills/it-departament-skill/` (user-scoped, Claude Code). Keep it outside the project's
    source tree you want the agents to modify.
2.  **Initialise the project** (idempotent, never overwrites existing notes or config):
    ```powershell
    pwsh -File <skill_root>/scripts/init-project.ps1 -ProjectRoot <project_root>
    ```
    ```bash
    <skill_root>/scripts/init-project.sh <project_root>
    ```
3.  **Adjust `<project_root>/.it-department/config.json`**: `cto_mode` (`VIRTUAL` or `USER`), the operating
    profile (`operating_profile` and the `profile_review` facts; the template starts at `pilot`), delegated
    authorities, branch names, quality gates, efficiency limits, the `documents` shown on the dashboard.
4.  **Validate** at any time:
    ```powershell
    pwsh -File <skill_root>/scripts/validate-project.ps1 -ProjectRoot <project_root>
    ```
5.  **Work.** Describe a goal to the host. The coordinator scores it, routes it (lightweight or full) at the
    depth of the operating profile, writes the task note, dispatches roles (sub-agents when the host supports
    them, sequential otherwise), and keeps the vault and dashboard current. Concurrent sessions follow the
    session protocol (`workflows/session-protocol.md`).

Requirements: PowerShell 7 or bash, git, Python 3.8+ (standard library only) for the usage, dashboard,
transition and lint scripts.

## Token optimizer (efficiency rules & usage audit)

Measured on the first production project: 90 % of the shared build host went to one edit → build → emulator
loop, and the token budget was dominated by full-resolution screenshots, re-read tool outputs and long log
tails. The optimizer makes that visible and keeps it down.

*   **Rules R1–R5** (limits in `efficiency.rules` of `config.json`, repeated in every role file and task
    brief): one build per fix round · screenshot budget with downscaling · targeted re-verification after
    fixes, full suite once per candidate · log discipline (short summaries, tailed logs, token cap on tool
    results) · one queue per shared build host.
*   **Usage ledger** — every session exports its own usage before it ends:
    ```bash
    python3 <skill_root>/scripts/usage_ledger.py --root <project_root> --role qa-engineer --task ATM-028
    ```
    One aggregate JSON per transcript (tokens by model, side and content group, tool calls, largest tool
    results, images, compactions, sub-agents, task mentions), no message text, safe to commit.
*   **Usage audit** — every `efficiency.audit_interval_days` (default 2) the strongest model runs
    ```bash
    python3 <skill_root>/scripts/usage_report.py --root <project_root>
    ```
    and follows `templates/usage-audit-prompt.md`: report with rule indicators and delta vs the previous
    audit in `vault/05-Reports/usage-audit-<date>.md`, a row in the dashboard, and a ≤ 15-line message to
    the CTO with at most 5 evidence-backed proposals. The CTO approves; the coordinator applies; the next
    audit shows the delta.
*   **Scheduling** — a cloud routine (Claude Code `/schedule`) with the prompt, or the local scheduler
    scripts (`schedule-usage-audit.ps1` / `.sh`: `-DryRun`, `-RunNow`, `-Register`) that run `claude -p` headless.

Full guide: [`workflows/efficiency-and-usage-audit.md`](./workflows/efficiency-and-usage-audit.md).

## Content & localization review (two checkpoints)

Tests pass with an untranslated button and screenshots look fine with a mistranslated label, so text gets
its own reviewer (`agents/content-reviewer.md`) who works twice per change and reports to the CTO:

*   **Checkpoint A — task creation.** Every task that adds or changes user-facing text carries a strings table
    (template §6) in every configured locale; the reviewer finalizes the wording before `Ready-For-Dev`
    and developers copy it verbatim into the project's resources.
*   **Checkpoint B — pre-release.** On the frozen candidate SHA the reviewer runs
    ```bash
    python3 <skill_root>/scripts/content_inventory.py --root <project_root> --base <production-sha>
    ```
    (missing, empty, untranslated and malformed strings; placeholder and writing-system mismatches;
    strings changed since the last release; hardcoded markup text; wrong-language content data), reads the
    changed texts in every locale, logs content defects as bugs, writes
    `vault/05-Reports/content-review-<date>-<sha7>.md` and sends the CTO a ≤ 15-line verdict.
    `Critical`/`Major` content defects block the release; `Minor` ones need the CTO's signed deferral.
*   **Reference files.** `vault/06-Content/glossary.md` and `style-guide.md`, created by `init-project`,
    owned by the reviewer; terms change only by CTO decision. Configuration in the `content_review` block of
    `config.json` (locales, resource globs, inline code tables, content data sources).

Full guide: [`workflows/content-review.md`](./workflows/content-review.md).

## Where to read next

*   [`SKILL.md`](./SKILL.md) — operating model, modes, the advisory lifecycle, the delivery pipeline.
*   [`workflows/operating-profiles.md`](./workflows/operating-profiles.md) — which gates apply at which stage of the product.
*   [`references/contracts-and-lifecycle.md`](./references/contracts-and-lifecycle.md) — statuses, severities, path contracts, single-writer rule.
*   [`workflows/`](./workflows/) — the runbooks the coordinator follows.
*   [`references/examples/SHOP-102.md`](./references/examples/SHOP-102.md) — a fully specified example task (never copied into real projects).
