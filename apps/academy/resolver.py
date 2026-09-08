import logging

from academy.models import Academy
from django.core.exceptions import ValidationError

logger = logging.getLogger(__name__)

def resolve_academy(academy_identifier):
    """
    Safely resolves an Academy instance using primary key (pk / id) or slug.
    Prevents 500 Internal Server Errors when an invalid UUID string or identifier is provided.
    """
    if not academy_identifier:
        return None

    if isinstance(academy_identifier, Academy):
        return academy_identifier

    # 1. Try lookup by primary key (id / pk)
    try:
        academy = Academy.objects.filter(pk=academy_identifier).first()
        if academy:
            return academy
    except (ValidationError, ValueError, TypeError, Exception) as e:
        logger.debug(f"Academy lookup by pk failed for '{academy_identifier}': {e}")

    # 2. Try lookup by slug
    try:
        academy = Academy.objects.filter(slug=academy_identifier).first()
        if academy:
            return academy
    except (ValidationError, ValueError, TypeError, Exception) as e:
        logger.debug(f"Academy lookup by slug failed for '{academy_identifier}': {e}")

    return None
