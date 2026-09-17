from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("builder", "0018_equipmentitem"),
    ]

    operations = [
        migrations.AlterField(
            model_name="equipmentitem",
            name="kind",
            field=models.CharField(choices=[("ally", "Ally"), ("emblem", "Emblem"), ("flask", "Flask"), ("banner", "Banner")], max_length=10),
        ),
    ]
