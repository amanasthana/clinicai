"""
Tests for core.middleware.CanonicalHostMiddleware and the related host/CSRF settings.
"""
from django.conf import settings
from django.contrib.auth.models import User
from django.test import TestCase, Client, override_settings

from accounts.models import Clinic, StaffMember
from accounts.permissions import set_permissions_from_role

OLD_HOST = 'clinicai.azurewebsites.net'
WWW_HOST = 'www.medlynai.com'
CANONICAL = 'medlynai.com'


class CanonicalHostSettingsTest(TestCase):

    def test_canonical_host_default(self):
        self.assertEqual(settings.CANONICAL_HOST, CANONICAL)

    def test_middleware_is_first(self):
        self.assertEqual(settings.MIDDLEWARE[0], 'core.middleware.CanonicalHostMiddleware')

    def test_allowed_hosts_include_all_public_hosts(self):
        for host in (CANONICAL, WWW_HOST, OLD_HOST):
            self.assertIn(host, settings.ALLOWED_HOSTS)

    def test_csrf_trusted_origins_include_all_public_hosts(self):
        for host in (CANONICAL, WWW_HOST, OLD_HOST):
            self.assertIn(f'https://{host}', settings.CSRF_TRUSTED_ORIGINS)

    def test_proxy_ssl_header(self):
        self.assertEqual(settings.SECURE_PROXY_SSL_HEADER, ('HTTP_X_FORWARDED_PROTO', 'https'))


class CanonicalHostRedirectTest(TestCase):

    def setUp(self):
        # A clinic must exist or the login view redirects to first-time setup.
        Clinic.objects.create(name='Test Clinic', address='1 Test Rd', city='Mumbai', phone='9000000099')

    def test_get_old_host_301_keeps_path_and_query(self):
        resp = self.client.get('/some/path?x=1', HTTP_HOST=OLD_HOST)
        self.assertEqual(resp.status_code, 301)
        self.assertEqual(resp['Location'], 'https://medlynai.com/some/path?x=1')

    def test_head_old_host_301(self):
        resp = self.client.head('/some/path?x=1', HTTP_HOST=OLD_HOST)
        self.assertEqual(resp.status_code, 301)
        self.assertEqual(resp['Location'], 'https://medlynai.com/some/path?x=1')

    def test_post_old_host_308_same_location(self):
        resp = self.client.post('/some/path?x=1', {'a': 'b'}, HTTP_HOST=OLD_HOST)
        self.assertEqual(resp.status_code, 308)
        self.assertEqual(resp['Location'], 'https://medlynai.com/some/path?x=1')

    def test_put_patch_delete_old_host_308(self):
        for method in ('put', 'patch', 'delete'):
            resp = getattr(self.client, method)('/some/path?x=1', HTTP_HOST=OLD_HOST)
            self.assertEqual(resp.status_code, 308, method)
            self.assertEqual(resp['Location'], 'https://medlynai.com/some/path?x=1', method)

    def test_uppercase_host_redirects(self):
        resp = self.client.get('/some/path?x=1', HTTP_HOST='ClinicAI.AzureWebsites.NET')
        self.assertEqual(resp.status_code, 301)
        self.assertEqual(resp['Location'], 'https://medlynai.com/some/path?x=1')

    def test_host_with_port_redirects(self):
        resp = self.client.get('/some/path?x=1', HTTP_HOST=f'{OLD_HOST}:443')
        self.assertEqual(resp.status_code, 301)
        self.assertEqual(resp['Location'], 'https://medlynai.com/some/path?x=1')

    def test_www_redirects_to_root(self):
        resp = self.client.get('/', HTTP_HOST=WWW_HOST)
        self.assertEqual(resp.status_code, 301)
        self.assertEqual(resp['Location'], 'https://medlynai.com/')

    def test_canonical_host_not_redirected(self):
        resp = self.client.get('/accounts/login/', HTTP_HOST=CANONICAL, secure=True)
        self.assertEqual(resp.status_code, 200)

    def test_canonical_host_root_no_loop(self):
        resp = self.client.get('/', HTTP_HOST=CANONICAL, secure=True)
        # Anonymous users go to login; never a 301 back to medlynai.com itself.
        self.assertNotEqual(resp.status_code, 301)
        self.assertFalse(resp.get('Location', '').startswith('https://medlynai.com'))

    def test_exempt_prefixes_not_redirected(self):
        for prefix in settings.CANONICAL_REDIRECT_EXEMPT_PREFIXES:
            path = prefix + ('test' if prefix.endswith('/') else '')
            resp = self.client.get(path, HTTP_HOST=OLD_HOST, secure=True)
            self.assertNotIn(resp.status_code, (301, 308), path)

    def test_exempt_list_is_configurable(self):
        with override_settings(CANONICAL_REDIRECT_EXEMPT_PREFIXES=['/hooks/']):
            client = Client()
            resp = client.get('/hooks/razorpay/', HTTP_HOST=OLD_HOST, secure=True)
            self.assertNotIn(resp.status_code, (301, 308))
            resp = client.get('/.well-known/x', HTTP_HOST=OLD_HOST, secure=True)
            self.assertEqual(resp.status_code, 301)

    def test_scm_host_not_redirected(self):
        with override_settings(ALLOWED_HOSTS=[*settings.ALLOWED_HOSTS, 'clinicai.scm.azurewebsites.net']):
            resp = Client().get('/accounts/login/', HTTP_HOST='clinicai.scm.azurewebsites.net', secure=True)
            self.assertEqual(resp.status_code, 200)

    def test_unknown_host_400(self):
        resp = self.client.get('/', HTTP_HOST='evil.example.com')
        self.assertEqual(resp.status_code, 400)


class CanonicalHostCsrfTest(TestCase):

    def setUp(self):
        clinic = Clinic.objects.create(name='Test Clinic', address='1 Test Rd', city='Mumbai', phone='9000000099')
        user = User.objects.create_user(username='csrfdoc', password='testpass123')
        sm = StaffMember.objects.create(user=user, clinic=clinic, role='doctor', display_name='Dr. Test')
        set_permissions_from_role(sm)
        sm.save()
        self.client = Client(enforce_csrf_checks=True)

    def _post_login(self, token):
        data = {'username': 'csrfdoc', 'password': 'testpass123'}
        if token:
            data['csrfmiddlewaretoken'] = token
        return self.client.post(
            '/accounts/login/', data,
            HTTP_HOST=CANONICAL, secure=True,
            HTTP_ORIGIN='https://medlynai.com',
            HTTP_REFERER='https://medlynai.com/accounts/login/',
        )

    def test_form_post_with_valid_token_succeeds(self):
        self.client.get('/accounts/login/', HTTP_HOST=CANONICAL, secure=True)
        token = self.client.cookies['csrftoken'].value
        resp = self._post_login(token)
        self.assertEqual(resp.status_code, 302)
        self.assertIn('_auth_user_id', self.client.session)

    def test_form_post_without_token_rejected(self):
        resp = self._post_login(None)
        self.assertEqual(resp.status_code, 403)
