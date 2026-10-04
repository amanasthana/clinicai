#!/bin/bash
set -e

echo "--- Ensuring persistent media directory ---"
mkdir -p /home/media/letterheads

echo "--- Running migrations ---"
python manage.py migrate --no-input

echo "--- Seeding reference data (skips if already loaded) ---"
python manage.py seed_medicine_catalog
python manage.py seed_medical_terms
python manage.py seed_drug_interactions
python manage.py seed_demo_doctor
python manage.py activate_pending_registrations || echo "WARN: activate_pending_registrations failed — continuing startup"

echo "--- Starting gunicorn ---"
gunicorn --bind=0.0.0.0:8000 --timeout=120 --workers=2 clinicai.wsgi
