# Backend Integration Architecture Audit

**Project:** Enterprise SaaS E-commerce Super Admin Dashboard  
**Audit type:** Read-only static code review  
**Scope:** Frontend source, API adapters, types, mock repository, authentication UI, environment configuration, and README. No source or configuration files were changed for this audit; this report is the only new file.

## Executive assessment

The project has a useful frontend boundary for a future JSON/HTTP backend: API base URL and timeout are centralized, domain API modules exist, and the UI's directory data access goes through `dataRepository.ts`. That is a starting architecture, not a finished backend integration. Most domain API modules are not used by the pages, several contracts disagree with the generic adapter's assumptions, and the mock implementation is the only runtime path verified in this project.

The frontend is **database-neutral by design only in the limited sense that it does not connect to a database**. FastAPI, Express, PostgreSQL, MongoDB, MySQL, or Supabase could sit behind a compatible backend API, but no backend or database adapter is included or runtime-tested. Multi-tenant isolation, authentication, authorization, and production data integrity must be implemented and enforced server-side before connecting real tenant data.

### Priority summary

| Priority | Finding | Consequence |
| --- | --- | --- |
| **P0** | No real authentication, route guard, or permission enforcement | Anyone who can load the frontend can view the admin UI; no request identity is currently attached. |
| **P0** | No tenant identity or isolation contract in the models/repository | A backend cannot safely infer tenant scope from these frontend records or query parameters. |
| **P1** | Generic CRUD/status adapter does not match resource semantics or proposed endpoint coverage | Production mode can issue unsupported or unsafe operations on invoices, audit logs, monitoring, security sessions, and other resources. |
| **P1** | API response/error handling assumes JSON and inconsistent envelopes | 204 responses, backend validation errors, and alternate response shapes can fail or lose useful detail. |
| **P1** | Mock mode is the default when the environment variable is missing | A production deployment can silently show and mutate demo data if build configuration is omitted. |
| **P2** | Domain service modules and interceptor helpers are mostly disconnected from the UI data path | There are parallel API abstractions and no single exercised contract boundary. |
| **P2** | Models are broad and incomplete for enterprise SaaS entities | Tenant relationships, audit context, refund state, and several workflow-specific data contracts are not expressed strongly. |

## 1. Implemented architecture vs. proposed architecture

### Implemented in the frontend

- `src/services/api/http.ts` provides a centralized Fetch client with an environment-based base URL, timeout/abort, JSON request headers, and basic non-2xx handling.
- `src/services/api/endpoints.ts` defines a set of version-relative route strings.
- Resource-specific modules exist under `src/services/api/` for stores, tenants, plans, users, billing, payments, and other areas.
- `src/services/dataRepository.ts` selects mock or HTTP behavior for directory listing, save, delete, and status changes. The pages use this adapter for their directory operations.
- `src/services/mock/repository.ts` implements local demo listing, search, filtering, sorting, pagination, and localStorage-backed CRUD.
- Domain interfaces and shared response/pagination types are present in `src/types/models.ts`.
- Authentication screens explicitly identify themselves as frontend demo UI. The login action does not authenticate with a server.
- The UI does not connect directly to PostgreSQL, MongoDB, MySQL, or Supabase, and no database credentials appear in the frontend environment example.

### Proposed, incomplete, or not verified

- API routes are proposals in the README; there is no server implementation, OpenAPI document, schema validation, or integration test proving those routes exist.
- Most `*Api.ts` service modules are not called by the dashboard pages. Directory pages use generic `dataRepository` functions; overview KPI values and analytics are still static/demo content.
- `interceptors.ts` is a placeholder export and is not connected to `http.ts`.
- `VITE_USE_MOCK_API=false` selects generic Fetch calls for directory operations, but it does not connect every dashboard feature to its domain API module.
- No backend, database, browser authentication flow, tenant provisioning, payment gateway, or database adapter is present.

## 2. API service architecture and backend independence

**Assessment: Partially backend-independent; suitable as a starting HTTP boundary, not yet a stable API contract.**

The positive architectural choice is keeping transport configuration in `http.ts` and placing persistence behind `dataRepository.ts`; this can let the UI remain largely unchanged when a backend replaces mock data. The frontend itself has no database vendor coupling.

