from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("account", "0001_initial"),
    ]

    operations = [
        migrations.AlterField(
            model_name="customuser",
            name="phone_number",
            field=models.CharField(blank=True, max_length=20, null=True),
        ),
    ]
