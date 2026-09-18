# Workflow Guide: Git Branching & Configurable Branch Management

## 1. Configurable Branch Architecture

The IT Department skill respects the target project's existing repository branch conventions rather than imposing hardcoded branch names. Branch names are read from `<project_root>/.it-department/config.json`:

```json
{
  "git_policy": {
    "production_branch": "main",
    "integration_branch": "development",
    "branch_naming_patterns": {
      "feature": "feature/{task-id}/{dd.mm.yyyy}/{agent}",
      "bug": "bug/{bug-id}/{dd.mm.yyyy}/{agent}",
      "hotfix": "hotfix/{task-id}/{dd.mm.yyyy}/{agent}"
    },
    "worktrees_enabled": true
  }
}
```

*   **`production_branch` (Default `main` or `production`):** Customer-facing live code. Merges strictly via verified release candidate commit SHAs with CTO approval.
*   **`integration_branch` (Default `development` or `develop`):** Internal staging and continuous integration target. Merges via approved pull requests.

---

## 2. Canonical Branch Naming Standard

All developers and agents follow these standardized branch templates:

| Branch Type | Formula Pattern | Realistic Example |
| :--- | :--- | :--- |
| **Feature Task** | `feature/{task-id}/{dd.mm.yyyy}/{agent}` | `feature/SHOP-102/10.09.2026/dev-backend` |
| **Defect / Bugfix** | `bug/{bug-id}/{dd.mm.yyyy}/{agent}` | `bug/BUG-204/10.09.2026/dev-backend` |
| **Emergency Hotfix** | `hotfix/{task-id}/{dd.mm.yyyy}/{agent}` | `hotfix/SEC-001/10.09.2026/dev-backend` |

---

## 3. Worktree Checkout & Lifecycle (Multi-Repo Capable)

All git commands explicitly specify the target repository root:
*   `$REPO_ROOT`: Canonical path to the specific repository (`<project_root>` or `<project_root>/services/<repo-name>`).
*   `$WORKTREE_PATH`: Absolute path under `<project_root>/${paths.worktrees_relative_path}/<repo-id>/<task-id>`.

### Step 1: Create Isolated Worktree from Configured Integration Branch
Implementation agents never work in the shared repository checkout:
```bash
git -C "$REPO_ROOT" worktree add -b "feature/SHOP-102/10.09.2026/dev-backend" \
  "$WORKTREE_PATH" "$INT_BRANCH"
```

### Step 2: Implement, Test & Open Pull Request
Work is committed inside the worktree with atomic messages referencing the task ID:
```bash
git -C "$WORKTREE_PATH" commit -m "feat(SHOP-102): implement multi-currency pricing tier batch conversion"
git -C "$WORKTREE_PATH" push origin "feature/SHOP-102/10.09.2026/dev-backend"
```

### Step 3: Worktree Pruning on Merge
Once the pull request is merged into `$INT_BRANCH`:
1. Verify worktree has no uncommitted changes:
```bash
git -C "$WORKTREE_PATH" status --porcelain
```
2. Remove worktree cleanly:
```bash
git -C "$REPO_ROOT" worktree remove "$WORKTREE_PATH"
```

---

## 4. The Emergency Production Hotfix Exception

When a critical vulnerability or production blocker must be patched immediately:
1.  **Worktree from Production:** Check out directly from configured `production_branch`:
    ```bash
    git -C "$REPO_ROOT" worktree add -b "hotfix/SEC-001/10.09.2026/dev-backend" \
      "$HOTFIX_WORKTREE_PATH" "$PROD_BRANCH"
    ```
2.  **Verify & Deploy:** Run targeted test suite, obtain CTO approval, and deploy the hotfix artifact. Fast-forward `$PROD_BRANCH` with release tag.
3.  **Mandatory Synchronization Back to Integration:**
    *   Merge the hotfix back into `$INT_BRANCH` via standard pull request:
    ```bash
    git -C "$REPO_ROOT" checkout "$INT_BRANCH"
    git -C "$REPO_ROOT" merge "$PROD_BRANCH"
    git -C "$REPO_ROOT" push origin "$INT_BRANCH"
    ```
