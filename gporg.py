import os
import json
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

# 1. SETUP: Path to your JSON key file
SERVICE_ACCOUNT_FILE = 'your-key-file.json' 
SCOPES = ['https://www.googleapis.com/auth/photoslibrary', 
          'https://www.googleapis.com/auth/photoslibrary.sharing']

def get_service():
    """Establishes connection to the Google Photos API."""
    creds = service_account.Credentials.from_service_account_file(
        SERVICE_ACCOUNT_FILE, scopes=SCOPES)
    # The Photos API discovery doc is often needed for the Python client
    return build('photoslibrary', 'v1', credentials=creds, static_discovery=False)

def get_or_create_album(service, album_title):
    """Checks if an album exists, creates it if not."""
    try:
        # Check existing albums
        results = service.albums().list(pageSize=50).execute()
        albums = results.get('albums', [])
        
        for album in albums:
            if album['title'] == album_title:
                print(f"Found existing album: {album_title}")
                return album['id']
        
        # Create if not found
        print(f"Creating new album: {album_title}")
        body = {'album': {'title': album_title}}
        new_album = service.albums().create(body=body).execute()
        return new_album['id']
    except HttpError as e:
        print(f"Error handling album: {e}")
        return None

def find_photos_by_year(service, year):
    """Finds media items matching a specific year."""
    print(f"Searching for photos from {year}...")
    
    # Generic search body - easy to modify for other criteria
    search_body = {
        "filters": {
            "dateFilter": {
                "ranges": [
                    {
                        "startDate": {"year": year, "month": 1, "day": 1},
                        "endDate": {"year": year, "month": 12, "day": 31}
                    }
                ]
            }
        },
        "pageSize": 100
    }
    
    items = []
    results = service.mediaItems().search(body=search_body).execute()
    items.extend(results.get('mediaItems', []))
    
    # Handle pagination if you have thousands of photos
    next_page_token = results.get('nextPageToken')
    while next_page_token:
        search_body['pageToken'] = next_page_token
        results = service.mediaItems().search(body=search_body).execute()
        items.extend(results.get('mediaItems', []))
        next_page_token = results.get('nextPageToken')
        
    return items

def add_to_album(service, album_id, photo_ids):
    """Adds a list of photo IDs to the specified album."""
    if not photo_ids:
        return
    
    # API limits batch additions to 50 at a time
    for i in range(0, len(photo_ids), 50):
        batch = photo_ids[i:i+50]
        body = {"mediaItemIds": batch}
        service.albums().batchAddMediaItems(albumId=album_id, body=body).execute()
        print(f"Added {len(batch)} photos to album.")

def main():
    service = get_service()
    
    # Define your criteria here (Generic part)
    TARGET_YEAR = 2023 
    ALBUM_NAME = f"Photos from {TARGET_YEAR}"
    
    # Execute
    album_id = get_or_create_album(service, ALBUM_NAME)
    if album_id:
        photos = find_photos_by_year(service, TARGET_YEAR)
        photo_ids = [photo['id'] for photo in photos]
        
        if photo_ids:
            add_to_album(service, album_id, photo_ids)
            print(f"Done! Organized {len(photo_ids)} photos.")
        else:
            print("No photos found for that criteria.")

if __name__ == '__main__':
    main()
