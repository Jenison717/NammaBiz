# NammaBiz

NammaBiz is a Python marketplace for local B2B sourcing in Madurai. It helps builders, workshops, contractors, and professional buyers discover suppliers, review products, and send RFQs.

## Run

Requires Python 3.10 or later. No package install is required for local development.

```powershell
python app.py
```

Open http://127.0.0.1:8000.

To run a second instance on another port, use `python app.py 8001`.

## Browser and mobile app

NammaBiz is a responsive Progressive Web App (PWA). It works in desktop and mobile browsers, and can be installed from a supported browser's menu as an app-like shortcut. The manifest and service worker are served from `/static/manifest.json` and `/sw.js`.

To test it from another device on the same Wi-Fi network, run:

```powershell
python app.py 8000 0.0.0.0
```

Open the computer's local network IP address on the phone. Public access requires deployment behind HTTPS with a production WSGI server and a hosted database.

## Render deployment

The repository includes `render.yaml`, `wsgi.py`, and a production server dependency for a Render Web Service. Connect the repository in Render and create a Blueprint from `render.yaml`; Render will provide a public `onrender.com` URL.

The current SQLite database is suitable for a first preview only. Render's free service filesystem is ephemeral, so RFQs and other database changes will not survive restarts. Before production launch, migrate the database to PostgreSQL.

## Included workflows

- Search suppliers by material, category, availability, and verification
- Browse detailed supplier profiles and quoted products
- Send an RFQ directly to a supplier
- Manage supplier visibility, buyer RFQs, and new supplier listings
- Use JSON endpoints at `/api/businesses` and `/api/rfqs`

Data is stored locally in `data/nammabiz.sqlite3` and seeded on the first run.

## Test

```powershell
python -m unittest discover -s tests
```
