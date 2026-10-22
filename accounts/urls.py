from django.urls import path, reverse_lazy
from django.contrib.auth import views as auth
from . import views

app_name = 'accounts'
urlpatterns = [
    path('signup/', views.SignupView.as_view(), name='signup'),
    path('login/', auth.LoginView.as_view(template_name='shared/form.html', extra_context={'title': 'Connexion', 'button_label': 'Se connecter'}), name='login'),
    path('logout/', auth.LogoutView.as_view(), name='logout'),
    path('profile/', views.ProfileView.as_view(), name='profile'),
    path('profile/edit/', views.ProfileUpdateView.as_view(), name='profile-edit'),
    path('password/', auth.PasswordChangeView.as_view(template_name='shared/form.html',
        success_url=reverse_lazy('accounts:password-done'), extra_context={'title': 'Changer mon mot de passe'}), name='password'),
    path('password/done/', auth.PasswordChangeDoneView.as_view(template_name='accounts/password_done.html'), name='password-done'),
    path('skills/add/', views.SkillCreateView.as_view(), name='skill-add'),
    path('skills/<int:pk>/edit/', views.SkillUpdateView.as_view(), name='skill-edit'),
    path('skills/<int:pk>/delete/', views.SkillDeleteView.as_view(), name='skill-delete'),
]
