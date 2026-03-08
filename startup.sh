#!/bin/bash
set -e

echo "--- Installing packages ---"
pip install -r /home/site/wwwroot/requirements.txt --quiet

echo "--- Running migrations ---"
python manage.py migrate --no-input

echo "--- Starting gunicorn ---"
gunicorn --bind=0.0.0.0:8000 --timeout=120 --workers=2 clinicai.wsgi
