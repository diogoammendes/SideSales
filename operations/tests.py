from decimal import Decimal

from django.core.exceptions import ValidationError
from django.test import TestCase
from django.urls import reverse

from .models import (
    AdditionalCost,
    Purchase,
    PurchaseContribution,
    Sale,
    SalePayment,
    User,
)
from .views import _compute_ledger, _compute_sales_buckets


class BaseFinanceTest(TestCase):
    def setUp(self):
        self.admin = User.objects.create_user(
            username='admin', password='pw', role=User.Roles.ADMIN, is_superuser=False,
        )
        self.manager = User.objects.create_user(
            username='manager', password='pw', role=User.Roles.MANAGER,
        )
        self.viewer = User.objects.create_user(
            username='viewer', password='pw', role=User.Roles.VIEWER,
        )
        self.superuser = User.objects.create_superuser(
            username='root', password='pw', email='root@example.com',
        )


class LedgerReconciliationTests(BaseFinanceTest):
    def _make_purchase(self) -> Purchase:
        purchase = Purchase.objects.create(
            title='P1',
            quantity=Decimal('10'),
            total_amount_eur=Decimal('1000'),
            signal_amount_eur=Decimal('100'),
            signal_paid_by=self.admin,
        )
        PurchaseContribution.objects.create(
            purchase=purchase,
            payer=self.manager,
            contribution_type=PurchaseContribution.ContributionType.ABSOLUTE,
            value=Decimal('600'),
        )
        PurchaseContribution.objects.create(
            purchase=purchase,
            payer=self.viewer,
            contribution_type=PurchaseContribution.ContributionType.ABSOLUTE,
            value=Decimal('400'),
        )
        AdditionalCost.objects.create(
            purchase=purchase, label='Transporte', amount=Decimal('50'), paid_by=self.manager,
        )
        return purchase

    def test_total_invested_equals_sum_of_ledger_rows(self):
        """The dashboard total must exactly equal sum(row.invested)."""
        self._make_purchase()
        purchases = list(Purchase.objects.prefetch_related(
            'additional_costs__paid_by', 'contributions__payer', 'sales',
        ))
        rows, total = _compute_ledger(purchases)
        self.assertEqual(total, sum(r['invested'] for r in rows))

    def test_inactive_users_still_appear_in_ledger(self):
        """Deactivating a user must not delete their financial history."""
        self._make_purchase()
        self.manager.is_active = False
        self.manager.save()

        purchases = list(Purchase.objects.prefetch_related(
            'additional_costs__paid_by', 'contributions__payer', 'sales',
        ))
        rows, total = _compute_ledger(purchases)
        users_in_ledger = {row['user'].pk for row in rows}
        self.assertIn(self.manager.pk, users_in_ledger)
        # Totals still reconcile even with an inactive user.
        self.assertEqual(total, sum(r['invested'] for r in rows))

    def test_payments_to_inactive_receiver_still_counted(self):
        purchase = self._make_purchase()
        sale = Sale.objects.create(
            purchase=purchase,
            buyer_name='B',
            quantity=Decimal('1'),
            unit_price=Decimal('150'),
            status=Sale.SaleStatus.CONFIRMED,
        )
        SalePayment.objects.create(
            sale=sale,
            receiver=self.manager,
            amount=Decimal('150'),
            method=SalePayment.PaymentMethod.CASH,
        )
        self.manager.is_active = False
        self.manager.save()

        purchases = list(Purchase.objects.prefetch_related(
            'additional_costs__paid_by', 'contributions__payer', 'sales',
        ))
        rows, _ = _compute_ledger(purchases)
        manager_row = next(r for r in rows if r['user'].pk == self.manager.pk)
        self.assertEqual(manager_row['received_actual'], Decimal('150'))


class ContributionSnapshotTests(BaseFinanceTest):
    def test_percentage_contribution_is_frozen_at_save(self):
        purchase = Purchase.objects.create(
            title='P', quantity=Decimal('1'), total_amount_eur=Decimal('100'),
        )
        contribution = PurchaseContribution.objects.create(
            purchase=purchase,
            payer=self.manager,
            contribution_type=PurchaseContribution.ContributionType.PERCENTAGE,
            value=Decimal('50'),
        )
        self.assertEqual(contribution.resolved_amount, Decimal('50'))

        # Changing the purchase later must not retroactively change it.
        purchase.total_amount_eur = Decimal('500')
        purchase.save()
        contribution.refresh_from_db()
        self.assertEqual(contribution.resolved_amount, Decimal('50'))


class SaleValidationTests(BaseFinanceTest):
    def test_overselling_non_draft_sale_is_rejected(self):
        purchase = Purchase.objects.create(
            title='P', quantity=Decimal('5'), total_amount_eur=Decimal('100'),
        )
        Sale.objects.create(
            purchase=purchase,
            buyer_name='A',
            quantity=Decimal('4'),
            unit_price=Decimal('10'),
            status=Sale.SaleStatus.CONFIRMED,
        )
        extra = Sale(
            purchase=purchase,
            buyer_name='B',
            quantity=Decimal('2'),
            unit_price=Decimal('10'),
            status=Sale.SaleStatus.CONFIRMED,
        )
        with self.assertRaises(ValidationError):
            extra.full_clean()

    def test_draft_sales_do_not_consume_stock(self):
        purchase = Purchase.objects.create(
            title='P', quantity=Decimal('1'), total_amount_eur=Decimal('100'),
        )
        Sale.objects.create(
            purchase=purchase,
            buyer_name='A',
            quantity=Decimal('1'),
            unit_price=Decimal('10'),
            status=Sale.SaleStatus.DRAFT,
        )
        extra = Sale(
            purchase=purchase,
            buyer_name='B',
            quantity=Decimal('1'),
            unit_price=Decimal('10'),
            status=Sale.SaleStatus.CONFIRMED,
        )
        extra.full_clean()  # must not raise


