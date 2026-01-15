from decimal import Decimal

from django.contrib import messages
from django.contrib.auth import logout
from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin
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
    AdditionalCostFormSet,
    LoginForm,
    PurchaseForm,
    PurchaseContributionFormSet,
    SaleForm,
    SalePaymentFormSet,
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
        purchases = Purchase.objects.prefetch_related('additional_costs', 'sales')
        total_invested = sum(p.total_cost for p in purchases)
        total_revenue = sum(p.total_revenue for p in purchases)
        total_profit = total_revenue - total_invested

        ledger = []
        users = User.objects.all()
        for user in users:
            contributions = PurchaseContribution.objects.filter(payer=user).select_related('purchase')
            invested_contributions = sum(item.resolved_amount for item in contributions)
            invested_costs = (
                AdditionalCost.objects.filter(paid_by=user).aggregate(total=Sum('amount'))['total']
                or Decimal('0')
            )
            invested_signal = (
                Purchase.objects.filter(signal_paid_by=user).aggregate(total=Sum('signal_amount'))['total']
                or Decimal('0')
            )
            invested = invested_contributions + invested_costs + invested_signal
            received = (
                SalePayment.objects.filter(receiver=user).aggregate(total=Sum('amount'))['total']
                or Decimal('0')
            )
            ledger.append(
                {
                    'user': user,
                    'invested': invested,
                    'received': received,
                    'net': received - invested,
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


class PurchaseCreateView(LoginRequiredMixin, RoleRequiredMixin, View):
    template_name = 'operations/purchases/form.html'
    required_roles = (User.Roles.ADMIN, User.Roles.MANAGER)

    def get(self, request):
        form = PurchaseForm()
        contrib_formset, cost_formset = self._build_formsets()
        return render(
            request,
            self.template_name,
            {
                'form': form,
                'contribution_formset': contrib_formset,
                'cost_formset': cost_formset,
                'title': _('Nova Compra'),
                'submit_label': _('Guardar Compra'),
            },
        )

    def post(self, request):
        form = PurchaseForm(request.POST)
        dummy_purchase = Purchase()
        contrib_formset, cost_formset = self._build_formsets(data=request.POST, instance=dummy_purchase)
        if all([form.is_valid(), contrib_formset.is_valid(), cost_formset.is_valid()]):
            with transaction.atomic():
                purchase = form.save()
                contrib_formset.instance = purchase
                cost_formset.instance = purchase
                contrib_formset.save()
                cost_formset.save()
            messages.success(request, _('Compra criada com sucesso.'))
            return redirect('operations:purchase_detail', pk=purchase.pk)
        messages.error(request, _('Por favor corrija os erros abaixo.'))
        return render(
            request,
            self.template_name,
            {
                'form': form,
                'contribution_formset': contrib_formset,
                'cost_formset': cost_formset,
                'title': _('Nova Compra'),
                'submit_label': _('Guardar Compra'),
            },
        )

    def _build_formsets(self, data=None, instance=None):
        contribution = PurchaseContributionFormSet(data=data, instance=instance, prefix='contrib')
        costs = AdditionalCostFormSet(data=data, instance=instance, prefix='cost')
        return contribution, costs


class PurchaseUpdateView(LoginRequiredMixin, RoleRequiredMixin, View):
    template_name = 'operations/purchases/form.html'
    required_roles = (User.Roles.ADMIN, User.Roles.MANAGER)

    def dispatch(self, request, *args, **kwargs):
        self.purchase = get_object_or_404(Purchase, pk=kwargs['pk'])
        return super().dispatch(request, *args, **kwargs)

    def get(self, request, pk):
        form = PurchaseForm(instance=self.purchase)
        contrib_formset, cost_formset = self._build_formsets(instance=self.purchase)
        return render(
            request,
            self.template_name,
            {
                'form': form,
                'contribution_formset': contrib_formset,
                'cost_formset': cost_formset,
                'title': _('Editar Compra'),
                'submit_label': _('Atualizar Compra'),
            },
        )

    def post(self, request, pk):
        form = PurchaseForm(request.POST, instance=self.purchase)
        contrib_formset, cost_formset = self._build_formsets(data=request.POST, instance=self.purchase)
        if all([form.is_valid(), contrib_formset.is_valid(), cost_formset.is_valid()]):
            with transaction.atomic():
                purchase = form.save()
                contrib_formset.instance = purchase
                cost_formset.instance = purchase
                contrib_formset.save()
                cost_formset.save()
            messages.success(request, _('Compra atualizada.'))
            return redirect('operations:purchase_detail', pk=purchase.pk)
        messages.error(request, _('Por favor corrija os erros abaixo.'))
        return render(
            request,
            self.template_name,
            {
                'form': form,
                'contribution_formset': contrib_formset,
                'cost_formset': cost_formset,
                'title': _('Editar Compra'),
                'submit_label': _('Atualizar Compra'),
            },
        )

    def _build_formsets(self, data=None, instance=None):
        contribution = PurchaseContributionFormSet(data=data, instance=instance, prefix='contrib')
        costs = AdditionalCostFormSet(data=data, instance=instance, prefix='cost')
        return contribution, costs


class SaleListView(LoginRequiredMixin, ListView):
    model = Sale
    context_object_name = 'sales'
    template_name = 'operations/sales/list.html'

    def get_queryset(self):
        return Sale.objects.select_related('purchase').prefetch_related('payments').order_by('-sold_on')


class SaleCreateView(LoginRequiredMixin, RoleRequiredMixin, View):
    template_name = 'operations/sales/form.html'
    required_roles = (User.Roles.ADMIN, User.Roles.MANAGER)

    def get(self, request):
        form = SaleForm(initial={'purchase': request.GET.get('purchase')})
        payment_formset = self._build_formset()
        return render(
            request,
            self.template_name,
            {
                'form': form,
                'payment_formset': payment_formset,
                'title': _('Nova Venda'),
                'submit_label': _('Guardar Venda'),
            },
        )

    def post(self, request):
        form = SaleForm(request.POST)
        dummy_sale = Sale()
        payment_formset = self._build_formset(data=request.POST, instance=dummy_sale)
        if form.is_valid() and payment_formset.is_valid():
            with transaction.atomic():
                sale = form.save()
                payment_formset.instance = sale
                payment_formset.save()
            messages.success(request, _('Venda registada.'))
            return redirect('operations:sale_list')
        messages.error(request, _('Por favor corrija os erros abaixo.'))
        return render(
            request,
            self.template_name,
            {
                'form': form,
                'payment_formset': payment_formset,
                'title': _('Nova Venda'),
                'submit_label': _('Guardar Venda'),
            },
        )

    def _build_formset(self, data=None, instance=None):
        return SalePaymentFormSet(data=data, instance=instance, prefix='payment')


class SaleUpdateView(LoginRequiredMixin, RoleRequiredMixin, View):
    template_name = 'operations/sales/form.html'
    required_roles = (User.Roles.ADMIN, User.Roles.MANAGER)

    def dispatch(self, request, *args, **kwargs):
        self.sale = get_object_or_404(Sale, pk=kwargs['pk'])
        return super().dispatch(request, *args, **kwargs)

    def get(self, request, pk):
        form = SaleForm(instance=self.sale)
        payment_formset = self._build_formset(instance=self.sale)
        return render(
            request,
            self.template_name,
            {
                'form': form,
                'payment_formset': payment_formset,
                'title': _('Editar Venda'),
                'submit_label': _('Atualizar Venda'),
            },
        )

    def post(self, request, pk):
        form = SaleForm(request.POST, instance=self.sale)
        payment_formset = self._build_formset(data=request.POST, instance=self.sale)
        if form.is_valid() and payment_formset.is_valid():
            with transaction.atomic():
                sale = form.save()
                payment_formset.instance = sale
                payment_formset.save()
            messages.success(request, _('Venda atualizada.'))
            return redirect('operations:sale_list')
        messages.error(request, _('Por favor corrija os erros abaixo.'))
        return render(
            request,
            self.template_name,
            {
                'form': form,
                'payment_formset': payment_formset,
                'title': _('Editar Venda'),
                'submit_label': _('Atualizar Venda'),
            },
        )

    def _build_formset(self, data=None, instance=None):
        return SalePaymentFormSet(data=data, instance=instance, prefix='payment')


class UserListView(LoginRequiredMixin, RoleRequiredMixin, ListView):
    model = User
    context_object_name = 'users'
    template_name = 'operations/users/list.html'
    required_roles = (User.Roles.ADMIN,)

    def get_queryset(self):
        return User.objects.order_by('first_name', 'username')


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

    def post(self, request, pk):
        form = UserUpdateForm(request.POST, instance=self.user_obj)
        if form.is_valid():
            form.save()
            messages.success(request, _('Utilizador atualizado.'))
            return redirect('operations:user_list')
        messages.error(request, _('Por favor corrija os erros abaixo.'))
        return render(
            request,
            self.template_name,
            {
                'form': form,
                'title': _('Editar Utilizador'),
                'submit_label': _('Atualizar Utilizador'),
            },
        )
