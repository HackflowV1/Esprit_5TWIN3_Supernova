"""
accounts/admin.py
"""
from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from django.contrib.auth.admin import GroupAdmin
from django.contrib.auth.models import Group
from .models import User
from .models import Profile, Skill, UserSkill, RoleAssignment, RoleAssignmentHistory, SponsorMembership
from .services import set_role
from core.admin import SuperuserAdmin

admin.site.unregister(Group)


@admin.register(Group)
class TechnicalGroupAdmin(SuperuserAdmin, GroupAdmin):
    pass


@admin.register(User)
class CustomUserAdmin(SuperuserAdmin, UserAdmin):
    """Administration du modèle User personnalisé."""
    search_fields = ('username', 'first_name', 'last_name', 'email')


class ProfileInline(admin.TabularInline):
    model = Profile
    extra = 0


class UserSkillInline(admin.TabularInline):
    model = UserSkill
    extra = 0


CustomUserAdmin.inlines = [ProfileInline, UserSkillInline]


@admin.register(Skill)
class SkillAdmin(SuperuserAdmin):
    list_display = ('name', 'category')
    search_fields = ('name', 'category')
    list_filter = ('category',)


@admin.register(RoleAssignment)
class RoleAdmin(SuperuserAdmin):
    list_display = ('user', 'hackathon', 'role', 'status', 'assigned_at', 'assigned_by')
    list_filter = ('role', 'status', 'hackathon')
    search_fields = ('user__username', 'hackathon__title')
    readonly_fields = ('assigned_at', 'updated_at', 'assigned_by')

    def get_readonly_fields(self, request, obj=None):
        return self.readonly_fields + (('user', 'hackathon', 'role') if obj else ())

    def save_model(self, request, obj, form, change):
        saved = set_role(actor=request.user, user=obj.user, hackathon=obj.hackathon, role=obj.role, status=obj.status)
        obj.pk = saved.pk


@admin.register(SponsorMembership)
class MembershipAdmin(SuperuserAdmin):
    list_display = ('user', 'organization', 'status', 'can_propose_challenges')
    search_fields = ('user__username', 'organization__name')
    list_filter = ('status', 'can_propose_challenges')


@admin.register(RoleAssignmentHistory)
class RoleHistoryAdmin(SuperuserAdmin):
    list_display = ('assignment', 'actor', 'previous_status', 'status', 'timestamp')

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False
