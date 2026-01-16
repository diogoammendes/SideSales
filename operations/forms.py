from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.forms import AuthenticationForm, UserCreationForm
from django.forms import inlineformset_factory

from .models import (
    AdditionalCost,
    Purchase,
    PurchaseContribution,
    Sale,
    SalePayment,
    User,
)


class LoginForm(AuthenticationForm):
    username = forms.CharField(label='Utilizador')
    password = forms.CharField(widget=forms.PasswordInput, label='Password')


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


class PurchaseContributionForm(forms.ModelForm):
    class Meta:
        model = PurchaseContribution
        fields = ['payer', 'contribution_type', 'value', 'paid_on', 'notes']
        widgets = {'paid_on': forms.DateInput(attrs={'type': 'date'})}


class AdditionalCostForm(forms.ModelForm):
    class Meta:
        model = AdditionalCost
        fields = ['label', 'amount', 'paid_by', 'incurred_on']
        widgets = {'incurred_on': forms.DateInput(attrs={'type': 'date'})}


class SaleForm(forms.ModelForm):
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


class SalePaymentForm(forms.ModelForm):
    class Meta:
        model = SalePayment
        fields = ['receiver', 'amount', 'method', 'paid_on', 'notes']
        widgets = {'paid_on': forms.DateInput(attrs={'type': 'date'})}


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
    role = forms.ChoiceField(choices=User.Roles.choices, label='Perfil')

    class Meta(UserCreationForm.Meta):
        model = User
        fields = ('username', 'email', 'first_name', 'last_name', 'role')


class UserUpdateForm(forms.ModelForm):
    class Meta:
        model = get_user_model()
        fields = ('email', 'first_name', 'last_name', 'role', 'is_active')
