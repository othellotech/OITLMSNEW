#!/usr/bin/env bash
# Exit on error
set -o errexit

# Install dependencies
pip install -r requirements.txt

# Convert static asset files
python manage.py collectstatic --no-input

# Apply any outstanding database migrations
python manage.py migrate

# Load initial data (superuser) - uncomment if you have fixtures
# python manage.py loaddata fixtures/initial_data.json