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

    def test_list_albums(self, mock_credentials_file, mock_token_file, mock_photos_service):
        """Test listing albums."""
        import core

        config = core.Config()
        config.set_credentials(str(mock_credentials_file))

        with patch.object(core.Config, 'load_credentials') as mock_load:
            mock_creds = MagicMock()
            mock_creds.valid = True
            mock_load.return_value = mock_creds

            with patch('core.build', return_value=mock_photos_service):
                service = core.PhotosService(config)
                albums = service.list_albums()

                assert len(albums) == 2
                assert albums[0]['title'] == 'Photos 2023'
                assert albums[1]['title'] == 'Photos 2022'

    def test_list_albums_pagination(self, mock_credentials_file, mock_token_file):
        """Test listing albums with pagination."""
        import core

        config = core.Config()
        config.set_credentials(str(mock_credentials_file))

        mock_service = MagicMock()
        mock_service.albums().list().execute.side_effect = [
            {'albums': [{'id': 'a1', 'title': 'Album 1'}], 'nextPageToken': 'token1'},
            {'albums': [{'id': 'a2', 'title': 'Album 2'}]}
        ]

        with patch.object(core.Config, 'load_credentials') as mock_load:
            mock_creds = MagicMock()
            mock_creds.valid = True
            mock_load.return_value = mock_creds

            with patch('core.build', return_value=mock_service):
                service = core.PhotosService(config)
                albums = service.list_albums()

                assert len(albums) == 2

    def test_create_album(self, mock_credentials_file, mock_token_file, mock_photos_service):
        """Test creating a new album."""
        import core

        config = core.Config()
        config.set_credentials(str(mock_credentials_file))

        with patch.object(core.Config, 'load_credentials') as mock_load:
            mock_creds = MagicMock()
            mock_creds.valid = True
            mock_load.return_value = mock_creds

            with patch('core.build', return_value=mock_photos_service):
                service = core.PhotosService(config)
                album = service.create_album('Test Album')

                assert album['id'] == 'new_album_id'

    def test_get_or_create_album_existing(self, mock_credentials_file, mock_token_file):
        """Test get_or_create returns existing album."""
        import core

        config = core.Config()
        config.set_credentials(str(mock_credentials_file))

        mock_service = MagicMock()
        mock_service.albums().list().execute.return_value = {
            'albums': [
                {'id': 'album1', 'title': 'Photos 2023'},
                {'id': 'album2', 'title': 'Photos 2022'},
            ]
        }

        with patch.object(core.Config, 'load_credentials') as mock_load:
            mock_creds = MagicMock()
            mock_creds.valid = True
            mock_load.return_value = mock_creds

            with patch('core.build', return_value=mock_service):
                service = core.PhotosService(config)
                album_id = service.get_or_create_album('Photos 2023')

                assert album_id == 'album1'
                mock_service.albums().create.assert_not_called()

    def test_get_or_create_album_new(self, mock_credentials_file, mock_token_file):
        """Test get_or_create creates new album if not found."""
        import core

        config = core.Config()
        config.set_credentials(str(mock_credentials_file))

        mock_service = MagicMock()
        mock_service.albums().list().execute.return_value = {
            'albums': [{'id': 'album1', 'title': 'Photos 2023'}]
        }
        mock_service.albums().create().execute.return_value = {
            'id': 'new_album_id',
            'title': 'New Album Name'
        }

        with patch.object(core.Config, 'load_credentials') as mock_load:
            mock_creds = MagicMock()
            mock_creds.valid = True
            mock_load.return_value = mock_creds

            with patch('core.build', return_value=mock_service):
                service = core.PhotosService(config)
                album_id = service.get_or_create_album('New Album Name')

                assert album_id == 'new_album_id'

    def test_search_photos_by_year(self, mock_credentials_file, mock_token_file, mock_photos_service):
        """Test searching photos by year."""
        import core

        config = core.Config()
        config.set_credentials(str(mock_credentials_file))

        with patch.object(core.Config, 'load_credentials') as mock_load:
            mock_creds = MagicMock()
            mock_creds.valid = True
            mock_load.return_value = mock_creds

            with patch('core.build', return_value=mock_photos_service):
                service = core.PhotosService(config)
                photos = service.search_photos_by_year(2023)

                assert len(photos) == 3
                assert photos[0]['id'] == 'photo1'

    def test_search_photos_with_progress_callback(self, mock_credentials_file, mock_token_file, mock_photos_service):
        """Test search calls progress callback."""
        import core

        config = core.Config()
        config.set_credentials(str(mock_credentials_file))
        callback = MagicMock()

        with patch.object(core.Config, 'load_credentials') as mock_load:
            mock_creds = MagicMock()
            mock_creds.valid = True
            mock_load.return_value = mock_creds

            with patch('core.build', return_value=mock_photos_service):
                service = core.PhotosService(config)
                service.search_photos_by_year(2023, progress_callback=callback)

                callback.assert_called_with(3)

    def test_add_to_album_batching(self, mock_credentials_file, mock_token_file, sample_photos):
        """Test that add_to_album processes photos in batches."""
        import core
        from core import BATCH_SIZE
        photo_ids = [p['id'] for p in sample_photos]

        config = core.Config()
        config.set_credentials(str(mock_credentials_file))

        mock_service = MagicMock()
        mock_service.albums().batchAddMediaItems().execute.return_value = {}

        with patch.object(core.Config, 'load_credentials') as mock_load:
            mock_creds = MagicMock()
            mock_creds.valid = True
            mock_load.return_value = mock_creds

            with patch('core.build', return_value=mock_service):
                service = core.PhotosService(config)

                results = list(service.add_to_album('album1', photo_ids, skip_existing=False, workers=1))

                expected_batches = (len(photo_ids) + BATCH_SIZE - 1) // BATCH_SIZE
                assert len(results) == expected_batches

                final_added, final_total = results[-1]
                assert final_added == len(photo_ids)
                assert final_total == len(photo_ids)

    def test_add_to_album_skip_existing(self, mock_credentials_file, mock_token_file):
        """Test that skip_existing filters out photos already in album."""
        import core
        photo_ids = ['photo1', 'photo2', 'photo3', 'photo4']

        config = core.Config()
        config.set_credentials(str(mock_credentials_file))

        mock_service = MagicMock()
        mock_service.mediaItems().search().execute.return_value = {
            'mediaItems': [{'id': 'photo1'}, {'id': 'photo2'}]
        }
        mock_service.albums().batchAddMediaItems().execute.return_value = {}

        with patch.object(core.Config, 'load_credentials') as mock_load:
            mock_creds = MagicMock()
            mock_creds.valid = True
            mock_load.return_value = mock_creds

            with patch('core.build', return_value=mock_service):
                service = core.PhotosService(config)
                results = list(service.add_to_album('album1', photo_ids, skip_existing=True, workers=1))

                if results:
                    final_added, final_total = results[-1]
                    assert final_total == 2

    def test_add_to_album_progress_callback(self, mock_credentials_file, mock_token_file):
        """Test that progress callback is called."""
        import core
        photo_ids = ['photo1', 'photo2', 'photo3']
        callback = MagicMock()

        config = core.Config()
        config.set_credentials(str(mock_credentials_file))

        mock_service = MagicMock()
        mock_service.albums().batchAddMediaItems().execute.return_value = {}

        with patch.object(core.Config, 'load_credentials') as mock_load:
            mock_creds = MagicMock()
            mock_creds.valid = True
            mock_load.return_value = mock_creds

            with patch('core.build', return_value=mock_service):
                service = core.PhotosService(config)
                service.add_to_album_sync(
                    'album1', photo_ids,
                    skip_existing=False,
                    progress_callback=callback,
                    workers=1
                )

                callback.assert_called()

    def test_add_to_album_empty_list(self, mock_credentials_file, mock_token_file):
        """Test add_to_album with empty photo list."""
        import core

        config = core.Config()
        config.set_credentials(str(mock_credentials_file))

        mock_service = MagicMock()

        with patch.object(core.Config, 'load_credentials') as mock_load:
            mock_creds = MagicMock()
            mock_creds.valid = True
            mock_load.return_value = mock_creds

            with patch('core.build', return_value=mock_service):
                service = core.PhotosService(config)
                results = list(service.add_to_album('album1', [], skip_existing=False))

                assert len(results) == 0


