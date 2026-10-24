"""Technical inspection only: business mutations use the same services as the site."""
from django.contrib import admin, messages
from django.core.exceptions import ValidationError, PermissionDenied
from django.utils.html import format_html
from django.utils.translation import gettext_lazy as _
from core.admin import SuperuserAdmin
from .models import Registration, Team, TeamMembership, TeamInvitation, JoinRequest, TeamSkillNeed, TeamHistory
from . import services


class InspectAdmin(SuperuserAdmin):
    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(Registration)
class RegistrationAdmin(InspectAdmin):
    list_display = ['user', 'hackathon', 'status', 'created_at']
    list_filter = ['hackathon', 'status']
    search_fields = ['user__username', 'user__first_name', 'user__last_name']
    actions = ['cancel_selected']

    @admin.action(description=_('Annuler les inscriptions sélectionnées (règles M2)'))
    def cancel_selected(self, request, queryset):
        for reg in queryset.select_related('user', 'hackathon'):
            try:
                services.cancel_registration(actor=request.user, registration=reg)
            except (ValidationError, PermissionDenied) as exc:
                self.message_user(request, f'{reg}: {" ".join(exc.messages) if isinstance(exc, ValidationError) else str(exc)}', messages.ERROR)
            else:
                self.message_user(request, _('Inscription annulée.'))


@admin.register(Team)
class TeamAdmin(InspectAdmin):
    list_display = ['name', 'hackathon', 'captain', 'recruiting', 'closed_at', 'workspace']
    list_filter = ['hackathon', 'recruiting']
    search_fields = ['name', 'description']

    @admin.display(description=_('Gestion'))
    def workspace(self, obj):
        return format_html('<a href="{}">{}</a>', obj.get_absolute_url(), _('Ouvrir l’équipe'))


@admin.register(TeamMembership)
class MembershipAdmin(InspectAdmin):
    list_display = ['registration', 'team', 'joined_at', 'ended_at']
    list_filter = ['team__hackathon', 'ended_at']
    search_fields = ['registration__user__username', 'team__name']


class RecruitmentAdmin(InspectAdmin):
    list_display = ['team', 'registration', 'status', 'created_at', 'decided_by']
    list_filter = ['team__hackathon', 'status']
    search_fields = ['team__name', 'registration__user__username']


admin.site.register(TeamInvitation, RecruitmentAdmin)
admin.site.register(JoinRequest, RecruitmentAdmin)


@admin.register(TeamSkillNeed)
class NeedAdmin(InspectAdmin):
    list_display = ['team', 'skill', 'level', 'priority']
    list_filter = ['team__hackathon', 'priority']
    search_fields = ['team__name', 'skill__name']


@admin.register(TeamHistory)
class HistoryAdmin(InspectAdmin):
    list_display = ['hackathon', 'team', 'action', 'actor', 'timestamp']
    list_filter = ['hackathon', 'action']
    search_fields = ['team__name', 'actor__username']
