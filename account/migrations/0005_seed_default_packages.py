from decimal import Decimal

from django.db import migrations


def seed_default_packages(apps, schema_editor):
    Package = apps.get_model("account", "Package")

    defaults = {
        "bronze": {
            "price": Decimal("150.00"),
            "duration_days": 30,
            "max_students": 50,
            "max_teachers": 10,
            "features": {
                "attendance": True,
                "email_support": True,
                "basic_reporting": True,
            },
            "is_active": True,
        },
        "silver": {
            "price": Decimal("450.00"),
            "duration_days": 30,
            "max_students": 500,
            "max_teachers": 75,
            "features": {
                "attendance": True,
                "sms_notifications": True,
                "finance_dashboard": True,
                "priority_support": True,
            },
            "is_active": True,
        },
        "gold": {
            "price": Decimal("999.00"),
            "duration_days": 30,
            "max_students": 5000,
            "max_teachers": 500,
            "features": {
                "attendance": True,
                "multi_campus": True,
                "api_access": True,
                "dedicated_manager": True,
            },
            "is_active": True,
        },
    }

    for name, values in defaults.items():
        Package.objects.update_or_create(name=name, defaults=values)


def unseed_default_packages(apps, schema_editor):
    Package = apps.get_model("account", "Package")
    Package.objects.filter(name__in=["bronze", "silver", "gold"]).delete()


class Migration(migrations.Migration):
    dependencies = [
        ("account", "0004_schoolonboardingrequest"),
    ]

    operations = [
        migrations.RunPython(seed_default_packages, unseed_default_packages),
    ]
