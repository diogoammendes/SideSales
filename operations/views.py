from collections import defaultdict
from decimal import Decimal

from django.contrib import messages
from django.contrib.auth import logout
from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin
from django.contrib.auth.forms import AuthenticationForm, SetPasswordForm, UserCreationForm
from django.contrib.auth.views import LoginView as AuthLoginView
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.db.models import Sum
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse, reverse_lazy
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


class DashboardView(LoginRequiredMixin, TemplateView):
    template_name = 'operations/dashboard.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        purchases = Purchase.objects.prefetch_related(
            'additional_costs__paid_by', 'contributions__payer', 'sales'
        )
        total_invested = sum(p.total_cost for p in purchases)
        total_revenue = sum(p.total_revenue for p in purchases)
        total_profit = total_revenue - total_invested

        ledger_map: dict[int, dict[str, Decimal | User]] = defaultdict(
            lambda: {
                'user': None,
                'invested': Decimal('0'),
                'attributed': Decimal('0'),
                'actual': Decimal('0'),
            }
        )

        active_users = User.objects.filter(is_active=True)
        for user in active_users:
            ledger_map[user.pk]['user'] = user

        for purchase in purchases:
            purchase_investments: dict[int, Decimal] = defaultdict(Decimal)

            for contribution in purchase.contributions.all():
                if contribution.payer_id:
                    purchase_investments[contribution.payer_id] += contribution.resolved_amount

            for cost in purchase.additional_costs.all():
                if cost.paid_by_id:
                    purchase_investments[cost.paid_by_id] += cost.amount

            if purchase.signal_paid_by_id:
                purchase_investments[purchase.signal_paid_by_id] += purchase.signal_amount_eur or Decimal('0')

            purchase_total_invested = sum(purchase_investments.values())
            purchase_revenue = purchase.total_revenue

            if not purchase_investments:
                continue

            for user_id, invested in purchase_investments.items():
                entry = ledger_map[user_id]
                entry['invested'] += invested
                if purchase_total_invested > 0 and purchase_revenue:
                    entry['attributed'] += (invested / purchase_total_invested) * purchase_revenue

        payment_totals = (
            SalePayment.objects.filter(receiver__is_active=True)
            .values('receiver_id')
            .annotate(total=Sum('amount'))
        )
        for payment in payment_totals:
            entry = ledger_map.get(payment['receiver_id'])
            if entry:
                entry['actual'] = payment['total'] or Decimal('0')

        ledger = []
        for entry in ledger_map.values():
            user = entry['user']
            if not user:
                continue
            invested = entry['invested']
            attributed = entry['attributed']
            actual = entry['actual']
            ledger.append(
                {
                    'user': user,
                    'invested': invested,
                    'received_actual': actual,
                    'received_attributed': attributed,
                    'real_balance': actual - invested,
                    'attributed_balance': attributed - invested,
                }
            )

        context.update(
            {
                'purchases': purchases,
                'totals': {
                    'invested': total_invested,
                    'revenue': total_revenue,
                    'profit': total_profit,
                },
                'ledger': ledger,
            }
        )
        return context


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
            .all()
        )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['contribution_form'] = PurchaseContributionForm()
        context['cost_form'] = AdditionalCostForm()
        return context


class PurchaseCreateView(LoginRequiredMixin, RoleRequiredMixin, View):
    template_name = 'operations/purchases/form.html'
    required_roles = (User.Roles.ADMIN, User.Roles.MANAGER)

    def get(self, request):
        form = PurchaseForm()
        return render(
            request,
            self.template_name,
            {
                'form': form,
                'title': _('Nova Compra'),
                'submit_label': _('Guardar Compra'),
            },
        )

    def post(self, request):
        form = PurchaseForm(request.POST)
        if form.is_valid():
            purchase = form.save()
            messages.success(request, _('Compra criada com sucesso.'))
            return redirect('operations:purchase_detail', pk=purchase.pk)
        messages.error(request, _('Por favor corrija os erros abaixo.'))
        return render(
            request,
            self.template_name,
            {
                'form': form,
                'title': _('Nova Compra'),
                'submit_label': _('Guardar Compra'),
            },
        )


