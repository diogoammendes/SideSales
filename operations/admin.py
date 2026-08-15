from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as DjangoUserAdmin

from .models import (
    AdditionalCost,
    Purchase,
    PurchaseContribution,
    Sale,
    SalePayment,
    SystemSettings,
    User,
)


@admin.register(User)
class UserAdmin(DjangoUserAdmin):
    list_display = ('username', 'email', 'first_name', 'last_name', 'role', 'is_active', 'is_superuser')
    list_filter = ('role', 'is_active', 'is_superuser')
    fieldsets = DjangoUserAdmin.fieldsets + (
        ('Aplicação', {'fields': ('role',)}),
    )
    add_fieldsets = DjangoUserAdmin.add_fieldsets + (
        ('Aplicação', {'fields': ('role',)}),
    )


class AdditionalCostInline(admin.TabularInline):
    model = AdditionalCost
    extra = 0


class PurchaseContributionInline(admin.TabularInline):
    model = PurchaseContribution
    extra = 0
    readonly_fields = ('resolved_amount_snapshot',)


class SaleInline(admin.TabularInline):
    model = Sale
    extra = 0
    show_change_link = True


@admin.register(Purchase)
class PurchaseAdmin(admin.ModelAdmin):
    list_display = ('title', 'purchased_on', 'quantity', 'total_amount_eur', 'signal_amount_eur')
    list_filter = ('purchased_on',)
    search_fields = ('title', 'description')
    inlines = [PurchaseContributionInline, AdditionalCostInline, SaleInline]


@admin.register(AdditionalCost)
class AdditionalCostAdmin(admin.ModelAdmin):
    list_display = ('label', 'purchase', 'amount', 'paid_by', 'incurred_on')
    list_filter = ('incurred_on',)


@admin.register(PurchaseContribution)
class PurchaseContributionAdmin(admin.ModelAdmin):
    list_display = ('purchase', 'payer', 'contribution_type', 'value', 'resolved_amount_snapshot', 'paid_on')
    list_filter = ('contribution_type', 'paid_on')
    readonly_fields = ('resolved_amount_snapshot',)


class SalePaymentInline(admin.TabularInline):
    model = SalePayment
    extra = 0


@admin.register(Sale)
class SaleAdmin(admin.ModelAdmin):
    list_display = ('id', 'purchase', 'buyer_name', 'quantity', 'unit_price', 'status', 'sold_on')
    list_filter = ('status', 'sold_on')
    search_fields = ('buyer_name', 'buyer_description')
    inlines = [SalePaymentInline]


@admin.register(SalePayment)
class SalePaymentAdmin(admin.ModelAdmin):
    list_display = ('sale', 'receiver', 'amount', 'method', 'paid_on')
    list_filter = ('method', 'paid_on')


@admin.register(SystemSettings)
class SystemSettingsAdmin(admin.ModelAdmin):
    list_display = ('distribution_mode',)
    
    def has_add_permission(self, request):
        return not SystemSettings.objects.exists()
    
    def has_delete_permission(self, request, obj=None):
        return False
