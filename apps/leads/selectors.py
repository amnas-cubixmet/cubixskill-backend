from django.db.models import Q, QuerySet
from django.utils import timezone
from leads.models import (
    FollowUpStatus,
    Lead,
    LeadFollowUp,
    LeadStatus,
)

# --------------------------------------------------------------
# Lead Selectors
# Optimized Academy-scoped queries for CRM lists, timelines, and dashboards.
# Database aggregation is used to prevent N+1 queries on CRM dashboards.
# --------------------------------------------------------------

class LeadSelector:

    @classmethod
    def get_academy_leads(
        cls,
        academy,
        status: str = None,
        priority: str = None,
        source: str = None,
        assigned_to_id: str = None,
        course_id: str = None,
        search: str = None,
        follow_up_due_today: bool = False
    ) -> QuerySet[Lead]:
        """
        Retrieves Academy-scoped leads with filtering, search, and prefetching.
        """
        queryset = Lead.objects.filter(academy=academy).select_related(
            'assigned_to', 'converted_user', 'converted_student'
        ).prefetch_related('course_interests', 'course_interests__course', 'tags')

        if status:
            queryset = queryset.filter(status=status)
        if priority:
            queryset = queryset.filter(priority=priority)
        if source:
            queryset = queryset.filter(source=source)
        if assigned_to_id:
            queryset = queryset.filter(assigned_to_id=assigned_to_id)
        if course_id:
            queryset = queryset.filter(course_interests__course_id=course_id)

        if search:
            queryset = queryset.filter(
                Q(full_name__icontains=search) |
                Q(email__icontains=search) |
                Q(phone__icontains=search)
            )

        if follow_up_due_today:
            now = timezone.now()
            today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
            today_end = today_start + timezone.timedelta(days=1)
            queryset = queryset.filter(next_follow_up_at__range=(today_start, today_end))

        return queryset.distinct().order_by('-created_at')

    @classmethod
    def get_lead_timeline(cls, lead: Lead) -> list[dict]:
        """
        Builds a unified chronological timeline for a Lead combining activities, follow-ups, notes, and assignments.
        """
        timeline = []

        # 1. Activities
        for act in lead.activities.all():
            timeline.append({
                'type': 'ACTIVITY',
                'event': act.activity_type,
                'timestamp': act.occurred_at,
                'performed_by': act.performed_by.full_name if act.performed_by else 'System',
                'details': act.metadata
            })

        # 2. Follow-ups
        for fu in lead.follow_ups.all():
            timeline.append({
                'type': 'FOLLOW_UP',
                'event': f"Follow-up ({fu.follow_up_type})",
                'timestamp': fu.scheduled_at,
                'status': fu.status,
                'outcome': fu.outcome,
                'notes': fu.notes,
                'assigned_to': fu.assigned_to.full_name if fu.assigned_to else None
            })

        # 3. Notes
        for n in lead.notes.all():
            timeline.append({
                'type': 'NOTE',
                'event': 'Internal Note',
                'timestamp': n.created_at,
                'author': n.author.full_name if n.author else 'Staff',
                'content': n.content,
                'is_pinned': n.is_pinned
            })

        # Sort timeline by timestamp descending
        timeline.sort(key=lambda x: x['timestamp'], reverse=True)
        return timeline

    @classmethod
    def get_dashboard_metrics(cls, academy) -> dict:
        """
        Calculates efficient dashboard summary metrics for an Academy's leads pipeline.
        """
        now = timezone.now()
        today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        today_end = today_start + timezone.timedelta(days=1)

        total_leads = Lead.objects.filter(academy=academy).count()
        new_leads = Lead.objects.filter(academy=academy, status=LeadStatus.NEW).count()
        interested = Lead.objects.filter(academy=academy, status=LeadStatus.INTERESTED).count()
        qualified = Lead.objects.filter(academy=academy, status=LeadStatus.QUALIFIED).count()
        converted = Lead.objects.filter(academy=academy, status=LeadStatus.CONVERTED).count()
        lost = Lead.objects.filter(academy=academy, status=LeadStatus.LOST).count()

        follow_ups_today = LeadFollowUp.objects.filter(
            lead__academy=academy,
            status=FollowUpStatus.PENDING,
            scheduled_at__range=(today_start, today_end)
        ).count()

        overdue_follow_ups = LeadFollowUp.objects.filter(
            lead__academy=academy,
            status=FollowUpStatus.PENDING,
            scheduled_at__lt=now
        ).count()

        return {
            'total_leads': total_leads,
            'new_leads': new_leads,
            'interested': interested,
            'qualified': qualified,
            'converted': converted,
            'lost': lost,
            'follow_ups_today': follow_ups_today,
            'overdue_follow_ups': overdue_follow_ups,
        }
