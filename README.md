# Northstar Platform — SaaS Super Admin Template

A responsive, frontend-only super admin dashboard starter for a multi-tenant SaaS e-commerce platform. The demo currently uses centralized mock data persisted in the browser. It does not create real stores, process billing, provision tenants, authorize roles, or authenticate administrators.

## Stack

- React 19, TypeScript, and Vite
- Bootstrap 5 layout, forms, utilities, and Bootstrap Icons
- React Router with lazy-loaded dashboard pages
- Recharts for responsive revenue visualizations
- Fetch-based API client and typed proposed service contracts

## Setup

```sh
npm ci
cp .env.example .env.local
npm run dev
```

Build and lint:

```sh
npm run build
npm run lint
npm run preview
```

## Environment

```dotenv
VITE_API_BASE_URL=http://localhost:5000/api/v1
VITE_API_TIMEOUT=15000
VITE_USE_MOCK_API=true
```

Only public configuration belongs in `VITE_*` variables. Never put provider credentials, signing secrets, or private API keys in frontend environment variables. Vite requires `VITE_USE_MOCK_API` to be explicitly set to `true` or `false`. When it is `false`, set an absolute `VITE_API_BASE_URL`; use HTTPS outside localhost. API mode is only an integration seam and does not add authentication or authorization.

## Mock mode

With `VITE_USE_MOCK_API=true`, the UI reads fixtures from `src/data/mockData.ts` through `src/services/dataRepository.ts` and `src/services/mock/repository.ts`. Lists support search, status filtering, sorting, pagination, CSV export, and browser-local CRUD changes. Store CSV import accepts at most 100 data rows and 2 MB; export includes all matching pages and protects formula-like cells. Set `VITE_USE_MOCK_API=false` to route directory operations through the typed HTTP repository; that mode requires the proposed backend contracts to exist. Use “Clear site data” in browser settings to reset the demo. Data is explicitly illustrative. A displayed payment, invoice, health status, or audit entry is not a verified production record.

The directory pages share a reusable mock CRUD workflow. Status changes and deletion only affect the local demo dataset. Store creation and other forms do not provision real infrastructure or send invitations. Authentication screens are demonstrations only.

## API integration

`src/services/api/http.ts` centralizes the base URL, timeout, JSON headers, abort timeout, and normalized fetch errors, including empty 204 responses. Build/dev startup validates explicit mock/API configuration and rejects non-HTTPS remote API URLs. Domain API modules are split by resource and use the contracts in `endpoints.ts` and `resource.ts`. These endpoints are proposed examples and are not proof that a backend exists. Replace the mock repository adapter with API-backed repository implementations while preserving page interfaces.

API contract prefix: `/api/v1`.

| Area | Proposed routes |
| --- | --- |
| Platform | `GET /platform/overview`, `/platform/analytics`, `/platform/health` |
| Stores | `GET/POST /stores`, `GET/PATCH/DELETE /stores/:id`, `PATCH /stores/:id/status` |
| Tenants | `GET/POST /tenants`, `GET/PATCH /tenants/:id`, `PATCH /tenants/:id/status` |
| Platform users | `GET /platform/users`, `POST /platform/users/invitations`, `PATCH/DELETE /platform/users/:id` |
| Roles and plans | `/roles`, `/permissions`, `/plans`, and resource `/:id` CRUD routes |
| Subscriptions | `GET /subscriptions`, `GET/PATCH /subscriptions/:id`, `POST /:id/cancel`, `POST /:id/reactivate` |
| Billing and payments | `/billing/invoices`, `/payments`, with send/void/refund subroutes |
| Promotions | CRUD on `/promotions` |
| Monitoring and audit | `/monitoring/health`, `/monitoring/metrics`, `/monitoring/incidents`, `/audit-logs` |
| Notifications | `/notifications`, with `POST /:id/send` |
| Integrations and webhooks | `/integrations`, `/webhooks` |
| Settings and security | `/settings`, `/security/sessions`, `/security/events` |
| Support | `/support/tickets` |

All resource list contracts accept query parameters for search, filters, sort, and pagination. The backend should validate permissions and tenant boundaries on every request. UI permission checks are never a security boundary.

## Routes

`/` Overview · `/analytics` Platform analytics · `/stores` Stores · `/tenants` Tenants · `/platform-users` Platform users · `/roles` Roles & permissions · `/plans` Plans · `/subscriptions` Subscriptions · `/billing` Invoices · `/payments` Payments · `/promotions` Promotions · `/monitoring` Monitoring · `/audit-logs` Audit logs · `/notifications` Notifications · `/integrations` Integrations & API · `/settings` Global settings · `/security` Security · `/support` Helpdesk.

Authentication presentation routes: `/login`, `/forgot-password`, `/reset-password`, `/two-factor`, `/unauthorized`, `/session-expired`.

## Authentication and secrets

Use a backend session with secure, HTTP-only, same-site cookies where appropriate, CSRF protections for state-changing requests, server-side session revocation, and rate limiting. Do not store passwords or long-lived sensitive credentials in local storage. The demo login only displays a notice and navigates to the dashboard; it does not establish an authenticated session.

Integrations should send API key creation and rotation to the backend. Show a newly created key once if the backend contract requires it, then only show a masked identifier. Never store the secret in browser storage or ship it in client code.

## Feature notes and limits

- Responsive navigation, light/dark theme, dashboard KPI cards, Recharts revenue and plan charts, recent activity, analytics date filters, and CSV export.
- Shared record directories for stores, tenants, staff, roles, plans, subscriptions, billing, payments, promotions, monitoring, audit, notifications, integrations, settings, security sessions, and support.
- Directory actions operate on local mock data. Production-specific workflows such as verified refunds, invoice payment, plan comparisons, role authorization, webhooks, mail delivery, security policy enforcement, and ticket replies require backend APIs and additional page-specific UI.
- The app is a super admin console and does not contain merchant storefront management. Original-source license terms are not yet supplied. Third-party package, font, and asset inventory is in `THIRD_PARTY_NOTICES.md`; resolve ownership and redistribution rights before commercial distribution.

## Deployment

Run `npm ci`, copy `.env.example` to `.env.local`, set the intended mode and API URL, then run `npm run build` and deploy the generated `dist/` directory to a static host. Configure SPA history fallback so deep links resolve to `index.html`. Configure the public API base URL at build time. Production API calls must use HTTPS and server-side authorization.
