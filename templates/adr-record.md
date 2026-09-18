---
id: ADR-{ID}
title: "{Decision Title}"
status: Proposed # Proposed | Accepted | Rejected | Superseded
decision_type: standard # standard | stubborn_donkey_override
date: "{YYYY-MM-DD}"
proposer: "{Agent Name / Role}"
challenger: "{Agent Name / Role}"
approver: "{CTO / User}"
tags:
  - adr
  - architecture
  - decision
---

# [ADR-{ID}] {Decision Title}

## 1. Context & Problem Statement
{Describe the engineering challenge, debate, or design decision. What are the constraints, requirements, and performance expectations?}

## 2. Debate Summary

### Proposal A ({Proposer Agent})
- **Approach:** {Summary of Option A}
- **Pros:**
  - {Advantage 1}
  - {Advantage 2}
- **Cons & Risks:**
  - {Disadvantage 1}

### Counter-Proposal B ({Challenger Agent})
- **Approach:** {Summary of Option B}
- **Pros:**
  - {Advantage 1}
  - {Advantage 2}
- **Cons & Risks:**
  - {Disadvantage 1}

## 3. Decision Outcome & Rationale
- **Chosen Option:** {Option A | Option B | Hybrid Solution | User Override}
- **Rationale:** {Why was this option chosen? How does it balance speed, scalability, and maintenance?}
- **Approved By:** {Virtual CTO / User as CTO}
- **Stubborn Donkey Override (if applicable):**
  - **User Verbatim Confirmation:** `"Yes, I am a stubborn donkey. Build it exactly as I asked."`
  - **Confirmation Timestamp:** `{YYYY-MM-DDTHH:MM:SSZ}`
  - **Documented Warnings:** {Summary of security, architectural, or scalability risks warned by the team}

## 4. Consequences & Follow-up Tasks
- **Positive Impacts:** {What improvements are locked in?}
- **Negative Trade-offs & Mitigations:** {What technical debt or complexity is accepted, and how will it be monitored?}
- **Action Items:**
  - [[{TASK-ID-1}]]: Implement database schema per ADR.
  - [[{TASK-ID-2}]]: Configure caching layer per ADR.
