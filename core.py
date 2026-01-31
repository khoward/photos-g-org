"""
Core business logic for Google Photos Organizer.
Shared between CLI, TUI, and Web interfaces.
"""

import os
import json
import secrets
import stat
from dataclasses import dataclass, field
from datetime import datetime, date
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Optional, Callable, Generator, List

from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

# Constants
SCOPES = [
    'https://www.googleapis.com/auth/photoslibrary',
    'https://www.googleapis.com/auth/photoslibrary.sharing'
]
CONFIG_DIR = Path.home() / '.config' / 'gporg'
CONFIG_FILE = CONFIG_DIR / 'config.json'
TOKEN_FILE = CONFIG_DIR / 'token.json'
BATCH_SIZE = 50  # Google API limit
MAX_ALBUM_SIZE = 20000  # Google API limit

# Security constants
API_KEY_LENGTH = 32
MAX_ALBUM_NAME_LENGTH = 500
MIN_YEAR = 1900
MAX_YEAR = 2100

# Media types
MEDIA_TYPE_ALL = 'ALL'
MEDIA_TYPE_PHOTO = 'PHOTO'
MEDIA_TYPE_VIDEO = 'VIDEO'

# Content categories (Google Photos API)
CONTENT_CATEGORIES = [
    'NONE', 'LANDSCAPES', 'RECEIPTS', 'CITYSCAPES', 'LANDMARKS',
    'SELFIES', 'PEOPLE', 'PETS', 'WEDDINGS', 'BIRTHDAYS',
    'DOCUMENTS', 'TRAVEL', 'ANIMALS', 'FOOD', 'SPORT',
    'NIGHT', 'PERFORMANCES', 'WHITEBOARDS', 'SCREENSHOTS', 'UTILITY'
]


@dataclass
class PhotoFilter:
    """
    Filter options for searching photos.

    All filter parameters are optional. When not provided, no filter
    is applied for that criterion.
    """
    # Date range filters (takes precedence over year if both provided)
    start_date: Optional[date] = None
    end_date: Optional[date] = None

    # Legacy year filter (used if start_date/end_date not provided)
    year: Optional[int] = None

    # Media type filter: PHOTO, VIDEO, or ALL (default)
    media_type: str = MEDIA_TYPE_ALL

    # Content categories to include (e.g., ['LANDSCAPES', 'SELFIES'])
    categories: List[str] = field(default_factory=list)

    # Only return favorite/starred items
    favorites_only: bool = False

    def to_api_filter(self) -> dict:
        """
        Convert filter options to Google Photos API filter body.

        Returns:
            dict: Filter body for mediaItems.search API call
        """
        filters = {}

        # Date filter - prioritize date range over year
        if self.start_date or self.end_date:
            date_range = {}
            if self.start_date:
                date_range['startDate'] = {
                    'year': self.start_date.year,
                    'month': self.start_date.month,
                    'day': self.start_date.day
                }
            if self.end_date:
                date_range['endDate'] = {
                    'year': self.end_date.year,
                    'month': self.end_date.month,
                    'day': self.end_date.day
                }
            filters['dateFilter'] = {'ranges': [date_range]}
        elif self.year:
            filters['dateFilter'] = {
                'ranges': [{
                    'startDate': {'year': self.year, 'month': 1, 'day': 1},
                    'endDate': {'year': self.year, 'month': 12, 'day': 31}
                }]
            }

        # Media type filter
        if self.media_type != MEDIA_TYPE_ALL:
            filters['mediaTypeFilter'] = {
                'mediaTypes': [self.media_type]
            }

        # Content category filter
        if self.categories:
            # Validate categories
            valid_categories = [c for c in self.categories if c in CONTENT_CATEGORIES]
            if valid_categories:
                filters['contentFilter'] = {
                    'includedContentCategories': valid_categories
                }

        # Feature filter (favorites)
        if self.favorites_only:
            filters['featureFilter'] = {
                'includedFeatures': ['FAVORITES']
            }

        return filters

    def describe(self) -> str:
        """Return a human-readable description of the filter."""
        parts = []

        if self.start_date or self.end_date:
            if self.start_date and self.end_date:
                parts.append(f"from {self.start_date} to {self.end_date}")
            elif self.start_date:
                parts.append(f"from {self.start_date} onwards")
            else:
                parts.append(f"up to {self.end_date}")
        elif self.year:
            parts.append(f"from {self.year}")

        if self.media_type != MEDIA_TYPE_ALL:
            parts.append(f"type: {self.media_type.lower()}s")

        if self.categories:
            parts.append(f"categories: {', '.join(self.categories)}")

        if self.favorites_only:
            parts.append("favorites only")

        return "; ".join(parts) if parts else "all photos"


