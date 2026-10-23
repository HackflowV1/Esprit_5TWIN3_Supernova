from django.urls import path

from . import views

app_name = 'mentoring'
urlpatterns = [
    path('expertise/', views.ExpertiseListView.as_view(), name='expertise-list'),
    path('expertise/add/', views.ExpertiseCreateView.as_view(), name='expertise-add'),
    path('expertise/<int:pk>/edit/', views.ExpertiseUpdateView.as_view(), name='expertise-edit'),
    path('expertise/<int:pk>/delete/', views.ExpertiseDeleteView.as_view(), name='expertise-delete'),
]
