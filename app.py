"""NammaBiz local B2B marketplace. Runs on the Python standard library."""

from __future__ import annotations

import html
import json
import os
import re
import sqlite3
import sys
from pathlib import Path
from urllib.parse import parse_qs, urlencode

ROOT = Path(__file__).resolve().parent
TEMPLATES = ROOT / "src" / "main" / "resources" / "templates"
STATIC = ROOT / "src" / "main" / "resources" / "static"
DEFAULT_DB = ROOT / "data" / "nammabiz.sqlite3"

CATEGORIES = [
    ("Steel & Metal", "TMT bars, MS pipes, sheets and fabrication"),
    ("Construction", "Cement, aggregates, tiles and building supplies"),
    ("Hardware", "Fasteners, tools and industrial hardware"),
    ("Welding & Fabrication", "Grills, gates, welding and custom work"),
    ("Electrical", "Cables, panels, motors and electrical supplies"),
    ("Plumbing", "Pipes, fittings, pumps and sanitaryware"),
]
SEED = [
    ("Bharath Steels", "Steel & Metal", "TMT and structural steel", "KK Nagar, Madurai", "Wholesale TMT bars, angles, channels and MS pipes for project orders.", "Builders, fabricators", "TMT bars, MS pipes, angles, channels", "Bulk dispatch, cut-to-size", "0452 245 1034", 4.8, 1, 1, 1),
    ("Meenakshi Buildmart", "Construction", "Construction materials", "Anna Nagar, Madurai", "Reliable construction material partner for residential and commercial projects.", "Builders, contractors", "Cement, M-sand, blue metal, blocks", "Site delivery, bulk pricing", "0452 253 8190", 4.7, 1, 1, 1),
    ("Pandian Hardware Traders", "Hardware", "Industrial hardware", "South Masi Street, Madurai", "Trade supplier for fasteners, power tools and building hardware.", "Contractors, workshops", "Fasteners, drill bits, locks, hand tools", "Bulk sourcing, project kits", "0452 234 6691", 4.5, 1, 1, 1),
    ("Vaigai Fabrications", "Welding & Fabrication", "Gates and grill work", "K. Pudur, Madurai", "Custom MS gates, window grills, sheds and industrial fabrication.", "Homeowners, builders", "MS gates, grills, roofing sheets", "On-site measurement, installation", "0452 267 4182", 4.9, 1, 0, 1),
    ("Arun Electricals", "Electrical", "Electrical wholesale", "Goripalayam, Madurai", "Wholesale electrical supplies for contractors, shops and construction teams.", "Electricians, contractors", "Cables, switches, MCBs, LED lights", "Panel assembly, site delivery", "0452 252 9984", 4.6, 1, 1, 1),
    ("Thirumalai Pipes", "Plumbing", "Pipes and fittings", "Kalavasal, Madurai", "PVC, CPVC and GI pipe supplier with fittings for every plumbing project.", "Plumbers, builders", "PVC pipes, CPVC fittings, valves, pumps", "Bulk rates, dispatch", "0452 260 5342", 4.6, 1, 1, 1),
    ("Madura Timber Depot", "Construction", "Timber and plywood", "Sellur, Madurai", "Plywood, doors, laminates and timber for interiors and building work.", "Carpenters, builders", "Plywood, doors, laminates, timber", "Cutting, edge banding", "0452 266 8208", 4.4, 1, 1, 0),
    ("Kaveri Industrial Supplies", "Hardware", "Safety and tools", "Simmakkal, Madurai", "PPE, welding consumables, abrasives and workshop tools for industrial buyers.", "Workshops, fabricators", "Safety shoes, welding rods, abrasives, tools", "Trade pricing, recurring supply", "0452 237 4511", 4.7, 0, 1, 1),
]
PRODUCTS = [(1, "Fe 550D TMT Bars", "Steel", "per tonne", 58500, "High-strength reinforcement bars for commercial projects."), (1, "MS Square Pipe", "Steel", "per length", 740, "Structural pipe for gates, frames and fabrication."), (2, "OPC 53 Grade Cement", "Cement", "per bag", 415, "Cement for structural concrete and masonry work."), (4, "Custom MS Main Gate", "Fabrication", "per sq ft", 620, "Measured, fabricated and installed for your site."), (5, "FR Copper Cable", "Electrical", "per coil", 2475, "Reliable cable for contractor and site use."), (6, "CPVC Pipe and Fitting Set", "Plumbing", "per set", 890, "Hot and cold water pipe set for residential plumbing.")]


