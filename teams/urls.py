from django.urls import path
from . import views

app_name = 'teams'
urlpatterns = [
    path('', views.mine, name='mine'),
    path('<slug:slug>/register/', views.register, name='register'),
    path('<slug:slug>/registrations/<int:pk>/cancel/', views.cancel, name='cancel'),
    path('<slug:slug>/teams/', views.listing, name='list'),
    path('<slug:slug>/teams/create/', views.create, name='create'),
    path('<slug:slug>/inbox/', views.inbox, name='inbox'),
    path('<slug:slug>/manage/', views.manage, name='manage'),
    path('<slug:slug>/teams/<int:pk>/', views.detail, name='detail'),
    path('<slug:slug>/teams/<int:pk>/edit/', views.edit, name='edit'),
    path('<slug:slug>/teams/<int:pk>/apply/', views.apply, name='apply'),
    path('<slug:slug>/teams/<int:pk>/invite/', views.invite, name='invite'),
    path('<slug:slug>/teams/<int:pk>/candidates/', views.candidates, name='candidates'),
    path('<slug:slug>/teams/<int:pk>/members/<int:member_pk>/<str:action>/', views.member_action, name='member-action'),
    path('<slug:slug>/teams/<int:pk>/needs/add/', views.need_edit, name='need-add'),
    path('<slug:slug>/teams/<int:pk>/needs/<int:need_pk>/edit/', views.need_edit, name='need-edit'),
    path('<slug:slug>/teams/<int:pk>/needs/<int:need_pk>/delete/', views.need_delete, name='need-delete'),
    path('<slug:slug>/requests/<str:kind>/<int:pk>/<str:decision>/', views.decide, name='decide'),
]
