#!/usr/bin/env python3
"""
Google Photos Organizer - Unified CLI

Usage:
    gporg                     # Start TUI (default)
    gporg web                 # Start web server
    gporg web --stop          # Stop background web server
    gporg config <path>       # Set credentials
    gporg config --show       # Show current config
    gporg organize --year N   # Quick organize from CLI
"""

import argparse
import logging
import os
import sys
import signal
from pathlib import Path

from core import (
    Config, PhotosService, PhotoFilter, get_available_years,
    validate_credentials_path, validate_year, validate_date,
    validate_media_type, validate_categories,
    MEDIA_TYPE_ALL, MEDIA_TYPE_PHOTO, MEDIA_TYPE_VIDEO, CONTENT_CATEGORIES
)

# Verbosity levels: 0=WARNING, 1=INFO, 2=DEBUG, 3+=TRACE (DEBUG with extra)
VERBOSITY = 0

def setup_logging(verbosity: int):
    """Configure logging based on verbosity level."""
    global VERBOSITY
    VERBOSITY = verbosity

    if verbosity == 0:
        level = logging.WARNING
    elif verbosity == 1:
        level = logging.INFO
    else:
        level = logging.DEBUG

    # Format varies by verbosity
    if verbosity >= 3:
        fmt = '%(asctime)s %(levelname)s %(name)s:%(lineno)d %(message)s'
    elif verbosity >= 2:
        fmt = '%(levelname)s %(name)s: %(message)s'
    elif verbosity >= 1:
        fmt = '%(levelname)s: %(message)s'
    else:
        fmt = '%(message)s'

    logging.basicConfig(level=level, format=fmt)

    # Set third-party loggers to WARNING unless very verbose
    if verbosity < 3:
        logging.getLogger('urllib3').setLevel(logging.WARNING)
        logging.getLogger('googleapiclient').setLevel(logging.WARNING)

def log_debug(msg):
    """Log debug message."""
    logging.debug(msg)

def log_info(msg):
    """Log info message."""
    logging.info(msg)

def log_trace(msg):
    """Log trace message (only at -vvv or higher)."""
    if VERBOSITY >= 3:
        logging.debug(f"[TRACE] {msg}")

PID_FILE = Path.home() / '.config' / 'gporg' / 'web.pid'


def cmd_tui(args):
    """Launch the terminal UI."""
    from tui import run_tui
    run_tui()


def cmd_web(args):
    """Start or stop the web server."""
    if args.stop:
        log_info("Stopping web server")
        stop_web_server()
        return

    from web import run_server

    if args.background:
        log_info(f"Starting web server in background on port {args.port}")
        start_web_background(args.port, args.public)
    else:
        log_info(f"Starting web server on port {args.port} (public={args.public})")
        run_server(port=args.port, public=args.public)


def start_web_background(port: int, public: bool):
    """Start web server in background."""
    import subprocess

    # Build command
    cmd = [sys.executable, '-c', f'''
import sys
sys.path.insert(0, {repr(str(Path(__file__).parent))})
from web import run_server
run_server(port={port}, public={public}, debug=False)
''']

    # Start detached process
    process = subprocess.Popen(
        cmd,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True
    )

    # Save PID
    PID_FILE.parent.mkdir(parents=True, exist_ok=True)
    PID_FILE.write_text(str(process.pid))

    host = '0.0.0.0' if public else '127.0.0.1'
    print(f"Web server started in background (PID: {process.pid})")
    print(f"URL: http://{host}:{port}")
    print(f"Stop with: gporg web --stop")


def stop_web_server():
    """Stop the background web server."""
    if not PID_FILE.exists():
        print("No background web server running.")
        return

    try:
        pid = int(PID_FILE.read_text().strip())
        os.kill(pid, signal.SIGTERM)
        PID_FILE.unlink()
        print(f"Web server stopped (PID: {pid})")
    except ProcessLookupError:
        PID_FILE.unlink()
        print("Web server was not running (stale PID file removed).")
    except ValueError:
        PID_FILE.unlink()
        print("Invalid PID file removed.")
    except PermissionError:
        print(f"Permission denied stopping PID {pid}.")


def cmd_config(args):
    """Configure credentials."""
    log_debug("Loading configuration")
    config = Config()

    if args.show:
        log_trace(f"Config file location: {config.credentials_path}")
        if config.is_configured:
            print(f"Credentials: {config.credentials_path}")
            print(f"API Key: {config.api_key or 'Not generated'}")
        else:
            print("Not configured.")
        return

    if args.path:
        log_info(f"Validating credentials path: {args.path}")
        # Validate and set credentials
        is_valid, result = validate_credentials_path(args.path)
        if not is_valid:
            log_debug(f"Validation failed: {result}")
            print(f"Error: {result}")
            sys.exit(1)

        log_debug(f"Saving credentials: {result}")
        config.set_credentials(result)
        print(f"Credentials saved: {result}")

        # Generate API key if needed
        api_key = config.get_or_create_api_key()
        log_debug("API key generated/retrieved")
        print(f"API Key: {api_key}")
    else:
        # No path given, show current config
        cmd_config(argparse.Namespace(show=True, path=None))


