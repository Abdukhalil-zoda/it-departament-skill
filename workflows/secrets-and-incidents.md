# Workflow Guide: Secrets Security & CI/CD Incident Triage

## 1. The Three-Tier Secrets Security Model

To prevent catastrophic leaks while enabling test automation, secrets are governed by three strict tiers:

```mermaid
flowchart TD
    subgraph T1["Tier 1: Dummy / Mock Credentials"]
        MOCK["Example values: sk_test_mock_12345, postgres://test:test@localhost:5432/test<br/>Scope: Offline unit tests, template files.<br/>Permitted: Safe to commit in git (.env.test.example)."]
    end

    subgraph T2["Tier 2: Real Staging / Non-Production Secrets"]
        STAGE["Actual Staging API Keys, Cloud Sandboxes, QA DBs.<br/>Scope: Integration testing and staging clusters.<br/>Permitted: Managed by DevOps agent in uncommitted .env.local or staging secret manager.<br/>PROHIBITED: Never commit real staging credentials to version control."]
    end

    subgraph T3["Tier 3: Production Secrets (STRICT HUMAN BOUNDARY)"]
        PROD["Live Stripe Keys, Production DB Passwords, Cloud IAM Tokens.<br/>Scope: Live customer traffic only.<br/>PROHIBITED: Agents must NEVER request, handle, print, or commit production secrets.<br/>MANAGEMENT: Solely by the human business owner / user via cloud vault."]
    end
```

### Proactive Secret Auditing
*   Before any code is committed or merged, the pre-deploy CI checks execute regex credential scanning (e.g. searching for `AKIA[0-9A-Z]{16}`, `ghp_[0-9a-zA-Z]{36}`, `-----BEGIN PRIVATE KEY-----`).
*   Any detection immediately blocks the pipeline and alerts the developer.

---

## 2. CI/CD Failure Incident Triage Protocol

When an automated build, lint, test, or deploy step fails, the **DevOps Agent** classifies and triages the failure:

```mermaid
flowchart TD
    ALERT["CI/CD Pipeline Failure Alert"] --> DIAG["DevOps Agent Inspects Logs in Assigned Worktree"]
    DIAG --> CLASS{"Classify Root Cause"}
    
    CLASS -- "Class 1: Infra / Flake<br/>(Cache timeout, runner disk, network glitch)" --> AUTO["DevOps Resolves Immediately<br/>(Prune Docker cache, adjust timeout, restart runner)"]
    AUTO --> RETRY["Re-trigger Pipeline"]
    
    CLASS -- "Class 2: Architectural / Code<br/>(Schema conflict, breaking API contract, failed test)" --> HALT["Halt Deployment"]
    HALT --> NOTIFY["Notify Responsible Developer & Post Log Summary to Task"]
    NOTIFY --> FIX["Developer Resolves in Worktree<br/>(Max 2 Retries before CTO Escalation)"]
```

### Incident Triage Rules

| Failure Category | Classification | Resolution Authority | Escalation Threshold |
| :--- | :--- | :--- | :--- |
| **Dependency Cache / Network Flake** | Class 1: Infra-only | DevOps Engineer | Auto-fix immediately. |
| **Ephemeral Test Port Conflict** | Class 1: Infra-only | DevOps Engineer | Auto-fix immediately. |
| **Failed Unit / Integration Test** | Class 2: Code Defect | Assigned Developer | Assigned to developer; fails PR check. |
| **Database Migration Mismatch** | Class 2: Architectural | Developer + Architect | Halts deployment. Architect review required. |
| **Missing Production Configuration** | Class 2: Operational | Human User / CTO | Coordinator prepares concrete config template for user injection. |
