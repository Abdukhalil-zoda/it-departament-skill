# Workflow Guide: Efficiency Rules & Usage Audit (Token Optimizer)

The token optimizer is the part of the IT Department that measures what the department costs (tokens
and machine time), enforces five efficiency rules in every task brief, and every few days hands the CTO
a short, numbers-backed list of optimizations. It was adopted after the first measurement on a real
project (2026-10-06): 90 % of the shared build host went to one mobile edit → build → emulator loop, and the
token budget was dominated by screenshots read through vision at full resolution, re-read tool outputs
and 200-line log tails. None of that was visible until it was counted.

> **Principle.** In a long session every token in the context is re-read on every later turn (cached reads
> cost about 0.1× but there are hundreds of turns), so **the cheapest token is the one never added to the
> context**, and the cheapest minute is the build that was never started.

Three parts, all project-local and host-agnostic:

| Part | What | Where |
| :--- | :--- | :--- |
| **Rules R1–R5** | Limits every role follows; the coordinator writes them into task briefs. | `efficiency.rules` in `<project_root>/.it-department/config.json`, agent files |
| **Usage ledger** (collection) | One aggregate JSON per session transcript, exported by the session itself. | `scripts/usage_ledger.py` → `<project_root>/{efficiency.ledger_path}/` |
| **Usage audit** (analysis) | Every `audit_interval_days` the strongest model turns ledger + job logs into a report and ≤ 5 proposals for the CTO. | `scripts/usage_report.py`, `templates/usage-audit-prompt.md` → `<project_root>/{efficiency.reports_path}/` |

---

## 1. Efficiency rules (R1–R5)

| # | Rule | Who | Config key (default) | How the audit measures it |
| :--- | :--- | :--- | :--- | :--- |
| **R1** | **One build per fix round.** Fixes are batched into rounds; between builds only unit tests run (seconds). The expensive artifact (app, APK, container image, deploy) is produced once at the end of the round and once for the QA hand-off. Clean / non-incremental builds only for the final QA build. | developers | `R1_builds_per_fix_round_max` (2) | build jobs per task per day from the machine-time feed |
| **R2** | **Screenshot budget.** At most N screenshots per scenario; every screenshot is downscaled before it is read through vision (crops at full resolution only for pixel-level defects). Originals may stay on disk but are not read. | developers, QA | `R2_screenshots_per_scenario_max` (10), `R2_screenshot_scale` (0.5) | images per session folder on disk; `images_read` per session in the ledger |
| **R3** | **Targeted re-verification.** After a fix round QA re-checks only the fixed defects plus one smoke path. The full scenario suite runs once per release candidate SHA ([`review-qa-and-release.md`](./review-qa-and-release.md)). | QA | `R3_full_suite_runs_per_candidate_max` (1) | time of QA re-verification jobs vs first runs |
| **R4** | **Log discipline.** Agents return ≤ N-line summaries to the coordinator, never full logs. Job logs are tailed (the tool default), large tool results are summarised before they come back, nothing above the token limit is pasted into the coordinator session. | all | `R4_summary_lines_max` (10), `R4_log_tail_lines` (40), `R4_tool_result_tokens_max` (2000) | largest tool results, `files`/`device` share, compactions per session |
| **R5** | **Shared host scheduling.** One shared build/device host means one job queue: developer builds and QA device runs must not interleave. The coordinator schedules QA rounds when no developer build is pending and splits long jobs. | coordinator, devops | `R5_queue_wait_minutes_max` (5), `R5_split_jobs_longer_than_minutes` (10) | queue wait per job, dev/QA overlap minutes |

The limits are **project policy owned by the CTO** ([`agents/cto.md`](../agents/cto.md)): the coordinator reads
them from `config.json`, copies the relevant ones into every Task Assignment Contract
([`orchestration-and-worktrees.md`](./orchestration-and-worktrees.md) §2) and the role files repeat them for
each agent. Changing a limit is a CTO decision recorded in the decisions journal
(`<vault>/03-ADR/decisions-log.md`) or an ADR.

---

## 2. Configuration (`efficiency` block of `config.json`)

