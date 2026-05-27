from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Iterable

from django.contrib import messages
from django.contrib.auth import logout, update_session_auth_hash
from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin
from django.contrib.auth.forms import SetPasswordForm
from django.contrib.auth.views import LoginView as AuthLoginView
from django.contrib.sessions.models import Session
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.db.models import ProtectedError, Sum
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse_lazy
from django.utils import timezone
from django.utils.translation import gettext_lazy as _
from django.views import View
from django.views.generic import DetailView, ListView, TemplateView
from django.views.generic.edit import FormView

from .forms import (
    AdditionalCostForm,
    LoginForm,
    PurchaseForm,
    PurchaseContributionForm,
    SaleForm,
    SalePaymentForm,
    UserCreateForm,
    UserUpdateForm,
)
from .models import AdditionalCost, Purchase, PurchaseContribution, Sale, SalePayment, User


ZERO = Decimal('0')


# ---------------------------------------------------------------------------
# Auth / role helpers
# ---------------------------------------------------------------------------

class RoleRequiredMixin(UserPassesTestMixin):
    required_roles: tuple[str, ...] | None = None
    raise_exception = True

    def test_func(self):
        user = self.request.user
        if not user.is_authenticated:
            return False
        if user.is_superuser:
            return True
        if not self.required_roles:
            return True
        return getattr(user, 'role', None) in self.required_roles


class LoginView(AuthLoginView):
    template_name = 'registration/login.html'
    authentication_form = LoginForm


def logout_view(request):
    logout(request)
    return redirect('login')


def _invalidate_sessions_for(user: User) -> None:
    """Invalidate every active session belonging to the given user.

    Used when we deactivate an account or change its password administratively:
    without this the target would stay logged in until their session expired.
    """
    now = timezone.now()
    for session in Session.objects.filter(expire_date__gte=now):
        data = session.get_decoded()
        if str(data.get('_auth_user_id')) == str(user.pk):
            session.delete()


# ---------------------------------------------------------------------------
# Dashboard
# ---------------------------------------------------------------------------

@dataclass
class LedgerEntry:
    user: User | None = None
    invested: Decimal = ZERO
    attributed_revenue: Decimal = ZERO
    attributed_profit: Decimal = ZERO
    actual_received: Decimal = ZERO

    @property
    def real_balance(self) -> Decimal:
        return self.actual_received - self.invested

    @property
    def attributed_balance(self) -> Decimal:
        return self.attributed_profit

    def as_template_dict(self) -> dict:
        return {
            'user': self.user,
            'invested': self.invested,
            'received_actual': self.actual_received,
            'received_attributed': self.attributed_revenue,
            'real_balance': self.real_balance,
            'attributed_balance': self.attributed_balance,
        }


@dataclass
class SalesBucket:
    value: Decimal = ZERO
    profit: Decimal = ZERO
    count: int = 0
    share: Decimal = ZERO


@dataclass
class DashboardContext:
    purchases: Iterable[Purchase]
    total_invested: Decimal
    total_revenue: Decimal
    total_profit: Decimal
    projected_revenue: Decimal
    projected_profit: Decimal
    sales_summary: dict[str, SalesBucket]
    ledger: list[dict]


def _compute_sales_buckets(purchases: Iterable[Purchase]) -> tuple[dict[str, SalesBucket], Decimal, Decimal]:
    """Return (buckets, realized_revenue, draft_revenue)."""
    buckets: dict[str, SalesBucket] = {'realized': SalesBucket(), 'draft': SalesBucket()}
    for purchase in purchases:
        per_unit_cost = ZERO
        if purchase.quantity:
            per_unit_cost = (purchase.total_cost or ZERO) / purchase.quantity
        for sale in purchase.sales.all():
            sale_value = sale.total_price
            sale_qty = sale.quantity or ZERO
            sale_profit = sale_value - (sale_qty * per_unit_cost)
            bucket = 'draft' if sale.status == Sale.SaleStatus.DRAFT else 'realized'
            buckets[bucket].value += sale_value
            buckets[bucket].profit += sale_profit
            buckets[bucket].count += 1
    return buckets, buckets['realized'].value, buckets['draft'].value


