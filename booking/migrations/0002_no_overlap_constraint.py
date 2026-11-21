"""Spärr i databasen mot överlappande bokningar (bara PostgreSQL).

Applikationen kontrollerar redan överlapp under lås, men den här regeln gör det
omöjligt även vid buggar eller ändringar direkt i databasen. SQLite (utveckling)
hoppar över den.
"""

from django.db import migrations

CREATE = """
CREATE EXTENSION IF NOT EXISTS btree_gist;
ALTER TABLE booking_booking ADD CONSTRAINT booking_no_overlap
  EXCLUDE USING gist (resource_id WITH =, tstzrange(start, "end", '[)') WITH &&)
  WHERE (status IN ('active', 'pending_payment'));
"""
DROP = "ALTER TABLE booking_booking DROP CONSTRAINT IF EXISTS booking_no_overlap;"


def forwards(apps, schema_editor):
    if schema_editor.connection.vendor == "postgresql":
        schema_editor.execute(CREATE)


def backwards(apps, schema_editor):
    if schema_editor.connection.vendor == "postgresql":
        schema_editor.execute(DROP)


class Migration(migrations.Migration):
    dependencies = [("booking", "0001_initial")]
    operations = [migrations.RunPython(forwards, backwards)]
