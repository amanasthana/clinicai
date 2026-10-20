"""
Canonical host redirect.

Sends requests that arrive on a legacy host (e.g. clinicai.azurewebsites.net,
www.medlynai.com) to the same path + query string on https://CANONICAL_HOST.
Must sit first in MIDDLEWARE so it runs before SecurityMiddleware's own
http->https redirect and before anything touches the session or CSRF.
"""

from django.conf import settings
from django.http import HttpResponsePermanentRedirect
from django.http.request import split_domain_port


class HttpResponsePermanentRedirectKeepMethod(HttpResponsePermanentRedirect):
    status_code = 308


class CanonicalHostMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response
        self.canonical_host = settings.CANONICAL_HOST.lower()
        self.redirect_hosts = {
            h.lower() for h in settings.CANONICAL_REDIRECT_HOSTS
        } - {self.canonical_host}
        self.exempt_prefixes = tuple(settings.CANONICAL_REDIRECT_EXEMPT_PREFIXES)

    def __call__(self, request):
        # Read the raw Host header rather than request.get_host(): unknown hosts
        # must fall through to Django's normal ALLOWED_HOSTS check (400).
        domain, _port = split_domain_port(request.META.get('HTTP_HOST', ''))
        if (domain in self.redirect_hosts
                and not request.path.startswith(self.exempt_prefixes)):
            location = f'https://{self.canonical_host}{request.get_full_path()}'
            if request.method in ('GET', 'HEAD'):
                return HttpResponsePermanentRedirect(location)
            return HttpResponsePermanentRedirectKeepMethod(location)
        return self.get_response(request)
