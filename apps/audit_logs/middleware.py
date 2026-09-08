import uuid
from dataclasses import dataclass


@dataclass
class AuditRequestContext:
    request_id: str
    ip_address: str
    user_agent: str

# --------------------------------------------------------------
# Request Context Middleware for Audit Logging
# Record trusted request context (request_id, IP address, user_agent) where available.
# Attaches request.audit_context for consumption by domain audit services.
# AuditLog should not duplicate every normal application event.
# Audit creation should not break the main business transaction unnecessarily.
# --------------------------------------------------------------


class AuditContextMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        request_id = request.headers.get('X-Request-ID') or str(uuid.uuid4())
        
        # IP Address extraction with proxy header handling
        x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
        if x_forwarded_for:
            ip_address = x_forwarded_for.split(',')[0].strip()
        else:
            ip_address = request.META.get('REMOTE_ADDR', '')

        user_agent = request.META.get('HTTP_USER_AGENT', '')[:500]

        request.audit_context = AuditRequestContext(
            request_id=request_id,
            ip_address=ip_address,
            user_agent=user_agent
        )

        response = self.get_response(request)
        response['X-Request-ID'] = request_id
        return response
