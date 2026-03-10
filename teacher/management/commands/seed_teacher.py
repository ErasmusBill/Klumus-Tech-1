from __future__ import annotations

from django.core.management import BaseCommand, call_command


class Command(BaseCommand):
    help = "Seed teacher-related data. Delegates to seed_account."

    def add_arguments(self, parser):
        parser.add_argument("--admin-username", type=str, default="")
        parser.add_argument("--school-name", type=str, default="")
        parser.add_argument("--seed", type=int, default=42)

    def handle(self, *args, **options):
        call_command(
            "seed_account",
            admin_username=options["admin_username"],
            school_name=options["school_name"],
            seed=options["seed"],
        )
        self.stdout.write(self.style.SUCCESS("Teacher seeding completed via seed_account."))
