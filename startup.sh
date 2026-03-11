#!/bin/bash
set -e

echo "--- Ensuring persistent media directory ---"
mkdir -p /home/media/letterheads

echo "--- Installing packages ---"
pip install -r /home/site/wwwroot/requirements.txt --quiet

echo "--- Running migrations ---"
python manage.py migrate --no-input

echo "--- Seeding medicine catalog (idempotent) ---"
python manage.py seed_medicine_catalog

echo "--- Seeding medical terms (idempotent) ---"
python manage.py seed_medical_terms

echo "--- Starting gunicorn ---"
gunicorn --bind=0.0.0.0:8000 --timeout=120 --workers=2 clinicai.wsgi
