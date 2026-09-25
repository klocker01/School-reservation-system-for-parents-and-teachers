from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('reservations', '0008_reservation_tipas'),
    ]

    operations = [
        migrations.AddField(
            model_name='break',
            name='pasalintas_laikas',
            field=models.BooleanField(default=False, verbose_name='Pašalintas laikas'),
        ),
    ]
