from django.contrib import admin, messages
from django.core.exceptions import ValidationError, PermissionDenied
from core.admin import SuperuserAdmin
from .models import Hackathon, Track, Challenge, EventPhase, SponsorOrganization, Sponsorship, EventHistory
from . import services


class TrackInline(admin.TabularInline):
    model = Track
    fields = ('name', 'active')
    readonly_fields = fields
    extra = 0
    can_delete = False

    def has_add_permission(self, request, obj=None):
        return False


class PhaseInline(TrackInline):
    model = EventPhase
    fields = ('kind', 'start', 'end')
    readonly_fields = fields


@admin.register(Hackathon)
class HackathonAdmin(SuperuserAdmin):
    list_display = ('title', 'start_date', 'end_date', 'status', 'capacity', 'created_by')
    search_fields = ('title', 'description', 'location')
    list_filter = ('status', 'format', 'start_date')
    readonly_fields = ('status', 'created_by', 'created_at', 'updated_at', 'archived_at', 'archive_metrics')
    prepopulated_fields = {'slug': ('title',)}
    inlines = [TrackInline, PhaseInline]
    fieldsets = (
        ('Événement', {'fields': ('title', 'slug', 'description', 'rules', 'participation_conditions', 'image', 'location', 'format')}),
        ('Calendrier', {'fields': ('start_date', 'end_date', 'registration_open', 'registration_close', 'submission_deadline')}),
        ('Capacités', {'fields': ('capacity', 'min_team_size', 'max_team_size')}),
        ('Cycle de vie', {'fields': readonly_fields}),
    )
    actions = ('publish', 'archive')

    def has_change_permission(self, request, obj=None):
        return super().has_change_permission(request, obj) and (obj is None or obj.status != 'ARCHIVED')

    def save_model(self, request, obj, form, change):
        if not change:
            services.create_hackathon(actor=request.user, event=obj)
        else:
            services.save_configuration(actor=request.user, event=obj)

    def run_transition(self, request, queryset, target):
        for event in queryset:
            try:
                services.transition(actor=request.user, event=event, target=target)
            except (ValidationError, PermissionDenied) as exc:
                detail = ' '.join(exc.messages) if isinstance(exc, ValidationError) else str(exc)
                self.message_user(request, f'{event}: {detail}', messages.ERROR)

    @admin.action(description='Publier après validation métier')
    def publish(self, request, queryset):
        self.run_transition(request, queryset, Hackathon.Status.PUBLISHED)

    @admin.action(description='Archiver les éditions terminées')
    def archive(self, request, queryset):
        self.run_transition(request, queryset, Hackathon.Status.ARCHIVED)


class ResourceAdmin(SuperuserAdmin):
    def has_change_permission(self, request, obj=None):
        return super().has_change_permission(request, obj) and (obj is None or obj.get_hackathon().status != 'ARCHIVED')

    def get_readonly_fields(self, request, obj=None):
        fields = super().get_readonly_fields(request, obj)
        if not obj:
            return fields
        parent_fields = ('track',) if isinstance(obj, Challenge) else ('hackathon',)
        if isinstance(obj, Sponsorship):
            parent_fields += ('organization',)
        return tuple(fields) + parent_fields

    def save_model(self, request, obj, form, change):
        if isinstance(obj, Challenge) and not change:
            obj.proposed_by = request.user
        services.save_resource(actor=request.user, resource=obj, action='Administration')


@admin.register(Track)
class TrackAdmin(ResourceAdmin):
    list_display = ('name', 'hackathon', 'active')
    search_fields = ('name', 'hackathon__title')
    list_filter = ('hackathon', 'active')


@admin.register(EventPhase)
class PhaseAdmin(ResourceAdmin):
    list_display = ('hackathon', 'kind', 'start', 'end')
    list_filter = ('kind', 'hackathon')
    search_fields = ('hackathon__title',)


@admin.register(Challenge)
class ChallengeAdmin(ResourceAdmin):
    list_display = ('title', 'track', 'status', 'sponsorship')
    search_fields = ('title', 'problem', 'track__hackathon__title')
    list_filter = ('status', 'track__hackathon')
    readonly_fields = ('status', 'proposed_by', 'approved_by', 'approved_at', 'updated_at')


@admin.register(SponsorOrganization)
class OrganizationAdmin(SuperuserAdmin):
    list_display = ('name', 'sector', 'website')
    search_fields = ('name', 'sector')
    list_filter = ('sector',)


@admin.register(Sponsorship)
class SponsorshipAdmin(ResourceAdmin):
    list_display = ('organization', 'hackathon', 'status', 'estimated_value', 'confirmed_at')
    list_filter = ('status', 'hackathon')
    search_fields = ('organization__name', 'hackathon__title')
    readonly_fields = ('confirmed_at',)


@admin.register(EventHistory)
class HistoryAdmin(SuperuserAdmin):
    list_display = ('hackathon', 'actor', 'action', 'target', 'timestamp')
    list_filter = ('hackathon', 'action')
    search_fields = ('target', 'actor__username')

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False
