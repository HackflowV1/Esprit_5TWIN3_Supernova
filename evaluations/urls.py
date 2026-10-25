from django.urls import path
from . import views

app_name = 'evaluations'
urlpatterns = [
    path('', views.hub, name='hub'),
    path('assignments/<int:pk>/', views.evaluate, name='evaluate'),
    path('assignments/<int:pk>/action/', views.assignment_action, name='assignment-action'),
    path('assignments/<int:pk>/files/<int:deliverable_pk>/', views.download, name='download'),
    path('<slug:slug>/', views.dashboard, name='dashboard'),
    path('<slug:slug>/rubric/', views.rubric, name='rubric'),
    path('<slug:slug>/assignments/', views.assignments, name='assignments'),
    path('<slug:slug>/anomalies/', views.anomalies, name='anomalies'),
    path('<slug:slug>/anomalies/<int:pk>/analyze/', views.analyze_divergence, name='analyze-divergence'),
    path('<slug:slug>/ranking/', views.ranking, name='ranking'),
    path('<slug:slug>/publish/<int:pk>/', views.publish, name='publish'),
    path('<slug:slug>/review/<int:pk>/', views.review, name='review'),
    path('<slug:slug>/prizes/', views.prizes, name='prizes'),
    path('<slug:slug>/results/', views.results, name='results'),
]
