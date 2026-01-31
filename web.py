"""
Flask web server for Google Photos Organizer.
Provides a beautiful glassmorphism web UI on port 8099.
"""

import os
import time
import logging
import threading
import functools
from pathlib import Path
from collections import defaultdict
from flask import Flask, render_template, jsonify, request, send_from_directory, g

from core import (
    Config, PhotosService, PhotoFilter, get_available_years,
    validate_credentials_path, validate_year, validate_album_name,
    validate_date, validate_media_type, validate_categories,
    MEDIA_TYPE_ALL, MEDIA_TYPE_PHOTO, MEDIA_TYPE_VIDEO, CONTENT_CATEGORIES
)

app = Flask(__name__)
config = Config()

# Configure logging - don't expose to clients
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Global state for tracking organization progress
organize_state = {
    'running': False,
    'progress': 0,
    'total': 0,
    'message': '',
    'error': None
}
organize_lock = threading.Lock()

# Rate limiting storage
rate_limit_storage = defaultdict(list)
rate_limit_lock = threading.Lock()

# Rate limit settings
RATE_LIMIT_REQUESTS = 60  # requests per window
RATE_LIMIT_WINDOW = 60  # seconds


def get_client_ip():
    """Get client IP address, handling proxies."""
    if request.headers.get('X-Forwarded-For'):
        return request.headers.get('X-Forwarded-For').split(',')[0].strip()
    return request.remote_addr or 'unknown'


def check_rate_limit():
    """Check if client has exceeded rate limit."""
    client_ip = get_client_ip()
    current_time = time.time()

    with rate_limit_lock:
        # Clean old entries
        rate_limit_storage[client_ip] = [
            t for t in rate_limit_storage[client_ip]
            if current_time - t < RATE_LIMIT_WINDOW
        ]

        # Check limit
        if len(rate_limit_storage[client_ip]) >= RATE_LIMIT_REQUESTS:
            return False

        # Record request
        rate_limit_storage[client_ip].append(current_time)
        return True


def require_api_key(f):
    """Decorator to require API key authentication."""
    @functools.wraps(f)
    def decorated(*args, **kwargs):
        # Get API key from header or query param
        api_key = request.headers.get('X-API-Key') or request.args.get('api_key')

        if not api_key:
            return jsonify({'error': 'API key required'}), 401

        if not config.verify_api_key(api_key):
            logger.warning(f"Invalid API key attempt from {get_client_ip()}")
            return jsonify({'error': 'Invalid API key'}), 401

        return f(*args, **kwargs)
    return decorated


def rate_limited(f):
    """Decorator to apply rate limiting."""
    @functools.wraps(f)
    def decorated(*args, **kwargs):
        if not check_rate_limit():
            logger.warning(f"Rate limit exceeded for {get_client_ip()}")
            return jsonify({'error': 'Rate limit exceeded. Please try again later.'}), 429
        return f(*args, **kwargs)
    return decorated


def safe_error_response(error_msg: str, status_code: int = 500):
    """Return a safe error response without leaking internal details."""
    return jsonify({'error': error_msg}), status_code


@app.after_request
def add_security_headers(response):
    """Add security headers to all responses."""
    # Prevent clickjacking
    response.headers['X-Frame-Options'] = 'DENY'
    # Prevent MIME sniffing
    response.headers['X-Content-Type-Options'] = 'nosniff'
    # XSS protection
    response.headers['X-XSS-Protection'] = '1; mode=block'
    # Content Security Policy
    response.headers['Content-Security-Policy'] = (
        "default-src 'self'; "
        "script-src 'self' 'unsafe-inline'; "
        "style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
        "img-src 'self' data:; "
        "font-src 'self' https://cdn.jsdelivr.net; "
        "connect-src 'self'; "
        "frame-ancestors 'none';"
    )
    # Referrer policy
    response.headers['Referrer-Policy'] = 'strict-origin-when-cross-origin'
    return response


@app.route('/')
@rate_limited
def index():
    """Main page."""
    return render_template('index.html')


@app.route('/static/<path:filename>')
@rate_limited
def static_files(filename):
    """Serve static files."""
    # send_from_directory is safe against path traversal
    return send_from_directory('static', filename)


@app.route('/api/config', methods=['GET'])
@rate_limited
@require_api_key
def get_config():
    """Get current configuration (without exposing sensitive paths)."""
    return jsonify({
        'configured': config.is_configured,
        # Only return filename, not full path
        'credentials_file': config.credentials_filename
    })


