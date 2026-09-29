# NammaBiz

NammaBiz is a Madurai marketplace for local services and B2B supplies. The existing supplier directory, product pages, RFQs, and project estimators remain available alongside customer, contractor, and administrator workflows.

## Local setup

Use Python 3.10 or later, install the dependencies, then apply the versioned migrations:

```powershell
python -m pip install -r requirements.txt
$env:AUTO_CREATE_DB = "false"
flask --app wsgi:application db upgrade
Remove-Item Env:AUTO_CREATE_DB
python app.py
```

Open http://127.0.0.1:8000. Local development defaults to `data/nammabiz.sqlite3`; `DATABASE_URL` can select another SQLAlchemy database URL. The first local run seeds the existing sample supplier catalog and a configurable service catalog. Production sample supplier seeding is disabled.

Admin accounts are provisioned automatically at application startup when `ADMIN_EMAIL` and `ADMIN_PASSWORD` are configured. For local development, set them in the process environment before starting the app:

```powershell
$env:ADMIN_EMAIL = "jenison717@gmail.com"
$env:ADMIN_PASSWORD = "<set securely>"
python app.py
```

The password is hashed before storage and is never committed to the repository. Render uses the same variables; set `ADMIN_PASSWORD` as a secret environment variable. Public registration cannot create an admin account.

## Roles and workflows

- Customers register, search active services and approved contractors, create requests with optional photos, track jobs, message the assigned contractor, submit complaints, review completed work, and view pending payment records.
- Contractors register with service and business details, maintain a profile and portfolio, publish weekly hours and leave, respond to matching requests after approval, schedule jobs, and mark work started/completed.
- Admins are provisioned from deployment environment credentials. They manage accounts, contractor verification, service categories and services, jobs, payment records, reviews, complaints, notifications, reports, and the platform fee setting. Administrative actions are audited.
- The original supplier search, product directory, RFQs, estimator, and JSON business endpoint remain. RFQ contact data and supplier-management actions are no longer public; supplier writes require an admin session.

Routes are split across `routes/`, business rules across `services/`, and SQLAlchemy models across `models/`. Flask-Migrate revisions live under `database/migrations/`. Migrations preserve the existing `businesses`, `products`, and `rfqs` tables; the existing SQLite database is not replaced.

## Security and integrations

Passwords are hashed, roles are checked on the server, unsafe forms use CSRF tokens, and uploads use generated filenames with an 8 MB request-size limit. Reset emails require `MAIL_SERVER`, `MAIL_PORT`, `MAIL_USERNAME`, `MAIL_PASSWORD`, and `MAIL_DEFAULT_SENDER` environment variables. Notifications other than password resets are in-app only.

Razorpay Checkout is integrated but disabled by default. To demo with Razorpay test credentials, configure the following process environment variables from the Razorpay test dashboard before starting the app:

```powershell
$env:PAYMENT_MODE = "razorpay_test"
$env:RAZORPAY_KEY_ID = "rzp_test_..."
$env:RAZORPAY_KEY_SECRET = "..."
$env:RAZORPAY_WEBHOOK_SECRET = "..."
```

The key ID must have the `rzp_test_` prefix in test mode. The webhook secret is optional for the browser checkout callback, but required for the `/payments/webhooks/razorpay` endpoint. Checkout creates a Razorpay order; NammaBiz records `SUCCESS` only after server-side signature verification and a provider fetch confirms captured status, order, INR currency, and exact amount. Test-mode payments do not move real money. Do not use live credentials for a demo. Live mode requires `PAYMENT_MODE=razorpay_live` and an `rzp_live_` key ID. Refunds and contractor payouts are not implemented.

Uploads are stored under `UPLOAD_ROOT` (default: `uploads/`). This local directory is ignored by Git and is not durable on Render's ephemeral web filesystem. Configure persistent storage or object storage before using uploads in production. The PWA shell is preserved; it does not synchronize marketplace data offline.

## Render

The Blueprint provisions a PostgreSQL database, applies migrations during build, and serves the Flask WSGI application through Gunicorn. Set SMTP variables in Render to enable password-reset delivery. A newly provisioned Render database does not automatically contain the local SQLite supplier records; import those records before switching live traffic. Review the selected Render database plan and storage retention for production use.

To copy the legacy supplier, product, and RFQ records into an empty PostgreSQL database, configure `DATABASE_URL` to that database in your local environment, then run:

```powershell
$env:AUTO_CREATE_DB = "false"
$env:SEED_SAMPLE_DATA = "false"
flask --app wsgi:application db upgrade
python -m scripts.import_legacy_sqlite data/nammabiz.sqlite3
```

The importer reads the SQLite source in read-only mode, preserves record IDs, and refuses to run if any destination legacy table already contains data. It does not copy local uploads or seed sample listings.

## Tests

```powershell
python -m unittest discover -s tests
```
