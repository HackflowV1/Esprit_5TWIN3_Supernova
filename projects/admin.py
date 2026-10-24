from django.contrib import admin
from teams.admin import InspectAdmin
from .models import Project, Milestone, Submission, Deliverable, ProjectActivity


@admin.register(Project)
class ProjectAdmin(InspectAdmin):
    list_display = ['title', 'team', 'challenge', 'status', 'official_submission', 'published']
    list_filter = ['team__hackathon', 'status', 'published']
    search_fields = ['title', 'team__name', 'solution']


@admin.register(Submission)
class SubmissionAdmin(InspectAdmin):
    list_display = ['project', 'version', 'status', 'created_by', 'submitted_at']
    list_filter = ['project__team__hackathon', 'status']
    search_fields = ['project__title']


@admin.register(Milestone)
class MilestoneAdmin(InspectAdmin):
    list_display = ['title', 'project', 'state', 'progress', 'due_at']
    list_filter = ['state', 'project__team__hackathon']
    search_fields = ['title', 'project__title']


@admin.register(Deliverable)
class DeliverableAdmin(InspectAdmin):
    list_display = ['submission', 'kind', 'commit']
    list_filter = ['kind']
    search_fields = ['submission__project__title', 'commit']


@admin.register(ProjectActivity)
class ActivityAdmin(InspectAdmin):
    list_display = ['project', 'actor', 'action', 'created_at']
    list_filter = ['action', 'project__team__hackathon']
    search_fields = ['project__title', 'actor__username']