def _compute_ledger(purchases: Iterable[Purchase]) -> tuple[list[dict], Decimal]:
    """Build the per-user ledger.

    Returns (rows_for_template, total_invested_from_ledger). The total is
    derived from the SAME source as the per-user rows so the dashboard always
    reconciles.

    Critically, we do NOT filter users by is_active here: deactivating a user
    must never make their investments or received payments disappear from the
    financial record.
    """
    ledger_map: dict[int, LedgerEntry] = {}

    def entry_for(user_id: int) -> LedgerEntry:
        entry = ledger_map.get(user_id)
        if entry is None:
            entry = LedgerEntry()
            ledger_map[user_id] = entry
        return entry

    total_invested = ZERO

    for purchase in purchases:
        purchase_investments: dict[int, Decimal] = {}
        purchase_realized_revenue = ZERO
        purchase_realized_cost = ZERO

        per_unit_cost = ZERO
        if purchase.quantity:
            per_unit_cost = (purchase.total_cost or ZERO) / purchase.quantity

        for sale in purchase.sales.all():
            if sale.status == Sale.SaleStatus.DRAFT:
                continue
            purchase_realized_revenue += sale.total_price
            purchase_realized_cost += (sale.quantity or ZERO) * per_unit_cost

        purchase_realized_profit = purchase_realized_revenue - purchase_realized_cost

        def add_investment(user_id: int | None, amount: Decimal) -> None:
            if not user_id or not amount:
                return
            purchase_investments[user_id] = purchase_investments.get(user_id, ZERO) + amount

        for contribution in purchase.contributions.all():
            add_investment(contribution.payer_id, contribution.resolved_amount)

        for cost in purchase.additional_costs.all():
            add_investment(cost.paid_by_id, cost.amount)

        add_investment(purchase.signal_paid_by_id, purchase.signal_amount_eur or ZERO)

        purchase_total_invested = sum(purchase_investments.values(), ZERO)
        total_invested += purchase_total_invested

        if not purchase_investments or purchase_total_invested <= 0:
            continue

        for user_id, invested in purchase_investments.items():
            entry = entry_for(user_id)
            entry.invested += invested
            share = invested / purchase_total_invested
            entry.attributed_revenue += share * purchase_realized_revenue
            entry.attributed_profit += share * purchase_realized_profit

    # Actual received: sum payments per receiver, regardless of active status.
    payment_totals = (
        SalePayment.objects.values('receiver_id').annotate(total=Sum('amount'))
    )
    for payment in payment_totals:
        entry = entry_for(payment['receiver_id'])
        entry.actual_received = payment['total'] or ZERO

    # Resolve user objects in one query, including inactive ones.
    user_ids = list(ledger_map.keys())
    users_by_id = {u.pk: u for u in User.objects.filter(pk__in=user_ids)}
    for uid, entry in ledger_map.items():
        entry.user = users_by_id.get(uid)

    rows = [
        entry.as_template_dict()
        for entry in ledger_map.values()
        if entry.user is not None
    ]
    rows.sort(key=lambda row: (row['user'].first_name or '', row['user'].username))
    return rows, total_invested


