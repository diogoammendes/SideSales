from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator, MaxValueValidator
from django.contrib.auth.models import AbstractUser
from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _


ZERO = Decimal('0')
NON_NEGATIVE = [MinValueValidator(ZERO)]
POSITIVE = [MinValueValidator(Decimal('0.01'))]
PERCENTAGE_RANGE = [MinValueValidator(ZERO), MaxValueValidator(Decimal('100'))]


class User(AbstractUser):
    class Roles(models.TextChoices):
        ADMIN = 'ADMIN', _('Administrador')
        MANAGER = 'MANAGER', _('Gestor')
        VIEWER = 'VIEWER', _('Consulta')

    role = models.CharField(max_length=20, choices=Roles.choices, default=Roles.MANAGER)

    def __str__(self) -> str:
        return self.get_full_name() or self.username

    @property
    def display_role(self) -> str:
        return self.get_role_display()

    @property
    def has_elevated_privileges(self) -> bool:
        """True if this account should be considered privileged for admin
        operations (superuser or ADMIN role)."""
        return bool(self.is_superuser or self.role == self.Roles.ADMIN)


class TimeStampedModel(models.Model):
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


class Purchase(TimeStampedModel):
    title = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    quantity = models.DecimalField(max_digits=12, decimal_places=2, validators=POSITIVE)
    purchased_on = models.DateField(default=timezone.now)
    total_amount_original = models.DecimalField(
        max_digits=12, decimal_places=2, null=True, blank=True, validators=NON_NEGATIVE,
    )
    total_currency = models.CharField(max_length=10, blank=True)
    total_amount_eur = models.DecimalField(
        max_digits=12, decimal_places=2, default=Decimal('0.00'), validators=NON_NEGATIVE,
    )
    signal_amount_original = models.DecimalField(
        max_digits=12, decimal_places=2, null=True, blank=True, validators=NON_NEGATIVE,
    )
    signal_currency = models.CharField(max_length=10, blank=True)
    signal_amount_eur = models.DecimalField(
        max_digits=12, decimal_places=2, default=Decimal('0.00'), validators=NON_NEGATIVE,
    )
    signal_paid_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name='signal_payments',
    )
    signal_paid_on = models.DateField(null=True, blank=True)

    class Meta:
        ordering = ['-purchased_on', '-created_at']

    def __str__(self) -> str:
        return self.title

    @property
    def unit_cost(self) -> Decimal:
        if not self.quantity:
            return ZERO
        return (self.total_amount_eur or ZERO) / self.quantity

    @property
    def total_base(self) -> Decimal:
        return self.total_amount_eur or ZERO

    @property
    def total_additional_costs(self) -> Decimal:
        prefetched = getattr(self, '_prefetched_objects_cache', {})
        if 'additional_costs' in prefetched:
            total = sum((cost.amount for cost in self.additional_costs.all()), ZERO)
        else:
            total = self.additional_costs.aggregate(total=models.Sum('amount'))['total']
        return total or ZERO

    @property
    def total_cost(self) -> Decimal:
        return self.total_base + (self.signal_amount_eur or ZERO) + self.total_additional_costs

    @property
    def total_revenue(self) -> Decimal:
        prefetched = getattr(self, '_prefetched_objects_cache', {})
        if 'sales' in prefetched:
            total = sum((sale.total_price for sale in self.sales.all()), ZERO)
        else:
            total = self.sales.annotate(
                line_total=models.ExpressionWrapper(
                    models.F('quantity') * models.F('unit_price'),
                    output_field=models.DecimalField(max_digits=14, decimal_places=2),
                )
            ).aggregate(total=models.Sum('line_total'))['total']
        return total or ZERO

    @property
    def total_profit(self) -> Decimal:
        return self.total_revenue - self.total_cost

    @property
    def quantity_sold(self) -> Decimal:
        prefetched = getattr(self, '_prefetched_objects_cache', {})
        if 'sales' in prefetched:
            return sum((sale.quantity or ZERO for sale in self.sales.all()), ZERO)
        return self.sales.aggregate(total=models.Sum('quantity'))['total'] or ZERO

    @property
    def quantity_remaining(self) -> Decimal:
        return (self.quantity or ZERO) - self.quantity_sold


