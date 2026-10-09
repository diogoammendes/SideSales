# Generated manually on 2026-10-09

import django.db.models.deletion
import django.utils.timezone
from decimal import Decimal
from django.conf import settings
from django.core.validators import MinValueValidator
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("operations", "0005_add_system_settings"),
    ]

    operations = [
        migrations.CreateModel(
            name="SettlementTransfer",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "amount",
                    models.DecimalField(
                        decimal_places=2,
                        max_digits=12,
                        validators=[MinValueValidator(Decimal("0.01"))],
                    ),
                ),
                ("settled_on", models.DateField(default=django.utils.timezone.now)),
                ("notes", models.CharField(blank=True, max_length=255)),
                (
                    "from_user",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="settlement_transfers_sent",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "recorded_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="settlement_transfers_recorded",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "to_user",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="settlement_transfers_received",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "verbose_name": "Acerto entre utilizadores",
                "verbose_name_plural": "Acertos entre utilizadores",
                "ordering": ["-settled_on", "-created_at"],
            },
        ),
    ]