class DashboardView(LoginRequiredMixin, TemplateView):
    template_name = 'operations/dashboard.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        purchases = list(
            Purchase.objects.prefetch_related(
                'additional_costs__paid_by',
                'contributions__payer',
                'sales',
            )
        )

        sales_buckets, realized_revenue, draft_revenue = _compute_sales_buckets(purchases)
        ledger_rows, ledger_invested = _compute_ledger(purchases)

        # Reconcile: global totals are derived from the same source as the
        # per-user ledger so "sum(row.invested)" always equals total_invested.
        total_invested = ledger_invested
        total_revenue = realized_revenue
        total_profit = total_revenue - total_invested
        projected_revenue = realized_revenue + draft_revenue
        projected_profit = projected_revenue - total_invested

        if projected_revenue > 0:
            sales_buckets['realized'].share = (realized_revenue / projected_revenue) * Decimal('100')
            sales_buckets['draft'].share = Decimal('100') - sales_buckets['realized'].share
        # Template still accesses dict-style keys; translate dataclass -> dict.
        sales_summary = {
            name: {
                'value': bucket.value,
                'profit': bucket.profit,
                'count': bucket.count,
                'share': bucket.share,
            }
            for name, bucket in sales_buckets.items()
        }

        context.update(
            {
                'purchases': purchases,
                'totals': {
                    'invested': total_invested,
                    'revenue': total_revenue,
                    'profit': total_profit,
                },
                'projections': {
                    'revenue': projected_revenue,
                    'profit': projected_profit,
                },
                'sales_summary': sales_summary,
                'ledger': ledger_rows,
            }
        )
        return context


def _compute_settlement(purchases: Iterable[Purchase]) -> dict:
    """Per-user balances and minimum transfers for the settlement view.

    Fair amount per user = (their investment / total investment) * total revenue.
    Only non-draft sale payments count as received revenue.
    """
    invested_by_user: dict[int, Decimal] = {}

    def add_investment(user_id: int | None, amount: Decimal | None) -> None:
        if not user_id or not amount:
            return
        invested_by_user[user_id] = invested_by_user.get(user_id, ZERO) + amount

    for purchase in purchases:
        for contribution in purchase.contributions.all():
            add_investment(contribution.payer_id, contribution.resolved_amount)
        for cost in purchase.additional_costs.all():
            add_investment(cost.paid_by_id, cost.amount)
        add_investment(purchase.signal_paid_by_id, purchase.signal_amount_eur or ZERO)

    total_invested = sum(invested_by_user.values(), ZERO)

    payment_qs = (
        SalePayment.objects
        .exclude(sale__status=Sale.SaleStatus.DRAFT)
        .values('receiver_id')
        .annotate(total=Sum('amount'))
    )
    received_by_user: dict[int, Decimal] = {
        p['receiver_id']: p['total'] or ZERO for p in payment_qs
    }
    total_received = sum(received_by_user.values(), ZERO)

    all_user_ids = set(invested_by_user) | set(received_by_user)
    n_users = len(all_user_ids) or 1

    balances: dict[int, dict] = {}
    for uid in all_user_ids:
        invested = invested_by_user.get(uid, ZERO)
        received = received_by_user.get(uid, ZERO)
        if total_invested > ZERO:
            share_pct = (invested / total_invested) * Decimal('100')
            fair = (invested / total_invested) * total_received
        else:
            share_pct = Decimal('100') / n_users
            fair = total_received / n_users
        balance = received - fair
        balances[uid] = {
            'invested': invested,
            'received': received,
            'share_pct': share_pct,
            'fair': fair,
            'balance': balance,
            'balance_abs': abs(balance),
        }

    # Minimum transfers — greedy Splitwise algorithm.
    EPSILON = Decimal('0.005')
    debtors = [[uid, info['balance']]
               for uid, info in balances.items() if info['balance'] > EPSILON]
    creditors = [[uid, -info['balance']]
                 for uid, info in balances.items() if info['balance'] < -EPSILON]
    debtors.sort(key=lambda x: x[1], reverse=True)
    creditors.sort(key=lambda x: x[1], reverse=True)

    transfers = []
    i = j = 0
    while i < len(debtors) and j < len(creditors):
        amount = min(debtors[i][1], creditors[j][1])
        if amount > EPSILON:
            transfers.append({
                'from_user_id': debtors[i][0],
                'to_user_id': creditors[j][0],
                'amount': amount.quantize(Decimal('0.01')),
            })
        debtors[i][1] -= amount
        creditors[j][1] -= amount
        if debtors[i][1] <= EPSILON:
            i += 1
        if creditors[j][1] <= EPSILON:
            j += 1

    users_by_id = {u.pk: u for u in User.objects.filter(pk__in=all_user_ids)}
    for uid, info in balances.items():
        info['user'] = users_by_id.get(uid)
    for t in transfers:
        t['from_user'] = users_by_id.get(t['from_user_id'])
        t['to_user'] = users_by_id.get(t['to_user_id'])

    balance_rows = sorted(
        [info for info in balances.values() if info.get('user')],
        key=lambda x: x['balance'],
    )

    return {
        'balance_rows': balance_rows,
        'transfers': transfers,
        'total_invested': total_invested,
        'total_received': total_received,
        'total_profit': total_received - total_invested,
    }


