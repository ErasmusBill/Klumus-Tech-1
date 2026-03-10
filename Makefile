# Makefile

# Variables
DC = docker compose --profile dev
APP = $(DC) run --rm web

.PHONY: build up down logs shell migrate makemigrations test install restart format clean superuser fullseed seed

# --- Docker Control ---
build:
	$(DC) build

up:
	$(DC) up

down:
	$(DC) down

logs:
	$(DC) logs -f

restart:
	$(DC) restart web

# --- Django Commands ---
migrate:
	$(APP) python manage.py migrate

makemigrations:
	$(APP) python manage.py makemigrations

superuser:
	$(APP) python manage.py createsuperuser

shell:
	$(APP) python manage.py shell

# --- Code Quality ---
format:
	$(APP) black .

# --- Package Management ---
# Usage: make install package=stripe
install:
	$(APP) poetry add $(package)
	$(DC) build

# --- Testing ---
test:
	$(APP) pytest

# --- Maintenance ---
clean:
	find . -type d -name "__pycache__" -exec rm -rf {} +

## --- Seeding ---
#fullseed:
#	echo "Making migrations..."
#	$(APP) python manage.py makemigrations
#	echo "Migrating database..."
#	$(APP) python manage.py migrate
#	echo "Seeding data..."
#	$(APP) python manage.py setup_roles
#	$(APP) python manage.py seed_vehicles
#	$(APP) python manage.py seed_ghana_locations
#	$(APP) python manage.py seed_rentals_config
#	$(APP) python manage.py seed_rental_products
#	$(APP) python manage.py seed_rental_tags
#	$(APP) python manage.py seed_compliance
#	$(APP) python manage.py seed_support
#	echo "Seeding complete!"

# --- Custom Seeding Command ---
seed:
	$(APP) python manage.py $(filter-out seed,$(MAKECMDGOALS))
%:
	@:
