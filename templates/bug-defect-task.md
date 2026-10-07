---
id: BUG-{ID}
parent_task: "[[{TASK-ID}]]"
title: "[BUG] {Brief description of defect}"
status: Open # Open | In-Development | Code-Review | Retesting | Closed | Archived
severity: Major # Critical | Major | Minor | Trivial
category: functional # functional | content | security | performance | accessibility
locale: "" # for content defects: the locale code (ru, uz, en-US …); empty otherwise
assigned_agent: dev-backend # dev-backend | dev-frontend
branch: "bug/BUG-{ID}/{DD.MM.YYYY}/{AGENT}"
date_created: "{YYYY-MM-DD}"
date_resolved: ""
release_blocking: true # true for Critical & Major, false for Minor & Trivial
deferral_signoff: "" # for deferred Minor defects: who signed (CTO / User) and when
tags:
  - bug
  - defect
  - qa-reported # qa-reported | content-review
---

# [BUG-{ID}] {Brief description of defect}

## Defect Summary
- **Affected Feature:** [[{TASK-ID}]]
- **Environment:** Test / Staging (`development` branch commit `{COMMIT_SHA}`)
- **Severity:** {Critical | Major | Minor | Trivial}
- **Category:** {functional | content | security | performance | accessibility}
- **Release Blocking:** {Yes (Critical / Major) | No (Minor / Trivial)}
- **Discovered By:** {QA Automation Agent | Content & Localization Reviewer}

## Steps to Reproduce
1. Send request to endpoint `{METHOD} {route}` with payload:
   ```json
   {
     "key": "edge_case_value"
   }
   ```
2. Inspect database state or response code.
3. Observe unexpected failure or unhandled exception.

*(Content defect: replace with — screen / flow, selected locale `{locale}`, the key or data path, e.g. `AppResources.uz.resx` → `BankTitle`.)*

## Expected vs. Actual Behavior
- **Expected:** Should return HTTP 400 with `{ "status": 400, "errorCode": "INVALID_VALUE", ... }`.
- **Actual:** Returns HTTP 500 with unhandled `NullReferenceException` in `{Controller.cs}` line {N}.

*(Content defect: **Current text:** `{text as shown}` · **Proposed text:** `{approved wording}` · **Reason:** {meaning / glossary / wrong script / placeholder / truncation / tone}.)*

## Logs & Stack Trace
```text
System.NullReferenceException: Object reference not set to an instance of an object.
   at Billing.Application.Handlers.ProcessPaymentHandler.Handle(...) in ProcessPaymentHandler.cs:line 84
```

## Proposed Fix & Root Cause
Validation is missing on line 84 before attempting to dereference property `{Property}` when payload contains `{EdgeCondition}`.
