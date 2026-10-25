from django.urls import path

from . import views

app_name = 'mentoring'
urlpatterns = [
    path('', views.MentoringEntryView.as_view(), name='hub'),
    path('expertise/', views.ExpertiseListView.as_view(), name='expertise-list'),
    path('expertise/add/', views.ExpertiseCreateView.as_view(), name='expertise-add'),
    path('expertise/<int:pk>/edit/', views.ExpertiseUpdateView.as_view(), name='expertise-edit'),
    path('expertise/<int:pk>/delete/', views.ExpertiseDeleteView.as_view(), name='expertise-delete'),
    path('slots/', views.SlotListView.as_view(), name='slot-list'),
    path('slots/add/', views.SlotCreateView.as_view(), name='slot-add'),
    path('slots/<int:pk>/edit/', views.SlotUpdateView.as_view(), name='slot-edit'),
    path('slots/<int:pk>/cancel/', views.SlotCancelView.as_view(), name='slot-cancel'),
    path('support/', views.SupportListView.as_view(), name='support-list'),
    path('support/new/', views.SupportCreateView.as_view(), name='support-new'),
    path('support/<int:pk>/', views.SupportDetailView.as_view(), name='support-detail'),
    path('support/<int:pk>/cancel/', views.SupportCancelView.as_view(), name='support-cancel'),
    path('support/<int:pk>/book/', views.SupportBookView.as_view(), name='support-book'),
    path('support/<int:pk>/book/<int:slot_pk>/', views.SupportBookSlotView.as_view(), name='support-book-slot'),
    path('appointments/', views.AppointmentsView.as_view(), name='appointments'),
    path('sessions/<int:pk>/', views.SessionDetailView.as_view(), name='session-detail'),
    path('sessions/<int:pk>/cancel/', views.SessionCancelView.as_view(), name='session-cancel'),
    path('workshops/', views.WorkshopListView.as_view(), name='workshop-list'),
    path('workshops/add/', views.WorkshopCreateView.as_view(), name='workshop-add'),
    path('workshops/suggest/', views.WorkshopSuggestView.as_view(), name='workshop-suggest'),
    path('workshops/<int:pk>/', views.WorkshopDetailView.as_view(), name='workshop-detail'),
    path('workshops/<int:pk>/edit/', views.WorkshopUpdateView.as_view(), name='workshop-edit'),
    path('workshops/<int:pk>/cancel/', views.WorkshopCancelView.as_view(), name='workshop-cancel'),
    path('workshops/<int:pk>/register/', views.WorkshopRegisterView.as_view(), name='workshop-register'),
    path('workshops/<int:pk>/unregister/', views.WorkshopUnregisterView.as_view(), name='workshop-unregister'),
    path('workshops/<int:pk>/attendance/<int:registration_pk>/', views.WorkshopAttendanceView.as_view(), name='workshop-attendance'),
]
