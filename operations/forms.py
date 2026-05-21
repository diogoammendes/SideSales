from decimal import Decimal, ROUND_HALF_UP

from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.forms import AuthenticationForm, UserCreationForm
from django.db.models import Q
from django.forms import inlineformset_factory
from django.utils.translation import gettext_lazy as _

from .models import (
    AdditionalCost,
    Purchase,
    PurchaseContribution,
    Sale,
    SalePayment,
    User,
)


def _active_users_including(instance_user_id: int | None):
    """Return active users, plus the (possibly deactivated) user currently
    selected on the instance being edited, so we never silently drop the
    historical value."""
    qs = User.objects.filter(is_active=True)
    if instance_user_id:
        qs = User.objects.filter(Q(is_active=True) | Q(pk=instance_user_id))
    return qs.order_by('first_name', 'username')


class LoginForm(AuthenticationForm):
    username = forms.CharField(label=_('Utilizador'))
    password = forms.CharField(widget=forms.PasswordInput, label=_('Password'))


class PurchaseForm(forms.ModelForm):
    class Meta:
        model = Purchase
        fields = [
            'title',
            'description',
            'quantity',
            'total_amount_original',
            'total_currency',
            'total_amount_eur',
            'purchased_on',
            'signal_amount_original',
            'signal_currency',
            'signal_amount_eur',
            'signal_paid_by',
            'signal_paid_on',
        ]
        widgets = {
            'purchased_on': forms.DateInput(attrs={'type': 'date'}),
            'signal_paid_on': forms.DateInput(attrs={'type': 'date'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if 'signal_paid_by' in self.fields:
            current = getattr(self.instance, 'signal_paid_by_id', None)
            self.fields['signal_paid_by'].queryset = _active_users_including(current)


class PurchaseContributionForm(forms.ModelForm):
    class Meta:
        model = PurchaseContribution
        fields = ['payer', 'contribution_type', 'value', 'paid_on', 'notes']
        widgets = {'paid_on': forms.DateInput(attrs={'type': 'date'})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if 'payer' in self.fields:
            current = getattr(self.instance, 'payer_id', None)
            self.fields['payer'].queryset = _active_users_including(current)

    def clean(self):
        cleaned = super().clean()
        contribution_type = cleaned.get('contribution_type')
        value = cleaned.get('value')
        if value is not None and value < 0:
            self.add_error('value', _('Valor não pode ser negativo.'))
        if (
            contribution_type == PurchaseContribution.ContributionType.PERCENTAGE
            and value is not None
            and (value < 0 or value > Decimal('100'))
        ):
            self.add_error('value', _('Percentagem tem de estar entre 0 e 100.'))
        return cleaned


class AdditionalCostForm(forms.ModelForm):
    class Meta:
        model = AdditionalCost
        fields = ['label', 'amount', 'paid_by', 'incurred_on']
        widgets = {'incurred_on': forms.DateInput(attrs={'type': 'date'})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if 'paid_by' in self.fields:
            current = getattr(self.instance, 'paid_by_id', None)
            self.fields['paid_by'].queryset = _active_users_including(current)

    def clean_amount(self):
        amount = self.cleaned_data.get('amount')
        if amount is not None and amount < 0:
            raise forms.ValidationError(_('Montante não pode ser negativo.'))
        return amount


class SaleForm(forms.ModelForm):
    price_mode = forms.CharField(
        widget=forms.HiddenInput,
        initial='unit',
        required=False,
    )
    total_price_input = forms.DecimalField(
        label=_('Valor total'),
        max_digits=12,
        decimal_places=2,
        required=False,
        widget=forms.NumberInput(attrs={'step': '0.01', 'min': '0'}),
    )

    class Meta:
        model = Sale
        fields = [
            'purchase',
            'buyer_name',
            'buyer_description',
            'quantity',
            'unit_price',
            'sold_on',
            'status',
            'notes',
        ]
        widgets = {'sold_on': forms.DateInput(attrs={'type': 'date'})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Field-level required is disabled; we validate in clean() so we can
        # control which field shows the error based on the selected price mode.
        self.fields['unit_price'].required = False

    def clean(self):
        cleaned = super().clean()
        quantity = cleaned.get('quantity')
        price_mode = cleaned.get('price_mode') or 'unit'

        if price_mode == 'total':
            total_price_input = cleaned.get('total_price_input')
            if total_price_input is None:
                self.add_error('total_price_input', _('Insere o valor total.'))
            elif total_price_input < 0:
                self.add_error('total_price_input', _('Valor total não pode ser negativo.'))
            elif quantity and quantity > 0:
                unit_price = (total_price_input / quantity).quantize(
                    Decimal('0.01'), rounding=ROUND_HALF_UP
                )
                cleaned['unit_price'] = unit_price
                self.instance.unit_price = unit_price
        else:
            unit_price = cleaned.get('unit_price')
            if unit_price is None and 'unit_price' not in self.errors:
                self.add_error('unit_price', _('Preço unitário é obrigatório.'))
            elif unit_price is not None and unit_price < 0:
                self.add_error('unit_price', _('Preço unitário não pode ser negativo.'))

        if quantity is not None and quantity <= 0:
            self.add_error('quantity', _('Quantidade tem de ser maior que zero.'))

        # Delegate overselling check to model.clean().
        instance = self.instance
        instance.purchase = cleaned.get('purchase', instance.purchase_id and instance.purchase)
        instance.quantity = quantity
        instance.status = cleaned.get('status', instance.status)
        try:
            instance.clean()
        except forms.ValidationError as exc:
            self._update_errors(exc)
        return cleaned


class SalePaymentForm(forms.ModelForm):
    class Meta:
        model = SalePayment
        fields = ['receiver', 'amount', 'method', 'paid_on', 'notes']
        widgets = {'paid_on': forms.DateInput(attrs={'type': 'date'})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if 'receiver' in self.fields:
            current = getattr(self.instance, 'receiver_id', None)
            self.fields['receiver'].queryset = _active_users_including(current)

    def clean_amount(self):
        amount = self.cleaned_data.get('amount')
        if amount is None or amount <= 0:
            raise forms.ValidationError(_('Montante tem de ser maior que zero.'))
        return amount


PurchaseContributionFormSet = inlineformset_factory(
    parent_model=Purchase,
    model=PurchaseContribution,
    form=PurchaseContributionForm,
    extra=1,
    can_delete=True,
)

AdditionalCostFormSet = inlineformset_factory(
    parent_model=Purchase,
    model=AdditionalCost,
    form=AdditionalCostForm,
    extra=1,
    can_delete=True,
)

SalePaymentFormSet = inlineformset_factory(
    parent_model=Sale,
    model=SalePayment,
    form=SalePaymentForm,
    extra=1,
    can_delete=True,
)


class UserCreateForm(UserCreationForm):
    role = forms.ChoiceField(choices=User.Roles.choices, label=_('Perfil'))

    class Meta(UserCreationForm.Meta):
        model = User
        fields = ('username', 'email', 'first_name', 'last_name', 'role')

    def clean_email(self):
        email = (self.cleaned_data.get('email') or '').strip()
        if email and User.objects.filter(email__iexact=email).exists():
            raise forms.ValidationError(_('Já existe um utilizador com este email.'))
        return email


class UserUpdateForm(forms.ModelForm):
    """Role and is_active are intentionally controlled at the view layer to
    prevent self-demotion and privilege escalation; see UserUpdateView."""

    class Meta:
        model = get_user_model()
        fields = ('email', 'first_name', 'last_name', 'role', 'is_active')

    def __init__(self, *args, editor=None, **kwargs):
        super().__init__(*args, **kwargs)
        self._editor = editor

    def clean_email(self):
        email = (self.cleaned_data.get('email') or '').strip()
        if email:
            qs = get_user_model().objects.filter(email__iexact=email)
            if self.instance.pk:
                qs = qs.exclude(pk=self.instance.pk)
            if qs.exists():
                raise forms.ValidationError(_('Já existe um utilizador com este email.'))
        return email

    def clean(self):
        cleaned = super().clean()
        editor = self._editor
        target = self.instance
        if editor is None or target.pk is None:
            return cleaned

        is_self = editor.pk == target.pk
        role = cleaned.get('role')
        is_active = cleaned.get('is_active')

        # Never allow modifying superusers unless the editor is also a superuser.
        if target.is_superuser and not editor.is_superuser:
            raise forms.ValidationError(
                _('Não é possível modificar uma conta de super-utilizador.')
            )

        # Never allow self-demotion or self-deactivation; the only admin could
        # otherwise lock themselves out.
        if is_self:
            if role and role != target.role:
                self.add_error('role', _('Não pode alterar o seu próprio perfil.'))
            if is_active is False:
                self.add_error('is_active', _('Não pode desativar a sua própria conta.'))

        return cleaned