class SettlementView(LoginRequiredMixin, TemplateView):
    template_name = 'operations/settlement.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        purchases = list(
            Purchase.objects.prefetch_related(
                'additional_costs__paid_by',
                'contributions__payer',
            )
        )
        context.update(_compute_settlement(purchases))
        return context


# ---------------------------------------------------------------------------
# Form-view helper
# ---------------------------------------------------------------------------

class _FormPageMixin:
    """Small helper to remove the copy-pasted render(...) blocks in every
    create/update view. Subclasses set template_name, title and submit_label."""

    template_name: str
    title: str = ''
    submit_label: str = ''

    def render_form(self, request, form, *, extra_context: dict | None = None):
        context = {
            'form': form,
            'title': self.title,
            'submit_label': self.submit_label,
        }
        if extra_context:
            context.update(extra_context)
        return render(request, self.template_name, context)


# ---------------------------------------------------------------------------
# Purchase views
# ---------------------------------------------------------------------------

class PurchaseListView(LoginRequiredMixin, ListView):
    model = Purchase
    context_object_name = 'purchases'
    template_name = 'operations/purchases/list.html'

    def get_queryset(self):
        return (
            Purchase.objects.prefetch_related('additional_costs', 'sales')
            .select_related('signal_paid_by')
            .order_by('-purchased_on')
        )


class PurchaseDetailView(LoginRequiredMixin, DetailView):
    model = Purchase
    context_object_name = 'purchase'
    template_name = 'operations/purchases/detail.html'

    def get_queryset(self):
        return (
            Purchase.objects.select_related('signal_paid_by')
            .prefetch_related(
                'additional_costs__paid_by',
                'contributions__payer',
                'sales__payments__receiver',
            )
        )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['contribution_form'] = PurchaseContributionForm()
        context['cost_form'] = AdditionalCostForm()
        return context


class PurchaseCreateView(LoginRequiredMixin, RoleRequiredMixin, _FormPageMixin, View):
    template_name = 'operations/purchases/form.html'
    required_roles = (User.Roles.ADMIN, User.Roles.MANAGER)
    title = _('Nova Compra')
    submit_label = _('Guardar Compra')

    def get(self, request):
        return self.render_form(request, PurchaseForm())

    @transaction.atomic
    def post(self, request):
        form = PurchaseForm(request.POST)
        if form.is_valid():
            purchase = form.save()
            messages.success(request, _('Compra criada com sucesso.'))
            return redirect('operations:purchase_detail', pk=purchase.pk)
        messages.error(request, _('Por favor corrija os erros abaixo.'))
        return self.render_form(request, form)


class PurchaseUpdateView(LoginRequiredMixin, RoleRequiredMixin, _FormPageMixin, View):
    template_name = 'operations/purchases/form.html'
    required_roles = (User.Roles.ADMIN, User.Roles.MANAGER)
    title = _('Editar Compra')
    submit_label = _('Atualizar Compra')

    def dispatch(self, request, *args, **kwargs):
        self.purchase = get_object_or_404(Purchase, pk=kwargs['pk'])
        return super().dispatch(request, *args, **kwargs)

    def get(self, request, pk):
        return self.render_form(request, PurchaseForm(instance=self.purchase))

    @transaction.atomic
    def post(self, request, pk):
        form = PurchaseForm(request.POST, instance=self.purchase)
        if form.is_valid():
            purchase = form.save()
            messages.success(request, _('Compra atualizada.'))
            return redirect('operations:purchase_detail', pk=purchase.pk)
        messages.error(request, _('Por favor corrija os erros abaixo.'))
        return self.render_form(request, form)


