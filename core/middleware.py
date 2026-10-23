"""French on first visit; an explicit choice persists in Django's cookie."""
from django.conf import settings
from django.middleware.locale import LocaleMiddleware


class PreferredLanguageMiddleware(LocaleMiddleware):
    def process_request(self, request):
        if request.COOKIES.get(settings.LANGUAGE_COOKIE_NAME) not in dict(settings.LANGUAGES):
            request.META['HTTP_ACCEPT_LANGUAGE'] = settings.LANGUAGE_CODE
        return super().process_request(request)
