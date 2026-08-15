# Generated manually on 2026-08-15

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("operations", "0004_add_total_price_override_to_sale"),
    ]

    operations = [
        migrations.CreateModel(
            name="SystemSettings",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                (
                    "distribution_mode",
                    models.CharField(
                        choices=[
                            ("PROPORTIONAL", "Proporcional ao investimento"),
                            ("EQUAL", "Equitativa (50/50)"),
                        ],
                        default="PROPORTIONAL",
                        help_text="Escolha como os lucros serão distribuídos entre os utilizadores",
                        max_length=20,
                        verbose_name="Modo de distribuição de lucros",
                    ),
                ),
            ],
            options={
                "verbose_name": "Configurações do sistema",
                "verbose_name_plural": "Configurações do sistema",
            },
        ),
    ]
