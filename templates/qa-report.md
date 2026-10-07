---
id: QA-{YYYY-MM-DD}-{scope}          # scope = {TASK-ID} for a task-level report, RC-{sha7} for a release candidate
scope: "{TASK-ID or RC-<sha7>}"
candidate_sha: "{candidate commit SHA}"
baseline_sha: "{production baseline SHA}"
operating_profile: pilot             # prototype | pilot | production (config.json operating_profile)
qa_scope: targeted                   # smoke | targeted | full (full suite once per candidate SHA, rule R3)
environment: "{test | staging | production after a named backup (prototype / pilot only)}"
verdict: passed                      # passed | failed | passed-with-deferrals
defects: { critical: 0, major: 0, minor: 0, trivial: 0 }
screenshots: { count: 0, max_allowed: 10, scale: 0.5 }   # R2 budget from efficiency.rules
date: "{YYYY-MM-DD}"
tags: [qa-report]
---

# QA report — {qa_scope}: {scope} @ {sha7}

## 1. Scope & environment
- **What was tested:** {acceptance criteria §7 of the task | fixed defects + one smoke path per feature | full suite of the candidate}
- **Why this depth:** profile `{operating_profile}` → `{qa_scope}` (matrix in `workflows/operating-profiles.md`; full suite at most once per candidate SHA)
- **Environment:** {URL / device or emulator, OS, build number, database snapshot or backup name}
- **Versions:** candidate `{candidate_sha}` vs baseline `{baseline_sha}`; {runtime, SDK, browser versions}
- **Commands run:**
  ```text
  {test command}   → {N passed, M failed, K skipped} ({duration})
  {smoke command}  → {result}
  ```

## 2. Scenarios
| # | Scenario | Steps ref | Result | Evidence |
| :--- | :--- | :--- | :--- | :--- |
| 1 | {acceptance criterion or user flow} | {task §7 item / test case id} | {pass \| fail \| blocked} | {log tail, screenshot file, test report} |
| 2 | {edge or negative case} | {…} | {…} | {…} |

## 3. Defects
| Bug | Severity | Category | Status |
| :--- | :--- | :--- | :--- |
| [[BUG-{id}]] | {Critical \| Major \| Minor \| Trivial} | {functional \| content \| security \| performance \| accessibility} | {Open \| Retesting \| Closed \| deferred — signed by {CTO} on {date}} |

Counts match the `defects` frontmatter; `Critical` and `Major` block the verdict, deferred `Minor` defects need the
CTO's `deferral_signoff` in the bug note.

## 4. Regression & re-verification (R3)
- **Full suite on this candidate:** {run once on {date}: N passed / M failed | not owed: `{qa_scope}` per profile}
- **After fix rounds:** {round 1: BUG-…, BUG-… re-verified + smoke path {flow} → pass}
- **Not re-run, and why:** {suites skipped because the candidate SHA did not change}

## 5. Screenshots (R2)
{count} of {max_allowed} allowed, downscaled to {scale} before any vision read, stored in `{session directory}/screenshots/`:
- `{file name}` — {what it shows, which scenario}

## 6. Verdict & transition
**{passed | failed | passed-with-deferrals}** — {one sentence: what passed, what blocks, which deferrals were signed}.
- **Open blocking defects:** {none | [[BUG-{id}]]}
- **Deferrals signed:** {BUG-{id} by {CTO} on {YYYY-MM-DD} | none}
- **Transition request:** `{session directory}/transition-request.json` — `QA-Testing → Ready-For-Release`,
  `qa_status: passed`, `candidate_sha: {candidate_sha}`, `evidence_file: qa-report.md` (task-level report)
- **Copies:** task level `{sessions}/{TASK-ID}/qa-engineer/{session-id}/qa-report.md`; release level
  `{vault}/05-Reports/qa-report-{YYYY-MM-DD}-{sha7}.md`

### Summary for the coordinator (≤ R4 summary lines)
```text
QA {qa_scope} {scope} @ {sha7}: {verdict}. Profile {operating_profile}, env {environment}.
Scenarios: {passed}/{total}. Defects: C {0} / M {0} / m {0} / T {0}; blocking open: {none}.
Re-verified after fixes: {BUG-…}. Screenshots: {count}/{max_allowed}.
Report: {path}.
```