class PurchaseContribution(TimeStampedModel):
    class ContributionType(models.TextChoices):
        ABSOLUTE = 'ABSOLUTE', 'Valor Fixo'
        PERCENTAGE = 'PERCENTAGE', 'Percentual'

    purchase = models.ForeignKey(Purchase, on_delete=models.CASCADE, related_name='contributions')
    payer = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name='purchase_contributions',
    )
    contribution_type = models.CharField(max_length=20, choices=ContributionType.choices)
    value = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        help_text='Valor ou percentagem conforme o tipo',
        validators=NON_NEGATIVE,
    )
    # Snapshot of resolved EUR amount at the time the contribution was saved.
    # This prevents retroactive changes when the parent purchase's
    # total_amount_eur is edited.
    resolved_amount_snapshot = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        null=True,
        blank=True,
        validators=NON_NEGATIVE,
        help_text='Valor em EUR congelado no momento do registo.',
    )
    paid_on = models.DateField(default=timezone.now)
    notes = models.CharField(max_length=255, blank=True)

    class Meta:
        ordering = ['-paid_on', '-created_at']

    def __str__(self) -> str:
        return f"{self.payer} - {self.purchase}"

    def clean(self) -> None:
        super().clean()
        if self.contribution_type == self.ContributionType.PERCENTAGE:
            if self.value is None or self.value < ZERO or self.value > Decimal('100'):
                raise ValidationError({'value': _('Percentagem tem de estar entre 0 e 100.')})
        elif self.value is not None and self.value < ZERO:
            raise ValidationError({'value': _('Valor não pode ser negativo.')})

    def _compute_resolved_amount(self) -> Decimal:
        if self.value is None:
            return ZERO
        if self.contribution_type == self.ContributionType.ABSOLUTE:
            return self.value
        total_base = self.purchase.total_base if self.purchase_id else ZERO
        if total_base == 0:
            return ZERO
        return (total_base * self.value) / Decimal('100')

    def save(self, *args, **kwargs) -> None:
        # Freeze the EUR amount on first save so later edits of the parent
        # purchase do not retroactively rewrite historical contributions.
        if self.resolved_amount_snapshot is None:
            self.resolved_amount_snapshot = self._compute_resolved_amount()
        super().save(*args, **kwargs)

    @property
    def resolved_amount(self) -> Decimal:
        if self.resolved_amount_snapshot is not None:
            return self.resolved_amount_snapshot
        return self._compute_resolved_amount()


class AdditionalCost(TimeStampedModel):
    purchase = models.ForeignKey(Purchase, on_delete=models.CASCADE, related_name='additional_costs')
    label = models.CharField(max_length=255)
    amount = models.DecimalField(max_digits=12, decimal_places=2, validators=NON_NEGATIVE)
    paid_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name='additional_costs_paid',
    )
    incurred_on = models.DateField(default=timezone.now)

    class Meta:
        ordering = ['-incurred_on', '-created_at']

    def __str__(self) -> str:
        return f"{self.label} ({self.purchase})"