```json
"efficiency": {
  "audit_interval_days": 2,
  "audit_model": "claude-fable-5-1",
  "report_language": "English",
  "rules": { "R1_builds_per_fix_round_max": 2, "R2_screenshots_per_scenario_max": 10, "R2_screenshot_scale": 0.5,
             "R3_full_suite_runs_per_candidate_max": 1, "R4_summary_lines_max": 10, "R4_log_tail_lines": 40,
             "R4_tool_result_tokens_max": 2000, "R5_queue_wait_minutes_max": 5, "R5_split_jobs_longer_than_minutes": 10 },
  "token_weights": { "input": 1, "cache_write": 2, "cache_read": 0.1, "output": 5 },
  "ledger_path": ".it-department/sessions/_usage/ledger",
  "jobs_log_path": ".it-department/jobs",
  "reports_path": "vault/05-Reports"
}
```

*   `audit_model` — always the strongest model available to the project; the audit is a judgement task and
    runs rarely, so its own cost is negligible compared with what it saves.
*   `token_weights` — "effective" cost weights (input = 1). Cache writes with a 1-hour TTL cost 2×, cache reads
    0.1×, output 5×. Raw counts are always stored next to the weighted numbers, so changing the weights
    later does not destroy history. The scripts accept `--weights in,cw,cr,out` as an override.
*   Projects initialised before this block existed keep working; copy the block from
    [`assets/config-template.json`](../assets/config-template.json) to enable the audit
    (`validate-project` warns when it is missing).

---

## 3. Usage ledger — collection inside every working session

### 3.1 What is exported
`scripts/usage_ledger.py` reads the session transcripts (`*.jsonl`, including sub-agent transcripts under
`<session-id>/subagents/`) and writes **one JSON per transcript** into `{efficiency.ledger_path}`:
raw token counts (input, cache write, cache read, output, thinking) and their weighted total, tokens by
model, by main/sub-agent side and by **content group** (`instructions`, `conversation`, `assistant`,
`files`, `device`, `chrome`, `web`, `subagents`, `connector:<name>`, `other`), tool call counts, the ten
largest tool results, images read, context compactions, sub-agent launches, task ids mentioned, and the
optional `--role` / `--task` tags. No message text is stored (only a 120-character prefix of the first
user message, with system reminders stripped), so the ledger can be committed to git.

Session cost attribution is approximate by design: it splits each request's input tokens over the
content added in that turn and the cache reads over everything added earlier, proportionally to size.
Ratios between groups are what the audit needs; absolute numbers come from the raw counts.

### 3.2 When and where to run it

