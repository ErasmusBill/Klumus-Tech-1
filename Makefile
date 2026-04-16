DC = docker compose
RUN_APP = $(DC) run --rm -e RUN_MIGRATIONS=0 -e COLLECTSTATIC=0 app

.PHONY: build up up-with-docker-nginx down restart logs ps app-logs worker-logs nginx-logs shell dbshell migrate makemigrations createsuperuser collectstatic check check-mnotify test clean

build:
	$(DC) build

up:
	$(DC) up -d

up-with-docker-nginx:
	$(DC) --profile docker-nginx up -d

down:
	$(DC) down

restart:
	$(DC) restart app worker

logs:
	$(DC) logs -f

ps:
	$(DC) ps

app-logs:
	$(DC) logs -f app

worker-logs:
	$(DC) logs -f worker

nginx-logs:
	$(DC) --profile docker-nginx logs -f nginx

shell:
	$(RUN_APP) python manage.py shell

dbshell:
	$(RUN_APP) python manage.py dbshell

migrate:
	$(RUN_APP) python manage.py migrate --noinput

makemigrations:
	$(RUN_APP) python manage.py makemigrations

createsuperuser:
	$(RUN_APP) python manage.py createsuperuser

collectstatic:
	$(RUN_APP) python manage.py collectstatic --noinput

check:
	$(RUN_APP) python manage.py check

check-mnotify:
	$(RUN_APP) python manage.py check_mnotify

test:
	$(RUN_APP) python manage.py test

clean:
	$(DC) down -v