Key gaps:

1. `dataRepository.ts` maps resource names to paths and performs broad generic operations. It does not delegate to the resource-specific API modules, so special operations and resource-specific request/response types are bypassed.
2. The API modules use different shapes: `createResourceApi` expects `ApiResponse<T>` for single items and `PaginatedResponse<T>` for lists, while the mock service returns paginated data directly and `dataRepository.savePlatformRecord` expects `{ data: BaseRecord }`. These are conventions, not a backend-enforced contract.
3. `http.ts` always parses successful responses as JSON. A valid `204 No Content` response (for example, a DELETE) will fail while parsing. It also converts non-2xx responses into only a status-based message and does not parse structured validation details.
4. The resource list API sends `page`, `pageSize`, `search`, `status`, `sortBy`, and `sortDirection`; no formal contract states whether sorting/filtering names or pagination metadata match a server implementation.
5. `monitoring` in the generic repository maps to `/monitoring/incidents`, while the declared monitoring health endpoint is `/monitoring/health`. The generic page therefore does not model health/metrics/incidents as separate resources.
6. Generic `PATCH /:id/status` is issued for every directory resource. That route is only proposed for stores and tenants. Subscriptions use cancel/reactivate actions; invoices, payments, audit logs, sessions, and monitoring data need narrower semantics or read-only access.

**Recommendation:** Define resource-specific repository interfaces and make both mock and HTTP adapters implement those interfaces. Define one documented envelope and error schema, then make pages call the appropriate service methods (for example, `cancelSubscription`, `voidInvoice`, and `revokeSession`) instead of generic status/delete operations.

## 3. FastAPI and Express compatibility

**Architectural compatibility: Yes, with contract alignment. Runtime compatibility: Not tested.**

Both FastAPI and Express can serve the proposed versioned JSON/HTTP routes. Neither framework is required by the frontend, and there is no framework-specific client code. FastAPI/Pydantic models or Express/Zod (or another server validator) could implement equivalent DTOs.

The backend must agree with the frontend on:

- URL prefix and route methods, including special actions versus generic PATCH/DELETE.
- List query names and pagination envelope.
- Single-resource response envelope.
- Error body shape, validation field errors, and status-code semantics.
- Date/time format, currency minor-unit rules, nullability, and enum values.
- Cookie/session behavior, CORS, and CSRF protections if API and frontend use different origins.

The current client has no generated OpenAPI client, schema validation at runtime, or contract test. Compatibility is therefore a reasonable design target, not something demonstrated by a running FastAPI or Express service.

## 4. Database compatibility through backend adapters

| Database/service | Frontend finding | Required backend work |
| --- | --- | --- |
| PostgreSQL | No direct driver or SQL assumptions in the browser. | Implement API repositories/queries, migrations, constraints, indexes, and tenant scoping. |
| MySQL | No direct driver or SQL assumptions in the browser. | Implement equivalent API behavior and transactions behind the same DTO contract. |
| MongoDB | No direct driver or document assumptions in the browser. | Map documents to stable API DTOs; enforce ownership, validation, indexes, and transaction semantics server-side. |
| Supabase | No Supabase SDK or direct database connection is present. | Prefer a server-side adapter for privileged operations. If using Supabase Auth/PostgREST directly, design RLS and public-key exposure carefully; never expose a service-role key. |

These options can be interchangeable **only behind a backend contract**. Database compatibility is not achieved by the current frontend adapter and must not be represented as runtime-tested support.

## 5. Multi-tenant SaaS data architecture

**Assessment: Tenant concepts appear in labels and fixture records, but tenant isolation is not modeled.**

The models do not define a canonical `tenantId` on tenant-owned records or typed relationships between tenant, store, subscription, invoice, payment, and user. For example, a store contains an owner name and plan name as strings, while a tenant contains only a store count. These are presentation fixtures, not durable relational contracts. Platform-level records and tenant-owned records are not distinguished by scope.

Before production integration, establish a backend ownership model with at least:

