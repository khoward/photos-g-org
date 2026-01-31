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
    Config, PhotosService, get_available_years,
    validate_credentials_path, validate_year
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
    """Organize photos from CLI."""
    log_debug("Starting organize command")
    config = Config()

    if not config.is_configured:
        print("Error: No credentials configured.")
        print("Run: gporg config /path/to/service-account.json")
        sys.exit(1)

    # Validate year
    is_valid, error, year = validate_year(args.year)
    if not is_valid:
        print(f"Error: {error}")
        sys.exit(1)

    album_name = args.album or f"Photos from {year}"
    skip_existing = not args.no_skip

    log_info(f"Organizing year={year} album='{album_name}' skip_existing={skip_existing}")
    print(f"Organizing photos from {year} into '{album_name}'...")

    try:
        log_debug(f"Creating PhotosService with {config.credentials_path}")
        service = PhotosService(config.credentials_path)

        # Get or create album
        print("Finding/creating album...")
        log_debug(f"Looking for album: {album_name}")
        album_id = service.get_or_create_album(album_name)
        log_info(f"Using album ID: {album_id}")

        # Search for photos
        print(f"Searching for photos from {year}...")
        log_debug(f"Searching photos with date filter: {year}-01-01 to {year}-12-31")

        def search_progress(count):
            log_trace(f"Search progress: {count} photos found")
            print(f"  Found {count} photos...", end='\r')

        photos = service.search_photos_by_year(year, progress_callback=search_progress)
        print()  # newline after progress

        photo_ids = [p['id'] for p in photos]
        log_info(f"Found {len(photo_ids)} photos for year {year}")

        if not photo_ids:
            print(f"No photos found for {year}.")
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
  gporg web                          Start web server on port 9090
  gporg web --public --port 8080     Start on all interfaces, port 8080
  gporg web --background             Start in background
  gporg web --stop                   Stop background server
  gporg config ~/creds.json          Set credentials file
  gporg config --show                Show current configuration
  gporg organize --year 2023         Organize 2023 photos
  gporg organize --year 2023 --album "Vacation 2023"

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
    web_parser.add_argument('--port', type=int, default=9090, help='Port (default: 9090)')
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
    organize_parser = subparsers.add_parser('organize', help='Organize photos by year')
    organize_parser.add_argument('--year', type=int, required=True, help='Year to organize')
    organize_parser.add_argument('--album', type=str, help='Album name')
    organize_parser.add_argument('--no-skip', action='store_true', help="Don't skip existing")
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
