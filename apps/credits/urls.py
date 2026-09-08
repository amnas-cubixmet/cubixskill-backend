from credits.views import (
    AdminCreditAccountsViewSet,
    AdminCreditCouponViewSet,
    AdminCreditPackageViewSet,
    AdminCreditRateViewSet,
    AdminReversalView,
    CreditActivateUsageView,
    CreditBalanceView,
    CreditLedgerViewSet,
    CreditPackageListView,
    CreditPurchaseRatesView,
    CreditPurchaseViewSet,
    CreditSummaryView,
    CreditUsagePreviewView,
    CreditUsageView,
    MonthlyInvoicesViewSet,
    StorageSummaryView,
)
from django.urls import include, path
from rest_framework.routers import DefaultRouter

router = DefaultRouter()
router.register(r'ledger', CreditLedgerViewSet, basename='credit-ledger')
router.register(r'transactions', CreditLedgerViewSet, basename='credit-transactions')
router.register(r'purchases', CreditPurchaseViewSet, basename='credit-purchases')
router.register(r'monthly/invoices', MonthlyInvoicesViewSet, basename='monthly-invoices')
router.register(r'admin/accounts', AdminCreditAccountsViewSet, basename='admin-credit-accounts')
router.register(r'admin/rates', AdminCreditRateViewSet, basename='admin-credit-rates')
router.register(r'admin/packages', AdminCreditPackageViewSet, basename='admin-credit-packages')
router.register(r'admin/coupons', AdminCreditCouponViewSet, basename='admin-credit-coupons')

urlpatterns = [
    path('balance/', CreditBalanceView.as_view(), name='credit-balance'),
    path('summary/', CreditSummaryView.as_view(), name='credit-summary'),
    path('usage/', CreditUsageView.as_view(), name='credit-usage'),
    path('usage-preview/', CreditUsagePreviewView.as_view(), name='credit-usage-preview'),
    path('activate-usage/', CreditActivateUsageView.as_view(), name='credit-activate-usage'),
    path('purchase-rates/', CreditPurchaseRatesView.as_view(), name='credit-purchase-rates'),
    path('packages/', CreditPackageListView.as_view(), name='credit-packages-list'),
    path('storage/summary/', StorageSummaryView.as_view(), name='storage-summary'),
    path('admin/entries/<uuid:entry_id>/reverse/', AdminReversalView.as_view(), name='admin-credit-reversal'),
    path('', include(router.urls)),
]

