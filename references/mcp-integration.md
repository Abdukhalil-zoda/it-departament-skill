# Reference: Obsidian Integration, MCP & Telemetry

## 1. Vault Access: Primary & Fallback Mechanisms

The IT Department skill uses Markdown notes in `<project_root>/vault/` for live project telemetry, sprint tracking, and immutable decision logging.

### 1.1 Primary Interface: Standard Filesystem Tools
The coordinator and agents can directly inspect and update vault files using native file reading and writing tools (`view_file`, `replace_file_content`, `write_to_file`).
*   **Zero Dependencies:** Works out of the box on any system without extra server processes or network ports.
*   **Idempotent Updates:** Agents update YAML frontmatter or append markdown sections directly.

### 1.2 Optional Interface: Obsidian Model Context Protocol (MCP) Server
When an Obsidian MCP server is configured in the host environment, agents can interact with the vault via MCP tools (reading notes, appending content, querying frontmatter).

#### Generic, Portable MCP Configuration (`mcp_config.json`)
Do **not** hardcode machine-specific absolute paths (such as `C:\Users\...`). Instead, configure the server using environment variables or relative workspace paths supported by your MCP client:

```json
{
  "mcpServers": {
    "obsidian-vault": {
      "command": "npx",
      "args": [
        "-y",
        "mcp-obsidian",
        "${PROJECT_ROOT}/vault"
      ],
      "env": {
        "OBSIDIAN_VAULT_PATH": "${PROJECT_ROOT}/vault"
      }
    }
  }
}
```

*Note: If the MCP server fails to start, times out, or is unsupported, agents automatically fall back to direct filesystem operations.*

---

## 2. Dashboard Telemetry Maintenance

The file `<project_root>/vault/00-Dashboard.md` provides an executive overview of the project.

### Who Updates the Dashboard and When
The dashboard is maintained by the **Release Coordinator** (or the **DevOps Agent**) at specific lifecycle transitions:
1.  **Task Assigned:** When a task moves to `In-Development`.
2.  **Task Ready for Release:** When QA marks `qa_status: passed`.
3.  **Defect Logged / Resolved:** When a bug is opened or closed in `vault/02-Bugs/`.
4.  **Production Release Completed:** When the release candidate commit SHA is deployed to production and tasks move to `vault/04-Archive/Completed-Tasks/`.

### Preventing Race Conditions
To prevent concurrent overwrite of the dashboard:
*   The dashboard is regenerated deterministically from the current contents of `vault/01-Tasks/`, `vault/02-Bugs/`, and `vault/04-Archive/`.
*   Agents do not modify the dashboard while holding lock on a feature task. Dashboard updates happen synchronously at the completion of a lifecycle stage.

---

## 3. Automation vs. Coordinator-Driven Steps

To maintain operational integrity, we distinguish implemented automation from coordinator actions:

| Workflow Step | Actual Implementation Mechanism | Notes |
| :--- | :--- | :--- |
| **Branch CI Pipeline** | Coordinator runs local test commands (`npm test`, `dotnet test`, `pytest`) in the assigned worktree. | If host CI (e.g. GitHub Actions) is configured, coordinator inspects check status via git/CLI. |
| **Code Review Handoff** | Coordinator loads the reviewer persona and supplies the diff from the worktree. | Independent peer review must use separate context or subagents where available. |
| **QA Deployment** | Coordinator triggers test environment deploy script or runs docker compose in staging. | Does not fabricate test results; requires real test run execution. |
| **Dashboard Refresh** | Re-scans task notes and updates `00-Dashboard.md`. | Fully deterministic from file state. |

---

## 4. Secrets Security Boundary

```mermaid
flowchart TD
    subgraph S1["1. Mock / Dummy Credentials"]
        DUMMY["Harmless placeholders:<br/>sk_test_mock_12345<br/>Safe to commit in .env.test examples"]
    end

    subgraph S2["2. Real Test / Staging Credentials"]
        STAGING["Actual Staging Keys & DB Passwords:<br/>NEVER commit to version control.<br/>Store in uncommitted .env.local or staging secret manager."]
    end

    subgraph S3["3. Production Secrets"]
        PROD["Live Production Credentials:<br/>STRICT HUMAN BOUNDARY.<br/>Zero agent access.<br/>Injected directly into cloud vault by user."]
    end
```

*   **Mock Credentials:** Dummy strings used for offline unit testing. Safe to commit.
*   **Real Test Secrets:** Never commit real staging API keys or database passwords to git. Staging secrets must be treated with operational security and kept out of public or shared repositories.
*   **Production Secrets:** Strictly human-managed. Agents must never ask for, log, or persist production secrets.
