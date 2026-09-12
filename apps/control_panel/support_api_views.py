import uuid
import random
import string
from django.db import transaction
from django.db.models import Q
from django.shortcuts import get_object_or_404
from django.http import Http404
from rest_framework import viewsets, status, permissions
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.pagination import PageNumberPagination

from control_panel.models import SupportTicket, TicketMessage, TicketAttachment, TicketStatus, TicketPriority
from control_panel.support_serializers import (
    SupportTicketListSerializer,
    SupportTicketDetailSerializer,
    SupportTicketCreateSerializer,
    TicketReplyCreateSerializer,
    TicketMessageSerializer,
)
from storage.models import MediaFile
from audit_logs.models import AuditLog, AuditAction


class StandardResultsSetPagination(PageNumberPagination):
    page_size = 10
    page_size_query_param = 'page_size'
    max_page_size = 100


class SupportTicketViewSet(viewsets.ModelViewSet):
    permission_classes = [permissions.IsAuthenticated]
    pagination_class = StandardResultsSetPagination

    def get_queryset(self):
        user = self.request.user
        qs = SupportTicket.objects.select_related('academy', 'user', 'assigned_to').prefetch_related(
            'messages__sender', 'messages__attachments', 'attachments'
        ).all()

        # Central support / Superusers see all tickets. Academy users see only their academy tickets.
        if not (user.is_superuser or getattr(user, 'is_central_support', False)):
            if getattr(user, 'academy', None):
                qs = qs.filter(academy=user.academy)
            else:
                qs = qs.filter(user=user)

        # Filters (only applied during list queries, not single ticket detail lookup)
        if getattr(self, 'action', None) == 'list':
            search = self.request.query_params.get('search', '').strip()
            if search:
                qs = qs.filter(
                    Q(subject__icontains=search) |
                    Q(ticket_number__icontains=search) |
                    Q(category__icontains=search) |
                    Q(messages__message__icontains=search)
                ).distinct()

            ticket_status = self.request.query_params.get('status', '').strip()
            if ticket_status and ticket_status.upper() != 'ALL':
                qs = qs.filter(status=ticket_status.upper())

            priority = self.request.query_params.get('priority', '').strip()
            if priority and priority.upper() != 'ALL':
                qs = qs.filter(priority=priority.upper())

            category = self.request.query_params.get('category', '').strip()
            if category and category.upper() != 'ALL':
                qs = qs.filter(category__iexact=category)

        return qs.order_by('-updated_at', '-created_at')

    def get_serializer_class(self):
        if self.action == 'list':
            return SupportTicketListSerializer
        elif self.action == 'create':
            return SupportTicketCreateSerializer
        return SupportTicketDetailSerializer

    def get_object(self):
        queryset = self.get_queryset()
        lookup_url_kwarg = self.lookup_url_kwarg or self.lookup_field or 'pk'
        identifier = self.kwargs.get(lookup_url_kwarg)

        if not identifier:
            raise Http404("No ticket identifier provided.")

        clean_id = str(identifier).strip()

        is_uuid = False
        try:
            uuid_obj = uuid.UUID(clean_id)
            is_uuid = True
        except (ValueError, AttributeError, TypeError):
            is_uuid = False

        if is_uuid:
            obj = get_object_or_404(queryset, id=uuid_obj)
        else:
            obj = get_object_or_404(queryset, ticket_number=clean_id)

        self.check_object_permissions(self.request, obj)
        return obj

    def list(self, request, *args, **kwargs):
        queryset = self.filter_queryset(self.get_queryset())
        page = self.paginate_queryset(queryset)
        if page is not None:
            serializer = SupportTicketListSerializer(page, many=True, context={'request': request})
            return self.get_paginated_response(serializer.data)
        serializer = SupportTicketListSerializer(queryset, many=True, context={'request': request})
        return Response(serializer.data)

    def create(self, request, *args, **kwargs):
        serializer = SupportTicketCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        user = request.user
        academy = getattr(user, 'academy', None)

        with transaction.atomic():
            # Generate unique ticket number
            ticket_number = f"SUP-{''.join(random.choices(string.digits, k=4))}"
            while SupportTicket.objects.filter(ticket_number=ticket_number).exists():
                ticket_number = f"SUP-{''.join(random.choices(string.digits, k=4))}"

            ticket = SupportTicket.objects.create(
                ticket_number=ticket_number,
                academy=academy,
                user=user,
                subject=data['subject'],
                category=data.get('category', 'GENERAL'),
                priority=data.get('priority', TicketPriority.MEDIUM),
                status=TicketStatus.OPEN,
            )

            # Create initial message
            msg = TicketMessage.objects.create(
                ticket=ticket,
                sender=user,
                is_internal_note=False,
                message=data['description'],
            )

            # Attach media files if provided
            attachment_ids = data.get('attachment_ids', [])
            for att_id in attachment_ids:
                try:
                    media_file = MediaFile.objects.get(id=att_id)
                    TicketAttachment.objects.create(
                        ticket=ticket,
                        message=msg,
                        media_file=media_file,
                        file_name=media_file.original_filename or "attachment",
                        file_url=media_file.file_url,
                        file_size=media_file.size_bytes or 0,
                    )
                except (MediaFile.DoesNotExist, ValueError):
                    pass

            # Log Audit Trail
            AuditLog.objects.create(
                actor=user,
                academy=academy,
                action=AuditAction.TICKET_CREATED,
                target_type='SupportTicket',
                target_id=str(ticket.id),
                description=f"Created support ticket {ticket.ticket_number}: {ticket.subject}"
            )

        output_serializer = SupportTicketDetailSerializer(ticket, context={'request': request})
        return Response(output_serializer.data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=['post'])
    def reply(self, request, pk=None):
        ticket = self.get_object()
        serializer = TicketReplyCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        user = request.user
        is_central = user.is_superuser or getattr(user, 'is_central_support', False)
        is_internal_note = data.get('is_internal_note', False)

        # Enforce that only central support can leave internal notes
        if is_internal_note and not is_central:
            return Response(
                {"detail": "Only central support team members can add internal notes."},
                status=status.HTTP_403_FORBIDDEN
            )

        with transaction.atomic():
            msg = TicketMessage.objects.create(
                ticket=ticket,
                sender=user,
                is_internal_note=is_internal_note,
                message=data['message'],
            )

            # If ticket was closed/resolved and reply comes in from customer, re-open ticket
            if not is_internal_note and ticket.status in [TicketStatus.CLOSED, TicketStatus.RESOLVED]:
                ticket.status = TicketStatus.IN_PROGRESS
                ticket.save(update_fields=['status', 'updated_at'])
            else:
                ticket.touch() if hasattr(ticket, 'touch') else ticket.save(update_fields=['updated_at'])

            # Attach media files if provided
            attachment_ids = data.get('attachment_ids', [])
            for att_id in attachment_ids:
                try:
                    media_file = MediaFile.objects.get(id=att_id)
                    TicketAttachment.objects.create(
                        ticket=ticket,
                        message=msg,
                        media_file=media_file,
                        file_name=media_file.original_filename or "attachment",
                        file_url=media_file.file_url,
                        file_size=media_file.size_bytes or 0,
                    )
                except (MediaFile.DoesNotExist, ValueError):
                    pass

            AuditLog.objects.create(
                actor=user,
                academy=ticket.academy,
                action=AuditAction.TICKET_REPLIED,
                target_type='SupportTicket',
                target_id=str(ticket.id),
                description=f"Added {'internal note' if is_internal_note else 'reply'} on {ticket.ticket_number}"
            )

        return Response(
            TicketMessageSerializer(msg, context={'request': request}).data,
            status=status.HTTP_201_CREATED
        )

    @action(detail=True, methods=['patch'])
    def status(self, request, pk=None):
        ticket = self.get_object()
        new_status = request.data.get('status')
        new_priority = request.data.get('priority')

        updated_fields = []
        if new_status:
            valid_statuses = [choice[0] for choice in TicketStatus.choices]
            if new_status.upper() not in valid_statuses:
                return Response(
                    {"detail": f"Invalid status. Allowed values: {valid_statuses}"},
                    status=status.HTTP_400_BAD_REQUEST
                )
            ticket.status = new_status.upper()
            updated_fields.append('status')

        if new_priority:
            valid_priorities = [choice[0] for choice in TicketPriority.choices]
            if new_priority.upper() not in valid_priorities:
                return Response(
                    {"detail": f"Invalid priority. Allowed values: {valid_priorities}"},
                    status=status.HTTP_400_BAD_REQUEST
                )
            ticket.priority = new_priority.upper()
            updated_fields.append('priority')

        if updated_fields:
            updated_fields.append('updated_at')
            ticket.save(update_fields=updated_fields)

            AuditLog.objects.create(
                actor=request.user,
                academy=ticket.academy,
                action=AuditAction.TICKET_UPDATED,
                target_type='SupportTicket',
                target_id=str(ticket.id),
                description=f"Updated ticket {ticket.ticket_number} ({', '.join(updated_fields)})"
            )

        return Response(SupportTicketDetailSerializer(ticket, context={'request': request}).data)