class PurchaseUpdateView(LoginRequiredMixin, RoleRequiredMixin, View):
    template_name = 'operations/purchases/form.html'
    required_roles = (User.Roles.ADMIN, User.Roles.MANAGER)

    def dispatch(self, request, *args, **kwargs):
        self.purchase = get_object_or_404(Purchase, pk=kwargs['pk'])
        return super().dispatch(request, *args, **kwargs)

    def get(self, request, pk):
        form = PurchaseForm(instance=self.purchase)
        return render(
            request,
            self.template_name,
            {
                'form': form,
                'title': _('Editar Compra'),
                'submit_label': _('Atualizar Compra'),
            },
        )

    def post(self, request, pk):
        form = PurchaseForm(request.POST, instance=self.purchase)
        if form.is_valid():
            purchase = form.save()
            messages.success(request, _('Compra atualizada.'))
            return redirect('operations:purchase_detail', pk=purchase.pk)
        messages.error(request, _('Por favor corrija os erros abaixo.'))
        return render(
            request,
            self.template_name,
            {
                'form': form,
                'title': _('Editar Compra'),
                'submit_label': _('Atualizar Compra'),
            },
        )


class PurchaseDeleteView(LoginRequiredMixin, RoleRequiredMixin, View):
    required_roles = (User.Roles.ADMIN, User.Roles.MANAGER)

    def post(self, request, pk):
        purchase = get_object_or_404(Purchase, pk=pk)
        purchase.delete()
        messages.success(request, _('Compra eliminada.'))
        return redirect('operations:purchase_list')


class PurchaseContributionCreateView(LoginRequiredMixin, RoleRequiredMixin, View):
    required_roles = (User.Roles.ADMIN, User.Roles.MANAGER)

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

    def post(self, request, pk, contribution_pk):
        contribution = get_object_or_404(PurchaseContribution, pk=contribution_pk, purchase_id=pk)
        contribution.delete()
        messages.success(request, _('Participação removida.'))
        return redirect('operations:purchase_detail', pk=pk)


class AdditionalCostCreateView(LoginRequiredMixin, RoleRequiredMixin, View):
    required_roles = (User.Roles.ADMIN, User.Roles.MANAGER)

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

    def post(self, request, pk, cost_pk):
        cost = get_object_or_404(AdditionalCost, pk=cost_pk, purchase_id=pk)
        cost.delete()
        messages.success(request, _('Custo adicional removido.'))
        return redirect('operations:purchase_detail', pk=pk)


class SaleListView(LoginRequiredMixin, ListView):
    model = Sale
    context_object_name = 'sales'
    template_name = 'operations/sales/list.html'

    def get_queryset(self):
        return Sale.objects.select_related('purchase').prefetch_related('payments').order_by('-sold_on')


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


class SaleCreateView(LoginRequiredMixin, RoleRequiredMixin, View):
    template_name = 'operations/sales/form.html'
    required_roles = (User.Roles.ADMIN, User.Roles.MANAGER)

    def get(self, request):
        form = SaleForm(initial={'purchase': request.GET.get('purchase')})
        return render(
            request,
            self.template_name,
            {
                'form': form,
                'title': _('Nova Venda'),
                'submit_label': _('Guardar Venda'),
            },
        )

    def post(self, request):
        form = SaleForm(request.POST)
        if form.is_valid():
            sale = form.save()
            messages.success(request, _('Venda registada.'))
            return redirect('operations:sale_detail', pk=sale.pk)
        messages.error(request, _('Por favor corrija os erros abaixo.'))
        return render(
            request,
            self.template_name,
            {
                'form': form,
                'title': _('Nova Venda'),
                'submit_label': _('Guardar Venda'),
            },
        )


