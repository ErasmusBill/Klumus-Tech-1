from django.db import migrations, models
import account.models

def dedupe_reset_tokens(apps, schema_editor):
    RequestPasswordReset = apps.get_model("account", "RequestPasswordReset")
    seen = set()
    for row in RequestPasswordReset.objects.all().only("id", "token"):
        token = row.token
        if token in seen or not token:
            row.token = account.models.generate_generalized_integer()
            while row.token in seen:
                row.token = account.models.generate_generalized_integer()
            row.save(update_fields=["token"])
        seen.add(row.token)


class Migration(migrations.Migration):

    dependencies = [
        ("account", "0002_alter_customuser_phone_number"),
    ]

    operations = [
        migrations.RunPython(dedupe_reset_tokens, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="requestpasswordreset",
            name="token",
            field=models.CharField(db_index=True, default=account.models.generate_generalized_integer, max_length=50, unique=True),
        ),
    ]
