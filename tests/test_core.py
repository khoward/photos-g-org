"""
Unit tests for core.py - business logic.
"""

import json
from pathlib import Path
from unittest.mock import MagicMock, patch, call

import pytest


class TestConfig:
    """Tests for Config class."""

    def test_config_defaults(self):
        """Test config initializes with None credentials."""
        import core
        config = core.Config()
        assert config.credentials_path is None
        assert not config.is_configured

    def test_config_save_and_load(self, mock_credentials_file, isolate_config):
        """Test saving and loading credentials path."""
        import core
        config = core.Config()
        config.set_credentials(str(mock_credentials_file))

        assert config.credentials_path == str(mock_credentials_file)
        assert config.is_configured

        # Verify file was written
        config_file = isolate_config / 'config.json'
        assert config_file.exists()

        data = json.loads(config_file.read_text())
        assert data['credentials_path'] == str(mock_credentials_file)

    def test_config_reload(self, mock_credentials_file):
        """Test config reloads from file."""
        import core
        # Save config
        config1 = core.Config()
        config1.set_credentials(str(mock_credentials_file))

        # Create new instance (simulates restart)
        config2 = core.Config()
        assert config2.credentials_path == str(mock_credentials_file)
        assert config2.is_configured

    def test_config_invalid_path(self):
        """Test is_configured returns False for non-existent file."""
        import core
        config = core.Config()
        config.credentials_path = '/nonexistent/path.json'
        assert not config.is_configured

    def test_config_creates_directory(self, tmp_path):
        """Test config creates directory if it doesn't exist."""
        import core

        # Create a new config dir inside tmp_path
        config_dir = tmp_path / 'brand_new_dir' / 'gporg'
        config_file = config_dir / 'config.json'

        # Temporarily change the module constants
        orig_config_dir = core.CONFIG_DIR
        orig_config_file = core.CONFIG_FILE

        try:
            core.CONFIG_DIR = config_dir
            core.CONFIG_FILE = config_file

            config = core.Config()
            config.set_credentials('/some/path.json')

            assert config_dir.exists()
        finally:
            # Restore
            core.CONFIG_DIR = orig_config_dir
            core.CONFIG_FILE = orig_config_file


