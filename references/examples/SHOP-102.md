---
id: SHOP-102
title: "Multi-Currency Pricing Tier & Batch Conversion Endpoint in OrderBillingService"
status: Example-Reference # FICTIONAL REFERENCE MATERIAL - NOT AN ACTIVE PROJECT TASK
type: feature
priority: high
assigned_agent: dev-backend
branch: feature/SHOP-102/10.09.2026/dev-backend
date_created: 2026-09-10
date_updated: 2026-09-10
pr_link: ""
qa_status: pending
content_review: not-applicable # internal service-to-service API; error payloads are developer-facing (see workflows/content-review.md)
content_review_intake: not-applicable
cto_approved: true
tags:
  - example
  - reference-only
  - billing-service
---

> [!NOTE]
> **Fictional Reference Material**: This task specification is a structural and depth reference for the IT Department skill. It illustrates the expected level of detail for a full-route backend task. It must **not** be copied into an active project backlog or dashboard during project initialization.

# [OrderBillingService] SHOP-102: Multi-Currency Pricing Tier & Batch Conversion Endpoint

Currently, `OrderBillingService` only calculates order line totals and tier discounts in the merchant's base currency (USD). With the European market expansion, checkout carts must display customer-localized currencies (`EUR`, `GBP`, `CHF`) with fixed conversion rates. The `MS-Orders` checkout service groups cart items by merchant tier and needs to convert all line items in a single call: currently, `OrderBillingService` only supports single-item conversion, causing severe N+1 HTTP latency during checkout.

---

## 1. Repository Inspection & Fact Verification

*   **Verified Existing Artifacts:**
    *   Entity file `Billing.Domain/Entities/PricingTier.cs` exists and defines base tier properties (`Id`, `TierName`, `BaseDiscountPercentage`).
    *   Persistence layer uses Entity Framework Core with migrations in `Billing.Infrastructure/Persistence/Migrations/`.
    *   Base API routing is `/api/v1/billing`.
*   **Proposed New Artifacts:**
    *   New command handler `BatchConvertCurrencyQuery` in `Billing.Application/Features/Currency/Queries/BatchConvert/`.
    *   New controller endpoint `POST /internal/currency/batch-convert` in `Billing.Api/Controllers/InternalCurrencyController.cs`.
    *   Migration script `20260910_AddCurrencyAndRateToPricingTiers.sql`.
*   **Assumptions & Non-functional Constraints:**
    *   Target database is PostgreSQL 15+. Regex constraint uses standard POSIX syntax (`~ '^[A-Z]{3}$'`).
    *   Batch size limit is strictly 250 items to prevent thread starvation.

---

## 2. Database & Schema Changes

Target Table: `billing.PricingTiers` in database `ShopFlow_Billing`.

### Column Alterations
- Add column `CurrencyCode`: `VARCHAR(3)`, `NOT NULL`, default `'USD'`, uppercase ISO-4217 standard.
- Add column `ExchangeRate`: `NUMERIC(12, 6)`, `NOT NULL`, default `1.000000`. Must be $> 0.000000$.
- Add column `RoundingRule`: `VARCHAR(20)`, `NOT NULL`, default `'HALF_UP'`. Allowed values: `HALF_UP`, `FLOOR`, `CEILING`.
- Add composite index: `IX_PricingTiers_TierId_CurrencyCode` on `(TierId, CurrencyCode)` with index inclusion `(ExchangeRate, RoundingRule)`.

### Database Migration Script
File location: `Billing.Infrastructure/Persistence/Migrations/20260910_AddCurrencyAndRateToPricingTiers.sql`:
```sql
ALTER TABLE billing.PricingTiers
ADD COLUMN CurrencyCode VARCHAR(3) NOT NULL DEFAULT 'USD',
ADD COLUMN ExchangeRate NUMERIC(12, 6) NOT NULL DEFAULT 1.000000,
ADD COLUMN RoundingRule VARCHAR(20) NOT NULL DEFAULT 'HALF_UP';

ALTER TABLE billing.PricingTiers
ADD CONSTRAINT CK_PricingTiers_CurrencyCode CHECK (CurrencyCode ~ '^[A-Z]{3}$');

ALTER TABLE billing.PricingTiers
ADD CONSTRAINT CK_PricingTiers_ExchangeRate_Positive CHECK (ExchangeRate > 0.000000);

CREATE INDEX IX_PricingTiers_TierId_CurrencyCode
ON billing.PricingTiers (TierId, CurrencyCode)
INCLUDE (ExchangeRate, RoundingRule);
```

---

## 3. Endpoints Modified & Created

Service Base Route: `/api/v1/billing`

| Method | Endpoint | Permission Key | What Changes / Purpose |
| :--- | :--- | :--- | :--- |
| **POST** | `/internal/currency/batch-convert` | `Billing_Internal_Service` | **NEW**: Accepts up to 250 line items, retrieves tier exchange rates, computes converted totals, and returns batch payload. |
| **GET** | `/pricing-tiers/{tierId}` | `PricingTiers_View` | **UPDATED**: Returns `currencyCode`, `exchangeRate`, and `roundingRule` in the tier detail object. |
| **GET** | `/pricing-tiers` | `PricingTiers_View_List` | **UPDATED**: Includes new currency fields in the tier collection response. |
| **POST** | `/pricing-tiers` | `PricingTiers_Create` | **UPDATED**: Accepts `currencyCode`, `exchangeRate`, and `roundingRule` in `CreatePricingTierDto`. |
| **PUT** | `/pricing-tiers/{tierId}` | `PricingTiers_Edit` | **UPDATED**: Allows updating `exchangeRate` and `roundingRule`; `currencyCode` is immutable once created. |

*Note: `DELETE /pricing-tiers/{tierId}` is not affected.*