| Session type | Where the transcript lives | What to do |
| :--- | :--- | :--- |
| Claude Code CLI / desktop on a workstation | `~/.claude/projects/<encoded project path>/` (persists) | Run the ledger at the end of the session; the audit can also rebuild it later from the same folder. |
| Cloud sandbox session (Cowork, Claude Code web, cloud routine) | inside the sandbox (`~/.claude/projects/...`), **gone when the session ends** | The session **must** export before it ends and commit the JSON into the project (`--out` to a staging folder, then the host's commit / file-sync tool). |
| Sub-agents launched with the Agent tool | under the parent session folder (`subagents/agent-*.jsonl`) | Covered automatically when the parent session runs the ledger. |

```bash
# workstation (Windows: python instead of python3); run from anywhere
python3 <skill_root>/scripts/usage_ledger.py --root <project_root> --role qa-engineer --task ATM-028

# cloud sandbox: export to a staging folder, then commit the JSON files into <project_root>/{ledger_path}
python3 <skill_root>/scripts/usage_ledger.py --root <project_root> --out /mnt/user-data/outputs/usage --role coordinator

# explicit transcript location (e.g. transcripts copied from another machine)
python3 <skill_root>/scripts/usage_ledger.py --root <project_root> --transcripts <dir-with-jsonl> --out <ledger-dir>
```

**Checkpoints:** after every task wave, before every hand-off, before closing the session. The script is
idempotent (same session → same file, overwritten); resumed or forked copies of one conversation are
marked `duplicate_of_resumed_session` and ignored by the report. Exit code 3 means no transcripts were
found — fix the path instead of skipping the export.

---

## 4. Usage audit — analysis every `audit_interval_days` days or on demand

The auditor is a separate session of the strongest model (`efficiency.audit_model`) that follows
[`templates/usage-audit-prompt.md`](../templates/usage-audit-prompt.md):

1.  **Refresh the ledger.** On the workstation: run `usage_ledger.py --root <project_root>`. From a sandbox:
    copy new host transcripts into `{ledger_path}/../raw/` with the project's file-transfer mechanism, run
    the ledger on them, delete the raw copies. If the host is unreachable, work with the committed ledger
    and say so in the report.
2.  **Generate the numbers.** `python3 <skill_root>/scripts/usage_report.py --root <project_root>` writes
    `{reports_path}/usage-audit-<date>.md` (+ a `.json` sidecar with the totals; never pass `--no-json` for a real
    audit — the dashboard's token block and the next delta read the sidecar). `--since` defaults to the
    date of the previous report; sections 1–5 are deterministic: tokens by session / role / model / content
    group, largest tool results, machine time by role / kind / task, queue waits and dev/QA overlaps,
    screenshots per folder, **rule indicators R1–R5 against the configured limits**, and the delta against
    the previous audit.
3.  **Judge.** Fill section 6 (what the indicators mean, named tasks and jobs, top-3 token sources and
    top-3 time consumers, better/worse/same vs the previous audit) and section 7: **at most five
    proposals**, each with evidence (numbers), expected saving (tokens or minutes), where it is applied
    (`config.json` rule, agent file, tool default, task brief) and its risk. No proposal is applied by the
    auditor. If the window has no ledger files, the first proposal names the sessions that did not export.
    The `Decision` column of section 7 stays empty: the dashboard counts a proposal as pending until the
    CTO's decision is mirrored there (step 6).
4.  **Record.** Commit the report and its sidecar on the integration branch (`vault: usage audit <date>`).
    The dashboard's token block (last audit, delta, R1–R5 status, proposals pending a CTO decision, next
    audit due) and its "Usage Audits" row are generated from the sidecar and the report by
    `scripts/dashboard_sync.py`, so the auditor never edits the dashboard: its row reaches the dashboard via
    the coordinator, who runs the sync as lock holder ([`session-protocol.md`](./session-protocol.md)). The
    audit session writes only `{reports_path}/` and its own ledger file; it never moves task notes
    (single-writer rule).
5.  **Export its own usage** (`usage_ledger.py`); the auditor is measured too.
6.  **Report to the CTO** in ≤ 15 lines: what grew, what shrank, the proposals one line each, and the
    question which ones to approve. CTO decisions go into the decisions journal
    (`<vault>/03-ADR/decisions-log.md`, one `D-NNN` row each, format in
    [`templates/decision-record.md`](../templates/decision-record.md)), or into an ADR when the change is
    architectural, and are mirrored in the report's `Decision` column (`approved D-NNN`, `rejected D-NNN`,
    `amended D-NNN`). The coordinator then applies the approved ones to the skill files, `config.json` or task
    briefs; the next audit reports the delta. In the `prototype` and `pilot` profiles a proposal that only
    changes tool defaults may be applied by the coordinator without a decision note; its `Decision` cell then
    reads `applied: tool default` ([`operating-profiles.md`](./operating-profiles.md)).

Auditor rules: numbers only from the scripts and files (no estimates "by eye"); never read screenshots or
whole transcripts, only aggregates; keep its own spend minimal.

---

## 5. Scheduling the audit

Pick one; keep `efficiency.audit_interval_days` in sync with the schedule so the report windows line up.

### A. Cloud routine (Claude Code `/schedule`, Cowork) — recommended when the project host supports it
A routine runs the audit prompt in a fresh cloud session on a cron schedule, bound to the project folder
on the user's machine (so it can refresh the ledger through the host's job mechanism) or to the git
repository. Settings that worked in production:

