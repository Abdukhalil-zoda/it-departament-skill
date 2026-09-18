---
id: BUG-{ID}
parent_task: "[[{TASK-ID}]]"
title: "[BUG] {Brief description of defect}"
status: Open # Open | In-Development | Code-Review | Retesting | Closed | Archived
severity: Major # Critical | Major | Minor | Trivial
assigned_agent: dev-backend # dev-backend | dev-frontend
branch: "bug/BUG-{ID}/{DD.MM.YYYY}/{AGENT}"
date_created: "{YYYY-MM-DD}"
date_resolved: ""
release_blocking: true # true for Critical & Major, false for Minor & Trivial
tags:
  - bug
  - defect
  - qa-reported
---

# [BUG-{ID}] {Brief description of defect}

## Defect Summary
- **Affected Feature:** [[{TASK-ID}]]
- **Environment:** Test / Staging (`development` branch commit `{COMMIT_SHA}`)
- **Severity:** {Critical | Major | Minor | Trivial}
- **Release Blocking:** {Yes (Critical / Major) | No (Minor / Trivial)}
- **Discovered By:** QA Automation Agent

## Steps to Reproduce
1. Send request to endpoint `{METHOD} {route}` with payload:
   ```json
   {
     "key": "edge_case_value"
   }
   ```
2. Inspect database state or response code.
3. Observe unexpected failure or unhandled exception.

## Expected vs. Actual Behavior
- **Expected:** Should return HTTP 400 with `{ "status": 400, "errorCode": "INVALID_VALUE", ... }`.
- **Actual:** Returns HTTP 500 with unhandled `NullReferenceException` in `{Controller.cs}` line {N}.

## Logs & Stack Trace
```text
System.NullReferenceException: Object reference not set to an instance of an object.
   at Billing.Application.Handlers.ProcessPaymentHandler.Handle(...) in ProcessPaymentHandler.cs:line 84
```

## Proposed Fix & Root Cause
Validation is missing on line 84 before attempting to dereference property `{Property}` when payload contains `{EdgeCondition}`.
