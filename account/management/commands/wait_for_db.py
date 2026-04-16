from time import sleep

from django.core.management.base import BaseCommand
from django.db import connections
from django.db.utils import OperationalError


class Command(BaseCommand):
    help = "Block until the default database is available."

    def handle(self, *args, **options):
        self.stdout.write("Waiting for database...")
        while True:
            try:
                connection = connections["default"]
                connection.cursor()
            except OperationalError:
                self.stdout.write("Database unavailable, retrying in 1 second.")
                sleep(1)
                continue

            self.stdout.write(self.style.SUCCESS("Database is available."))
            break
