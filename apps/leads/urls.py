from django.urls import include, path
from leads.views import (
    DemoLeadCreateView,
    LeadFollowUpViewSet,
    LeadImportViewSet,
    LeadViewSet,
    PublicLeadEnquiryView,
)
from rest_framework.routers import DefaultRouter

router = DefaultRouter()
router.register(r'leads', LeadViewSet, basename='lead')
router.register(r'lead-follow-ups', LeadFollowUpViewSet, basename='lead-follow-up')

urlpatterns = [
    path('public/academies/<slug:academy_slug>/enquiries/', PublicLeadEnquiryView.as_view(), name='public-lead-enquiry'),
    path('demo-leads/', DemoLeadCreateView.as_view(), name='demo-lead-create'),
    path('leads/import/', LeadImportViewSet.as_view(), name='lead-import'),
    path('', include(router.urls)),
]
