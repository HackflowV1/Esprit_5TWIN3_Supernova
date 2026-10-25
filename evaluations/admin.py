"""Admin is deliberately read-only: business writes use audited, scoped pages."""
from django.contrib import admin
from . import models


class ReadOnlyAdmin(admin.ModelAdmin):
    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


for model in (models.EvaluationCampaign, models.EvaluationCriterion, models.JuryAssignment,
              models.Evaluation, models.CriterionScore, models.ReviewHistory,
              models.ResultPublication, models.Prize, models.Award):
    admin.site.register(model, ReadOnlyAdmin)
