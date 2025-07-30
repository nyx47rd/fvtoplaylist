import os
import secrets
import datetime
from fastapi import FastAPI, Request, Depends, HTTPException
from fastapi.responses import RedirectResponse, HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware
from spotipy.oauth2 import SpotifyOAuth
import spotipy
from dotenv import load_dotenv
import logging

# --- Basic Setup ---
load_dotenv()
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# --- FastAPI App Initialization ---
app = FastAPI()
app.add_middleware(
    SessionMiddleware,
    secret_key=os.getenv("APP_SECRET_KEY", secrets.token_hex(32)),
    https_only=True,
    same_site="lax"
)
templates = Jinja2Templates(directory="templates")

# --- Spotify API Configuration ---
SPOTIPY_CLIENT_ID = os.getenv("SPOTIPY_CLIENT_ID")
SPOTIPY_CLIENT_SECRET = os.getenv("SPOTIPY_CLIENT_SECRET")
SPOTIPY_REDIRECT_URI = os.getenv("SPOTIPY_REDIRECT_URI")
TOKEN_INFO_SESSION_KEY = "spotify_token_info"
SCOPES = "user-library-read playlist-modify-public playlist-modify-private"
TARGET_PLAYLIST_NAME = "Liked Songs Sync ✨"

# --- In-memory State Management ---
# This dictionary will hold the sync status for the CURRENT request.
# It's no longer a long-lived global state.
sync_status = {}

# --- Helper Functions ---
def create_spotify_oauth() -> SpotifyOAuth:
    return SpotifyOAuth(
        client_id=SPOTIPY_CLIENT_ID,
        client_secret=SPOTIPY_CLIENT_SECRET,
        redirect_uri=SPOTIPY_REDIRECT_URI,
        scope=SCOPES,
        cache_handler=None
    )

def get_token_from_session(request: Request) -> dict | None:
    return request.session.get(TOKEN_INFO_SESSION_KEY)

def add_log(log_list: list, message: str):
    timestamp = datetime.datetime.now().strftime("%H:%M:%S")
    log_list.insert(0, f"[{timestamp}] {message}")

def get_spotify_client(token_info: dict) -> spotipy.Spotify:
    """Initializes a Spotipy client with automatic retries for rate limiting."""
    return spotipy.Spotify(
        auth=token_info['access_token'],
        retries=5,  # Number of retries
        status_forcelist=(429, 500, 502, 503, 504), # Retry on these status codes
        status_retries=5,
        backoff_factor=0.3 # Wait time between retries
    )

