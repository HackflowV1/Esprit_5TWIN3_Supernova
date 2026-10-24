from teams.models import Team
from . import services
from .permissions import is_mentor


def mentor_menu(request):
    """Expose `is_mentor` everywhere, and what the module tabs need to show only the user's own role."""
    user = request.user
    context = {'is_mentor': is_mentor(user)}
    match = request.resolver_match
    if user.is_authenticated and match and match.app_name == 'mentoring':
        context['m4_has_team'] = Team.objects.filter(closed_at__isnull=True, memberships__ended_at__isnull=True,
            memberships__registration__user=user).exists()
        context['m4_is_organizer'] = services.organized_hackathons(user).exists()
    return context
