"""
Core business logic for Google Photos Organizer.
Shared between CLI, TUI, and Web interfaces.
"""

import os
import json
import secrets
import stat
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Optional, Callable, Generator

from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

# Constants
SCOPES = [
    'https://www.googleapis.com/auth/photoslibrary',
    'https://www.googleapis.com/auth/photoslibrary.sharing'
]
CONFIG_DIR = Path.home() / '.config' / 'gporg'
CONFIG_FILE = CONFIG_DIR / 'config.json'
BATCH_SIZE = 50  # Google API limit
MAX_ALBUM_SIZE = 20000  # Google API limit

# Security constants
API_KEY_LENGTH = 32
MAX_ALBUM_NAME_LENGTH = 500
MIN_YEAR = 1900
MAX_YEAR = 2100


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
    Validate that a credentials path is safe to use.

    Returns:
        Tuple of (is_valid, error_message)
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

    # Try to parse as JSON to verify it's valid
    try:
        with open(expanded) as f:
            data = json.load(f)
        # Check for expected service account fields
        if 'type' not in data or data.get('type') != 'service_account':
            return False, "File does not appear to be a service account JSON"
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
    def credentials_filename(self) -> Optional[str]:
        """Get just the filename of credentials (not full path) for display."""
        if self.credentials_path:
            return Path(self.credentials_path).name
        return None


class PhotosService:
    """Google Photos API service wrapper."""

    def __init__(self, credentials_path: str):
        self.credentials_path = credentials_path
        self._service = None

    @property
    def service(self):
        """Lazy-load the service."""
        if self._service is None:
            creds = service_account.Credentials.from_service_account_file(
                self.credentials_path, scopes=SCOPES
            )
            self._service = build(
                'photoslibrary', 'v1',
                credentials=creds,
                static_discovery=False
            )
        return self._service

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
        """Search for photos from a specific year."""
        search_body = {
            "filters": {
                "dateFilter": {
                    "ranges": [{
                        "startDate": {"year": year, "month": 1, "day": 1},
                        "endDate": {"year": year, "month": 12, "day": 31}
                    }]
                }
            },
            "pageSize": 100
        }

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
