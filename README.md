# Google Photos Organizer

Organize your Google Photos library by year into albums. Features a rich terminal UI, web interface, and CLI.

## Features

- **TUI**: Rich terminal interface with keyboard navigation
- **Web UI**: Glassmorphism dark theme, mobile-friendly (port 9090)
- **CLI**: Quick commands for scripting and automation
- **Parallel Processing**: Batch operations with 4 concurrent workers
- **Security**: API key authentication, rate limiting, localhost-only by default

## Quick Start

```bash
# Create and activate virtual environment
python -m venv venv
source venv/bin/activate  # Linux/Mac
# venv\Scripts\activate   # Windows

# Install dependencies
pip install -r requirements.txt

# Configure credentials
python gporg.py config ~/path/to/service-account.json

# Launch TUI (default)
python gporg.py

# Or start web server
python gporg.py web
```

## Usage

```
gporg                              Start TUI (default)
gporg web                          Start web server (foreground)
gporg web --background             Start in background
gporg web --stop                   Stop background server
gporg web --public --port 8080     Network access on custom port
gporg config ~/creds.json          Set credentials
gporg config --show                Show current config
gporg organize --year 2023         Quick organize photos from 2023
gporg organize --year 2023 --album "Vacation 2023"
```

## Interfaces

### Terminal UI
```bash
python gporg.py
```
Arrow keys to navigate, Enter to select, Escape to go back.

### Web UI
```bash
python gporg.py web
```
Open http://localhost:9090 in your browser. The API key is displayed on startup.

### CLI
```bash
python gporg.py organize --year 2023 --album "Photos 2023"
```

## Configuration

Config stored in `~/.config/gporg/config.json`:
- `credentials_path`: Path to Google service account JSON
- `api_key`: Generated API key for web authentication

## Google Photos API Limits

- 50 items per batch request
- 20,000 items per album
- 10,000 API requests per day

## License

MIT