class TestPhotosService:
    """Tests for PhotosService class."""

    def test_list_albums(self, mock_credentials_file, mock_photos_service):
        """Test listing albums."""
        from core import PhotosService

        with patch('core.service_account.Credentials.from_service_account_file'), \
             patch('core.build', return_value=mock_photos_service):

            service = PhotosService(str(mock_credentials_file))
            albums = service.list_albums()

            assert len(albums) == 2
            assert albums[0]['title'] == 'Photos 2023'
            assert albums[1]['title'] == 'Photos 2022'

    def test_list_albums_pagination(self, mock_credentials_file):
        """Test listing albums with pagination."""
        from core import PhotosService
        mock_service = MagicMock()

        # First page
        mock_service.albums().list().execute.side_effect = [
            {'albums': [{'id': 'a1', 'title': 'Album 1'}], 'nextPageToken': 'token1'},
            {'albums': [{'id': 'a2', 'title': 'Album 2'}]}
        ]

        with patch('core.service_account.Credentials.from_service_account_file'), \
             patch('core.build', return_value=mock_service):

            service = PhotosService(str(mock_credentials_file))
            albums = service.list_albums()

            assert len(albums) == 2

    def test_create_album(self, mock_credentials_file, mock_photos_service):
        """Test creating a new album."""
        from core import PhotosService

        with patch('core.service_account.Credentials.from_service_account_file'), \
             patch('core.build', return_value=mock_photos_service):

            service = PhotosService(str(mock_credentials_file))
            album = service.create_album('Test Album')

            assert album['id'] == 'new_album_id'

    def test_get_or_create_album_existing(self, mock_credentials_file):
        """Test get_or_create returns existing album."""
        from core import PhotosService
        mock_service = MagicMock()

        # Mock list_albums to return album with matching title
        mock_service.albums().list().execute.return_value = {
            'albums': [
                {'id': 'album1', 'title': 'Photos 2023'},
                {'id': 'album2', 'title': 'Photos 2022'},
            ]
        }

        with patch('core.service_account.Credentials.from_service_account_file'), \
             patch('core.build', return_value=mock_service):

            service = PhotosService(str(mock_credentials_file))
            album_id = service.get_or_create_album('Photos 2023')

            assert album_id == 'album1'
            # create should NOT be called since album exists
            mock_service.albums().create.assert_not_called()

    def test_get_or_create_album_new(self, mock_credentials_file):
        """Test get_or_create creates new album if not found."""
        from core import PhotosService
        mock_service = MagicMock()

        # Mock list_albums - album doesn't exist
        mock_service.albums().list().execute.return_value = {
            'albums': [{'id': 'album1', 'title': 'Photos 2023'}]
        }

        # Mock create
        mock_service.albums().create().execute.return_value = {
            'id': 'new_album_id',
            'title': 'New Album Name'
        }

        with patch('core.service_account.Credentials.from_service_account_file'), \
             patch('core.build', return_value=mock_service):

            service = PhotosService(str(mock_credentials_file))
            album_id = service.get_or_create_album('New Album Name')

            assert album_id == 'new_album_id'

    def test_search_photos_by_year(self, mock_credentials_file, mock_photos_service):
        """Test searching photos by year."""
        from core import PhotosService

        with patch('core.service_account.Credentials.from_service_account_file'), \
             patch('core.build', return_value=mock_photos_service):

            service = PhotosService(str(mock_credentials_file))
            photos = service.search_photos_by_year(2023)

            assert len(photos) == 3
            assert photos[0]['id'] == 'photo1'

    def test_search_photos_with_progress_callback(self, mock_credentials_file, mock_photos_service):
        """Test search calls progress callback."""
        from core import PhotosService
        callback = MagicMock()

        with patch('core.service_account.Credentials.from_service_account_file'), \
             patch('core.build', return_value=mock_photos_service):

            service = PhotosService(str(mock_credentials_file))
            service.search_photos_by_year(2023, progress_callback=callback)

            callback.assert_called_with(3)

    def test_add_to_album_batching(self, mock_credentials_file, sample_photos):
        """Test that add_to_album processes photos in batches."""
        from core import PhotosService, BATCH_SIZE
        photo_ids = [p['id'] for p in sample_photos]

        mock_service = MagicMock()

        # Mock batchAddMediaItems
        mock_service.albums().batchAddMediaItems().execute.return_value = {}

        with patch('core.service_account.Credentials.from_service_account_file'), \
             patch('core.build', return_value=mock_service):

            service = PhotosService(str(mock_credentials_file))

            # Consume the generator (skip_existing=False to avoid get_album_photos call)
            results = list(service.add_to_album('album1', photo_ids, skip_existing=False, workers=1))

            # With 150 photos and batch size 50, we should get 3 progress updates
            # (one per batch)
            expected_batches = (len(photo_ids) + BATCH_SIZE - 1) // BATCH_SIZE
            assert len(results) == expected_batches

            # Verify final result shows all photos added
            final_added, final_total = results[-1]
            assert final_added == len(photo_ids)
            assert final_total == len(photo_ids)

    def test_add_to_album_skip_existing(self, mock_credentials_file):
        """Test that skip_existing filters out photos already in album."""
        from core import PhotosService
        photo_ids = ['photo1', 'photo2', 'photo3', 'photo4']

        mock_service = MagicMock()

        # Mock: photo1 and photo2 already in album
        mock_service.mediaItems().search().execute.return_value = {
            'mediaItems': [{'id': 'photo1'}, {'id': 'photo2'}]
        }

        # Mock batchAddMediaItems
        mock_service.albums().batchAddMediaItems().execute.return_value = {}

        with patch('core.service_account.Credentials.from_service_account_file'), \
             patch('core.build', return_value=mock_service):

            service = PhotosService(str(mock_credentials_file))
            results = list(service.add_to_album('album1', photo_ids, skip_existing=True, workers=1))

            # Should only add photo3 and photo4
            if results:
                final_added, final_total = results[-1]
                assert final_total == 2

    def test_add_to_album_progress_callback(self, mock_credentials_file):
        """Test that progress callback is called."""
        from core import PhotosService
        photo_ids = ['photo1', 'photo2', 'photo3']
        callback = MagicMock()

        mock_service = MagicMock()
        mock_service.albums().batchAddMediaItems().execute.return_value = {}

        with patch('core.service_account.Credentials.from_service_account_file'), \
             patch('core.build', return_value=mock_service):

            service = PhotosService(str(mock_credentials_file))
            service.add_to_album_sync(
                'album1', photo_ids,
                skip_existing=False,
                progress_callback=callback,
                workers=1
            )

            callback.assert_called()

    def test_add_to_album_empty_list(self, mock_credentials_file):
        """Test add_to_album with empty photo list."""
        from core import PhotosService
        mock_service = MagicMock()

        with patch('core.service_account.Credentials.from_service_account_file'), \
             patch('core.build', return_value=mock_service):

            service = PhotosService(str(mock_credentials_file))
            results = list(service.add_to_album('album1', [], skip_existing=False))

            assert len(results) == 0