@app.route('/api/config', methods=['POST'])
@rate_limited
@require_api_key
def set_config():
    """Set credentials path with validation."""
    data = request.get_json()
    if not data:
        return safe_error_response('Invalid request body', 400)

    path = data.get('credentials_path')

    # Validate the credentials path
    is_valid, result = validate_credentials_path(path)
    if not is_valid:
        return safe_error_response(result, 400)

    # result contains the expanded path on success
    config.set_credentials(result)
    logger.info(f"Credentials updated by {get_client_ip()}")

    return jsonify({
        'success': True,
        'credentials_file': config.credentials_filename
    })


@app.route('/api/albums', methods=['GET'])
@rate_limited
@require_api_key
def list_albums():
    """List available albums."""
    if not config.is_configured:
        return safe_error_response('Not configured', 400)

    try:
        service = PhotosService(config)
        if not service.ensure_authorized():
            return safe_error_response('Authorization required', 401)

        albums = service.list_albums()
        return jsonify({
            'albums': [
                {'id': a['id'], 'title': a.get('title', 'Untitled')}
                for a in albums
            ]
        })
    except Exception as e:
        logger.error(f"Error listing albums: {e}")
        return safe_error_response('Failed to list albums', 500)


@app.route('/api/years', methods=['GET'])
@rate_limited
def list_years():
    """List available years for filtering (no auth required - public data)."""
    return jsonify({'years': get_available_years()})


@app.route('/api/filter-options', methods=['GET'])
@rate_limited
def get_filter_options():
    """Get available filter options (no auth required - public data)."""
    return jsonify({
        'media_types': [MEDIA_TYPE_ALL, MEDIA_TYPE_PHOTO, MEDIA_TYPE_VIDEO],
        'categories': CONTENT_CATEGORIES,
        'years': get_available_years()
    })


@app.route('/api/organize', methods=['POST'])
@rate_limited
@require_api_key
def start_organize():
    """Start organizing photos with advanced filter options."""
    global organize_state

    with organize_lock:
        if organize_state['running']:
            return safe_error_response('Organization already in progress', 400)

    if not config.is_configured:
        return safe_error_response('Not configured', 400)

    data = request.get_json()
    if not data:
        return safe_error_response('Invalid request body', 400)

    # Build PhotoFilter from request data
    photo_filter = PhotoFilter()

    # Date filtering - support both date range and legacy year
    start_date_str = data.get('start_date')
    end_date_str = data.get('end_date')
    year = data.get('year')

    if start_date_str or end_date_str:
        # Date range filtering
        if start_date_str:
            valid, error, start_date = validate_date(start_date_str)
            if not valid:
                return safe_error_response(f"Invalid start_date: {error}", 400)
            photo_filter.start_date = start_date

        if end_date_str:
            valid, error, end_date = validate_date(end_date_str)
            if not valid:
                return safe_error_response(f"Invalid end_date: {error}", 400)
            photo_filter.end_date = end_date

        # Validate date range
        if photo_filter.start_date and photo_filter.end_date:
            if photo_filter.start_date > photo_filter.end_date:
                return safe_error_response("start_date must be before end_date", 400)
    elif year is not None:
        # Legacy year filtering
        year_valid, year_error, validated_year = validate_year(year)
        if not year_valid:
            return safe_error_response(year_error, 400)
        photo_filter.year = validated_year
    else:
        return safe_error_response("Must provide year or start_date/end_date", 400)

    # Media type filter
    media_type = data.get('media_type', MEDIA_TYPE_ALL)
    if media_type:
        valid, error = validate_media_type(media_type)
        if not valid:
            return safe_error_response(error, 400)
        photo_filter.media_type = media_type.upper()

    # Categories filter
    categories = data.get('categories', [])
    if categories:
        if isinstance(categories, str):
            categories = [categories]
        valid, error, validated_categories = validate_categories(categories)
        if not valid:
            return safe_error_response(error, 400)
        photo_filter.categories = validated_categories

    # Favorites filter
    photo_filter.favorites_only = bool(data.get('favorites_only', False))

    # Album options
    album_id = data.get('album_id')
    album_name = data.get('album_name')
    skip_existing = data.get('skip_existing', True)

    # Validate album
    if not album_id and not album_name:
        return safe_error_response('Album ID or name is required', 400)

    if album_name:
        name_valid, name_error = validate_album_name(album_name)
        if not name_valid:
            return safe_error_response(name_error, 400)

    # Validate skip_existing is boolean
    if not isinstance(skip_existing, bool):
        skip_existing = bool(skip_existing)

    filter_desc = photo_filter.describe()
    logger.info(f"Organization started by {get_client_ip()}: {filter_desc}")

    # Start organization in background thread
    thread = threading.Thread(
        target=_run_organize,
        args=(photo_filter, album_id, album_name, skip_existing)
    )
    thread.daemon = True
    thread.start()

    return jsonify({'success': True, 'message': 'Organization started', 'filter': filter_desc})