def _set_secure_permissions(path: Path):
    """Set file permissions to owner-only (600)."""
    try:
        os.chmod(path, stat.S_IRUSR | stat.S_IWUSR)
    except OSError:
        pass  # Best effort on systems that don't support chmod


def _generate_api_key() -> str:
    """Generate a secure random API key."""
    return secrets.token_urlsafe(API_KEY_LENGTH)


def validate_credentials_path(path: str) -> tuple[bool, str]:
    """
    Validate that a credentials path is safe to use for OAuth 2.0 client credentials.

    Returns:
        Tuple of (is_valid, error_message_or_expanded_path)
    """
    if not path:
        return False, "Path is required"

    # Expand user path
    expanded = os.path.expanduser(path)
    path_obj = Path(expanded)

    # Must exist
    if not path_obj.exists():
        return False, "File not found"

    # Must be a file, not directory
    if not path_obj.is_file():
        return False, "Path must be a file"

    # Must have .json extension
    if path_obj.suffix.lower() != '.json':
        return False, "File must be a JSON file"

    # Must be readable
    if not os.access(expanded, os.R_OK):
        return False, "File is not readable"

    # Try to parse as JSON to verify it's valid OAuth client credentials
    try:
        with open(expanded) as f:
            data = json.load(f)
        # Check for OAuth client credentials format (has "installed" or "web" key)
        if 'installed' not in data and 'web' not in data:
            return False, "File does not appear to be an OAuth client credentials JSON (missing 'installed' or 'web' key)"
    except json.JSONDecodeError:
        return False, "File is not valid JSON"
    except IOError as e:
        return False, f"Cannot read file: {e}"

    return True, expanded


def validate_year(year) -> tuple[bool, str, Optional[int]]:
    """
    Validate year input.

    Returns:
        Tuple of (is_valid, error_message, validated_year)
    """
    if year is None:
        return False, "Year is required", None

    try:
        year_int = int(year)
    except (TypeError, ValueError):
        return False, "Year must be a number", None

    if year_int < MIN_YEAR or year_int > MAX_YEAR:
        return False, f"Year must be between {MIN_YEAR} and {MAX_YEAR}", None

    return True, "", year_int


def validate_album_name(name: str) -> tuple[bool, str]:
    """
    Validate album name.

    Returns:
        Tuple of (is_valid, error_message)
    """
    if not name:
        return False, "Album name is required"

    if len(name) > MAX_ALBUM_NAME_LENGTH:
        return False, f"Album name must be {MAX_ALBUM_NAME_LENGTH} characters or less"

    # Basic sanitization - no control characters
    if any(ord(c) < 32 for c in name):
        return False, "Album name contains invalid characters"

    return True, ""


def validate_date(date_str: str) -> tuple[bool, str, Optional[date]]:
    """
    Validate a date string in YYYY-MM-DD format.

    Returns:
        Tuple of (is_valid, error_message, validated_date)
    """
    if not date_str:
        return True, "", None  # Empty is valid (optional)

    try:
        parsed = datetime.strptime(date_str, '%Y-%m-%d').date()
    except ValueError:
        return False, "Date must be in YYYY-MM-DD format", None

    # Sanity check the year
    if parsed.year < MIN_YEAR or parsed.year > MAX_YEAR:
        return False, f"Year must be between {MIN_YEAR} and {MAX_YEAR}", None

    return True, "", parsed


