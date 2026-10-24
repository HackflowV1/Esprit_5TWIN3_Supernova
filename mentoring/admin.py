from django.contrib import admin
from django.utils.translation import gettext_lazy as _

from core.admin import SuperuserAdmin
from .models import M4History, MentoringSession, MentorExpertise, MentorSlot, SupportRequest, Workshop, WorkshopRegistration


class InspectionAdmin(SuperuserAdmin):

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False


@admin.register(MentorExpertise)
class MentorExpertiseAdmin(SuperuserAdmin):
    list_display = ('user', 'skill', 'level')
    list_filter = ('skill__category', 'level')
    search_fields = ('user__username', 'user__first_name', 'user__last_name', 'skill__name')


@admin.register(MentorSlot)
class MentorSlotAdmin(InspectionAdmin):
    list_display = ('mentor', 'hackathon', 'start', 'end', 'availability_state')
    list_filter = ('hackathon', 'withdrawn_at')
    search_fields = ('mentor__username', 'hackathon__title')
    date_hierarchy = 'start'
    list_select_related = ('mentor', 'hackathon')

    @admin.display(description=_('Disponibilité'))
    def availability_state(self, obj):
        return obj.availability_label


@admin.register(Workshop)
class WorkshopAdmin(InspectionAdmin):
    list_display = ('title', 'hackathon', 'trainer', 'start', 'capacity', 'status')
    list_filter = ('status', 'hackathon')
    search_fields = ('title', 'trainer__username', 'hackathon__title')
    date_hierarchy = 'start'


@admin.register(SupportRequest)
class SupportRequestAdmin(InspectionAdmin):
    list_display = ('subject', 'team', 'hackathon', 'priority', 'status', 'created_at')
    list_filter = ('status', 'priority', 'hackathon', 'skill')
    search_fields = ('subject', 'team__name', 'author__username')
    date_hierarchy = 'created_at'
    list_select_related = ('team', 'hackathon')


@admin.register(MentoringSession)
class MentoringSessionAdmin(InspectionAdmin):
    list_display = ('request', 'mentor_name', 'slot', 'status', 'feedback_rating')
    list_filter = ('status', 'slot__hackathon')
    search_fields = ('request__subject', 'request__team__name', 'slot__mentor__username')
    list_select_related = ('request', 'slot__mentor')

    @admin.display(description=_('Mentor'))
    def mentor_name(self, obj):
        return obj.slot.mentor


@admin.register(WorkshopRegistration)
class WorkshopRegistrationAdmin(InspectionAdmin):
    list_display = ('workshop', 'participant', 'status', 'attendance')
    list_filter = ('status', 'attendance', 'workshop__hackathon')
    search_fields = ('workshop__title', 'registration__user__username')
    list_select_related = ('workshop', 'registration__user')

    @admin.display(description=_('Participant'))
    def participant(self, obj):
        return obj.registration.user


@admin.register(M4History)
class M4HistoryAdmin(InspectionAdmin):
    list_display = ('timestamp', 'hackathon', 'actor', 'action', 'object_type', 'object_id')
    list_filter = ('action', 'object_type', 'hackathon')
    search_fields = ('actor__username', 'action')
    date_hierarchy = 'timestamp'
    list_select_related = ('hackathon', 'actor')
