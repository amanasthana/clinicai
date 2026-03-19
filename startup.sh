#!/bin/bash
set -e

echo "--- Ensuring persistent media directory ---"
mkdir -p /home/media/letterheads

echo "--- Installing packages ---"
pip install -r /home/site/wwwroot/requirements.txt --quiet

echo "--- Running migrations ---"
python manage.py migrate --no-input

echo "--- Seeding reference data (skips if already loaded) ---"
python manage.py seed_medicine_catalog --skip-if-exists 2>/dev/null || python manage.py seed_medicine_catalog
python manage.py seed_medical_terms --skip-if-exists 2>/dev/null || python manage.py seed_medical_terms
python manage.py seed_drug_interactions --skip-if-exists 2>/dev/null || python manage.py seed_drug_interactions

echo "--- Starting gunicorn ---"
gunicorn --bind=0.0.0.0:8000 --timeout=120 --workers=2 clinicai.wsgi
