from django.urls import path, include
from rest_framework.routers import DefaultRouter
from credits.views import (
    CreditBalanceView,
    CreditLedgerViewSet,
    CreditSummaryView,
    AdminCreditAccountsViewSet,
    AdminReversalView,
)

# --------------------------------------------------------------
# Credits URL Router Configuration
# Centralized REST endpoints for credit wallet, ledger, and administration.
# --------------------------------------------------------------

router = DefaultRouter()
router.register(r'credits/ledger', CreditLedgerViewSet, basename='credit-ledger')
router.register(r'admin/credits/accounts', AdminCreditAccountsViewSet, basename='admin-credit-accounts')

urlpatterns = [
    path('credits/balance/', CreditBalanceView.as_view(), name='credit-balance'),
    path('credits/summary/', CreditSummaryView.as_view(), name='credit-summary'),
    path('admin/credits/entries/<uuid:entry_id>/reverse/', AdminReversalView.as_view(), name='admin-credit-reversal'),
    path('', include(router.urls)),
]
