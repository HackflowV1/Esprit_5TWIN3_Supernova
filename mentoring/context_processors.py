from .permissions import is_mentor


def mentor_menu(request):
    """Expose `is_mentor` to templates so the navigation can show the mentor space."""
    return {'is_mentor': is_mentor(request.user)}