# --- Core Synchronization Logic ---
def run_manual_sync(token_info: dict, user_id: str) -> dict:
    """The main function to sync liked songs. Returns a status dictionary."""

    local_sync_status = {
        "playlist_name": TARGET_PLAYLIST_NAME,
        "playlist_id": None,
        "playlist_url": None,
        "synced_count": 0,
        "logs": [],
    }
    logs = local_sync_status["logs"]

    add_log(logs, "🚀 Manual sync process started.")
    sp = get_spotify_client(token_info)

    try:
        # 1. Find or Create Playlist
        playlists = sp.user_playlists(user_id)
        for p in playlists['items']:
            if p['name'] == TARGET_PLAYLIST_NAME:
                local_sync_status["playlist_id"] = p['id']
                local_sync_status["playlist_url"] = p['external_urls']['spotify']
                break
        if not local_sync_status.get("playlist_id"):
            playlist = sp.user_playlist_create(user_id, TARGET_PLAYLIST_NAME, public=True)
            local_sync_status["playlist_id"] = playlist['id']
            local_sync_status["playlist_url"] = playlist['external_urls']['spotify']
            add_log(logs, f"✅ Created new playlist: '{TARGET_PLAYLIST_NAME}'")

        playlist_id = local_sync_status["playlist_id"]

        # 2. Get All Liked Songs (with pagination)
        add_log(logs, "Fetching all liked songs...")
        liked_tracks = {}
        results = sp.current_user_saved_tracks(limit=50)
        while results:
            for item in results['items']:
                if item.get('track') and item['track'].get('id'):
                    liked_tracks[item['track']['id']] = item['track']['uri']
            if results['next']:
                results = sp.next(results)
            else:
                results = None
        add_log(logs, f"Found a total of {len(liked_tracks)} liked songs.")

        # 3. Get All Playlist Tracks (with pagination)
        add_log(logs, "Fetching all tracks from target playlist...")
        playlist_track_ids = set()
        results = sp.playlist_items(playlist_id, fields='items(track(id)),next')
        while results:
            for item in results['items']:
                if item.get('track') and item['track'].get('id'):
                    playlist_track_ids.add(item['track']['id'])
            if results['next']:
                results = sp.next(results)
            else:
                results = None
        add_log(logs, f"Playlist currently contains {len(playlist_track_ids)} songs.")

        # 4. Find New Songs to Add (in reverse order to maintain newest first)
        new_track_uris = [uri for track_id, uri in liked_tracks.items() if track_id not in playlist_track_ids]

        # 5. Add New Songs
        if new_track_uris:
            # Spotify API adds multiple tracks in the order they are provided.
            # To maintain "newest first", we add them in chunks of 100.
            add_log(logs, f"Adding {len(new_track_uris)} new song(s) to the playlist...")
            for i in range(0, len(new_track_uris), 100):
                chunk = new_track_uris[i:i + 100]
                sp.playlist_add_items(playlist_id, chunk, position=0)
            local_sync_status["synced_count"] = len(new_track_uris)
            add_log(logs, f"✅ Successfully synced {len(new_track_uris)} new song(s).")
        else:
            add_log(logs, "✅ Playlist is already up-to-date. No new songs to sync.")

    except spotipy.exceptions.SpotifyException as e:
        add_log(logs, f"🚨 Spotify API Error: {e.msg}")
    except Exception as e:
        add_log(logs, f"🚨 An unexpected error occurred: {e}")

    return local_sync_status

# --- FastAPI Routes ---
@app.get("/", response_class=HTMLResponse)
async def root(request: Request):
    token_info = get_token_from_session(request)
    user_profile = None
    if token_info:
        sp = get_spotify_client(token_info)
        try:
            user_profile = sp.current_user()
        except spotipy.exceptions.SpotifyException:
             # Invalid token, clear session and force re-login
            request.session.clear()
            return RedirectResponse(url="/")

    return templates.TemplateResponse(
        "index.html", {"request": request, "user": user_profile}
    )

@app.get("/login")
async def login():
    auth_url = create_spotify_oauth().get_authorize_url()
    return RedirectResponse(auth_url)

@app.get("/callback")
async def callback(request: Request):
    try:
        token_info = create_spotify_oauth().get_access_token(code=request.query_params.get("code"), check_cache=False)
        request.session[TOKEN_INFO_SESSION_KEY] = token_info
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Could not retrieve access token: {e}")
    return RedirectResponse(url="/")

@app.get("/logout")
async def logout(request: Request):
    request.session.clear()
    return RedirectResponse(url="/")

@app.post("/sync-now")
async def sync_now_endpoint(request: Request):
    token_info = get_token_from_session(request)
    if not token_info:
        raise HTTPException(status_code=401, detail="Not authenticated")

    # Refresh token if needed
    oauth_manager = create_spotify_oauth()
    if oauth_manager.is_token_expired(token_info):
        try:
            token_info = oauth_manager.refresh_access_token(token_info['refresh_token'])
            request.session[TOKEN_INFO_SESSION_KEY] = token_info
        except Exception as e:
            raise HTTPException(status_code=401, detail=f"Could not refresh token: {e}")

    sp = get_spotify_client(token_info)
    user_profile = sp.current_user()

    # Run the sync process and get the results
    sync_result = run_manual_sync(token_info, user_profile['id'])

    return JSONResponse(sync_result)