class PurchaseDeleteView(LoginRequiredMixin, RoleRequiredMixin, View):
    required_roles = (User.Roles.ADMIN, User.Roles.MANAGER)

    @transaction.atomic
    def post(self, request, pk):
        purchase = get_object_or_404(Purchase, pk=pk)
        # Refuse to destroy financial history if any money has been recorded
        # against this purchase. Force the operator to delete payments first.
        if SalePayment.objects.filter(sale__purchase_id=purchase.pk).exists():
            messages.error(
                request,
                _('Não é possível apagar uma compra com pagamentos registados.'),
            )
            return redirect('operations:purchase_detail', pk=purchase.pk)
        try:
            purchase.delete()
        except ProtectedError:
            messages.error(
                request,
                _('Não é possível apagar esta compra: existem registos protegidos.'),
            )
            return redirect('operations:purchase_detail', pk=purchase.pk)
        messages.success(request, _('Compra eliminada.'))
        return redirect('operations:purchase_list')


class PurchaseContributionCreateView(LoginRequiredMixin, RoleRequiredMixin, View):
    required_roles = (User.Roles.ADMIN, User.Roles.MANAGER)

    @transaction.atomic
    def post(self, request, pk):
        purchase = get_object_or_404(Purchase, pk=pk)
        form = PurchaseContributionForm(request.POST)
        if form.is_valid():
            contribution = form.save(commit=False)
            contribution.purchase = purchase
            contribution.save()
            messages.success(request, _('Participação adicionada.'))
        else:
            for error in form.errors.values():
                messages.error(request, error)
        return redirect('operations:purchase_detail', pk=pk)


class PurchaseContributionDeleteView(LoginRequiredMixin, RoleRequiredMixin, View):
    required_roles = (User.Roles.ADMIN, User.Roles.MANAGER)

    @transaction.atomic
    def post(self, request, pk, contribution_pk):
        contribution = get_object_or_404(
            PurchaseContribution, pk=contribution_pk, purchase_id=pk
        )
        contribution.delete()
        messages.success(request, _('Participação removida.'))
        return redirect('operations:purchase_detail', pk=pk)


class AdditionalCostCreateView(LoginRequiredMixin, RoleRequiredMixin, View):
    required_roles = (User.Roles.ADMIN, User.Roles.MANAGER)

    @transaction.atomic
    def post(self, request, pk):
        purchase = get_object_or_404(Purchase, pk=pk)
        form = AdditionalCostForm(request.POST)
        if form.is_valid():
            cost = form.save(commit=False)
            cost.purchase = purchase
            cost.save()
            messages.success(request, _('Custo adicional registado.'))
        else:
            for error in form.errors.values():
                messages.error(request, error)
        return redirect('operations:purchase_detail', pk=pk)


class AdditionalCostDeleteView(LoginRequiredMixin, RoleRequiredMixin, View):
    required_roles = (User.Roles.ADMIN, User.Roles.MANAGER)

    @transaction.atomic
    def post(self, request, pk, cost_pk):
        cost = get_object_or_404(AdditionalCost, pk=cost_pk, purchase_id=pk)
        cost.delete()
        messages.success(request, _('Custo adicional removido.'))
        return redirect('operations:purchase_detail', pk=pk)


# ---------------------------------------------------------------------------
# Sale views
# ---------------------------------------------------------------------------

class SaleListView(LoginRequiredMixin, ListView):
    model = Sale
    context_object_name = 'sales'
    template_name = 'operations/sales/list.html'

    def get_queryset(self):
        return (
            Sale.objects.select_related('purchase')
            .prefetch_related('payments')
            .order_by('-sold_on')
        )


class SaleDetailView(LoginRequiredMixin, DetailView):
    model = Sale
    context_object_name = 'sale'
    template_name = 'operations/sales/detail.html'

    def get_queryset(self):
        return Sale.objects.select_related('purchase').prefetch_related('payments__receiver')

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['payment_form'] = SalePaymentForm()
        return context