- Stable IDs and foreign-key relationships (`tenantId`, `storeId`, `subscriptionId`, etc.) rather than display names as references.
- Explicit platform-admin scope versus tenant-owned scope.
- Server-derived tenant context from the authenticated session/token, not a trusted client-supplied `tenantId` filter.
- Authorization and ownership checks on every read and mutation, including exports, global search, and background jobs.
- A documented isolation strategy (shared tables with tenant keys, schema/database per tenant, or another model), with indexes and unique constraints that include tenant scope where needed.
- Audit events recording actor, scope, action, target, result, and timestamp using server-generated values.

PostgreSQL RLS or Supabase RLS can provide an additional control layer, but it does not remove the need for correct server authentication and policy design. MongoDB and MySQL need equivalent explicit server-side scope enforcement.

## 6. Authentication and role-based access preparation

**Implemented:** Demo login, forgot/reset-password, two-factor, unauthorized, and session-expired presentation routes. The UI warns that authentication must come from a backend.

**Missing:** There is no auth adapter, protected route, identity/session provider, API credential attachment, refresh/logout contract, or route/action permission check. All dashboard routes are directly accessible. The admin role shown in the UI is not an authenticated identity. The role page is generic directory CRUD; the permission interface is not implemented as an enforceable permission matrix.

Recommended backend contract:

- Prefer secure HTTP-only, `Secure`, appropriately `SameSite` session cookies for browser sessions, with CSRF defenses on state-changing requests. If bearer tokens are chosen, define short-lived access and carefully controlled refresh behavior; do not put long-lived secrets in localStorage.
- Add frontend session bootstrap, explicit loading/expired states, and route guards for presentation. Treat those guards as UX only.
- Enforce role and object-level authorization on the server for every endpoint. A hidden button or client-side role check is not authorization.
- Define invitation, MFA enrollment/challenge/recovery, password reset, session revocation, lockout, and logout contracts.
- Keep authorization claims minimal and refresh/revoke them according to a server-defined policy.

## 7. TypeScript API contracts

**Assessment: Useful initial types, but not strict enough to serve as authoritative contracts.**

`tsconfig.app.json` enables strict TypeScript. Shared types cover common resource shapes, `ApiResponse<T>`, pagination, errors, sort/filter parameters, and several entity records.

Gaps and risks:

- `BaseRecord` has a broad `[key: string]` index signature and common required `status`/`createdAt`, which lets unrelated resources share generic CRUD but weakens resource-specific guarantees.
- `EntityStatus` is shared across unrelated domains and omits domain states (for example, refund and incident states); it also allows inappropriate generic state mutation across resources.
- Models are missing requested or needed entities/fields such as a dedicated `Refund`, invoice line items/tax/discount/address, typed platform settings sections, webhook model use, tenant/store IDs, role-permission assignments, session details, and typed monitoring metrics/incidents.
- `ApiError` does not specify a stable backend error envelope or validation-field format. `ApiResponse<T>` does not define whether list responses wrap `data` or return `items` directly.
- `resourceApi.ts` constrains every generic resource to `BaseRecord`, which is unsuitable for some aggregate endpoints and encourages generic behavior where specialized operations are needed.
- `integrationsApi.ts` currently types webhooks as `Integration`, not `Webhook`.

Recommended next step: define DTO schemas by resource/action, use discriminated domain-specific status unions, and generate or validate client types from an OpenAPI specification. Keep transport DTOs separate from UI view models.

## 8. Mock-data separation

**Assessment: A mock seam exists, but it is incomplete and has a risky implicit default.**

Mock fixtures are centralized in `src/data/mockData.ts`, and browser persistence is isolated in `src/services/mock/repository.ts`. The UI calls `dataRepository.ts`, which selects mock versus HTTP mode. This is a sound direction.

Risks and limitations:

- `useMock` is set to mock unless `VITE_USE_MOCK_API` is exactly the string `false`. Missing or misspelled production configuration therefore falls back to demo data instead of failing closed.
- Not all screens use API services; overview KPI cards and charts are static examples, while some directory records use repository data.
- The `*Api.ts` files and interceptor helper are mostly not the active adapter used by pages, so they can drift from the generic repository.
- The mock repository trusts `JSON.parse` through a type assertion and has no runtime shape validation or migration/version strategy for browser data.
- CSV import uses simple comma splitting, so quoted commas/escaped quotes are not handled correctly; imported rows are only partially validated.

