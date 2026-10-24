from django.urls import path
from . import views

app_name = 'projects'
urlpatterns = [
    path('', views.mine, name='mine'),
    path('gallery/', views.gallery, name='gallery'),
    path('gallery/<int:pk>/', views.public_detail, name='public'),
    path('teams/<int:team_pk>/create/', views.edit, name='create'),
    path('files/<int:deliverable_pk>/', views.download, name='download'),
    path('<int:pk>/', views.detail, name='detail'),
    path('<int:pk>/edit/', views.edit, name='edit'),
    path('<int:pk>/milestones/add/', views.milestone, name='milestone-add'),
    path('<int:pk>/milestones/<int:milestone_pk>/edit/', views.milestone, name='milestone-edit'),
    path('<int:pk>/milestones/<int:milestone_pk>/delete/', views.milestone_delete, name='milestone-delete'),
    path('<int:pk>/milestones/<int:milestone_pk>/move/', views.milestone_move, name='milestone-move'),
    path('<int:pk>/versions/create/', views.version_create, name='version-create'),
    path('<int:pk>/versions/<int:version>/', views.version, name='version'),
    path('<int:pk>/versions/<int:version>/submit/', views.submit, name='submit'),
    path('<int:pk>/versions/<int:version>/delete/', views.draft_delete, name='draft-delete'),
    path('<int:pk>/versions/<int:version>/restore/', views.draft_restore, name='draft-restore'),
    path('<int:pk>/versions/<int:version>/files/<int:deliverable_pk>/delete/', views.deliverable_delete, name='deliverable-delete'),
    path('<int:pk>/versions/<int:version>/files/<int:deliverable_pk>/edit/', views.deliverable_edit, name='deliverable-edit'),
    path('<int:pk>/reopen/', views.reopen, name='reopen'),
    path('<int:pk>/publication/<str:action>/', views.publication, name='publication'),
]
