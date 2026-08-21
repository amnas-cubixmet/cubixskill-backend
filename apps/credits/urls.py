from django.urls import path, include
from rest_framework.routers import DefaultRouter
from credits.views import (
    CreditBalanceView,
    CreditLedgerViewSet,
    CreditSummaryView,
    CreditUsageView,
    CreditPackageListView,
    CreditPurchaseViewSet,
    AdminCreditAccountsViewSet,
    AdminCreditRateViewSet,
    AdminCreditPackageViewSet,
    AdminCreditCouponViewSet,
    AdminReversalView,
)

router = DefaultRouter()
router.register(r'ledger', CreditLedgerViewSet, basename='credit-ledger')
router.register(r'transactions', CreditLedgerViewSet, basename='credit-transactions')
router.register(r'purchases', CreditPurchaseViewSet, basename='credit-purchases')
router.register(r'admin/accounts', AdminCreditAccountsViewSet, basename='admin-credit-accounts')
router.register(r'admin/rates', AdminCreditRateViewSet, basename='admin-credit-rates')
router.register(r'admin/packages', AdminCreditPackageViewSet, basename='admin-credit-packages')
router.register(r'admin/coupons', AdminCreditCouponViewSet, basename='admin-credit-coupons')

urlpatterns = [
    path('balance/', CreditBalanceView.as_view(), name='credit-balance'),
    path('summary/', CreditSummaryView.as_view(), name='credit-summary'),
    path('usage/', CreditUsageView.as_view(), name='credit-usage'),
    path('packages/', CreditPackageListView.as_view(), name='credit-packages-list'),
    path('admin/entries/<uuid:entry_id>/reverse/', AdminReversalView.as_view(), name='admin-credit-reversal'),
    path('', include(router.urls)),
]