class TestHelperFunctions:
    """Tests for helper functions."""

    def test_get_available_years(self):
        """Test get_available_years returns sensible range."""
        from core import get_available_years
        years = get_available_years()

        assert len(years) > 0
        assert years[0] >= 2024
        assert years[-1] == 2000
        assert years == sorted(years, reverse=True)


class TestValidationFunctions:
    """Tests for input validation functions."""

    def test_validate_year_valid(self):
        """Test validate_year with valid years."""
        from core import validate_year

        is_valid, error, year = validate_year(2023)
        assert is_valid
        assert error == ""
        assert year == 2023

        is_valid, error, year = validate_year("2020")
        assert is_valid
        assert year == 2020

    def test_validate_year_invalid(self):
        """Test validate_year with invalid years."""
        from core import validate_year

        is_valid, error, year = validate_year(None)
        assert not is_valid
        assert "required" in error.lower()

        is_valid, error, year = validate_year("abc")
        assert not is_valid
        assert "number" in error.lower()

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

        is_valid, error = validate_album_name("")
        assert not is_valid

        is_valid, error = validate_album_name("x" * 600)
        assert not is_valid

        is_valid, error = validate_album_name("test\x00name")
        assert not is_valid

    def test_validate_credentials_path_valid(self, mock_credentials_file):
        """Test validate_credentials_path with valid OAuth client credentials file."""
        from core import validate_credentials_path

        is_valid, result = validate_credentials_path(str(mock_credentials_file))
        assert is_valid
        assert result == str(mock_credentials_file)

    def test_validate_credentials_path_invalid(self, tmp_path):
        """Test validate_credentials_path with invalid paths."""
        from core import validate_credentials_path

        is_valid, error = validate_credentials_path("")
        assert not is_valid

        is_valid, error = validate_credentials_path("/nonexistent/file.json")
        assert not is_valid

        txt_file = tmp_path / "test.txt"
        txt_file.write_text("{}")
        is_valid, error = validate_credentials_path(str(txt_file))
        assert not is_valid

        bad_json = tmp_path / "bad.json"
        bad_json.write_text("not valid json")
        is_valid, error = validate_credentials_path(str(bad_json))
        assert not is_valid

        # Valid JSON but not OAuth client credentials
        non_oauth = tmp_path / "non_oauth.json"
        non_oauth.write_text('{"type": "service_account"}')
        is_valid, error = validate_credentials_path(str(non_oauth))
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


