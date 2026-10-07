# Workflow Guide: Orchestration, Worktrees & Session Records

## 1. Orchestration Model & Execution Modes

The Coordinator orchestrates specialized roles according to the host platform's capabilities:

### Mode 1: Subagent Invocation (Preferred)
*   When the host environment supports autonomous subagents (`invoke_subagent`), the coordinator dispatches tasks to independent subagents.
*   Each subagent receives an isolated prompt, its role instructions from `agents/<role>.md`, its dedicated worktree path, and its session output directory.
*   Independent peer review is genuine: the reviewer subagent inspects the diff in isolation without biased memory from the authoring session.
*   The Content & Localization Reviewer is dispatched twice: at task intake for specifications with `content_review: required`, and on the frozen release candidate in parallel with QA ([`content-review.md`](./content-review.md)).

### Mode 2: Sequential Execution (Fallback)
*   If subagents are unavailable or disabled, the coordinator runs roles sequentially within the session.
*   **Integrity Rule:** The coordinator must explicitly label sequential execution and must **never** fabricate independent peer reviews, fake approvals, or artificial multi-party debates. Review checklists must be evaluated methodically against the diff.

---

## 2. Standard Task Assignment Contract

Every assignment dispatched by the coordinator must contain these explicit fields:

```markdown
### Task Assignment Contract
- **Task ID & Objective:** {TASK_ID} - {ONE_LINE_GOAL}
- **Project Root:** {PROJECT_ROOT}
- **Target Repository:** {REPO_IDENTIFIER}
- **Repository Root:** {ABSOLUTE_REPOSITORY_ROOT}
- **Assigned Worktree Path:** {PROJECT_ROOT}/{CONFIGURED_WORKTREES_REL_PATH}/{REPO_IDENTIFIER}/{TASK_ID}
- **Target Branch:** {BRANCH_NAME}
- **Base Ref:** {CONFIGURED_INTEGRATION_BRANCH} (or production branch for hotfix)
- **Scope & File Ownership:**
  - Permitted modifications: {LIST_OF_FILES_OR_DIRECTORIES}
  - Protected / Out of scope: {PROTECTED_PATHS}
- **Dependencies & References:** {LIST_OF_DEPENDENT_TASKS_OR_DOCS}
- **Acceptance Criteria:** {EXPLICIT_TESTABLE_CONDITIONS}
- **Expected Deliverables:** Clean git commit, passing tests, PR draft summary.
- **Session Output Directory:** {PROJECT_ROOT}/{CONFIGURED_SESSIONS_REL_PATH}/{TASK_ID}/{AGENT_ROLE}/{SESSION_ID}/
- **Efficiency Budget (R1–R5, from config.json `efficiency.rules`):** builds per fix round ≤ {R1}; screenshots per scenario ≤ {R2} at {R2_SCALE} scale; re-verification scope: fixed defects + one smoke path ({R3}); summaries ≤ {R4_LINES} lines, log tails {R4_TAIL} lines, tool results ≤ {R4_TOKENS} tokens; shared-host queue rules ({R5}).
- **Usage Export:** before hand-off run `python3 {SKILL_ROOT}/scripts/usage_ledger.py --root {PROJECT_ROOT} --role {AGENT_ROLE} --task {TASK_ID}` (cloud sessions: `--out <staging>` + commit the JSON). See [`efficiency-and-usage-audit.md`](./efficiency-and-usage-audit.md).
- **Content Review:** `content_review: {required | not-applicable}`; intake verdict `{approved | n/a}` ({link to content-review-intake.md}); user-facing strings are taken verbatim from §6 of the task note for every configured locale and never authored by the developer. See [`content-review.md`](./content-review.md).
```

---

## 3. Worktree Isolation Rules & Commands

To allow safe concurrent implementation across multiple repositories without branch collisions:

1.  **Worktree Creation (Targeted Repository):**
    ```bash
    git -C "<repository_root>" worktree add -b "<branch_name>" "<absolute_worktree_path>" "<base_ref>"
    ```
2.  **No Shared Branch Switching:**
    *   Agents must never switch branches, rebase, or run checkout commands in the shared repository root. All work occurs strictly inside `<absolute_worktree_path>`.
    *   Never create nested `.it-department/` or `vault/` directories inside the worktree checkout.
3.  **Safe Cleanup on Merge:**
    *   Before removing any worktree, verify that it contains no uncommitted or unpreserved changes:
    ```bash
    git -C "<absolute_worktree_path>" status --porcelain
    ```
    *   Once confirmed clean and merged into the integration branch:
    ```bash
    git -C "<repository_root>" worktree remove "<absolute_worktree_path>"
    ```

---

## 4. Single-Writer Rule for Shared Records

To prevent race conditions, file corruption, and duplicate task claims:

1.  **Single Writer Principle:**
    *   The **Coordinator** is the exclusive writer of shared task notes, note moves between folders, and `<vault>/00-Dashboard.md`.
    *   Implementation agents (developers, QA, analyst, architect, devops) do **not** directly move notes or overwrite the dashboard.
2.  **Transition Request Hand-off:**
    *   When an agent completes an assignment, it writes its deliverables, logs, diff summary, and transition request to its session directory:  
        `<session_output_dir>/transition-request.json`
        ```json
        {
          "task_id": "SHOP-102",
          "from_status": "In-Development",
          "to_status": "Code-Review",
          "agent_role": "backend-dev",
          "evidence_file": "handoff.md",
          "timestamp": "2026-09-10T17:00:00Z"
        }
        ```
3.  **Coordinator Verification & Application:**
    *   The coordinator inspects the evidence, checks that `current_status == from_status`, moves the note file, updates frontmatter, and regenerates the dashboard table.
    *   Stale or out-of-order transition requests are rejected.
4.  **Task Claiming & Duplicate Prevention:**
    *   Before assignment, the coordinator marks `assigned_agent: <role>` and records the active worktree path in the task note.

---

## 5. Execution Outcomes & Bounded Retries

Every role execution concludes in one of five explicit states:

| Outcome | Meaning | Coordinator Action |
| :--- | :--- | :--- |
| **`completed`** | All deliverables and acceptance criteria satisfied; pre-deploy checks pass; session usage exported to the ledger. | Advance task to next lifecycle stage (`Code-Review` or `QA-Testing`). |
| **`blocked`** | Missing prerequisite, ambiguous specification, or dependency failure. | Pause task; assign to System Analyst or escalate to CTO. |
| **`failed`** | Unit tests fail, build errors occur, or lint checks reject code. | Trigger retry if retry count $< 2$; otherwise escalate. |
| **`interrupted`** | Session terminated by user, timeout, or external signal. | Preserve worktree and session state in `sessions/` for resumption. |
| **`resumed`** | Incomplete session re-opened using preserved worktree and session records. | Re-validate worktree diff and continue execution. |

### Bounded Retries & Escalation
*   **Maximum Retries:** A developer gets a maximum of **2 automated revision cycles** to resolve code review feedback or QA defect reports.
*   **Escalation Trigger:** If a task fails verification on the 2nd revision, the coordinator stops automated retry loops, compiles a root cause summary, and escalates to the **CTO** (Virtual or User).