class Sale(TimeStampedModel):
    class SaleStatus(models.TextChoices):
        DRAFT = 'DRAFT', 'Rascunho'
        CONFIRMED = 'CONFIRMED', 'Confirmada'
        SETTLED = 'SETTLED', 'Liquidada'

    purchase = models.ForeignKey(Purchase, on_delete=models.CASCADE, related_name='sales')
    buyer_name = models.CharField(max_length=255)
    buyer_description = models.TextField(blank=True)
    quantity = models.DecimalField(max_digits=12, decimal_places=2, validators=POSITIVE)
    unit_price = models.DecimalField(max_digits=12, decimal_places=2, validators=NON_NEGATIVE)
    total_price_override = models.DecimalField(
        max_digits=12, decimal_places=2, null=True, blank=True
    )
    sold_on = models.DateField(default=timezone.now)
    status = models.CharField(max_length=20, choices=SaleStatus.choices, default=SaleStatus.DRAFT)
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ['-sold_on', '-created_at']

    def __str__(self) -> str:
        return f"Venda #{self.pk} - {self.buyer_name}"

    def clean(self) -> None:
        super().clean()
        # Prevent overselling: sum of committed quantities must not exceed the
        # purchased quantity. Only non-draft sales consume stock.
        if self.status == self.SaleStatus.DRAFT:
            return
        if not self.purchase_id or self.quantity is None:
            return
        already_sold = (
            Sale.objects.filter(purchase_id=self.purchase_id)
            .exclude(pk=self.pk)
            .exclude(status=self.SaleStatus.DRAFT)
            .aggregate(total=models.Sum('quantity'))['total']
            or ZERO
        )
        purchase_qty = self.purchase.quantity or ZERO
        if already_sold + self.quantity > purchase_qty:
            remaining = purchase_qty - already_sold
            raise ValidationError({
                'quantity': _(
                    'Quantidade excede o stock disponível. Restante: %(remaining)s'
                ) % {'remaining': remaining},
            })

    @property
    def total_price(self) -> Decimal:
        if self.total_price_override is not None:
            return self.total_price_override
        return (self.quantity or ZERO) * (self.unit_price or ZERO)

    @property
    def total_payments(self) -> Decimal:
        prefetched = getattr(self, '_prefetched_objects_cache', {})
        if 'payments' in prefetched:
            total = sum((payment.amount for payment in self.payments.all()), ZERO)
        else:
            total = self.payments.aggregate(total=models.Sum('amount'))['total']
        return total or ZERO

    @property
    def outstanding_amount(self) -> Decimal:
        return self.total_price - self.total_payments


class SalePayment(TimeStampedModel):
    class PaymentMethod(models.TextChoices):
        PIX = 'PIX', 'PIX'
        TRANSFER = 'TRANSFER', 'Transferência'
        CASH = 'CASH', 'Dinheiro'
        CARD = 'CARD', 'Cartão'
        OTHER = 'OTHER', 'Outro'

    sale = models.ForeignKey(Sale, on_delete=models.CASCADE, related_name='payments')
    receiver = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name='sale_payments_received',
    )
    amount = models.DecimalField(max_digits=12, decimal_places=2, validators=POSITIVE)
    method = models.CharField(max_length=20, choices=PaymentMethod.choices)
    paid_on = models.DateField(default=timezone.now)
    notes = models.CharField(max_length=255, blank=True)

    class Meta:
        ordering = ['-paid_on', '-created_at']

    def __str__(self) -> str:
        return f"Pagamento {self.amount} - {self.sale}"


class SystemSettings(models.Model):
    class DistributionMode(models.TextChoices):
        PROPORTIONAL = 'PROPORTIONAL', _('Proporcional ao investimento')
        EQUAL = 'EQUAL', _('Lucro igual para todos (50/50)')

    distribution_mode = models.CharField(
        max_length=20,
        choices=DistributionMode.choices,
        default=DistributionMode.PROPORTIONAL,
        verbose_name=_('Modo de distribuição de lucros'),
        help_text=_('Como distribuir o lucro total: proporcional ao investimento ou em partes iguais'),
    )

    class Meta:
        verbose_name = _('Configurações do sistema')
        verbose_name_plural = _('Configurações do sistema')

    def __str__(self) -> str:
        return 'Configurações do sistema'

    @classmethod
    def get_settings(cls) -> 'SystemSettings':
        """Get or create the singleton settings instance."""
        obj, created = cls.objects.get_or_create(pk=1)
        return obj
