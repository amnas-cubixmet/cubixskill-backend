"""Regression tests for deployment env parsing and browser authentication preflight."""
import os
from unittest.mock import patch

from django.core.exceptions import ImproperlyConfigured
from django.test import SimpleTestCase, override_settings

from config.environment import env_bool, env_csv, env_int, env_origins


class EnvironmentParserTests(SimpleTestCase):
    def test_boolean_values_and_invalid_values(self):
        with patch.dict(os.environ, {'TEST_ENV_FLAG': 'yes'}):
            self.assertTrue(env_bool('TEST_ENV_FLAG'))
        with patch.dict(os.environ, {'TEST_ENV_FLAG': 'False'}):
            self.assertFalse(env_bool('TEST_ENV_FLAG', True))
        with patch.dict(os.environ, {'TEST_ENV_FLAG': 'perhaps'}):
            with self.assertRaises(ImproperlyConfigured):
                env_bool('TEST_ENV_FLAG')

    def test_integer_minimum_and_invalid_values(self):
        with patch.dict(os.environ, {'TEST_ENV_NUMBER': '45'}):
            self.assertEqual(env_int('TEST_ENV_NUMBER', 15, minimum=30), 45)
        with patch.dict(os.environ, {'TEST_ENV_NUMBER': '4'}):
            with self.assertRaises(ImproperlyConfigured):
                env_int('TEST_ENV_NUMBER', 15, minimum=30)
        with patch.dict(os.environ, {'TEST_ENV_NUMBER': 'oops'}):
            with self.assertRaises(ImproperlyConfigured):
                env_int('TEST_ENV_NUMBER', 15)

    def test_comma_delimited_values(self):
        with patch.dict(os.environ, {'TEST_ENV_HOSTS': 'localhost, 127.0.0.1, ,api.example.com'}):
            self.assertEqual(env_csv('TEST_ENV_HOSTS'), ['localhost', '127.0.0.1', 'api.example.com'])

    def test_valid_origin_list_and_markdown_escaped_colons(self):
        with patch.dict(os.environ, {
            'TEST_ENV_ORIGINS': r'http\://localhost:5173,http://localhost:5175,http://localhost:5175\\'
        }):
            self.assertEqual(env_origins('TEST_ENV_ORIGINS'), [
                'http://localhost:5173',
                'http://localhost:5175',
            ])

    def test_reject_invalid_origin_paths_and_ports(self):
        for value in ('localhost:5175', 'http://localhost:5175/login', 'http://localhost:99999', 'not-a-url'):
            with self.subTest(value=value), patch.dict(os.environ, {'TEST_ENV_ORIGINS': value}):
                with self.assertRaises(ImproperlyConfigured):
                    env_origins('TEST_ENV_ORIGINS')


class RegistrationCorsTests(SimpleTestCase):
    @override_settings(CORS_ALLOWED_ORIGINS=['http://localhost:5175'], CORS_ALLOW_CREDENTIALS=True)
    def test_public_registration_preflight_returns_credentials_headers(self):
        response = self.client.options(
            '/api/v1/auth/register/academy/',
            HTTP_ORIGIN='http://localhost:5175',
            HTTP_ACCESS_CONTROL_REQUEST_METHOD='POST',
            HTTP_ACCESS_CONTROL_REQUEST_HEADERS='content-type',
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Access-Control-Allow-Origin'], 'http://localhost:5175')
        self.assertEqual(response['Access-Control-Allow-Credentials'], 'true')
        self.assertIn('POST', response['Access-Control-Allow-Methods'])

    def test_unauthenticated_instructor_session_returns_401(self):
        self.assertEqual(self.client.get('/api/v1/auth/instructor/me/').status_code, 401)
        self.assertEqual(self.client.post('/api/v1/auth/instructor/refresh/').status_code, 401)