def validate_media_type(media_type: str) -> tuple[bool, str]:
    """
    Validate media type string.

    Returns:
        Tuple of (is_valid, error_message)
    """
    if not media_type:
        return True, ""  # Empty defaults to ALL

    valid_types = [MEDIA_TYPE_ALL, MEDIA_TYPE_PHOTO, MEDIA_TYPE_VIDEO]
    if media_type.upper() not in valid_types:
        return False, f"Media type must be one of: {', '.join(valid_types)}"
    return True, ""


def validate_categories(categories: List[str]) -> tuple[bool, str, List[str]]:
    """
    Validate content categories.

    Returns:
        Tuple of (is_valid, error_message, validated_categories)
    """
    if not categories:
        return True, "", []

    # Normalize to uppercase
    normalized = [c.upper() for c in categories]

    invalid = [c for c in normalized if c not in CONTENT_CATEGORIES]
    if invalid:
        return False, f"Invalid categories: {', '.join(invalid)}. Valid options: {', '.join(CONTENT_CATEGORIES)}", []

    return True, "", normalized


class Config:
    """Configuration management for gporg."""

    def __init__(self):
        self.credentials_path: Optional[str] = None
        self.api_key: Optional[str] = None
        self._load()

    def _load(self):
        """Load config from file."""
        if CONFIG_FILE.exists():
            try:
                with open(CONFIG_FILE) as f:
                    data = json.load(f)
                    self.credentials_path = data.get('credentials_path')
                    self.api_key = data.get('api_key')
            except (json.JSONDecodeError, IOError):
                pass

    def save(self):
        """Save config to file with secure permissions."""
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)

        with open(CONFIG_FILE, 'w') as f:
            json.dump({
                'credentials_path': self.credentials_path,
                'api_key': self.api_key
            }, f, indent=2)

        # Set secure permissions on config file
        _set_secure_permissions(CONFIG_FILE)

    def set_credentials(self, path: str):
        """Set and save credentials path."""
        self.credentials_path = path
        self.save()

    def get_or_create_api_key(self) -> str:
        """Get existing API key or generate a new one."""
        if not self.api_key:
            self.api_key = _generate_api_key()
            self.save()
        return self.api_key

    def regenerate_api_key(self) -> str:
        """Generate a new API key, invalidating the old one."""
        self.api_key = _generate_api_key()
        self.save()
        return self.api_key

    def verify_api_key(self, key: str) -> bool:
        """Verify an API key matches the stored key."""
        if not self.api_key or not key:
            return False
        # Use constant-time comparison to prevent timing attacks
        return secrets.compare_digest(self.api_key, key)

    @property
    def is_configured(self) -> bool:
        """Check if credentials are configured and file exists."""
        return (
            self.credentials_path is not None
            and Path(self.credentials_path).exists()
        )

    @property
    def is_authorized(self) -> bool:
        """Check if OAuth token exists (user has completed authorization)."""
        return TOKEN_FILE.exists()

    @property
    def token_path(self) -> Path:
        """Get the path to the OAuth token file."""
        return TOKEN_FILE

    @property
    def credentials_filename(self) -> Optional[str]:
        """Get just the filename of credentials (not full path) for display."""
        if self.credentials_path:
            return Path(self.credentials_path).name
        return None

    def clear_token(self):
        """Remove the stored OAuth token (for logout/re-authorization)."""
        if TOKEN_FILE.exists():
            TOKEN_FILE.unlink()

    def load_credentials(self) -> Optional[Credentials]:
        """
        Load OAuth credentials from token file, refreshing if needed.

        Returns:
            Valid Credentials object or None if not authorized.
        """
        if not TOKEN_FILE.exists():
            return None

        try:
            creds = Credentials.from_authorized_user_file(str(TOKEN_FILE), SCOPES)
        except (json.JSONDecodeError, ValueError, KeyError):
            # Token file is corrupted, remove it
            TOKEN_FILE.unlink()
            return None

        # Refresh if expired
        if creds and creds.expired and creds.refresh_token:
            try:
                creds.refresh(Request())
                self._save_token(creds)
            except Exception:
                # Refresh failed, token is invalid
                TOKEN_FILE.unlink()
                return None

        return creds if creds and creds.valid else None

    def _save_token(self, creds: Credentials):
        """Save credentials to token file with secure permissions."""
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        with open(TOKEN_FILE, 'w') as f:
            f.write(creds.to_json())
        _set_secure_permissions(TOKEN_FILE)