def _run_organize(photo_filter: PhotoFilter, album_id: str, album_name: str, skip_existing: bool):
    """Run organization in background with advanced filtering."""
    global organize_state

    filter_desc = photo_filter.describe()

    with organize_lock:
        organize_state = {
            'running': True,
            'progress': 0,
            'total': 0,
            'message': 'Starting...',
            'error': None,
            'filter': filter_desc
        }

    try:
        service = PhotosService(config)

        # Ensure we're authorized
        if not service.ensure_authorized():
            with organize_lock:
                organize_state['running'] = False
                organize_state['error'] = 'Authorization required'
                organize_state['message'] = 'Error: Authorization required. Please authorize first.'
            return

        # Get or create album
        with organize_lock:
            organize_state['message'] = 'Finding/creating album...'

        if album_id:
            target_album_id = album_id
        else:
            target_album_id = service.get_or_create_album(album_name)

        # Search for photos with filter
        with organize_lock:
            organize_state['message'] = f'Searching for photos ({filter_desc})...'

        def search_progress(count):
            with organize_lock:
                organize_state['message'] = f'Found {count} photos ({filter_desc})...'

        photos = service.search_photos(photo_filter, progress_callback=search_progress)
        photo_ids = [p['id'] for p in photos]

        if not photo_ids:
            with organize_lock:
                organize_state['running'] = False
                organize_state['message'] = f'No photos found matching filter ({filter_desc})'
            return

        with organize_lock:
            organize_state['total'] = len(photo_ids)
            organize_state['message'] = f'Adding {len(photo_ids)} photos to album...'

        # Add to album with progress updates
        def add_progress(added, total):
            with organize_lock:
                organize_state['progress'] = added
                organize_state['total'] = total
                organize_state['message'] = f'Added {added}/{total} photos...'

        final_count = service.add_to_album_sync(
            target_album_id,
            photo_ids,
            skip_existing=skip_existing,
            progress_callback=add_progress
        )

        with organize_lock:
            organize_state['running'] = False
            organize_state['progress'] = final_count
            organize_state['message'] = f'Done! Added {final_count} photos to album.'

        logger.info(f"Organization completed: {final_count} photos added")

    except Exception as e:
        logger.error(f"Organization failed: {e}")
        with organize_lock:
            organize_state['running'] = False
            organize_state['error'] = 'Organization failed'
            organize_state['message'] = 'Error: Organization failed. Check server logs.'


@app.route('/api/status', methods=['GET'])
@rate_limited
@require_api_key
def get_status():
    """Get current organization status."""
    with organize_lock:
        return jsonify(organize_state.copy())


@app.route('/api/key', methods=['GET'])
def get_initial_key():
    """
    Get or create API key. This endpoint is only accessible from localhost.
    The key is shown once and should be saved by the user.
    """
    # Only allow from localhost
    client_ip = get_client_ip()
    if client_ip not in ('127.0.0.1', '::1', 'localhost'):
        logger.warning(f"API key request from non-local IP: {client_ip}")
        return safe_error_response('This endpoint is only accessible from localhost', 403)

    api_key = config.get_or_create_api_key()
    return jsonify({
        'api_key': api_key,
        'message': 'Save this API key securely. Include it in requests as X-API-Key header.'
    })


@app.route('/api/key/regenerate', methods=['POST'])
def regenerate_key():
    """
    Regenerate API key. This endpoint is only accessible from localhost.
    """
    client_ip = get_client_ip()
    if client_ip not in ('127.0.0.1', '::1', 'localhost'):
        logger.warning(f"API key regenerate request from non-local IP: {client_ip}")
        return safe_error_response('This endpoint is only accessible from localhost', 403)

    api_key = config.regenerate_api_key()
    logger.info("API key regenerated")
    return jsonify({
        'api_key': api_key,
        'message': 'New API key generated. Old key is now invalid.'
    })


def run_server(host: str = '127.0.0.1', port: int = 8099, debug: bool = False, public: bool = False):
    """
    Run the Flask server.

    Args:
        host: Host to bind to (default: localhost only)
        port: Port to listen on
        debug: Enable debug mode (NEVER in production)
        public: If True, bind to 0.0.0.0 for network access
    """
    if public:
        host = '0.0.0.0'
        print("WARNING: Server is accessible from the network!")
        print("Make sure to use the API key for authentication.")

    # Generate API key on first run
    api_key = config.get_or_create_api_key()

    print(f"Starting web server at http://{host}:{port}")
    print(f"\nAPI Key (save this!): {api_key}")
    print("\nInclude this key in requests as 'X-API-Key' header")

    if public:
        print(f"\nAccess from other devices: http://<your-ip>:{port}")

    app.run(host=host, port=port, debug=debug, threaded=True)


if __name__ == '__main__':
    run_server(debug=True)
