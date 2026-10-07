---
id: {TASK-ID}
title: "{Short descriptive title of the task}"
status: In-Analysis # In-Analysis (default for Full route) | Ready-For-Dev (for Lightweight route)
route: full # full | lightweight
type: feature # feature | bug | refactor | docs
priority: high # critical | high | medium | low
target_repository: "{repo-identifier}" # repository subdirectory or '.' for single-repo
assigned_agent: dev-backend # dev-backend | dev-frontend | dev-mobile
branch: "feature/{TASK-ID}/{DD.MM.YYYY}/{AGENT}"
date_created: "{YYYY-MM-DD}"
date_updated: "{YYYY-MM-DD}"
pr_link: ""
docs: [] # related documents outside the vault, e.g. ["docs/requirements/spec.md"]
qa_status: pending # pending | testing | passed | failed
content_review: required # required (task adds or changes any user-facing text, localized resource or shipped content) | not-applicable
content_review_intake: pending # pending | approved | changes-requested | not-applicable  (set by the coordinator from the Content Reviewer's verdict)
cto_approved: false
tags:
  - task
  - {service-name}
  - in-analysis
---

# [{targetService}] {TASK-ID}: {Short descriptive title}

## 1. Context & Motivation
- **Target Repository:** `{repository_identifier}` (Root: `{repo_relative_path}`)
{Explain clearly WHY this change is needed, which user problem or business requirement it addresses, and how components interact. Mention upstream/downstream dependencies.}

## 2. Repository Facts vs. Assumptions
- **Verified Existing Artifacts:** {Confirmed files, classes, models, or endpoints verified via repository inspection}
- **Proposed New Artifacts:** {Files, endpoints, or migrations to be created}
- **Assumptions & Open Questions:** {Working technical assumptions; explicitly list unresolved questions if any}

## 3. Database & Schema Changes
*(For lightweight or non-database tasks, state: "Not applicable.")*
- **Target Table:** `{schema}.{TableName}`
- **Field Modifications:**
  - Add `{ColumnName}`: `{DATA_TYPE}`, `{nullable | NOT NULL}`, default `{value}`, description.
- **Indexes:** `{IndexName}` on `({columns})`
- **Migration File:** `{timestamp}_{MigrationName}.sql` in `{path/to/migrations}`.

## 4. Endpoints Modified & Created
*(For UI-only, refactoring, or non-API tasks, state: "Not applicable.")*
Base Route: `{base_path}`

| Method | Endpoint | Permission Key | Behavior & Impact |
| :--- | :--- | :--- | :--- |
| `POST` | `/api/v1/...` | `Permission_Key_Name` | Creates new resource, validates X, returns Y |
| `GET` | `/api/v1/...` | `Permission_Key_Name` | Now returns the newly added field Z |

## 5. Code Locations to Modify
List the exact source code files, classes, interfaces, and methods that the developer must touch:
- `{Project.Domain}/Entities/{Entity}.cs`: Add property `{Name}`.
- `{Project.Application}/Features/{Feature}/Commands/{Command}.cs`: Update command mapping.
- `{Project.Infrastructure}/Persistence/{Context}.cs`: Update ORM mapping.
- `{Project.Application}/Validators/{Validator}.cs`: Add validation rule.

## 6. User-Facing Content & Localization
*(State "Not applicable." and set `content_review: not-applicable` only when the task adds or changes no text a user can see. Otherwise every string the task introduces or changes is listed here, in every configured locale, and the Content Reviewer finalizes it before `Ready-For-Dev`. Developers copy the approved text verbatim; they do not write user-facing text themselves. Guide: `workflows/content-review.md`.)*
- **Locales:** {from `config.json` → `content_review.locales`, source locale first}
- **Glossary / style guide:** `{vault}/06-Content/glossary.md`, `{vault}/06-Content/style-guide.md`
- **Strings:**

| Key / Location | Context (screen, when shown) | {source locale} | {locale 2} | Limits & notes (max length, plural forms, placeholders) |
| :--- | :--- | :--- | :--- | :--- |
| `{Resource}.{Key}` (`{file}`) | {screen / state} | {text} | {text} | {≤ 24 chars; `{count}` kept} |

- **Shipped content touched (seeded / imported / generated):** {data set or file, locale rules that apply, or None}
- **Content review (intake):** verdict `{pending}` — note: `{sessions}/{TASK-ID}/content-reviewer/{session-id}/content-review-intake.md`

## 7. Acceptance Criteria
Concrete, measurable rules that QA will use to pass or fail this task:
1. Feature behaves as expected under valid inputs.
2. Invalid inputs return HTTP 400 with standard error payload.
3. Edge cases (nulls, boundary values, empty arrays) handled gracefully without unhandled exceptions.
4. Unit and integration tests cover newly introduced logic, meeting or exceeding the project's configured threshold (`quality_gates.test_coverage_threshold_percent`).
5. Every user-facing string of §6 exists in every configured locale with the approved text; `scripts/content_inventory.py` reports no missing, empty, placeholder or wrong-script findings for the task's keys. *(Omit when §6 is "Not applicable.")*

## 8. JSON Contracts
*(For non-API tasks, state: "Not applicable.")*

### {METHOD} {EndpointPath}
Header: `{Header-Name}: {Header-Value}`

#### Request Payload
```json
{
  "exampleKey": "exampleValue"
}
```

#### Response Payload (HTTP 200 OK)
```json
{
  "status": "success",
  "data": {
    "id": 123,
    "exampleKey": "exampleValue"
  }
}
```

#### Error Response Payload (HTTP 400 Bad Request)
```json
{
  "status": 400,
  "errorCode": "INVALID_INPUT_DATA",
  "message": "Field 'exampleKey' must match regex pattern '^[A-Z]{3}$'.",
  "timestamp": "{ISO_TIMESTAMP}"
}
```

## 9. Dependencies & Blockers
- Depends on: [[{ANOTHER-TASK-ID}]] (or None)
- Blocks: [[{FUTURE-TASK-ID}]] (or None)

## 10. Transition Log
- {YYYY-MM-DDTHH:MM:SSZ} In-Analysis → Ready-For-Dev by coordinator (evidence: …)