class AuthorizationError(Exception):
    """Raised when OAuth authorization is required but not available."""
    pass


def authorize(credentials_path: str, open_browser: bool = True) -> Credentials:
    """
    Run the OAuth 2.0 authorization flow.

    Args:
        credentials_path: Path to OAuth client credentials JSON file.
        open_browser: If True, automatically open browser for consent.

    Returns:
        Authorized Credentials object.

    Raises:
        FileNotFoundError: If credentials file doesn't exist.
        ValueError: If credentials file is invalid.
    """
    if not Path(credentials_path).exists():
        raise FileNotFoundError(f"Credentials file not found: {credentials_path}")

    flow = InstalledAppFlow.from_client_secrets_file(credentials_path, SCOPES)

    if open_browser:
        creds = flow.run_local_server(port=0)
    else:
        creds = flow.run_console()

    # Save the token
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    with open(TOKEN_FILE, 'w') as f:
        f.write(creds.to_json())
    _set_secure_permissions(TOKEN_FILE)

    return creds


class PhotosService:
    """Google Photos API service wrapper using OAuth 2.0."""

    def __init__(self, config: Config):
        """
        Initialize PhotosService with OAuth credentials.

        Args:
            config: Config object containing credentials path and token management.

        Raises:
            AuthorizationError: If not authorized and authorization is required.
        """
        self._config = config
        self._service = None
        self._creds = None

    @property
    def service(self):
        """Lazy-load the service with OAuth credentials."""
        if self._service is None:
            # Try to load existing credentials
            self._creds = self._config.load_credentials()

            if self._creds is None:
                raise AuthorizationError(
                    "Not authorized. Run authorization flow first using authorize()."
                )

            self._service = build(
                'photoslibrary', 'v1',
                credentials=self._creds,
                static_discovery=False
            )
        return self._service

    def ensure_authorized(self, open_browser: bool = True) -> bool:
        """
        Ensure user is authorized, running OAuth flow if needed.

        Args:
            open_browser: If True, automatically open browser for consent.

        Returns:
            True if authorized (existing or new), False if authorization failed.
        """
        # Check if already authorized
        self._creds = self._config.load_credentials()
        if self._creds is not None:
            return True

        # Need to run authorization flow
        if not self._config.credentials_path:
            return False

        try:
            self._creds = authorize(self._config.credentials_path, open_browser)
            self._service = None  # Force service rebuild with new creds
            return True
        except Exception:
            return False

    def list_albums(self, page_size: int = 50) -> list[dict]:
        """List all albums."""
        albums = []
        page_token = None

        while True:
            results = self.service.albums().list(
                pageSize=page_size,
                pageToken=page_token
            ).execute()

            albums.extend(results.get('albums', []))
            page_token = results.get('nextPageToken')

            if not page_token:
                break

        return albums

    def get_album(self, album_id: str) -> Optional[dict]:
        """Get album by ID."""
        try:
            return self.service.albums().get(albumId=album_id).execute()
        except HttpError:
            return None

    def create_album(self, title: str) -> dict:
        """Create a new album."""
        body = {'album': {'title': title}}
        return self.service.albums().create(body=body).execute()

    def get_or_create_album(self, title: str) -> str:
        """Get existing album by title or create new one. Returns album ID."""
        albums = self.list_albums()
        for album in albums:
            if album.get('title') == title:
                return album['id']

        new_album = self.create_album(title)
        return new_album['id']

    def get_album_photos(self, album_id: str) -> list[str]:
        """Get all photo IDs in an album."""
        photo_ids = []
        page_token = None

        while True:
            body = {'albumId': album_id, 'pageSize': 100}
            if page_token:
                body['pageToken'] = page_token

            results = self.service.mediaItems().search(body=body).execute()
            items = results.get('mediaItems', [])
            photo_ids.extend(item['id'] for item in items)

            page_token = results.get('nextPageToken')
            if not page_token:
                break

        return photo_ids

    def search_photos_by_year(
        self,
        year: int,
        progress_callback: Optional[Callable[[int], None]] = None
    ) -> list[dict]:
        """Search for photos from a specific year (legacy method)."""
        photo_filter = PhotoFilter(year=year)
        return self.search_photos(photo_filter, progress_callback)

    def search_photos(
        self,
        photo_filter: PhotoFilter,
        progress_callback: Optional[Callable[[int], None]] = None
    ) -> list[dict]:
        """
        Search for photos with flexible filtering options.

        Args:
            photo_filter: PhotoFilter object with filter criteria
            progress_callback: Called with count of items found so far

        Returns:
            List of media item dictionaries from Google Photos API
        """
        # Build search body from filter
        api_filters = photo_filter.to_api_filter()

        search_body = {"pageSize": 100}
        if api_filters:
            search_body["filters"] = api_filters

        items = []
        page_token = None

        while True:
            if page_token:
                search_body['pageToken'] = page_token

            results = self.service.mediaItems().search(body=search_body).execute()
            new_items = results.get('mediaItems', [])
            items.extend(new_items)

            if progress_callback:
                progress_callback(len(items))

            page_token = results.get('nextPageToken')
            if not page_token:
                break

        return items

    def _add_batch(self, album_id: str, photo_ids: list[str]) -> int:
        """Add a single batch of photos to album. Returns count added."""
        if not photo_ids:
            return 0

        body = {"mediaItemIds": photo_ids}
        self.service.albums().batchAddMediaItems(
            albumId=album_id, body=body
        ).execute()
        return len(photo_ids)

    def add_to_album(
        self,
        album_id: str,
        photo_ids: list[str],
        skip_existing: bool = True,
        workers: int = 4,
        progress_callback: Optional[Callable[[int, int], None]] = None
    ) -> Generator[tuple[int, int], None, None]:
        """
        Add photos to album with parallel batching.

        Args:
            album_id: Target album ID
            photo_ids: List of photo IDs to add
            skip_existing: If True, skip photos already in album
            workers: Number of parallel workers
            progress_callback: Called with (added_count, total_count)

        Yields:
            Tuple of (photos_added_so_far, total_to_add)
        """
        if not photo_ids:
            return

        # Filter out existing photos if requested
        if skip_existing:
            existing_ids = set(self.get_album_photos(album_id))
            photo_ids = [pid for pid in photo_ids if pid not in existing_ids]

        if not photo_ids:
            yield (0, 0)
            return

        total = len(photo_ids)
        added = 0

        # Split into batches
        batches = [
            photo_ids[i:i + BATCH_SIZE]
            for i in range(0, len(photo_ids), BATCH_SIZE)
        ]

        # Process batches in parallel
        with ThreadPoolExecutor(max_workers=workers) as executor:
            futures = {
                executor.submit(self._add_batch, album_id, batch): batch
                for batch in batches
            }

            for future in as_completed(futures):
                try:
                    count = future.result()
                    added += count
                    if progress_callback:
                        progress_callback(added, total)
                    yield (added, total)
                except HttpError as e:
                    # Log error but continue with other batches
                    print(f"Error adding batch: {e}")

    def add_to_album_sync(
        self,
        album_id: str,
        photo_ids: list[str],
        skip_existing: bool = True,
        workers: int = 4,
        progress_callback: Optional[Callable[[int, int], None]] = None
    ) -> int:
        """
        Synchronous version of add_to_album.
        Returns total photos added.
        """
        result = 0
        for added, total in self.add_to_album(
            album_id, photo_ids, skip_existing, workers, progress_callback
        ):
            result = added
        return result


def get_available_years() -> list[int]:
    """Get list of years for filtering (current year back to 2000)."""
    from datetime import datetime
    current_year = datetime.now().year
    return list(range(current_year, 1999, -1))
