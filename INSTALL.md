# Installation Guide

## Prerequisites

- Python 3.10+
- A Google Cloud project with Photos Library API enabled
- A service account with domain-wide delegation (for Google Workspace)

## Step 1: Clone and Install

```bash
cd photos-organizer
python -m venv venv
source venv/bin/activate  # Linux/Mac
# or: venv\Scripts\activate  # Windows

pip install -r requirements.txt
```

## Step 2: Google Cloud Setup

### Create a Service Account

1. Go to [Google Cloud Console](https://console.cloud.google.com/)
2. Create a new project or select existing
3. Enable the **Photos Library API**:
   - APIs & Services > Library
   - Search "Photos Library API"
   - Click Enable

4. Create a service account:
   - APIs & Services > Credentials
   - Create Credentials > Service Account
   - Name it (e.g., "photos-organizer")
   - Grant no roles (not needed)
   - Click Done

5. Create a key:
   - Click on the service account
   - Keys > Add Key > Create new key
   - Choose JSON
   - Save the file securely

### For Personal Google Accounts

Service accounts cannot directly access personal Google Photos. You'll need to:
1. Use OAuth 2.0 instead (requires code modification), or
2. Share specific albums with the service account email

### For Google Workspace

1. Go to [Admin Console](https://admin.google.com/)
2. Security > API Controls > Domain-wide Delegation
3. Add new API client:
   - Client ID: (from service account)
   - Scopes:
     ```
     https://www.googleapis.com/auth/photoslibrary
     https://www.googleapis.com/auth/photoslibrary.sharing
     ```

## Step 3: Configure

```bash
python gporg.py config /path/to/service-account.json
```

This saves the path and generates an API key for web access.

## Step 4: Verify

```bash
# Check configuration
python gporg.py config --show

# Launch TUI
python gporg.py

# Or start web server
python gporg.py web
```

## Running as a Service (Optional)

### Systemd (Linux)

Create `/etc/systemd/system/gporg.service`:

```ini
[Unit]
Description=Google Photos Organizer Web
After=network.target

[Service]
Type=simple
User=youruser
WorkingDirectory=/path/to/photos-organizer
ExecStart=/path/to/photos-organizer/venv/bin/python gporg.py web
Restart=on-failure

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl enable gporg
sudo systemctl start gporg
```

## Install to PATH (Optional)

```bash
sudo cp gporg /usr/local/bin/
```

The script defaults to `/home/khoward/ideas/photos-organizer`. To change it, either:
- Edit `GPORG_HOME` in the script, or
- Set the environment variable: `export GPORG_HOME=/your/path`

## Troubleshooting

### "No credentials configured"
Run `python gporg.py config /path/to/service-account.json`

### "File does not appear to be a service account JSON"
Ensure the JSON file contains `"type": "service_account"`

### API errors
- Check that Photos Library API is enabled
- Verify service account has proper delegation (Workspace)
- Check daily quota (10,000 requests)

### Web UI not accessible
- Default binds to localhost only
- Use `--public` flag for network access
- Check firewall allows port 8099