---

## 4. Exact Code Files to Modify

1.  **`Billing.Domain/Entities/PricingTier.cs`**
    *   Add public properties `string CurrencyCode { get; set; }`, `decimal ExchangeRate { get; set; }`, `RoundingRule RoundingRule { get; set; }`.
2.  **`Billing.Application/Common/Validators/CurrencyCodeValidator.cs`**
    *   Add validation rule checking regex `^[A-Z]{3}$`. Must match against ISO-4217 standard list.
3.  **`Billing.Application/Features/PricingTiers/Commands/CreateTier/CreatePricingTierCommand.cs`**
    *   Add fields `CurrencyCode`, `ExchangeRate`, `RoundingRule`.
    *   Add validation: `ExchangeRate` must be $> 0.000000$.
4.  **`Billing.Application/Features/Currency/Queries/BatchConvert/BatchConvertCurrencyQuery.cs`**
    *   Create command handler: takes `List<BatchConvertItemDto>` (maximum 250 items), queries `IX_PricingTiers_TierId_CurrencyCode` using batch query `WHERE (TierId, CurrencyCode) IN (...)`.
5.  **`Billing.Application/Features/Currency/Queries/BatchConvert/BatchConvertCurrencyHandler.cs`**
    *   Perform rounding using specified `RoundingRule`.
    *   Items whose `TierId` does not exist should return with `status: "ERROR"` and `errorCode: "TIER_NOT_FOUND"` while allowing the rest of the batch to complete successfully.
6.  **`Billing.Api/Controllers/InternalCurrencyController.cs`**
    *   Expose `POST /internal/currency/batch-convert` with `[Authorize(Policy = "Billing_Internal_Service")]`.
7.  **`Billing.Client/BillingApiClient.cs`** (Shared Client Library)
    *   Add method `Task<BatchConvertResponse> BatchConvertAsync(BatchConvertRequest request, CancellationToken ct)`.
    *   Publish updated client version `2.4.0` for consumption by `MS-Orders`.

---

## 5. Acceptance Criteria

1.  **Batch Performance:** A single `POST /internal/currency/batch-convert` call converts a list of 200 items in $< 35\text{ ms}$ on test database.
2.  **Input Validation:**
    *   Submitting an invalid currency code (e.g. `us`, `US1`, `EUROPE`) is rejected with `HTTP 400 Bad Request` and code `INVALID_CURRENCY_CODE`.
    *   Exchange rate $\le 0.000000$ is rejected with `HTTP 400 Bad Request` and code `INVALID_EXCHANGE_RATE`.
3.  **Partial Match Resilience:** If 5 out of 100 items reference non-existent `tierId`, the API returns HTTP 200 with converted prices for the 95 valid items and an error object (`status: "ERROR"`, `errorCode: "TIER_NOT_FOUND"`) in the result list for the 5 invalid items.
4.  **Immutability:** Attempting to modify `currencyCode` via `PUT /pricing-tiers/{tierId}` returns `HTTP 422 Unprocessable Entity` with message `"CurrencyCode cannot be modified after tier creation"`.
5.  **Test Coverage:** Unit tests on `BatchConvertCurrencyHandler` must cover all three rounding rules (`HALF_UP`, `FLOOR`, `CEILING`) with coverage meeting the project's configured threshold (`quality_gates.test_coverage_threshold_percent`, e.g. $\ge 80\%$).

---

## 6. Canonical JSON Contracts

### `POST /internal/currency/batch-convert`
Headers:
*   `Content-Type: application/json`
*   `X-Service-Client: MS-Orders`
*   `X-Correlation-ID: 7f8a9b2c-3d4e-5f6a-7b8c-9d0e1f2a3b4c`

#### Request Payload
```json
{
  "targetCurrency": "EUR",
  "items": [
    {
      "lineItemId": "cart-line-1001",
      "tierId": "tier-gold-eur",
      "baseAmount": 99.99
    },
    {
      "lineItemId": "cart-line-1002",
      "tierId": "tier-standard-eur",
      "baseAmount": 14.50
    },
    {
      "lineItemId": "cart-line-1003",
      "tierId": "tier-nonexistent",
      "baseAmount": 25.00
    }
  ]
}
```

#### Response Payload (HTTP 200 OK)
```json
{
  "targetCurrency": "EUR",
  "calculatedAt": "2026-09-10T14:32:00.124Z",
  "results": [
    {
      "lineItemId": "cart-line-1001",
      "status": "SUCCESS",
      "baseAmount": 99.99,
      "convertedAmount": 92.25,
      "appliedRate": 0.922584,
      "roundingRule": "HALF_UP"
    },
    {
      "lineItemId": "cart-line-1002",
      "status": "SUCCESS",
      "baseAmount": 14.50,
      "convertedAmount": 13.38,
      "appliedRate": 0.922584,
      "roundingRule": "HALF_UP"
    },
    {
      "lineItemId": "cart-line-1003",
      "status": "ERROR",
      "errorCode": "TIER_NOT_FOUND",
      "errorMessage": "Pricing tier 'tier-nonexistent' does not exist in currency 'EUR'."
    }
  ]
}
```

#### Canonical Error Response Payload (HTTP 400 Bad Request)
```json
{
  "status": 400,
  "errorCode": "INVALID_CURRENCY_CODE",
  "message": "The supplied targetCurrency 'EURO' is not a valid 3-letter ISO-4217 code.",
  "timestamp": "2026-09-10T14:32:00.124Z"
}
```

---

## 7. Dependencies & Task Order
- **Prerequisites:** None (standalone feature within OrderBillingService).
- **Subsequent Tasks:** Blocks `[SHOP-105]` (Frontend Checkout Currency Picker in Admin Dashboard).
