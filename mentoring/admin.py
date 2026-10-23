from django.contrib import admin

from core.admin import SuperuserAdmin
from .models import MentorExpertise, MentorSlot


@admin.register(MentorExpertise)
class MentorExpertiseAdmin(SuperuserAdmin):
    list_display = ('user', 'skill', 'level')
    list_filter = ('skill__category', 'level')
    search_fields = ('user__username', 'user__first_name', 'user__last_name', 'skill__name')


@admin.register(MentorSlot)
class MentorSlotAdmin(SuperuserAdmin):
    list_display = ('mentor', 'hackathon', 'start', 'end', 'status')
    list_filter = ('status', 'hackathon')
    search_fields = ('mentor__username', 'hackathon__title')
    date_hierarchy = 'start'