class PrivilegeEscalationTests(BaseFinanceTest):
    def test_admin_role_cannot_reset_superuser_password(self):
        self.client.login(username='admin', password='pw')
        url = reverse(
            'operations:user_password', kwargs={'pk': self.superuser.pk}
        )
        response = self.client.post(url, {
            'new_password1': 'Sup3rStr0ngPass!',
            'new_password2': 'Sup3rStr0ngPass!',
        })
        self.assertEqual(response.status_code, 403)
        self.superuser.refresh_from_db()
        self.assertTrue(self.superuser.check_password('pw'))

    def test_admin_cannot_self_demote(self):
        self.client.login(username='admin', password='pw')
        url = reverse('operations:user_update', kwargs={'pk': self.admin.pk})
        response = self.client.post(url, {
            'email': 'admin@example.com',
            'first_name': '',
            'last_name': '',
            'role': User.Roles.VIEWER,
            'is_active': 'on',
        })
        # Form re-renders with an error instead of saving.
        self.admin.refresh_from_db()
        self.assertEqual(self.admin.role, User.Roles.ADMIN)

    def test_admin_cannot_self_deactivate(self):
        self.client.login(username='admin', password='pw')
        url = reverse('operations:user_update', kwargs={'pk': self.admin.pk})
        self.client.post(url, {
            'email': 'admin@example.com',
            'first_name': '',
            'last_name': '',
            'role': User.Roles.ADMIN,
            # is_active intentionally missing -> False
        })
        self.admin.refresh_from_db()
        self.assertTrue(self.admin.is_active)

    def test_viewer_cannot_access_user_list(self):
        self.client.login(username='viewer', password='pw')
        response = self.client.get(reverse('operations:user_list'))
        self.assertEqual(response.status_code, 403)


class SaleDeleteTests(BaseFinanceTest):
    def _sale_without_payments(self) -> Sale:
        purchase = Purchase.objects.create(
            title='P', quantity=Decimal('2'), total_amount_eur=Decimal('100'),
        )
        return Sale.objects.create(
            purchase=purchase,
            buyer_name='B',
            quantity=Decimal('1'),
            unit_price=Decimal('50'),
            status=Sale.SaleStatus.DRAFT,
        )

    def test_manager_can_delete_sale_without_payments(self):
        sale = self._sale_without_payments()
        purchase_pk = sale.purchase_id
        self.client.login(username='manager', password='pw')
        response = self.client.post(
            reverse('operations:sale_delete', kwargs={'pk': sale.pk})
        )
        self.assertEqual(response.status_code, 302)
        self.assertFalse(Sale.objects.filter(pk=sale.pk).exists())
        self.assertEqual(
            response.url,
            reverse('operations:purchase_detail', kwargs={'pk': purchase_pk}),
        )

    def test_sale_with_payments_cannot_be_deleted(self):
        sale = self._sale_without_payments()
        SalePayment.objects.create(
            sale=sale,
            receiver=self.manager,
            amount=Decimal('10'),
            method=SalePayment.PaymentMethod.CASH,
        )
        self.client.login(username='admin', password='pw')
        response = self.client.post(
            reverse('operations:sale_delete', kwargs={'pk': sale.pk})
        )
        self.assertEqual(response.status_code, 302)
        self.assertTrue(Sale.objects.filter(pk=sale.pk).exists())

    def test_viewer_cannot_delete_sale(self):
        sale = self._sale_without_payments()
        self.client.login(username='viewer', password='pw')
        response = self.client.post(
            reverse('operations:sale_delete', kwargs={'pk': sale.pk})
        )
        self.assertEqual(response.status_code, 403)
        self.assertTrue(Sale.objects.filter(pk=sale.pk).exists())


class PurchaseDeleteProtectionTests(BaseFinanceTest):
    def test_purchase_with_payments_cannot_be_deleted(self):
        purchase = Purchase.objects.create(
            title='P', quantity=Decimal('1'), total_amount_eur=Decimal('100'),
        )
        sale = Sale.objects.create(
            purchase=purchase,
            buyer_name='B',
            quantity=Decimal('1'),
            unit_price=Decimal('100'),
            status=Sale.SaleStatus.CONFIRMED,
        )
        SalePayment.objects.create(
            sale=sale,
            receiver=self.manager,
            amount=Decimal('100'),
            method=SalePayment.PaymentMethod.CASH,
        )

        self.client.login(username='admin', password='pw')
        response = self.client.post(
            reverse('operations:purchase_delete', kwargs={'pk': purchase.pk})
        )
        self.assertEqual(response.status_code, 302)
        self.assertTrue(Purchase.objects.filter(pk=purchase.pk).exists())
