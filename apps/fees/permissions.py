from core.permissions import CanAccessAcademyPermission


class CanManageCourseFees(CanAccessAcademyPermission):
    """
    Permission check for configuring, collecting, waiving, or viewing student course fee accounts.
    Requires user to belong to the active Academy context.
    """
