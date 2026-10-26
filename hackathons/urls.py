from django.urls import path
from . import views
from .models import Track, Challenge, EventPhase, Sponsorship
from .forms import TrackForm, ChallengeForm, PhaseForm, SponsorshipForm, OrganizationForm

app_name = 'hackathons'
urlpatterns = [
    path('', views.HackathonListView.as_view(), name='list'),
    path('new/', views.HackathonCreateView.as_view(), name='create'),
    path('dashboard/', views.DashboardView.as_view(), name='dashboard'),
    path('compare/', views.CompareView.as_view(), name='compare'),
    path('<slug:slug>/', views.HackathonDetailView.as_view(), name='detail'),
    path('<slug:slug>/edit/', views.HackathonUpdateView.as_view(), name='edit'),
    path('<slug:slug>/manage/', views.ManageView.as_view(), name='manage'),
    path('<slug:slug>/history/', views.HistoryView.as_view(), name='history'),
    path('<slug:slug>/status/<str:target>/', views.LifecycleView.as_view(), name='status'),
    path('<slug:slug>/roles/', views.RoleManageView.as_view(), name='roles'),
    path('<slug:slug>/organizations/add/', views.OrganizationCreateView.as_view(form_class=OrganizationForm), name='organization-add'),
    path('<slug:slug>/propose/', views.SponsorProposalView.as_view(form_class=ChallengeForm), name='propose'),
    path('<slug:slug>/challenge/suggest/', views.ChallengeSuggestView.as_view(), name='challenge-suggest'),
    path('<slug:slug>/challenges/<int:pk>/<str:action>/', views.ChallengeReviewView.as_view(), name='challenge-action'),
]

for name, model, form in [('track', Track, TrackForm), ('phase', EventPhase, PhaseForm),
        ('challenge', Challenge, ChallengeForm), ('sponsorship', Sponsorship, SponsorshipForm)]:
    urlpatterns += [
        path(f'<slug:slug>/{name}/add/', views.ResourceCreateView.as_view(model=model, form_class=form), name=f'{name}-add'),
        path(f'<slug:slug>/{name}/<int:pk>/edit/', views.ResourceUpdateView.as_view(model=model, form_class=form), name=f'{name}-edit'),
        path(f'<slug:slug>/{name}/<int:pk>/delete/', views.ResourceDeleteView.as_view(model=model), name=f'{name}-delete'),
    ]