class TestHelperFunctions:
    """Tests for helper functions."""

    def test_get_available_years(self):
        """Test get_available_years returns sensible range."""
        from core import get_available_years
        years = get_available_years()

        assert len(years) > 0
        assert years[0] >= 2024  # Current or recent year
        assert years[-1] == 2000  # Goes back to 2000
        assert years == sorted(years, reverse=True)  # Descending order


class TestValidationFunctions:
    """Tests for input validation functions."""

    def test_validate_year_valid(self):
        """Test validate_year with valid years."""
        from core import validate_year

        is_valid, error, year = validate_year(2023)
        assert is_valid
        assert error == ""
        assert year == 2023

        # String year
        is_valid, error, year = validate_year("2020")
        assert is_valid
        assert year == 2020

    def test_validate_year_invalid(self):
        """Test validate_year with invalid years."""
        from core import validate_year

        # None
        is_valid, error, year = validate_year(None)
        assert not is_valid
        assert "required" in error.lower()

        # Non-numeric
        is_valid, error, year = validate_year("abc")
        assert not is_valid
        assert "number" in error.lower()

        # Out of range
        is_valid, error, year = validate_year(1800)
        assert not is_valid
        assert "between" in error.lower()

    def test_validate_album_name_valid(self):
        """Test validate_album_name with valid names."""
        from core import validate_album_name

        is_valid, error = validate_album_name("Photos 2023")
        assert is_valid
        assert error == ""

    def test_validate_album_name_invalid(self):
        """Test validate_album_name with invalid names."""
        from core import validate_album_name

        # Empty
        is_valid, error = validate_album_name("")
        assert not is_valid

        # Too long
        is_valid, error = validate_album_name("x" * 600)
        assert not is_valid

        # Control characters
        is_valid, error = validate_album_name("test\x00name")
        assert not is_valid

    def test_validate_credentials_path_valid(self, mock_credentials_file):
        """Test validate_credentials_path with valid file."""
        from core import validate_credentials_path

        is_valid, result = validate_credentials_path(str(mock_credentials_file))
        assert is_valid
        assert result == str(mock_credentials_file)

    def test_validate_credentials_path_invalid(self, tmp_path):
        """Test validate_credentials_path with invalid paths."""
        from core import validate_credentials_path

        # Empty
        is_valid, error = validate_credentials_path("")
        assert not is_valid

        # Non-existent
        is_valid, error = validate_credentials_path("/nonexistent/file.json")
        assert not is_valid

        # Not JSON extension
        txt_file = tmp_path / "test.txt"
        txt_file.write_text("{}")
        is_valid, error = validate_credentials_path(str(txt_file))
        assert not is_valid

        # Invalid JSON
        bad_json = tmp_path / "bad.json"
        bad_json.write_text("not valid json")
        is_valid, error = validate_credentials_path(str(bad_json))
        assert not is_valid

        # Valid JSON but not service account
        non_sa = tmp_path / "non_sa.json"
        non_sa.write_text('{"type": "not_service_account"}')
        is_valid, error = validate_credentials_path(str(non_sa))
        assert not is_valid


class TestApiKeyManagement:
    """Tests for API key management."""

    def test_generate_api_key(self, isolate_config):
        """Test API key generation."""
        import core
        config = core.Config()

        key = config.get_or_create_api_key()
        assert key is not None
        assert len(key) > 20

    def test_verify_api_key_correct(self, isolate_config):
        """Test API key verification with correct key."""
        import core
        config = core.Config()

        key = config.get_or_create_api_key()
        assert config.verify_api_key(key)

    def test_verify_api_key_incorrect(self, isolate_config):
        """Test API key verification with incorrect key."""
        import core
        config = core.Config()

        config.get_or_create_api_key()
        assert not config.verify_api_key("wrong-key")
        assert not config.verify_api_key("")
        assert not config.verify_api_key(None)

    def test_regenerate_api_key(self, isolate_config):
        """Test API key regeneration."""
        import core
        config = core.Config()

        old_key = config.get_or_create_api_key()
        new_key = config.regenerate_api_key()

        assert old_key != new_key
        assert not config.verify_api_key(old_key)
        assert config.verify_api_key(new_key)