class SaleCreateView(LoginRequiredMixin, RoleRequiredMixin, _FormPageMixin, View):
    template_name = 'operations/sales/form.html'
    required_roles = (User.Roles.ADMIN, User.Roles.MANAGER)
    title = _('Nova Venda')
    submit_label = _('Guardar Venda')

    def get(self, request):
        return self.render_form(
            request,
            SaleForm(initial={'purchase': request.GET.get('purchase')}),
        )

    @transaction.atomic
    def post(self, request):
        form = SaleForm(request.POST)
        if form.is_valid():
            sale = form.save()
            messages.success(request, _('Venda registada.'))
            return redirect('operations:sale_detail', pk=sale.pk)
        messages.error(request, _('Por favor corrija os erros abaixo.'))
        return self.render_form(request, form)


class SaleUpdateView(LoginRequiredMixin, RoleRequiredMixin, _FormPageMixin, View):
    template_name = 'operations/sales/form.html'
    required_roles = (User.Roles.ADMIN, User.Roles.MANAGER)
    title = _('Editar Venda')
    submit_label = _('Atualizar Venda')

    def dispatch(self, request, *args, **kwargs):
        self.sale = get_object_or_404(Sale, pk=kwargs['pk'])
        return super().dispatch(request, *args, **kwargs)

    def get(self, request, pk):
        return self.render_form(request, SaleForm(instance=self.sale))

    @transaction.atomic
    def post(self, request, pk):
        form = SaleForm(request.POST, instance=self.sale)
        if form.is_valid():
            sale = form.save()
            messages.success(request, _('Venda atualizada.'))
            return redirect('operations:sale_detail', pk=sale.pk)
        messages.error(request, _('Por favor corrija os erros abaixo.'))
        return self.render_form(request, form)


class SaleDeleteView(LoginRequiredMixin, RoleRequiredMixin, View):
    required_roles = (User.Roles.ADMIN, User.Roles.MANAGER)

    @transaction.atomic
    def post(self, request, pk):
        sale = get_object_or_404(Sale, pk=pk)
        purchase_pk = sale.purchase_id
        # Refuse to destroy financial history: if payments were already
        # recorded against this sale, force the operator to remove those
        # first so the ledger stays auditable.
        if sale.payments.exists():
            messages.error(
                request,
                _('Não é possível apagar uma venda com pagamentos registados.'),
            )
            return redirect('operations:sale_detail', pk=sale.pk)
        try:
            sale.delete()
        except ProtectedError:
            messages.error(
                request,
                _('Não é possível apagar esta venda: existem registos protegidos.'),
            )
            return redirect('operations:sale_detail', pk=sale.pk)
        messages.success(request, _('Venda eliminada.'))
        if purchase_pk:
            return redirect('operations:purchase_detail', pk=purchase_pk)
        return redirect('operations:sale_list')


class SalePaymentCreateView(LoginRequiredMixin, RoleRequiredMixin, View):
    required_roles = (User.Roles.ADMIN, User.Roles.MANAGER)

    @transaction.atomic
    def post(self, request, pk):
        sale = get_object_or_404(Sale, pk=pk)
        form = SalePaymentForm(request.POST)
        if form.is_valid():
            payment = form.save(commit=False)
            payment.sale = sale
            payment.save()
            messages.success(request, _('Pagamento registado.'))
        else:
            for error in form.errors.values():
                messages.error(request, error)
        return redirect('operations:sale_detail', pk=pk)


class SalePaymentDeleteView(LoginRequiredMixin, RoleRequiredMixin, View):
    required_roles = (User.Roles.ADMIN, User.Roles.MANAGER)

    @transaction.atomic
    def post(self, request, pk, payment_pk):
        payment = get_object_or_404(SalePayment, pk=payment_pk, sale_id=pk)
        payment.delete()
        messages.success(request, _('Pagamento removido.'))
        return redirect('operations:sale_detail', pk=pk)


# ---------------------------------------------------------------------------
# User management
# ---------------------------------------------------------------------------