Production builds should require an explicit mode and API URL, fail visibly if configuration is missing, and never silently present demo data as live records.

## 9. Frontend security risks

1. **No authentication or authorization boundary (P0).** Dashboard routes and operations are UI-only. Do not connect privileged APIs until server-side authentication and authorization exist.
2. **No tenant isolation contract (P0).** Frontend filters cannot enforce tenant boundaries; backend queries must derive scope from authenticated identity and verify object ownership.
3. **Production can default to mock data (P1).** Change deployment policy so production cannot silently build/run with mock mode.
4. **Credentialed cookie requests are not configured (P1 if cookie auth is selected).** Fetch does not set `credentials: 'include'`; CSRF and cross-origin behavior are also unspecified. Prefer same-origin proxying where practical and configure CORS narrowly.
5. **Generic actions may target sensitive/immutable data (P1).** The resource page exposes generic edit, delete, suspend/reactivate actions for all resource types. Several proposed resources should be read-only or use audited special actions.
6. **CSV formula injection (P2).** CSV export quotes values but does not neutralize spreadsheet formulas beginning with `=`, `+`, `-`, or `@`. Sanitize exported cell content and use a robust CSV encoder.
7. **Client-side storage is not appropriate for future real records/secrets (P2).** The current mock stores demo datasets and the theme in localStorage; do not reuse this persistence mechanism for credentials, private API keys, payment details, or sensitive production records.
8. **No runtime response validation.** Server payloads are asserted to TypeScript types at compile time; malformed or unexpectedly shaped JSON is not validated at runtime.
9. **Frontend URL configuration needs deployment controls.** `VITE_*` values are public. Ensure production uses HTTPS and never put secrets in these variables. Consider validating configured URLs and setting a restrictive Content Security Policy at the hosting layer.

The review did not find frontend payment secrets or server credentials in the inspected source. This is a source inspection, not a complete secret-scanning or deployment audit.

## 10. Missing backend integration requirements

Prioritized integration work:

### P0 — Required before connecting privileged production data

- Implement real admin authentication and server-side authorization, including MFA/session lifecycle where required.
- Establish tenant ownership/scope and enforce it on every route and background operation.
- Define platform-admin versus tenant-owned resources and immutable/audited operations.
- Require explicit production API configuration and prevent an accidental mock-mode deployment.

### P1 — Required for a reliable API adapter

- Publish an OpenAPI specification covering methods, DTOs, query parameters, pagination, error bodies, date formats, enums, and special actions.
- Reconcile generic repository routes with actual contracts; make audit logs, monitoring, settings, invoices, payments, and security sessions resource-specific.
- Standardize success and error envelopes; support `204` responses and structured validation errors in `http.ts`.
- Connect the page layer to the domain API modules or replace them with typed repository ports; remove duplicate, unused contract paths.
- Add appropriate cookie/bearer handling, CSRF controls, CORS policy, request/correlation IDs, cancellation, and server-side rate limiting.
- Implement domain workflows: invoice send/void, payment/refund verification, subscription cancel/reactivate, user invitation, role permissions, webhook signing/delivery, notification scheduling, support replies, security/session revocation.

### P2 — Required for data correctness and operations

- Add domain-specific DTOs and runtime validation; use stable resource IDs and tenant-scoped relationships.
- Build database adapters/migrations, indexes, constraints, transaction boundaries, idempotency keys for financial mutations, and audit trails.
- Add contract tests against the backend OpenAPI spec, integration tests for tenant isolation and authorization, and UI tests for failure/expired-session states.
- Add observability and operational safeguards for retries, timeouts, duplicate submissions, pagination limits, and export size limits.
- Harden CSV import/export, including proper quoting, formula neutralization, file size limits, and row-level validation feedback.

## Conclusion

The current frontend is a database-agnostic demo with an early REST adapter seam. It can be integrated with a FastAPI or Express backend that exposes the agreed HTTP contract, and that backend can use PostgreSQL, MongoDB, MySQL, or Supabase behind its own adapters. None of those backend/database combinations are implemented or runtime-tested here. The most important blockers are missing authentication/authorization and tenant isolation, followed by contract mismatches and generic actions that are unsafe for several domain resources.
