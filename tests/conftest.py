"""
Pytest fixtures for Google Photos Organizer tests.
"""

import json
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch
import importlib

import pytest


@pytest.fixture(autouse=True)
def isolate_config(tmp_path, monkeypatch):
    """Automatically isolate config for every test."""
    config_dir = tmp_path / '.config' / 'gporg'
    config_dir.mkdir(parents=True)

    # We need to patch the module-level constants AFTER import
    # because reload() would reset them. So we patch them directly.
    import core

    # Store original values
    orig_config_dir = core.CONFIG_DIR
    orig_config_file = core.CONFIG_FILE
    orig_token_file = core.TOKEN_FILE

    # Patch the module constants
    core.CONFIG_DIR = config_dir
    core.CONFIG_FILE = config_dir / 'config.json'
    core.TOKEN_FILE = config_dir / 'token.json'

    yield config_dir

    # Restore original values
    core.CONFIG_DIR = orig_config_dir
    core.CONFIG_FILE = orig_config_file
    core.TOKEN_FILE = orig_token_file


@pytest.fixture
def temp_config_dir(isolate_config):
    """Alias for isolate_config for backward compatibility."""
    return isolate_config


@pytest.fixture
def mock_credentials_file(tmp_path):
    """Create a mock OAuth client credentials JSON file."""
    creds_file = tmp_path / 'client_secret.json'
    creds_data = {
        "installed": {
            "client_id": "123456789.apps.googleusercontent.com",
            "project_id": "test-project",
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "client_secret": "test-secret",
            "redirect_uris": ["http://localhost"]
        }
    }
    creds_file.write_text(json.dumps(creds_data))
    return creds_file


@pytest.fixture
def mock_token_file(isolate_config):
    """Create a mock OAuth token file."""
    import core
    token_data = {
        "token": "mock_access_token",
        "refresh_token": "mock_refresh_token",
        "token_uri": "https://oauth2.googleapis.com/token",
        "client_id": "123456789.apps.googleusercontent.com",
        "client_secret": "test-secret",
        "scopes": core.SCOPES
    }
    core.TOKEN_FILE.write_text(json.dumps(token_data))
    return core.TOKEN_FILE


@pytest.fixture
def mock_photos_service():
    """Create a mock Google Photos API service."""
    mock_service = MagicMock()

    # Mock albums().list()
    mock_service.albums().list().execute.return_value = {
        'albums': [
            {'id': 'album1', 'title': 'Photos 2023'},
            {'id': 'album2', 'title': 'Photos 2022'},
        ]
    }

    # Mock albums().create()
    mock_service.albums().create().execute.return_value = {
        'id': 'new_album_id',
        'title': 'New Album'
    }

    # Mock albums().get()
    mock_service.albums().get().execute.return_value = {
        'id': 'album1',
        'title': 'Photos 2023'
    }

    # Mock mediaItems().search()
    mock_service.mediaItems().search().execute.return_value = {
        'mediaItems': [
            {'id': 'photo1', 'filename': 'IMG_001.jpg'},
            {'id': 'photo2', 'filename': 'IMG_002.jpg'},
            {'id': 'photo3', 'filename': 'IMG_003.jpg'},
        ]
    }

    # Mock albums().batchAddMediaItems()
    mock_service.albums().batchAddMediaItems().execute.return_value = {}

    return mock_service


@pytest.fixture
def sample_photos():
    """Sample photo data for testing."""
    return [
        {'id': f'photo{i}', 'filename': f'IMG_{i:04d}.jpg'}
        for i in range(150)  # More than batch size of 50
    ]


@pytest.fixture
def configured_service(mock_credentials_file, mock_token_file, mock_photos_service, isolate_config):
    """Create a fully configured and mocked PhotosService."""
    import core

    # Set up config
    config = core.Config()
    config.set_credentials(str(mock_credentials_file))

    # Create service with mocked internals
    with patch.object(core.Config, 'load_credentials') as mock_load:
        mock_creds = MagicMock()
        mock_creds.valid = True
        mock_creds.expired = False
        mock_load.return_value = mock_creds

        with patch('core.build', return_value=mock_photos_service):
            service = core.PhotosService(config)
            service._service = mock_photos_service
            service._creds = mock_creds
            yield service