class _AdminOnlyUserMixin(LoginRequiredMixin, RoleRequiredMixin):
    required_roles = (User.Roles.ADMIN,)

    def _guard_target(self, target: User) -> None:
        """Reject cross-privilege modifications.

        An ADMIN (non-superuser) must not be able to touch a superuser account,
        since this is a trivial path to full admin takeover: reset the
        superuser's password and log in as them.
        """
        editor = self.request.user
        if target.is_superuser and not editor.is_superuser:
            raise PermissionDenied(
                'Não é possível modificar uma conta de super-utilizador.'
            )


class UserListView(_AdminOnlyUserMixin, ListView):
    model = User
    context_object_name = 'users'
    template_name = 'operations/users/list.html'

    def get_queryset(self):
        # Show active accounts by default; deactivated accounts remain in the
        # database but are not actionable from this page.
        return User.objects.filter(is_active=True).order_by('first_name', 'username')


class UserCreateView(_AdminOnlyUserMixin, FormView):
    template_name = 'operations/users/form.html'
    form_class = UserCreateForm
    success_url = reverse_lazy('operations:user_list')

    @transaction.atomic
    def form_valid(self, form):
        form.save()
        messages.success(self.request, _('Utilizador criado.'))
        return super().form_valid(form)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update({'title': _('Novo Utilizador'), 'submit_label': _('Criar Utilizador')})
        return context


class UserUpdateView(_AdminOnlyUserMixin, View):
    template_name = 'operations/users/form.html'

    def dispatch(self, request, *args, **kwargs):
        self.user_obj = get_object_or_404(User, pk=kwargs['pk'])
        self._guard_target(self.user_obj)
        return super().dispatch(request, *args, **kwargs)

    def _render(self, request, form):
        return render(
            request,
            self.template_name,
            {
                'form': form,
                'user_obj': self.user_obj,
                'title': _('Editar Utilizador'),
                'submit_label': _('Atualizar Utilizador'),
            },
        )

    def get(self, request, pk):
        form = UserUpdateForm(instance=self.user_obj, editor=request.user)
        return self._render(request, form)

    @transaction.atomic
    def post(self, request, pk):
        was_active = self.user_obj.is_active
        form = UserUpdateForm(request.POST, instance=self.user_obj, editor=request.user)
        if form.is_valid():
            saved = form.save()
            if was_active and not saved.is_active:
                # Kick the deactivated user out of any live sessions.
                _invalidate_sessions_for(saved)
            messages.success(
                request,
                _('Utilizador %(user)s atualizado.')
                % {'user': saved.get_full_name() or saved.username},
            )
            return redirect('operations:user_list')
        messages.error(request, _('Por favor corrija os erros abaixo.'))
        return self._render(request, form)


class UserPasswordUpdateView(_AdminOnlyUserMixin, View):
    template_name = 'operations/users/password.html'

    def dispatch(self, request, *args, **kwargs):
        self.user_obj = get_object_or_404(User, pk=kwargs['pk'])
        self._guard_target(self.user_obj)
        return super().dispatch(request, *args, **kwargs)

    def _render(self, request, form):
        return render(
            request,
            self.template_name,
            {
                'form': form,
                'user_obj': self.user_obj,
                'title': _('Alterar password'),
                'submit_label': _('Guardar nova password'),
            },
        )

    def get(self, request, pk):
        return self._render(request, SetPasswordForm(user=self.user_obj))

    @transaction.atomic
    def post(self, request, pk):
        form = SetPasswordForm(user=self.user_obj, data=request.POST)
        if form.is_valid():
            form.save()
            if request.user == self.user_obj:
                update_session_auth_hash(request, self.user_obj)
            else:
                # Force other sessions of this user to re-authenticate.
                _invalidate_sessions_for(self.user_obj)
            messages.success(
                request,
                _('Password atualizada para %(user)s.')
                % {'user': self.user_obj.get_full_name() or self.user_obj.username},
            )
            return redirect('operations:user_list')
        messages.error(request, _('Por favor corrija os erros abaixo.'))
        return self._render(request, form)
