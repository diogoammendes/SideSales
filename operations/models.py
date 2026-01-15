from decimal import Decimal

from django.conf import settings
from django.contrib.auth.models import AbstractUser
from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _


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


class TimeStampedModel(models.Model):
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


class Purchase(TimeStampedModel):
    title = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    quantity = models.DecimalField(max_digits=12, decimal_places=2)
    unit_cost = models.DecimalField(max_digits=12, decimal_places=2)
    purchased_on = models.DateField(default=timezone.now)
    signal_amount = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('0.00'))
    signal_paid_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
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
    def total_base(self) -> Decimal:
        return (self.quantity or Decimal('0')) * (self.unit_cost or Decimal('0'))

    @property
    def total_additional_costs(self) -> Decimal:
        prefetched = getattr(self, '_prefetched_objects_cache', {})
        if 'additional_costs' in prefetched:
            total = sum(cost.amount for cost in self.additional_costs.all())
        else:
            total = self.additional_costs.aggregate(total=models.Sum('amount'))['total']
        return total or Decimal('0')

    @property
    def total_cost(self) -> Decimal:
        return self.total_base + self.signal_amount + self.total_additional_costs

    @property
    def total_revenue(self) -> Decimal:
        prefetched = getattr(self, '_prefetched_objects_cache', {})
        if 'sales' in prefetched:
            total = sum(sale.total_price for sale in self.sales.all())
        else:
            total = self.sales.annotate(
                line_total=models.ExpressionWrapper(
                    models.F('quantity') * models.F('unit_price'),
                    output_field=models.DecimalField(max_digits=14, decimal_places=2),
                )
            ).aggregate(total=models.Sum('line_total'))['total']
        return total or Decimal('0')

    @property
    def total_profit(self) -> Decimal:
        return self.total_revenue - self.total_cost


class PurchaseContribution(TimeStampedModel):
    class ContributionType(models.TextChoices):
        ABSOLUTE = 'ABSOLUTE', 'Valor Fixo'
        PERCENTAGE = 'PERCENTAGE', 'Percentual'

    purchase = models.ForeignKey(Purchase, on_delete=models.CASCADE, related_name='contributions')
    payer = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='purchase_contributions')
    contribution_type = models.CharField(max_length=20, choices=ContributionType.choices)
    value = models.DecimalField(max_digits=12, decimal_places=2, help_text='Valor ou percentagem conforme o tipo')
    paid_on = models.DateField(default=timezone.now)
    notes = models.CharField(max_length=255, blank=True)

    class Meta:
        ordering = ['-paid_on', '-created_at']

    def __str__(self) -> str:
        return f"{self.payer} - {self.purchase}"

    @property
    def resolved_amount(self) -> Decimal:
        if self.contribution_type == self.ContributionType.ABSOLUTE:
            return self.value
        total_base = self.purchase.total_base
        if total_base == 0:
            return Decimal('0')
        return (total_base * self.value) / Decimal('100')


class AdditionalCost(TimeStampedModel):
    purchase = models.ForeignKey(Purchase, on_delete=models.CASCADE, related_name='additional_costs')
    label = models.CharField(max_length=255)
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    paid_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
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
    quantity = models.DecimalField(max_digits=12, decimal_places=2)
    unit_price = models.DecimalField(max_digits=12, decimal_places=2)
    sold_on = models.DateField(default=timezone.now)
    status = models.CharField(max_length=20, choices=SaleStatus.choices, default=SaleStatus.DRAFT)
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ['-sold_on', '-created_at']

    def __str__(self) -> str:
        return f"Venda #{self.pk} - {self.buyer_name}"

    @property
    def total_price(self) -> Decimal:
        return (self.quantity or Decimal('0')) * (self.unit_price or Decimal('0'))

    @property
    def total_payments(self) -> Decimal:
        prefetched = getattr(self, '_prefetched_objects_cache', {})
        if 'payments' in prefetched:
            total = sum(payment.amount for payment in self.payments.all())
        else:
            total = self.payments.aggregate(total=models.Sum('amount'))['total']
        return total or Decimal('0')

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
    receiver = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='sale_payments_received')
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    method = models.CharField(max_length=20, choices=PaymentMethod.choices)
    paid_on = models.DateField(default=timezone.now)
    notes = models.CharField(max_length=255, blank=True)

    class Meta:
        ordering = ['-paid_on', '-created_at']

    def __str__(self) -> str:
        return f"Pagamento {self.amount} - {self.sale}"
