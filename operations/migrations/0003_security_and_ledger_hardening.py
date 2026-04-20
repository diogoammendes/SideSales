from decimal import Decimal

import django.core.validators
import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


def backfill_resolved_amount(apps, schema_editor):
    """Populate resolved_amount_snapshot for existing contributions.

    For ABSOLUTE contributions this is simply `value`. For PERCENTAGE
    contributions we freeze the current value derived from the parent
    purchase.total_amount_eur so that any later edits to the purchase do
    not retroactively alter historical contributions.
    """
    PurchaseContribution = apps.get_model('operations', 'PurchaseContribution')
    for contribution in PurchaseContribution.objects.select_related('purchase').all():
        if contribution.resolved_amount_snapshot is not None:
            continue
        if contribution.contribution_type == 'ABSOLUTE':
            contribution.resolved_amount_snapshot = contribution.value or Decimal('0')
        else:
            base = contribution.purchase.total_amount_eur or Decimal('0')
            value = contribution.value or Decimal('0')
            if base == 0:
                contribution.resolved_amount_snapshot = Decimal('0')
            else:
                contribution.resolved_amount_snapshot = (base * value) / Decimal('100')
        contribution.save(update_fields=['resolved_amount_snapshot'])


def noop_reverse(apps, schema_editor):
    # Snapshot values are data-only; reversing the migration simply drops
    # the column via the schema migration, no data to restore.
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('operations', '0002_rename_signal_amount_purchase_total_amount_eur_and_more'),
    ]

    operations = [
        # --- New snapshot field on PurchaseContribution ----------------------
        migrations.AddField(
            model_name='purchasecontribution',
            name='resolved_amount_snapshot',
            field=models.DecimalField(
                blank=True,
                decimal_places=2,
                help_text='Valor em EUR congelado no momento do registo.',
                max_digits=12,
                null=True,
                validators=[django.core.validators.MinValueValidator(Decimal('0'))],
            ),
        ),
        migrations.RunPython(backfill_resolved_amount, noop_reverse),

        # --- Tighten on_delete on FK-to-User references ---------------------
        # PROTECT is the safe default for financial ownership: refuse to
        # delete a user that still has associated payments/costs/signal.
        migrations.AlterField(
            model_name='additionalcost',
            name='paid_by',
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name='additional_costs_paid',
                to=settings.AUTH_USER_MODEL,
            ),
        ),
        migrations.AlterField(
            model_name='purchase',
            name='signal_paid_by',
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name='signal_payments',
                to=settings.AUTH_USER_MODEL,
            ),
        ),

        # --- Numeric validators --------------------------------------------
        migrations.AlterField(
            model_name='additionalcost',
            name='amount',
            field=models.DecimalField(
                decimal_places=2,
                max_digits=12,
                validators=[django.core.validators.MinValueValidator(Decimal('0'))],
            ),
        ),
        migrations.AlterField(
            model_name='purchase',
            name='quantity',
            field=models.DecimalField(
                decimal_places=2,
                max_digits=12,
                validators=[django.core.validators.MinValueValidator(Decimal('0.01'))],
            ),
        ),
        migrations.AlterField(
            model_name='purchase',
            name='signal_amount_eur',
            field=models.DecimalField(
                decimal_places=2,
                default=Decimal('0.00'),
                max_digits=12,
                validators=[django.core.validators.MinValueValidator(Decimal('0'))],
            ),
        ),
        migrations.AlterField(
            model_name='purchase',
            name='signal_amount_original',
            field=models.DecimalField(
                blank=True,
                decimal_places=2,
                max_digits=12,
                null=True,
                validators=[django.core.validators.MinValueValidator(Decimal('0'))],
            ),
        ),
        migrations.AlterField(
            model_name='purchase',
            name='total_amount_eur',
            field=models.DecimalField(
                decimal_places=2,
                default=Decimal('0.00'),
                max_digits=12,
                validators=[django.core.validators.MinValueValidator(Decimal('0'))],
            ),
        ),
        migrations.AlterField(
            model_name='purchase',
            name='total_amount_original',
            field=models.DecimalField(
                blank=True,
                decimal_places=2,
                max_digits=12,
                null=True,
                validators=[django.core.validators.MinValueValidator(Decimal('0'))],
            ),
        ),
        migrations.AlterField(
            model_name='purchasecontribution',
            name='value',
            field=models.DecimalField(
                decimal_places=2,
                help_text='Valor ou percentagem conforme o tipo',
                max_digits=12,
                validators=[django.core.validators.MinValueValidator(Decimal('0'))],
            ),
        ),
        migrations.AlterField(
            model_name='sale',
            name='quantity',
            field=models.DecimalField(
                decimal_places=2,
                max_digits=12,
                validators=[django.core.validators.MinValueValidator(Decimal('0.01'))],
            ),
        ),
        migrations.AlterField(
            model_name='sale',
            name='unit_price',
            field=models.DecimalField(
                decimal_places=2,
                max_digits=12,
                validators=[django.core.validators.MinValueValidator(Decimal('0'))],
            ),
        ),
        migrations.AlterField(
            model_name='salepayment',
            name='amount',
            field=models.DecimalField(
                decimal_places=2,
                max_digits=12,
                validators=[django.core.validators.MinValueValidator(Decimal('0.01'))],
            ),
        ),
    ]
