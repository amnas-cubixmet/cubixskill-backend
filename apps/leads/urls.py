from django.urls import path, include
from rest_framework.routers import DefaultRouter
from leads.views import (
    PublicLeadEnquiryView,
    LeadViewSet,
    LeadFollowUpViewSet,
    LeadImportViewSet,
)

# --------------------------------------------------------------
# Leads URL Router Configuration
# Centralized API endpoints for public enquiries and CRM management.
# --------------------------------------------------------------

router = DefaultRouter()
router.register(r'leads', LeadViewSet, basename='lead')
router.register(r'lead-follow-ups', LeadFollowUpViewSet, basename='lead-follow-up')

urlpatterns = [
    path('public/academies/<slug:academy_slug>/enquiries/', PublicLeadEnquiryView.as_view(), name='public-lead-enquiry'),
    path('leads/import/', LeadImportViewSet.as_view(), name='lead-import'),
    path('', include(router.urls)),
]