| Setting | Value |
| :--- | :--- |
| Name | `<project>: usage audit (it-departament)` |
| Cron | `CRON_TZ=<your timezone> 51 8 */2 * *` — every second day at 08:51 local time (`*/2` on day-of-month fires on odd days; month boundaries may give a 1- or 3-day gap, acceptable) |
| Model | `efficiency.audit_model` (strongest available) |
| Prompt | `templates/usage-audit-prompt.md` with the placeholders filled in |
| Tools | file tools, Bash, git; plus the host's device/file-sync tools when the project lives on a workstation |

The prompt must be self-contained: the routine starts with zero context, so it names the project path, the
skill path, the branch to commit to and the report language.

### B. Local scheduler on the workstation (Windows Task Scheduler / cron) — headless CLI
`scripts/schedule-usage-audit.ps1` (Windows) and `scripts/schedule-usage-audit.sh` (Linux/macOS) render the
prompt template for the project and run `claude -p` non-interactively with the configured model, a file/git
tool allow-list and the project as working directory:

```powershell
pwsh -File <skill_root>/scripts/schedule-usage-audit.ps1 -ProjectRoot <project_root>            # dry run: shows prompt, command, trigger
pwsh -File <skill_root>/scripts/schedule-usage-audit.ps1 -ProjectRoot <project_root> -RunNow    # one audit now
pwsh -File <skill_root>/scripts/schedule-usage-audit.ps1 -ProjectRoot <project_root> -Register  # scheduled task every audit_interval_days at 08:30
```
```bash
<skill_root>/scripts/schedule-usage-audit.sh <project_root> --dry-run | --run-now | --register   # crontab entry
```
Prerequisites: `claude` CLI logged in on that machine, Python 3.8+ on `PATH`, transcripts of the project
in `~/.claude/projects` (the audit rebuilds the ledger from them). Logs go to
`{ledger_path}/../audit-runs/<date>.log`.

### C. On demand
Paste the filled prompt into any project session, or run step B with `-RunNow`. Useful right after a big
wave of work and before a release.

---

## 6. Machine-time feed (optional, any build system)

The report reads two kinds of input from `{efficiency.jobs_log_path}` and skips the section when there
is none. Either works, and they can be mixed:

1.  **Job logs** — one `<job-name>.log` per job containing two marker lines (the Windows PowerShell
    job-runner used on the reference project writes them; any wrapper script can):
    ```text
    [runner] job <job-name>.ps1 started 2026-10-06T11:13:11
    ...
    [runner] exit=0 elapsed=301s
    ```
    If a `<job-name>.ps1` (the submitted script) sits next to the log, its modification time is used as
    the submit time and the queue wait is computed from it.
2.  **`jobs.jsonl`** — one JSON object per line, appended by CI wrappers, Makefile targets, etc.:
    ```json
    {"name": "qa-smoke-0931", "started": "2026-10-06T09:31:00", "elapsed_seconds": 412, "exit_code": 0,
     "kind": "device", "role": "qa", "task": "ATM-028", "wait_seconds": 30}
    ```
    `kind`, `role`, `task` and `wait_seconds` are optional.

Naming convention that makes the classification automatic: start QA jobs with `qa`, developer jobs with
the task id (`atm028-build-1`) or `dev`, operations jobs with `git`/`ops`; put `build`, `test`, `emu`/`device`,
`smoke`, `install` in the name for the kind; put `re`/`recheck`/`retest` in QA re-verification jobs (R3).

---

## 7. Data hygiene

*   `{ledger_path}/*.json` and `{reports_path}/*` are versioned (aggregates only). `{ledger_path}/../raw/`
    (copied transcripts) is git-ignored and deleted after the ledger is written — `init-project` writes
    that `.gitignore`.
*   Every ledger file records the weights it was computed with; the report prints the weights of the
    window. Change weights in `config.json`, never by editing old files.
*   The report sidecar (`usage-audit-<date>.json`) is what the next audit diffs against; keep it next to
    the markdown. A second audit on the same day overwrites both files of that day.
*   Transcripts contain everything a session saw. They stay where the host keeps them; the skill never
    copies them into the vault, and the ledger keeps no message bodies.
