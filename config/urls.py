"""
URL configuration for HackFlow project.
"""
from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static
from django.views.static import serve
from django.http import JsonResponse

urlpatterns = [
    path('healthz/', lambda request: JsonResponse({'status': 'ok'})),
    path('i18n/', include('django.conf.urls.i18n')),
    path('admin/', admin.site.urls),
    path('accounts/', include('accounts.urls')),
    path('hackathons/', include('hackathons.urls')),
    path('participation/', include('teams.urls')),
    path('mentoring/', include('mentoring.urls')),
    path('evaluations/', include('evaluations.urls')),
    path('projects/', include('projects.urls')),
    path('', include('core.urls')),
]

# Serve media files in development
if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
elif getattr(settings, 'RENDER_DEMO_MODE', False):
    urlpatterns += [path('media/<path:path>', serve, {'document_root': settings.MEDIA_ROOT})]
