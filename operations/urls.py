from django.urls import path

from . import views

app_name = 'operations'

urlpatterns = [
    path('', views.DashboardView.as_view(), name='dashboard'),
    # Purchases
    path('compras/', views.PurchaseListView.as_view(), name='purchase_list'),
    path('compras/nova/', views.PurchaseCreateView.as_view(), name='purchase_create'),
    path('compras/<int:pk>/', views.PurchaseDetailView.as_view(), name='purchase_detail'),
    path('compras/<int:pk>/editar/', views.PurchaseUpdateView.as_view(), name='purchase_update'),
    path('compras/<int:pk>/apagar/', views.PurchaseDeleteView.as_view(), name='purchase_delete'),
    path(
        'compras/<int:pk>/participacoes/',
        views.PurchaseContributionCreateView.as_view(),
        name='purchase_contribution_create',
    ),
    path(
        'compras/<int:pk>/participacoes/<int:contribution_pk>/apagar/',
        views.PurchaseContributionDeleteView.as_view(),
        name='purchase_contribution_delete',
    ),
    path(
        'compras/<int:pk>/custos/',
        views.AdditionalCostCreateView.as_view(),
        name='additional_cost_create',
    ),
    path(
        'compras/<int:pk>/custos/<int:cost_pk>/apagar/',
        views.AdditionalCostDeleteView.as_view(),
        name='additional_cost_delete',
    ),
    # Sales
    path('vendas/', views.SaleListView.as_view(), name='sale_list'),
    path('vendas/nova/', views.SaleCreateView.as_view(), name='sale_create'),
    path('vendas/<int:pk>/editar/', views.SaleUpdateView.as_view(), name='sale_update'),
    # Users
    path('utilizadores/', views.UserListView.as_view(), name='user_list'),
    path('utilizadores/novo/', views.UserCreateView.as_view(), name='user_create'),
    path('utilizadores/<int:pk>/editar/', views.UserUpdateView.as_view(), name='user_update'),
]
