import argparse
import sqlite3
from pathlib import Path
from urllib.parse import quote

from sqlalchemy import text

from app import DEFAULT_DB, create_app
from extensions import db
from models import LegacyBusiness, LegacyProduct, LegacyRFQ


LEGACY_TABLES = {
    "businesses": LegacyBusiness,
    "products": LegacyProduct,
    "rfqs": LegacyRFQ,
}


def import_legacy_records(source_path):
    source_path = Path(source_path).resolve()
    if not source_path.is_file():
        raise FileNotFoundError(source_path)
    source_uri = f"file:{quote(source_path.as_posix(), safe='/:')}?mode=ro"
    source = sqlite3.connect(source_uri, uri=True)
    source.row_factory = sqlite3.Row
    try:
        present = {row[0] for row in source.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        missing = set(LEGACY_TABLES) - present
        if missing:
            raise ValueError(f"Source database is missing tables: {', '.join(sorted(missing))}")
        rows_by_table = {name: [dict(row) for row in source.execute(f"SELECT * FROM {name}")] for name in LEGACY_TABLES}
    finally:
        source.close()

    app = create_app()
    with app.app_context():
        counts = {name: db.session.query(model).count() for name, model in LEGACY_TABLES.items()}
        if any(counts.values()):
            raise ValueError("Destination supplier tables must be empty; import was not started.")
        try:
            for name, model in LEGACY_TABLES.items():
                if rows_by_table[name]:
                    db.session.bulk_insert_mappings(model, rows_by_table[name])
            if db.engine.dialect.name == "postgresql":
                for name in LEGACY_TABLES:
                    db.session.execute(text(
                        f"SELECT setval(pg_get_serial_sequence('{name}', 'id'), "
                        f"COALESCE((SELECT MAX(id) FROM {name}), 1), true)"
                    ))
            db.session.commit()
        except Exception:
            db.session.rollback()
            raise
    return {name: len(rows) for name, rows in rows_by_table.items()}


def main():
    parser = argparse.ArgumentParser(description="Copy legacy supplier data to an empty configured NammaBiz database.")
    parser.add_argument("source", nargs="?", default=str(DEFAULT_DB), help="SQLite file to import")
    args = parser.parse_args()
    counts = import_legacy_records(args.source)
    print("Imported records:", ", ".join(f"{table}={count}" for table, count in counts.items()))


if __name__ == "__main__":
    main()