def esc(value): return html.escape(str(value or ""), quote=True)
def first(values, key): return values.get(key, [""])[0]
def pill(text, tone="muted"): return f'<span class="pill {tone}">{esc(text)}</span>'


class NammaBiz:
    def __init__(self, db_path=DEFAULT_DB):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.setup()

    def db(self):
        connection = sqlite3.connect(self.db_path)
        connection.row_factory = sqlite3.Row
        return connection

    def setup(self):
        db = self.db()
        try:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS businesses (id INTEGER PRIMARY KEY, name TEXT NOT NULL, category TEXT NOT NULL, subcategory TEXT NOT NULL, location TEXT NOT NULL, description TEXT NOT NULL, buyer_types TEXT NOT NULL, products TEXT NOT NULL, services TEXT NOT NULL, phone TEXT NOT NULL, rating REAL NOT NULL, available INTEGER NOT NULL, wholesale INTEGER NOT NULL, verified INTEGER NOT NULL, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
                CREATE TABLE IF NOT EXISTS products (id INTEGER PRIMARY KEY, business_id INTEGER NOT NULL, name TEXT NOT NULL, category TEXT NOT NULL, unit TEXT NOT NULL, price REAL NOT NULL, description TEXT NOT NULL, available INTEGER NOT NULL DEFAULT 1);
                CREATE TABLE IF NOT EXISTS rfqs (id INTEGER PRIMARY KEY, business_id INTEGER NOT NULL, buyer_name TEXT NOT NULL, buyer_email TEXT NOT NULL, requirement TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'PENDING', created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
            """)
            if not db.execute("SELECT COUNT(*) FROM businesses").fetchone()[0]:
                db.executemany("INSERT INTO businesses (name,category,subcategory,location,description,buyer_types,products,services,phone,rating,available,wholesale,verified) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)", SEED)
                db.executemany("INSERT INTO products (business_id,name,category,unit,price,description) VALUES (?,?,?,?,?,?)", PRODUCTS)
            db.commit()
        finally:
            db.close()

    def rows(self, sql, values=()):
        db = self.db()
        try: return db.execute(sql, values).fetchall()
        finally: db.close()

    def write(self, sql, values=()):
        db = self.db()
        try:
            db.execute(sql, values)
            db.commit()
        finally:
            db.close()

    def search(self, query="", category="", available=False, verified=False):
        terms = re.findall(r"[a-z0-9]+", query.lower())
        results = []
        for row in self.rows("SELECT * FROM businesses"):
            if (category and row["category"] != category) or (available and not row["available"]) or (verified and not row["verified"]): continue
            text = " ".join(str(row[key]).lower() for key in ("name", "category", "subcategory", "location", "description", "buyer_types", "products", "services"))
            score = sum(5 for term in terms if len(term) > 1 and term in text) + int(row["rating"]) + 5 * (row["available"] + row["verified"])
            if any(term in query.lower() for term in ("wholesale", "bulk", "supplier", "builder")) and row["wholesale"]: score += 15
            if any(term in query.lower() for term in ("welding", "grill", "fabrication", "gate")) and any(term in text for term in ("welding", "grill", "fabrication", "gate")): score += 15
            if any(term in query.lower() for term in ("steel", "tmt", "cement", "building")) and any(term in text for term in ("steel", "tmt", "cement", "building")): score += 15
            if not terms or score > int(row["rating"]) + 5 * (row["available"] + row["verified"]): results.append((score, row))
        return [row for _, row in sorted(results, reverse=True, key=lambda item: item[0])]

    def layout(self, title, body, notice=""):
        base = (TEMPLATES / "layout.html").read_text(encoding="utf-8")
        toast = f'<div class="notice">{esc(notice)}</div>' if notice else ""
        return base.replace("{{title}}", esc(title)).replace("{{notice}}", toast).replace("{{body}}", body).encode()

    def nav(self, active=""):
        link = lambda url, name, key: f'<a class="{"active" if key == active else ""}" href="{url}">{name}</a>'
        return f'<header class="topbar"><div class="shell nav"><a class="brand" href="/"><b>N</b><span>NammaBiz<small>LOCAL B2B NETWORK</small></span></a><nav>{link("/", "Discover", "discover")}{link("/categories", "Categories", "categories")}{link("/estimator", "Estimator", "estimator")}{link("/dashboard", "Supplier portal", "dashboard")}</nav><a class="button dark" href="/dashboard#add-supplier">List business</a></div></header>'

    def card(self, row):
        tags = pill("Available now", "success") if row["available"] else pill("Currently busy")
        if row["wholesale"]: tags += pill("Wholesale", "blue")
        if row["verified"]: tags += pill("Verified", "gold")
        return f'<article class="supplier-card"><div class="card-top"><i>{esc(row["name"][0])}</i><div>{tags}</div></div><p class="eyebrow">{esc(row["category"])}</p><h3>{esc(row["name"])}</h3><p class="subtle">{esc(row["subcategory"])} / {esc(row["location"])}</p><p>{esc(row["description"])}</p><div class="card-meta"><strong>{row["rating"]:.1f}<small>/5</small></strong><span>{esc(row["buyer_types"])}</span></div><a class="text-link" href="/business/{row["id"]}">View supplier <span>&rarr;</span></a></article>'

    def home(self, query):
        category_cards = "".join(f'<a class="category" href="/search?{urlencode({"category": name})}"><span>{index + 1:02d}</span><h3>{esc(name)}</h3><p>{esc(detail)}</p><small>{len(self.rows("SELECT id FROM businesses WHERE category=?", (name,)))} suppliers</small></a>' for index, (name, detail) in enumerate(CATEGORIES))
        cards = "".join(self.card(row) for row in self.search()[:6])
        active = len(self.rows("SELECT id FROM businesses WHERE available=1"))
        body = self.nav("discover") + f'''<main><section class="market"><div class="shell market-grid"><div><p class="eyebrow">MADURAI PROCUREMENT, MADE LOCAL</p><h1>Source the work.<br><em>Keep it moving.</em></h1><p class="lede">A B2B directory for builders, workshops and project teams who need dependable local supply.</p></div><aside><span class="signal"></span><p>Network status</p><strong>{active} suppliers available now</strong><small>Updated from the supplier portal</small></aside></div></section><section class="search-band"><div class="shell"><form class="finder" action="/search"><label for="q">What do you need?</label><div><input id="q" name="q" autofocus required placeholder="Try: 500 kg MS pipe for a grill project"><button class="button accent">Find suppliers</button></div></form><div class="quick">{''.join(f'<a href="/search?{urlencode({"q": term})}">{term}</a>' for term in ("TMT steel", "Cement", "Welding", "Electrical", "PVC pipes"))}</div></div></section><section class="shell section"><div class="section-title"><div><p class="eyebrow">BROWSE BY TRADE</p><h2>Everyday procurement, one local network.</h2></div><a class="text-link" href="/categories">All categories <span>&rarr;</span></a></div><div class="category-grid">{category_cards}</div></section><section class="shell section"><div class="section-title"><div><p class="eyebrow">READY TO RESPOND</p><h2>Suppliers buyers are contacting today.</h2></div><a class="text-link" href="/search">See directory <span>&rarr;</span></a></div><div class="supplier-grid">{cards}</div></section><section class="workflow"><div class="shell workflow-grid"><div><p class="eyebrow">BUILT FOR REAL PROCUREMENT</p><h2>Find. Compare. Request a quote.</h2></div><ol><li><b>01</b> Search by material, purpose or trade.</li><li><b>02</b> Check local availability and supplier fit.</li><li><b>03</b> Send your requirement directly.</li></ol></div></section></main>'''
        return self.layout("NammaBiz | Local B2B sourcing", body, first(query, "notice"))

    def search_page(self, query):
        term, category = first(query, "q"), first(query, "category")
        available, verified = first(query, "available") == "1", first(query, "verified") == "1"
        results = self.search(term, category, available, verified)
        options = ''.join(f'<option value="{esc(name)}" {"selected" if category == name else ""}>{esc(name)}</option>' for name, _ in CATEGORIES)
        filters = f'<form class="filters"><input type="search" name="q" value="{esc(term)}" placeholder="Material, service or supplier"><select name="category"><option value="">All categories</option>{options}</select><label><input type="checkbox" name="available" value="1" {"checked" if available else ""}> Available now</label><label><input type="checkbox" name="verified" value="1" {"checked" if verified else ""}> Verified</label><button class="icon-button" aria-label="Apply filters" title="Apply filters">&#10003;</button></form>'
        cards = ''.join(self.card(row) for row in results) or '<div class="empty"><p class="eyebrow">NO MATCHES YET</p><h2>Try a broader material or remove a filter.</h2><a class="button dark" href="/search">Clear search</a></div>'
        body = self.nav("discover") + f'<main class="shell page"><p class="crumb"><a href="/">Marketplace</a> / Search</p><div class="page-head"><div><p class="eyebrow">SUPPLIER DISCOVERY</p><h1>{esc(term) if term else "Browse local suppliers"}</h1><p>{len(results)} supplier{"" if len(results) == 1 else "s"} ranked for your requirement.</p></div></div>{filters}<div class="supplier-grid results">{cards}</div></main>'
        return self.layout("Supplier search | NammaBiz", body, first(query, "notice"))

    def categories(self, query):
        cards = ''.join(f'<a class="category large" href="/search?{urlencode({"category": name})}"><span>{index + 1:02d}</span><h2>{esc(name)}</h2><p>{esc(detail)}</p><small>{len(self.rows("SELECT id FROM businesses WHERE category=?", (name,)))} local suppliers</small></a>' for index, (name, detail) in enumerate(CATEGORIES))
        body = self.nav("categories") + f'<main class="shell page"><p class="crumb"><a href="/">Marketplace</a> / Categories</p><div class="page-head"><p class="eyebrow">SOURCE BY TRADE</p><h1>The categories that keep Madurai projects moving.</h1><p>Each category is local, searchable, and ready for a direct requirement.</p></div><div class="category-grid category-list">{cards}</div></main>'
        return self.layout("Categories | NammaBiz", body, first(query, "notice"))

    @staticmethod
    def amount(values, key):
        try:
            value = float(first(values, key))
            return value if value > 0 else 0
        except ValueError:
            return 0

    def estimate(self, project, values):
        if project == "construction":
            area = self.amount(values, "area")
            quality = first(values, "quality") or "standard"
            rates = {"economy": (1650, 1950), "standard": (2100, 2500), "premium": (2700, 3300)}
            if not area or area > 200000: return None
            low, high = rates.get(quality, rates["standard"])
            return {
                "name": "Construction material budget", "area": f"{area:,.0f} sq ft", "low": area * low, "high": area * high,
                "search": "construction materials", "note": "Indicative built-up-area range. Site conditions, drawings, finishes and labour scope can change the final quote.",
                "items": [("Cement", f"{area * .38:,.0f} - {area * .46:,.0f} bags"), ("TMT steel", f"{area * 3.4:,.0f} - {area * 4.3:,.0f} kg"), ("M-sand and aggregates", f"{area * .04:,.1f} - {area * .06:,.1f} tonnes"), ("Indicative material share", "About 60% of total range")]
            }
        if project == "fabrication":
            width, height = self.amount(values, "width"), self.amount(values, "height")
            kind = first(values, "kind") or "gate"
            rates = {"gate": (650, 950, "MS gate"), "grill": (480, 720, "Window grill"), "shed": (340, 520, "Roofing shed"), "railing": (580, 850, "Stair or balcony railing")}
            if not width or not height or width * height > 10000: return None
            low, high, label = rates.get(kind, rates["gate"])
            area = width * height
            return {
                "name": f"{label} estimate", "area": f"{area:,.1f} sq ft", "low": area * low, "high": area * high,
                "search": "welding fabrication", "note": "Includes a typical fabrication and installation allowance. Design complexity, paint, site access and material thickness affect the supplier quote.",
                "items": [("Measured coverage", f"{area:,.1f} sq ft"), ("MS steel allowance", f"{area * 3.5:,.0f} - {area * 6:,.0f} kg"), ("Fabrication and installation", "Included in the range"), ("Recommended next step", "Share dimensions with a local fabricator")]
            }
        return None

    def estimator(self, query):
        project = first(query, "type") or "construction"
        if project not in {"construction", "fabrication"}: project = "construction"
        result = self.estimate(project, query)
        switcher = f'<div class="mode-switch"><a class="{"active" if project == "construction" else ""}" href="/estimator?type=construction">Construction</a><a class="{"active" if project == "fabrication" else ""}" href="/estimator?type=fabrication">Fabrication</a></div>'
        if project == "construction":
            fields = f'<label>Built-up area (sq ft)<input type="number" name="area" min="100" max="200000" required value="{esc(first(query, "area"))}" placeholder="Example: 1200"></label><label>Finish level<select name="quality"><option value="economy">Economy</option><option value="standard" selected>Standard</option><option value="premium">Premium</option></select></label>'
            guide = "Use this for a new residential or commercial build. It gives a high-level local materials budget from built-up area."
        else:
            fields = f'<label>Width (ft)<input type="number" name="width" min="1" max="200" step="0.1" required value="{esc(first(query, "width"))}" placeholder="Example: 12"></label><label>Height or length (ft)<input type="number" name="height" min="1" max="200" step="0.1" required value="{esc(first(query, "height"))}" placeholder="Example: 7"></label><label>Fabrication type<select name="kind"><option value="gate">MS gate</option><option value="grill">Window grill</option><option value="shed">Roofing shed</option><option value="railing">Railing</option></select></label>'
            guide = "Use this for gates, grills, sheds or railings. The estimate is based on the visible coverage area."
        result_html = ""
        if result:
            rows = ''.join(f'<div><span>{esc(label)}</span><strong>{esc(value)}</strong></div>' for label, value in result["items"])
            requirement = f"I need an estimate for {result['name'].lower()} covering {result['area']}. Budget range: Rs {result['low']:,.0f} - Rs {result['high']:,.0f}."
            result_html = f'<section class="estimate-result"><p class="eyebrow">YOUR INDICATIVE RANGE</p><h2>Rs {result["low"]:,.0f} - Rs {result["high"]:,.0f}</h2><p>{esc(result["name"])} for {esc(result["area"])}.</p><div class="estimate-lines">{rows}</div><p class="estimate-note">{esc(result["note"])}</p><a class="button accent" href="/search?{urlencode({"q": result["search"]})}">Find matching suppliers</a><p class="estimate-copy">Use this when requesting quotes: {esc(requirement)}</p></section>'
        body = self.nav("estimator") + f'<main class="shell page estimator"><p class="crumb"><a href="/">Marketplace</a> / Estimator</p><div class="page-head"><p class="eyebrow">PROJECT ESTIMATOR</p><h1>Start with a useful number.</h1><p>Build a local budget range before you contact suppliers. It is a planning estimate, not a final project quote.</p></div><div class="estimator-grid"><section class="estimator-form">{switcher}<h2>{"Construction material budget" if project == "construction" else "Fabrication cost range"}</h2><p>{guide}</p><form method="get"><input type="hidden" name="type" value="{project}">{fields}<button class="button dark">Calculate estimate</button></form></section>{result_html or "<aside class=\"estimate-placeholder\"><p class=\"eyebrow\">HOW IT WORKS</p><h2>Enter your project size.</h2><p>We will show a transparent local range and the material assumptions behind it.</p></aside>"}</div></main>'
        return self.layout("Project estimator | NammaBiz", body, first(query, "notice"))

    def business_page(self, ident, query):
        found = self.rows("SELECT * FROM businesses WHERE id=?", (ident,))
        if not found: return self.not_found()
        item = found[0]
        products = self.rows("SELECT * FROM products WHERE business_id=?", (ident,))
        product_rows = ''.join(f'<article class="product"><div><p class="eyebrow">{esc(product["category"])}</p><h3>{esc(product["name"])}</h3><p>{esc(product["description"])}</p></div><strong>Rs {product["price"]:,.0f}<small>{esc(product["unit"])}</small></strong></article>' for product in products) or '<p class="subtle">Product pricing is shared with qualified buyers on request.</p>'
        tags = (pill("Available now", "success") if item["available"] else pill("Temporarily busy")) + (pill("Wholesale", "blue") if item["wholesale"] else "") + (pill("Verified", "gold") if item["verified"] else "")
        body = self.nav("discover") + f'''<main class="shell page profile"><p class="crumb"><a href="/">Marketplace</a> / <a href="/search?{urlencode({"category": item["category"]})}">{esc(item["category"])}</a> / {esc(item["name"])}</p><section class="profile-head"><i>{esc(item["name"][0])}</i><div><div>{tags}</div><p class="eyebrow">{esc(item["category"])}</p><h1>{esc(item["name"])}</h1><p class="lede">{esc(item["description"])}</p><p class="facts">{esc(item["location"])} <span>/</span> {item["rating"]:.1f}/5 rating <span>/</span> For {esc(item["buyer_types"])}</p></div></section><div class="profile-grid"><section><div class="content"><p class="eyebrow">PRODUCTS AND SERVICES</p><h2>What this supplier can source.</h2><div class="product-list">{product_rows}</div></div><div class="content"><p class="eyebrow">SUPPLIER DETAILS</p><dl><div><dt>Products</dt><dd>{esc(item["products"])}</dd></div><div><dt>Services</dt><dd>{esc(item["services"])}</dd></div><div><dt>Contact</dt><dd>{esc(item["phone"])}</dd></div></dl></div></section><aside class="rfq"><p class="eyebrow">REQUEST QUOTATION</p><h2>Tell {esc(item["name"])} what you need.</h2><p>Share one clear requirement. The supplier will see it in their portal.</p><form method="post" action="/rfq"><input type="hidden" name="business_id" value="{item["id"]}"><label>Your name<input name="buyer_name" required placeholder="Name or company"></label><label>Work email<input name="buyer_email" type="email" required placeholder="you@company.com"></label><label>Requirement<textarea name="requirement" required placeholder="Material, quantity, specification and delivery location"></textarea></label><button class="button accent">Send RFQ</button></form></aside></div></main>'''
        return self.layout(f"{item['name']} | NammaBiz", body, first(query, "notice"))

    def dashboard(self, query):
        businesses = self.rows("SELECT * FROM businesses ORDER BY available DESC, rating DESC")
        rfqs = self.rows("SELECT rfqs.*, businesses.name AS business_name FROM rfqs JOIN businesses ON businesses.id=rfqs.business_id ORDER BY rfqs.created_at DESC LIMIT 8")
        stats = [("Suppliers", len(businesses)), ("Available", sum(row["available"] for row in businesses)), ("Wholesale", sum(row["wholesale"] for row in businesses)), ("Open RFQs", sum(row["status"] == "PENDING" for row in rfqs))]
        stat_cards = ''.join(f'<div class="stat"><span>{label}</span><strong>{value}</strong></div>' for label, value in stats)
        supplier_rows = ''.join(f'<tr><td><a href="/business/{row["id"]}">{esc(row["name"])}</a><small>{esc(row["subcategory"])}</small></td><td>{esc(row["category"])}</td><td>{esc(row["location"])}</td><td>{pill("Available" if row["available"] else "Busy", "success" if row["available"] else "muted")}</td><td><form method="post" action="/business/{row["id"]}/availability"><input type="hidden" name="value" value="{0 if row["available"] else 1}"><button class="table-button">{"Mark busy" if row["available"] else "Mark available"}</button></form></td></tr>' for row in businesses)
        rfq_rows = ''.join(f'<tr><td><strong>{esc(row["buyer_name"])}</strong><small>{esc(row["buyer_email"])}</small></td><td>{esc(row["business_name"])}</td><td class="requirement">{esc(row["requirement"])}</td><td>{pill(row["status"].title(), "blue" if row["status"] == "PENDING" else "success")}</td><td><form method="post" action="/rfq/{row["id"]}/status"><input type="hidden" name="status" value="RESPONDED"><button class="table-button">Mark responded</button></form></td></tr>' for row in rfqs) or '<tr><td colspan="5" class="subtle">No RFQs have arrived yet. They will appear here when buyers submit them.</td></tr>'
        choices = ''.join(f'<option>{esc(name)}</option>' for name, _ in CATEGORIES)
        body = self.nav("dashboard") + f'''<main class="shell page"><div class="dashboard-head"><div><p class="eyebrow">SUPPLIER PORTAL</p><h1>Run a sharper local network.</h1><p>Manage supplier visibility and see buyer requirements in one place.</p></div><a class="button accent" href="#add-supplier">Add supplier</a></div><div class="stat-grid">{stat_cards}</div><section class="dash-section"><div class="section-title"><div><p class="eyebrow">SUPPLIER DIRECTORY</p><h2>Network availability</h2></div><a class="text-link" href="/search">Open marketplace <span>&rarr;</span></a></div><div class="table-wrap"><table><thead><tr><th>Supplier</th><th>Category</th><th>Location</th><th>Status</th><th></th></tr></thead><tbody>{supplier_rows}</tbody></table></div></section><section class="dash-section"><div class="section-title"><div><p class="eyebrow">BUYER INBOX</p><h2>Latest RFQs</h2></div></div><div class="table-wrap"><table><thead><tr><th>Buyer</th><th>Supplier</th><th>Requirement</th><th>Status</th><th></th></tr></thead><tbody>{rfq_rows}</tbody></table></div></section><section class="add-supplier" id="add-supplier"><div><p class="eyebrow">GROW THE NETWORK</p><h2>Add a supplier</h2><p>Make a local business discoverable by buyers already searching here.</p></div><form method="post" action="/business"><label>Business name<input name="name" required></label><label>Category<select name="category">{choices}</select></label><label>Location<input name="location" required placeholder="Area, Madurai"></label><label>What do they supply?<textarea name="products" required placeholder="Products and services"></textarea></label><button class="button dark">Add supplier</button></form></section></main>'''
        return self.layout("Supplier portal | NammaBiz", body, first(query, "notice"))

    def redirect(self, path, message):
        return "302 Found", [("Location", f"{path}{'&' if '?' in path else '?'}{urlencode({'notice': message})}")], b""

    def post_rfq(self, form):
        try: business_id = int(first(form, "business_id"))
        except ValueError: business_id = 0
        name, email, requirement = (first(form, key).strip() for key in ("buyer_name", "buyer_email", "requirement"))
        if not all((business_id, name, email, requirement)): return self.redirect("/search", "Please complete the RFQ form.")
        if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email): return self.redirect(f"/business/{business_id}", "Enter a valid work email address.")
        if len(requirement) < 12: return self.redirect(f"/business/{business_id}", "Add a little more detail so the supplier can quote accurately.")
        self.write("INSERT INTO rfqs (business_id,buyer_name,buyer_email,requirement) VALUES (?,?,?,?)", (business_id, name, email, requirement))
        return self.redirect(f"/business/{business_id}", "Your RFQ is in the supplier inbox.")

    def post_business(self, form):
        name, category, location, products = (first(form, key).strip() for key in ("name", "category", "location", "products"))
        if not all((name, category, location, products)): return self.redirect("/dashboard", "Please complete the supplier details.")
        values = (name, category, "Local supplier", location, f"Local {category.lower()} supplier on NammaBiz.", "Professional buyers", products, "Direct enquiry", "Contact on request", 4.5, 1, 0, 0)
        self.write("INSERT INTO businesses (name,category,subcategory,location,description,buyer_types,products,services,phone,rating,available,wholesale,verified) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)", values)
        return self.redirect("/dashboard", f"{name} is now listed in the network.")

    def post_available(self, ident, form):
        self.write("UPDATE businesses SET available=? WHERE id=?", (1 if first(form, "value") == "1" else 0, ident))
        return self.redirect("/dashboard", "Supplier availability updated.")

    def post_rfq_status(self, ident, form):
        status = first(form, "status").upper()
        self.write("UPDATE rfqs SET status=? WHERE id=?", (status if status in {"PENDING", "RESPONDED", "CLOSED"} else "PENDING", ident))
        return self.redirect("/dashboard", "RFQ status updated.")

    def static(self, path):
        asset = (STATIC / path.removeprefix("/static/")).resolve()
        if STATIC.resolve() not in asset.parents or not asset.is_file(): return "404 Not Found", [("Content-Type", "text/plain")], b"Not found"
        mime_types = {
            ".css": "text/css; charset=utf-8",
            ".js": "application/javascript; charset=utf-8",
            ".json": "application/manifest+json; charset=utf-8",
            ".svg": "image/svg+xml",
        }
        mime = mime_types.get(asset.suffix, "application/octet-stream")
        return "200 OK", [("Content-Type", mime), ("Cache-Control", "public, max-age=3600")], asset.read_bytes()

    def service_worker(self):
        asset = STATIC / "sw.js"
        return "200 OK", [("Content-Type", "application/javascript; charset=utf-8"), ("Cache-Control", "no-cache")], asset.read_bytes()

    def api(self, path, method, body, form, query):
        try: payload = json.loads(body or b"{}") if body else {key: first(form, key) for key in form}
        except json.JSONDecodeError: payload = {}
        if path == "/api/businesses" and method == "GET": return self.json([dict(row) for row in self.rows("SELECT * FROM businesses ORDER BY rating DESC")])
        if path == "/api/rfqs" and method == "GET": return self.json([dict(row) for row in self.rows("SELECT * FROM rfqs ORDER BY created_at DESC")])
        if path == "/api/rfqs" and method == "POST":
            response = self.post_rfq({key: [str(value)] for key, value in payload.items()})
            return self.json({"created": response[0] == "302 Found"}, "201 Created")
        if re.fullmatch(r"/api/businesses/\d+/availability", path) and method == "POST":
            ident = int(path.split("/")[3]); value = payload.get("value", first(query, "value"))
            self.write("UPDATE businesses SET available=? WHERE id=?", (1 if str(value).lower() in {"1", "true"} else 0, ident))
            return self.json({"updated": True})
        return self.json({"error": "Not found"}, "404 Not Found")

    @staticmethod
    def json(data, status="200 OK"): return status, [("Content-Type", "application/json; charset=utf-8")], json.dumps(data, default=str).encode()

    def not_found(self):
        return self.layout("Not found | NammaBiz", self.nav() + '<main class="shell page"><div class="empty"><p class="eyebrow">404</p><h1>That page is not in the network.</h1><a class="button dark" href="/">Back to marketplace</a></div></main>')

    def __call__(self, environ, start_response):
        method, path = environ.get("REQUEST_METHOD", "GET").upper(), environ.get("PATH_INFO", "/")
        query = parse_qs(environ.get("QUERY_STRING", ""), keep_blank_values=True)
        length = int(environ.get("CONTENT_LENGTH") or 0)
        body = environ["wsgi.input"].read(length) if length else b""
        form = parse_qs(body.decode(), keep_blank_values=True) if "application/x-www-form-urlencoded" in environ.get("CONTENT_TYPE", "") else {}
        if path == "/sw.js" and method == "GET": response = self.service_worker()
        elif path.startswith("/static/") and method == "GET": response = self.static(path)
        elif path.startswith("/api/"): response = self.api(path, method, body, form, query)
        elif path == "/" and method == "GET": response = "200 OK", [("Content-Type", "text/html; charset=utf-8")], self.home(query)
        elif path == "/search" and method == "GET": response = "200 OK", [("Content-Type", "text/html; charset=utf-8")], self.search_page(query)
        elif path == "/categories" and method == "GET": response = "200 OK", [("Content-Type", "text/html; charset=utf-8")], self.categories(query)
        elif path == "/estimator" and method == "GET": response = "200 OK", [("Content-Type", "text/html; charset=utf-8")], self.estimator(query)
        elif path == "/dashboard" and method == "GET": response = "200 OK", [("Content-Type", "text/html; charset=utf-8")], self.dashboard(query)
        elif re.fullmatch(r"/business/\d+", path) and method == "GET": response = "200 OK", [("Content-Type", "text/html; charset=utf-8")], self.business_page(int(path.rsplit("/", 1)[1]), query)
        elif path == "/rfq" and method == "POST": response = self.post_rfq(form)
        elif path == "/business" and method == "POST": response = self.post_business(form)
        elif re.fullmatch(r"/business/\d+/availability", path) and method == "POST": response = self.post_available(int(path.split("/")[2]), form)
        elif re.fullmatch(r"/rfq/\d+/status", path) and method == "POST": response = self.post_rfq_status(int(path.split("/")[2]), form)
        else: response = "404 Not Found", [("Content-Type", "text/html; charset=utf-8")], self.not_found()
        status, headers, payload = response
        start_response(status, headers + [("Content-Length", str(len(payload)))])
        return [payload]


def create_app(db_path=DEFAULT_DB): return NammaBiz(db_path)


if __name__ == "__main__":
    from wsgiref.simple_server import make_server
    port = int(os.environ.get("PORT", sys.argv[1] if len(sys.argv) > 1 else 8000))
    host = os.environ.get("HOST", sys.argv[2] if len(sys.argv) > 2 else "127.0.0.1")
    display_host = "127.0.0.1" if host == "0.0.0.0" else host
    print(f"NammaBiz is running at http://{display_host}:{port}")
    make_server(host, port, create_app()).serve_forever()