class TestPhotoFilter:
    """Tests for PhotoFilter dataclass."""

    def test_photo_filter_defaults(self):
        """Test PhotoFilter default values."""
        from core import PhotoFilter, MEDIA_TYPE_ALL

        f = PhotoFilter()
        assert f.start_date is None
        assert f.end_date is None
        assert f.year is None
        assert f.media_type == MEDIA_TYPE_ALL
        assert f.categories == []
        assert f.favorites_only is False

    def test_photo_filter_to_api_filter_year(self):
        """Test PhotoFilter.to_api_filter with year."""
        from core import PhotoFilter

        f = PhotoFilter(year=2023)
        api_filter = f.to_api_filter()

        assert 'dateFilter' in api_filter
        assert api_filter['dateFilter']['ranges'][0]['startDate']['year'] == 2023

    def test_photo_filter_to_api_filter_date_range(self):
        """Test PhotoFilter.to_api_filter with date range."""
        from core import PhotoFilter
        from datetime import date

        f = PhotoFilter(start_date=date(2023, 6, 1), end_date=date(2023, 8, 31))
        api_filter = f.to_api_filter()

        assert 'dateFilter' in api_filter
        assert api_filter['dateFilter']['ranges'][0]['startDate']['month'] == 6
        assert api_filter['dateFilter']['ranges'][0]['endDate']['month'] == 8

    def test_photo_filter_to_api_filter_media_type(self):
        """Test PhotoFilter.to_api_filter with media type."""
        from core import PhotoFilter, MEDIA_TYPE_VIDEO

        f = PhotoFilter(year=2023, media_type=MEDIA_TYPE_VIDEO)
        api_filter = f.to_api_filter()

        assert 'mediaTypeFilter' in api_filter
        assert 'VIDEO' in api_filter['mediaTypeFilter']['mediaTypes']

    def test_photo_filter_to_api_filter_categories(self):
        """Test PhotoFilter.to_api_filter with categories."""
        from core import PhotoFilter

        f = PhotoFilter(year=2023, categories=['LANDSCAPES', 'TRAVEL'])
        api_filter = f.to_api_filter()

        assert 'contentFilter' in api_filter
        assert 'LANDSCAPES' in api_filter['contentFilter']['includedContentCategories']

    def test_photo_filter_to_api_filter_favorites(self):
        """Test PhotoFilter.to_api_filter with favorites."""
        from core import PhotoFilter

        f = PhotoFilter(year=2023, favorites_only=True)
        api_filter = f.to_api_filter()

        assert 'featureFilter' in api_filter
        assert 'FAVORITES' in api_filter['featureFilter']['includedFeatures']

    def test_photo_filter_describe(self):
        """Test PhotoFilter.describe method."""
        from core import PhotoFilter

        f = PhotoFilter(year=2023)
        assert "2023" in f.describe()

        f = PhotoFilter(year=2023, favorites_only=True)
        assert "favorites" in f.describe().lower()


class TestDateValidation:
    """Tests for date validation."""

    def test_validate_date_valid(self):
        """Test validate_date with valid dates."""
        from core import validate_date

        is_valid, error, d = validate_date("2023-06-15")
        assert is_valid
        assert d.year == 2023
        assert d.month == 6
        assert d.day == 15

    def test_validate_date_empty(self):
        """Test validate_date with empty string."""
        from core import validate_date

        is_valid, error, d = validate_date("")
        assert is_valid
        assert d is None

    def test_validate_date_invalid_format(self):
        """Test validate_date with invalid format."""
        from core import validate_date

        is_valid, error, d = validate_date("06/15/2023")
        assert not is_valid
        assert "YYYY-MM-DD" in error

    def test_validate_date_out_of_range(self):
        """Test validate_date with out of range year."""
        from core import validate_date

        is_valid, error, d = validate_date("1800-01-01")
        assert not is_valid
        assert "between" in error.lower()
