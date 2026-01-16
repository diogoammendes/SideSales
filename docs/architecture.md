# SideSales Architecture

## Stack Overview
- **Framework**: Django 5 (monolithic app combining backend APIs, server-rendered templates, and admin tooling)
- **Database**: PostgreSQL (via `dj-database-url`, compatible with Railway). SQLite is supported for local dev.
- **Frontend**: Django Templates + HTMX for dynamic interactions (small payload, no SPA build step).
- **Auth**: Django authentication with session cookies. Custom views layer user management over built-in `User`.
- **Static files**: Served via WhiteNoise inside the container.
- **Containerization**: Single Dockerfile exposing Gunicorn. Environment variables control secret key, debug, and database URL.

## Apps
- `operations`: domain logic for purchases, sales, payments, dashboards, and configuration screens.
- Future apps (e.g., reporting) can hook into shared services but are out of scope now.

## Core Use Cases
1. **Authentication / Configuration**
   - Users authenticate via Django auth.
   - Config area: manage users (create, reset password, enforce roles).
2. **Purchases**
   - Register a purchase with quantity, unit cost, optional notes, deposit ("sinal"), and additional costs.
   - Track who paid each component (percentual or absolute contribution) and signal amount.
3. **Sales & Payments**
   - Link sales to purchases (one purchase → many sales).
   - Register sale details (buyer info, quantity, negotiated unit price).
   - Record one or more payments per sale with payment method and receiver user.
4. **Dashboard**
   - Overall profit/loss = Σ(sales revenue) − Σ(purchase total incl. extra costs).
   - Per-user ledger = (received from sales) − (invested in purchases / extra costs).

## Data Model
```mermaid
erDiagram
    User ||--o{ PurchaseContribution : pays
    User ||--o{ AdditionalCost       : covers
    User ||--o{ SalePayment          : receives
    Purchase ||--o{ PurchaseContribution : contributions
    Purchase ||--o{ AdditionalCost       : extraCosts
    Purchase ||--o{ Sale                 : sales
    Sale ||--o{ SalePayment              : payments

    User {
        string username
        string email
        bool   is_active
        string role (choices: ADMIN, MANAGER, VIEWER)
    }

    Purchase {
        string title
        text   description
        decimal quantity
        date   purchased_on
        decimal total_amount_original (nullable)
        string  total_currency
        decimal total_amount_eur
        decimal signal_amount_original (nullable)
        string  signal_currency
        decimal signal_amount_eur
        decimal unit_cost (computed: total_amount_eur / quantity)
        decimal total_base (computed: total_amount_eur)
        decimal total_additional (aggregate of AdditionalCost)
        decimal total_cost (computed)
    }

    PurchaseContribution {
        Purchase purchase
        User     payer
        string   contribution_type (ABSOLUTE | PERCENTAGE)
        decimal  value
        decimal  resolved_amount (stored for reporting)
        date     paid_on
        text     notes
    }

    AdditionalCost {
        Purchase purchase
        string   label
        decimal  amount
        User     paid_by
        date     incurred_on
    }

    Sale {
        Purchase purchase
        string   buyer_name
        text     buyer_description
        decimal  quantity
        decimal  unit_price
        decimal  total_price (computed)
        string   status (DRAFT | CONFIRMED | SETTLED)
        date     sold_on
    }

    SalePayment {
        Sale   sale
        User   receiver
        decimal amount
        string method (PIX, TRANSFER, CASH, CARD, OTHER)
        date   paid_on
        text   notes
    }
```

### Derived Totals
- `Purchase.total_cost = total_base + signal_amount + Σ(additional_costs)`.
- `PurchaseContribution.resolved_amount` stores currency value regardless of percentage input.
- `Sale.total_price = quantity * unit_price`.
- Dashboard aggregates totals and user balances via ORM annotations.

## Service Layer
- Use Django model managers/services for encapsulating calculations:
  - `Purchase.objects.with_financials()` to annotate totals.
  - `UserLedgerService` to compute per-user investments vs receipts.

## Views & UX Flow
1. **Auth**: login/logout views using stock Django auth templates (customized theme).
2. **Config → Users**: list users, create new, trigger password reset or set temporary password.
3. **Purchases**:
   - List view with high-level totals and filters (status, date range, responsible user).
   - Create/Edit form capturing purchase core data.
   - Inline sections for contributions, additional costs, and deposit (HTMX partials to add rows).
4. **Sales**:
   - List view grouped by purchase.
   - Create sale tied to purchase, capture buyer info and default payment plan.
   - Payments subform for installments and receivers.
5. **Dashboard**:
   - Cards for overall totals (invested, revenue, net profit).
   - Table per user with `invested`, `received`, `net`.
   - Table per purchase summarizing cost vs revenue vs profit.

## Permissions / Roles
- `ADMIN`: full access incl. user management.
- `MANAGER`: manage purchases/sales/payments but cannot modify roles.
- `VIEWER`: read-only dashboards and listings.
- Enforced via Django's permission system + custom decorators.

## Deployment Notes
- `.env` driven config: `DJANGO_SECRET_KEY`, `DJANGO_DEBUG`, `DATABASE_URL`, `ALLOWED_HOSTS`, `CSRF_TRUSTED_ORIGINS`.
- Collect static files during CI/CD (`python manage.py collectstatic --noinput`).
- Dockerfile installs requirements, copies app, runs migrations + Gunicorn entrypoint.
```
ENTRYPOINT ["gunicorn", "sidesales.wsgi:application", "--bind", "0.0.0.0:8000"]
```
- Railway service just needs `PORT` env; Gunicorn respects it (pass via `$PORT`).

## Testing Strategy
- Model tests for totals and resolved amounts.
- Service tests for dashboard aggregates.
- View tests for permissions (role-based access).
- HTMX partial tests via Django test client.

## Roadmap (MVP scope)
1. Auth scaffolding + base template.
2. Purchases CRUD + contributions & extra costs inline forms.
3. Sales CRUD + payments.
4. Dashboard + ledger service.
5. User management UI.
6. Dockerization + Railway-ready settings.
