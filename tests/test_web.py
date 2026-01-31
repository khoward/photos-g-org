"""
Integration tests for web.py - Flask API endpoints.
"""

import json
import importlib
from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture
def web_client():
    """Create a Flask test client with API key."""
    import core
    import web
    importlib.reload(web)

    # Reset the global config in web module
    web.config = core.Config()

    # Generate an API key for testing
    api_key = web.config.get_or_create_api_key()

    # Reset organize state
    web.organize_state = {
        'running': False,
        'progress': 0,
        'total': 0,
        'message': '',
        'error': None
    }

    # Clear rate limit storage
    web.rate_limit_storage.clear()

    web.app.config['TESTING'] = True
    client = web.app.test_client()

    # Store API key on client for easy access
    client.api_key = api_key
    return client


def auth_headers(client):
    """Get headers with API key for authenticated requests."""
    return {'X-API-Key': client.api_key}


class TestConfigEndpoints:
    """Tests for /api/config endpoints."""

    def test_get_config_unconfigured(self, web_client):
        """Test GET /api/config when not configured."""
        response = web_client.get('/api/config', headers=auth_headers(web_client))
        data = response.get_json()

        assert response.status_code == 200
        assert data['configured'] is False

    def test_get_config_requires_auth(self, web_client):
        """Test GET /api/config requires API key."""
        response = web_client.get('/api/config')
        assert response.status_code == 401

    def test_get_config_invalid_key(self, web_client):
        """Test GET /api/config rejects invalid API key."""
        response = web_client.get('/api/config', headers={'X-API-Key': 'invalid-key'})
        assert response.status_code == 401

    def test_set_config_success(self, web_client, mock_credentials_file):
        """Test POST /api/config with valid path."""
        response = web_client.post(
            '/api/config',
            json={'credentials_path': str(mock_credentials_file)},
            content_type='application/json',
            headers=auth_headers(web_client)
        )
        data = response.get_json()

        assert response.status_code == 200
        assert data['success'] is True

    def test_set_config_file_not_found(self, web_client):
        """Test POST /api/config with non-existent file."""
        response = web_client.post(
            '/api/config',
            json={'credentials_path': '/nonexistent/file.json'},
            content_type='application/json',
            headers=auth_headers(web_client)
        )
        data = response.get_json()

        assert response.status_code == 400
        assert 'error' in data

    def test_set_config_no_path(self, web_client):
        """Test POST /api/config without path."""
        response = web_client.post(
            '/api/config',
            json={},
            content_type='application/json',
            headers=auth_headers(web_client)
        )
        data = response.get_json()

        assert response.status_code == 400
        assert 'error' in data


class TestYearsEndpoint:
    """Tests for /api/years endpoint."""

    def test_get_years(self, web_client):
        """Test GET /api/years returns year list."""
        response = web_client.get('/api/years')
        data = response.get_json()

        assert response.status_code == 200
        assert 'years' in data
        assert len(data['years']) > 0
        assert data['years'][0] >= 2024


class TestAlbumsEndpoint:
    """Tests for /api/albums endpoint."""

    def test_get_albums_not_configured(self, web_client):
        """Test GET /api/albums when not configured."""
        response = web_client.get('/api/albums', headers=auth_headers(web_client))
        data = response.get_json()

        assert response.status_code == 400
        assert 'error' in data

    def test_get_albums_requires_auth(self, web_client):
        """Test GET /api/albums requires API key."""
        response = web_client.get('/api/albums')
        assert response.status_code == 401

    def test_get_albums_success(self, web_client, mock_credentials_file, mock_photos_service):
        """Test GET /api/albums with valid configuration."""
        import core
        import web
        web.config.set_credentials(str(mock_credentials_file))

        mock_creds = MagicMock()
        mock_creds.valid = True
        mock_creds.expired = False

        with patch.object(core.Config, 'load_credentials', return_value=mock_creds), \
             patch('core.build', return_value=mock_photos_service):

            response = web_client.get('/api/albums', headers=auth_headers(web_client))
            data = response.get_json()

            assert response.status_code == 200
            assert 'albums' in data
            assert len(data['albums']) == 2


class TestOrganizeEndpoint:
    """Tests for /api/organize endpoint."""

    def test_organize_not_configured(self, web_client):
        """Test POST /api/organize when not configured."""
        response = web_client.post(
            '/api/organize',
            json={'year': 2023, 'album_name': 'Test'},
            content_type='application/json',
            headers=auth_headers(web_client)
        )
        data = response.get_json()

        assert response.status_code == 400
        assert 'error' in data

    def test_organize_requires_auth(self, web_client):
        """Test POST /api/organize requires API key."""
        response = web_client.post(
            '/api/organize',
            json={'year': 2023, 'album_name': 'Test'},
            content_type='application/json'
        )
        assert response.status_code == 401

    def test_organize_missing_date_filter(self, web_client, mock_credentials_file):
        """Test POST /api/organize without year or date range."""
        import web
        web.config.set_credentials(str(mock_credentials_file))

        response = web_client.post(
            '/api/organize',
            json={'album_name': 'Test'},
            content_type='application/json',
            headers=auth_headers(web_client)
        )
        data = response.get_json()

        assert response.status_code == 400
        assert 'year or start_date/end_date' in data['error']

    def test_organize_missing_album(self, web_client, mock_credentials_file):
        """Test POST /api/organize without album."""
        import web
        web.config.set_credentials(str(mock_credentials_file))

        response = web_client.post(
            '/api/organize',
            json={'year': 2023},
            content_type='application/json',
            headers=auth_headers(web_client)
        )
        data = response.get_json()

        assert response.status_code == 400
        assert 'Album' in data['error']


class TestStatusEndpoint:
    """Tests for /api/status endpoint."""

    def test_get_status_initial(self, web_client):
        """Test GET /api/status returns initial state."""
        response = web_client.get('/api/status', headers=auth_headers(web_client))
        data = response.get_json()

        assert response.status_code == 200
        assert 'running' in data
        assert 'progress' in data
        assert 'total' in data
        assert 'message' in data

    def test_get_status_requires_auth(self, web_client):
        """Test GET /api/status requires API key."""
        response = web_client.get('/api/status')
        assert response.status_code == 401


class TestIndexRoute:
    """Tests for main page route."""

    def test_index_returns_html(self, web_client):
        """Test GET / returns HTML page."""
        response = web_client.get('/')

        assert response.status_code == 200
        assert b'Google Photos Organizer' in response.data


class TestSecurityFeatures:
    """Tests for security features."""

    def test_security_headers_present(self, web_client):
        """Test that security headers are set."""
        response = web_client.get('/')

        assert response.headers.get('X-Frame-Options') == 'DENY'
        assert response.headers.get('X-Content-Type-Options') == 'nosniff'
        assert response.headers.get('X-XSS-Protection') == '1; mode=block'
        assert 'Content-Security-Policy' in response.headers
        assert 'Referrer-Policy' in response.headers

    def test_api_key_endpoint_localhost(self, web_client):
        """Test /api/key is accessible from localhost."""
        # Flask test client simulates localhost
        response = web_client.get('/api/key')

        assert response.status_code == 200
        data = response.get_json()
        assert 'api_key' in data

    def test_years_endpoint_no_auth_required(self, web_client):
        """Test /api/years doesn't require authentication."""
        response = web_client.get('/api/years')

        assert response.status_code == 200
        data = response.get_json()
        assert 'years' in data
