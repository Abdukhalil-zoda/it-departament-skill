# Template: Usage Audit Prompt (tokens and machine time)

Run by the strongest available model (`efficiency.audit_model`) every `efficiency.audit_interval_days`
days (default 2) or on CTO request. The prompt below is self-contained on purpose: a scheduled cloud
routine or a headless CLI run starts with zero context. Fill the placeholders, then paste the whole
block into the routine, into `schedule-usage-audit.*` (they render it automatically) or into any project
session for a one-off audit. Full process: [`workflows/efficiency-and-usage-audit.md`](../workflows/efficiency-and-usage-audit.md).

| Placeholder | Value |
| :--- | :--- |
| `{PROJECT_NAME}` | `project_name` from `config.json` |
| `{PROJECT_ROOT}` | absolute project path as seen by the audit session (workstation path, or the sandbox mount such as `$HOME/mnt/<project>`) |
| `{SKILL_ROOT}` | where the skill package is installed (e.g. `{PROJECT_ROOT}/.agents/skills/it-department-skill` or `~/.claude/skills/it-department-skill`) |
| `{INTEGRATION_BRANCH}` | `git_policy.integration_branch` |
| `{VAULT_PATH}`, `{LEDGER_PATH}`, `{REPORTS_PATH}` | `paths.vault_relative_path`, `efficiency.ledger_path`, `efficiency.reports_path` |
| `{AUDIT_INTERVAL_DAYS}` | `efficiency.audit_interval_days` |
| `{REPORT_LANGUAGE}` | `efficiency.report_language` (the CTO's language) |
| `{LEDGER_REFRESH_STEP}` | how this environment reaches the host transcripts — see the two variants under the prompt |

---

```text
You are the efficiency auditor of the IT Department of project {PROJECT_NAME}. The project is at
`{PROJECT_ROOT}`; the IT Department skill is at `{SKILL_ROOT}`. Process rules: `{SKILL_ROOT}/workflows/efficiency-and-usage-audit.md`
(rules R1-R5, ledger, audit), the efficiency section of the project's CLAUDE.md if present, and the
`efficiency` block of `{PROJECT_ROOT}/.it-department/config.json`. Your task: compute where tokens and
machine time went since the previous audit and propose optimizations to the CTO with numbers. Change
nothing in code or process yourself - only the report and the proposals. Write the report and the final
message in {REPORT_LANGUAGE}.

Steps:
1. Refresh the usage ledger. {LEDGER_REFRESH_STEP}
   If the host transcripts cannot be reached, work with the ledger already committed under
   `{PROJECT_ROOT}/{LEDGER_PATH}` and state that in the report.
2. Run `python3 {SKILL_ROOT}/scripts/usage_report.py --root {PROJECT_ROOT}` (use `python` on Windows). It writes
   `{PROJECT_ROOT}/{REPORTS_PATH}/usage-audit-<date>.md` plus a `.json` sidecar; the window starts at the
   previous audit automatically (or {AUDIT_INTERVAL_DAYS}+1 days ago when there is none). Read the new report and
   the previous one.
3. In the new report fill section 6: the R1-R5 indicators explained with concrete tasks, sessions and job
   names, the delta vs the previous audit (better / worse / same, with numbers), the top-3 token sources and
   the top-3 time consumers.
4. Fill section 7 "Proposals for the CTO": at most 5 changes, each with evidence (numbers), expected saving
   (tokens or minutes), where it is applied (rule in config.json or CLAUDE.md, agent file in the skill, tool
   default, task brief) and the risk; leave the "Decision" column empty - the CTO fills it. If the window
   has no ledger files, the first proposal names the sessions that did not export their usage with
   `usage_ledger.py`.
5. Do not edit `{PROJECT_ROOT}/{VAULT_PATH}/00-Dashboard.md`: its "Tokens & Machine Time" block and the
   "Usage Audits" row are generated from the report sidecar by `{SKILL_ROOT}/scripts/dashboard_sync.py`, which the
   coordinator runs. Commit report and sidecar on `{INTEGRATION_BRANCH}`: `git -C {PROJECT_ROOT} add {REPORTS_PATH}`
   then `git -C {PROJECT_ROOT} commit -m "vault: usage audit <date>"`. If the working copy is on another branch,
   do not switch; commit to the current branch and say so.
6. Before finishing export your own usage: `python3 {SKILL_ROOT}/scripts/usage_ledger.py --root {PROJECT_ROOT} --role auditor`
   (from a sandbox: `--out` to a staging folder, then commit the JSON into `{PROJECT_ROOT}/{LEDGER_PATH}/`).
7. Final message to the CTO, at most 15 lines: what grew, what shrank, the proposals one line each, and the
   question which ones to approve. Remind that the interval is changed in `efficiency.audit_interval_days`
   and in the scheduled task, and that a one-off audit uses this same prompt
   (`{SKILL_ROOT}/templates/usage-audit-prompt.md`).

Auditor rules: numbers only from the scripts and files, never estimated by eye; do not read screenshots or
whole transcripts, only aggregates; keep your own spend minimal - it is measured by the next audit.
```

### `{LEDGER_REFRESH_STEP}` variants

**Workstation / headless CLI (transcripts persist on this machine):**
```text
Run `python3 {SKILL_ROOT}/scripts/usage_ledger.py --root {PROJECT_ROOT}`; it reads this project's transcripts from
~/.claude/projects and rewrites `{PROJECT_ROOT}/{LEDGER_PATH}` (idempotent).
```

**Cloud routine / sandbox bound to a workstation folder (transcripts live on the host):**
```text
Through the project's host job mechanism copy new `*.jsonl` files from the host's `~/.claude/projects` into
`{PROJECT_ROOT}/{LEDGER_PATH}/../raw/` (incremental, only new or changed files), then run
`python3 {SKILL_ROOT}/scripts/usage_ledger.py --root {PROJECT_ROOT} --transcripts {PROJECT_ROOT}/{LEDGER_PATH}/../raw --out {PROJECT_ROOT}/{LEDGER_PATH}`
and delete the raw copies afterwards.
```

### Routine settings (cloud scheduler)
*   **Name:** `{PROJECT_NAME}: usage audit (it-department)`
*   **Schedule:** `CRON_TZ=<timezone> 51 8 */2 * *` for a 2-day interval (adjust day-of-month step to `audit_interval_days`)
*   **Model:** `efficiency.audit_model`
*   **Binding:** the project folder on the workstation (preferred, lets step 1 reach the host) or the git repository
*   **Tools:** file tools, Bash, git, plus the host's device / file-sync tools