class SaleUpdateView(LoginRequiredMixin, RoleRequiredMixin, View):
    template_name = 'operations/sales/form.html'
    required_roles = (User.Roles.ADMIN, User.Roles.MANAGER)

    def dispatch(self, request, *args, **kwargs):
        self.sale = get_object_or_404(Sale, pk=kwargs['pk'])
        return super().dispatch(request, *args, **kwargs)

    def get(self, request, pk):
        form = SaleForm(instance=self.sale)
        return render(
            request,
            self.template_name,
            {
                'form': form,
                'title': _('Editar Venda'),
                'submit_label': _('Atualizar Venda'),
            },
        )

    def post(self, request, pk):
        form = SaleForm(request.POST, instance=self.sale)
        if form.is_valid():
            sale = form.save()
            messages.success(request, _('Venda atualizada.'))
            return redirect('operations:sale_detail', pk=sale.pk)
        messages.error(request, _('Por favor corrija os erros abaixo.'))
        return render(
            request,
            self.template_name,
            {
                'form': form,
                'title': _('Editar Venda'),
                'submit_label': _('Atualizar Venda'),
            },
        )


class SalePaymentCreateView(LoginRequiredMixin, RoleRequiredMixin, View):
    required_roles = (User.Roles.ADMIN, User.Roles.MANAGER)

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

    def post(self, request, pk, payment_pk):
        payment = get_object_or_404(SalePayment, pk=payment_pk, sale_id=pk)
        payment.delete()
        messages.success(request, _('Pagamento removido.'))
        return redirect('operations:sale_detail', pk=pk)


class UserListView(LoginRequiredMixin, RoleRequiredMixin, ListView):
    model = User
    context_object_name = 'users'
    template_name = 'operations/users/list.html'
    required_roles = (User.Roles.ADMIN,)

    def get_queryset(self):
        return User.objects.filter(is_active=True).order_by('first_name', 'username')


class UserCreateView(LoginRequiredMixin, RoleRequiredMixin, FormView):
    template_name = 'operations/users/form.html'
    form_class = UserCreateForm
    success_url = reverse_lazy('operations:user_list')
    required_roles = (User.Roles.ADMIN,)

    def form_valid(self, form):
        form.save()
        messages.success(self.request, _('Utilizador criado.'))
        return super().form_valid(form)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update({'title': _('Novo Utilizador'), 'submit_label': _('Criar Utilizador')})
        return context


class UserUpdateView(LoginRequiredMixin, RoleRequiredMixin, View):
    template_name = 'operations/users/form.html'
    required_roles = (User.Roles.ADMIN,)

    def dispatch(self, request, *args, **kwargs):
        self.user_obj = get_object_or_404(User, pk=kwargs['pk'])
        return super().dispatch(request, *args, **kwargs)

    def get(self, request, pk):
        form = UserUpdateForm(instance=self.user_obj)
        return render(
            request,
            self.template_name,
            {
                'form': form,
                'title': _('Editar Utilizador'),
                'submit_label': _('Atualizar Utilizador'),
            },
        )


class UserPasswordUpdateView(LoginRequiredMixin, RoleRequiredMixin, View):
    template_name = 'operations/users/password.html'
    required_roles = (User.Roles.ADMIN,)

    def dispatch(self, request, *args, **kwargs):
        self.user_obj = get_object_or_404(User, pk=kwargs['pk'])
        return super().dispatch(request, *args, **kwargs)

    def get(self, request, pk):
        form = SetPasswordForm(user=self.user_obj)
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

    def post(self, request, pk):
        form = SetPasswordForm(user=self.user_obj, data=request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, _('Password atualizada para %(user)s.') % {'user': self.user_obj.get_full_name() or self.user_obj.username})
            return redirect('operations:user_list')
        messages.error(request, _('Por favor corrija os erros abaixo.'))
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