def cmd_organize(args):
    """Organize photos from CLI with flexible filtering."""
    log_debug("Starting organize command")
    config = Config()

    if not config.is_configured:
        print("Error: No credentials configured.")
        print("Run: gporg config /path/to/credentials.json")
        sys.exit(1)

    # Build PhotoFilter from arguments
    photo_filter = PhotoFilter()

    # Handle date range vs year filtering
    if args.start_date or args.end_date:
        # Date range filtering
        if args.start_date:
            is_valid, error, start_date = validate_date(args.start_date)
            if not is_valid:
                print(f"Error: Invalid start date: {error}")
                sys.exit(1)
            photo_filter.start_date = start_date

        if args.end_date:
            is_valid, error, end_date = validate_date(args.end_date)
            if not is_valid:
                print(f"Error: Invalid end date: {error}")
                sys.exit(1)
            photo_filter.end_date = end_date

        # Validate date range
        if photo_filter.start_date and photo_filter.end_date:
            if photo_filter.start_date > photo_filter.end_date:
                print("Error: Start date must be before end date")
                sys.exit(1)
    elif args.year:
        # Legacy year filtering
        is_valid, error, year = validate_year(args.year)
        if not is_valid:
            print(f"Error: {error}")
            sys.exit(1)
        photo_filter.year = year
    else:
        print("Error: Must specify either --year or --start-date/--end-date")
        sys.exit(1)

    # Handle media type
    if args.media_type:
        is_valid, error = validate_media_type(args.media_type)
        if not is_valid:
            print(f"Error: {error}")
            sys.exit(1)
        photo_filter.media_type = args.media_type.upper()

    # Handle categories
    if args.category:
        is_valid, error, categories = validate_categories(args.category)
        if not is_valid:
            print(f"Error: {error}")
            sys.exit(1)
        photo_filter.categories = categories

    # Handle favorites
    photo_filter.favorites_only = args.favorites

    # Generate album name if not provided
    if args.album:
        album_name = args.album
    elif photo_filter.year:
        album_name = f"Photos from {photo_filter.year}"
    elif photo_filter.start_date and photo_filter.end_date:
        album_name = f"Photos {photo_filter.start_date} to {photo_filter.end_date}"
    elif photo_filter.start_date:
        album_name = f"Photos from {photo_filter.start_date}"
    elif photo_filter.end_date:
        album_name = f"Photos until {photo_filter.end_date}"
    else:
        album_name = "Organized Photos"

    skip_existing = not args.no_skip

    filter_desc = photo_filter.describe()
    log_info(f"Organizing: {filter_desc}, album='{album_name}' skip_existing={skip_existing}")
    print(f"Organizing photos ({filter_desc}) into '{album_name}'...")

    try:
        log_debug(f"Creating PhotosService with config")
        service = PhotosService(config)

        # Ensure we're authorized
        if not service.ensure_authorized():
            print("Error: Authorization required. Please authorize through the web interface first.")
            sys.exit(1)

        # Get or create album
        print("Finding/creating album...")
        log_debug(f"Looking for album: {album_name}")
        album_id = service.get_or_create_album(album_name)
        log_info(f"Using album ID: {album_id}")

        # Search for photos with filter
        print(f"Searching for photos ({filter_desc})...")
        log_debug(f"Searching with filter: {photo_filter}")

        def search_progress(count):
            log_trace(f"Search progress: {count} photos found")
            print(f"  Found {count} photos...", end='\r')

        photos = service.search_photos(photo_filter, progress_callback=search_progress)
        print()  # newline after progress

        photo_ids = [p['id'] for p in photos]
        log_info(f"Found {len(photo_ids)} photos matching filter")

        if not photo_ids:
            print(f"No photos found matching filter.")
            return

        print(f"Found {len(photo_ids)} photos. Adding to album...")
        log_debug(f"skip_existing={skip_existing}")

        # Add to album with progress
        def add_progress(added, total):
            log_trace(f"Add progress: {added}/{total}")
            pct = int(added / total * 100) if total > 0 else 0
            bar = '#' * (pct // 5) + '-' * (20 - pct // 5)
            print(f"  [{bar}] {added}/{total} ({pct}%)", end='\r')

        final_count = service.add_to_album_sync(
            album_id,
            photo_ids,
            skip_existing=skip_existing,
            progress_callback=add_progress
        )

        print()  # newline after progress
        log_info(f"Organization complete: {final_count} photos added")
        print(f"Done! Added {final_count} photos to '{album_name}'.")

    except Exception as e:
        logging.debug(f"Exception during organize: {e}", exc_info=True)
        print(f"Error: {e}")
        sys.exit(1)


def main():
    parser = argparse.ArgumentParser(
        description='Google Photos Organizer',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  gporg                              Start TUI (default)
  gporg web                          Start web server on port 8099
  gporg web --public --port 8080     Start on all interfaces, port 8080
  gporg web --background             Start in background
  gporg web --stop                   Stop background server
  gporg config ~/creds.json          Set credentials file
  gporg config --show                Show current configuration

  # Organize by year
  gporg organize --year 2023
  gporg organize --year 2023 --album "Vacation 2023"

  # Organize by date range
  gporg organize --start-date 2023-06-01 --end-date 2023-08-31 --album "Summer 2023"

  # Filter by media type
  gporg organize --year 2023 --media-type VIDEO --album "Videos 2023"

  # Filter by content category
  gporg organize --year 2023 --category SELFIES --category PEOPLE --album "People 2023"

  # Favorites only
  gporg organize --year 2023 --favorites --album "Best of 2023"

  # Combined filters
  gporg organize --start-date 2023-01-01 --end-date 2023-12-31 \\
                 --media-type PHOTO --category LANDSCAPES --favorites \\
                 --album "Favorite Landscapes 2023"

Verbosity:
  -v      Show info messages
  -vv     Show debug messages
  -vvv    Show trace messages (very verbose)
  -vvvv   Show all messages including third-party libraries
"""
    )

    # Global verbosity flag
    parser.add_argument('-v', '--verbose', action='count', default=0,
                        help='Increase verbosity (use -vv, -vvv for more)')

    subparsers = parser.add_subparsers(dest='command', metavar='COMMAND')

    # Web subcommand
    web_parser = subparsers.add_parser('web', help='Start/stop web server')
    web_parser.add_argument('--port', type=int, default=8099, help='Port (default: 8099)')
    web_parser.add_argument('--public', action='store_true', help='Allow network access')
    web_parser.add_argument('--background', '-b', action='store_true', help='Run in background')
    web_parser.add_argument('--stop', action='store_true', help='Stop background server')
    web_parser.set_defaults(func=cmd_web)

    # Config subcommand
    config_parser = subparsers.add_parser('config', help='Configure credentials')
    config_parser.add_argument('path', nargs='?', help='Path to service account JSON')
    config_parser.add_argument('--show', action='store_true', help='Show current config')
    config_parser.set_defaults(func=cmd_config)

    # Organize subcommand
    organize_parser = subparsers.add_parser('organize', help='Organize photos with filters')

    # Date filtering (mutually exclusive groups aren't needed, we handle logic in cmd_organize)
    date_group = organize_parser.add_argument_group('date filters')
    date_group.add_argument('--year', type=int, help='Year to organize (e.g., 2023)')
    date_group.add_argument('--start-date', type=str, metavar='YYYY-MM-DD',
                           help='Start date for date range filter')
    date_group.add_argument('--end-date', type=str, metavar='YYYY-MM-DD',
                           help='End date for date range filter')

    # Content filtering
    filter_group = organize_parser.add_argument_group('content filters')
    filter_group.add_argument('--media-type', type=str, choices=['ALL', 'PHOTO', 'VIDEO'],
                             default='ALL', help='Filter by media type (default: ALL)')
    filter_group.add_argument('--category', type=str, action='append', metavar='CATEGORY',
                             help=f'Filter by content category (can be repeated). '
                                  f'Options: {", ".join(CONTENT_CATEGORIES)}')
    filter_group.add_argument('--favorites', action='store_true',
                             help='Only include favorite/starred items')

    # Album options
    album_group = organize_parser.add_argument_group('album options')
    album_group.add_argument('--album', type=str, help='Target album name')
    album_group.add_argument('--no-skip', action='store_true',
                            help="Don't skip photos already in album")

    organize_parser.set_defaults(func=cmd_organize)

    args = parser.parse_args()

    # Setup logging based on verbosity
    setup_logging(args.verbose)
    log_debug(f"Verbosity level: {args.verbose}")

    # Default to TUI if no command given
    if args.command is None:
        log_info("No command specified, launching TUI")
        cmd_tui(args)
    else:
        log_debug(f"Running command: {args.command}")
        args.func(args)


if __name__ == '__main__':
    main()
