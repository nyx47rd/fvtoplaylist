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
from apscheduler.schedulers.asyncio import AsyncIOScheduler
import logging

# --- Basic Setup ---
load_dotenv()
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# --- FastAPI App Initialization ---
app = FastAPI()
app.add_middleware(
    SessionMiddleware,
    secret_key=os.getenv("APP_SECRET_KEY", secrets.token_hex(32)),
    https_only=True,  # Ensures cookies are only sent over HTTPS
    same_site="lax"   # Recommended for OAuth callbacks and cross-site requests
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
# This simple state management is suitable for a single-user-per-instance deployment.
# It will reset if the application restarts.
sync_status = {
    "is_running": False,
    "playlist_name": TARGET_PLAYLIST_NAME,
    "playlist_id": None,
    "playlist_url": None,
    "synced_count": 0,
    "logs": [],
}
active_sync_state = {"token_info": None, "user_id": None, "job": None}
scheduler = AsyncIOScheduler()

# --- Helper Functions ---
def create_spotify_oauth() -> SpotifyOAuth:
    return SpotifyOAuth(
        client_id=SPOTIPY_CLIENT_ID,
        client_secret=SPOTIPY_CLIENT_SECRET,
        redirect_uri=SPOTIPY_REDIRECT_URI,
        scope=SCOPES,
        cache_handler=None  # Important for server-side applications
    )

def get_token_from_session(request: Request) -> dict | None:
    return request.session.get(TOKEN_INFO_SESSION_KEY)

def add_log(message: str):
    timestamp = datetime.datetime.now().strftime("%H:%M:%S")
    sync_status["logs"].insert(0, f"[{timestamp}] {message}")
    # Keep logs from growing indefinitely
    sync_status["logs"] = sync_status["logs"][:50]

# --- Core Synchronization Logic ---
async def sync_job():
    """The main background job to sync liked songs."""
    if not active_sync_state.get("token_info"):
        logging.warning("Sync job running without token info. Skipping.")
        return

    oauth_manager = create_spotify_oauth()
    token_info = active_sync_state["token_info"]

    # Refresh token if needed and update the global state
    if oauth_manager.is_token_expired(token_info):
        try:
            token_info = oauth_manager.refresh_access_token(token_info['refresh_token'])
            active_sync_state["token_info"] = token_info
            add_log("🔑 Token refreshed successfully.")
        except Exception as e:
            add_log(f"🚨 Error refreshing token: {e}")
            # Stop the sync if token refresh fails
            await stop_sync_task()
            return

    sp = spotipy.Spotify(auth=token_info['access_token'])

    try:
        # 1. Find or Create Playlist
        playlist_id = sync_status.get("playlist_id")
        if not playlist_id:
            user_id = active_sync_state["user_id"]
            playlists = sp.user_playlists(user_id)
            for p in playlists['items']:
                if p['name'] == TARGET_PLAYLIST_NAME:
                    sync_status["playlist_id"] = p['id']
                    sync_status["playlist_url"] = p['external_urls']['spotify']
                    add_log(f"✅ Found existing playlist: '{TARGET_PLAYLIST_NAME}'")
                    break
            if not sync_status.get("playlist_id"):
                playlist = sp.user_playlist_create(user_id, TARGET_PLAYLIST_NAME, public=True)
                sync_status["playlist_id"] = playlist['id']
                sync_status["playlist_url"] = playlist['external_urls']['spotify']
                add_log(f"✅ Created new playlist: '{TARGET_PLAYLIST_NAME}'")

        playlist_id = sync_status["playlist_id"]

        # 2. Get Liked Songs
        results = sp.current_user_saved_tracks(limit=50)
        liked_tracks = {item['track']['id']: item['track']['uri'] for item in results['items']}

        # 3. Get Playlist Tracks
        playlist_items = sp.playlist_items(playlist_id, fields='items(track(id))')
        playlist_track_ids = {item['track']['id'] for item in playlist_items['items'] if item.get('track')}

        # 4. Find New Songs to Add
        new_track_ids = [uri for track_id, uri in liked_tracks.items() if track_id not in playlist_track_ids]

        # 5. Add New Songs
        if new_track_ids:
            sp.playlist_add_items(playlist_id, new_track_ids, position=0)
            sync_status["synced_count"] += len(new_track_ids)
            add_log(f"🔄 Synced {len(new_track_ids)} new song(s).")
        else:
            add_log("✅ No new liked songs to sync.")

    except spotipy.exceptions.SpotifyException as e:
        add_log(f"🚨 Spotify API Error: {e}")
    except Exception as e:
        add_log(f"🚨 An unexpected error occurred: {e}")


# --- Scheduler Control ---
async def start_sync_task(request: Request):
    token_info = get_token_from_session(request)
    if not token_info:
        raise HTTPException(status_code=401, detail="Not authenticated")

    if not sync_status["is_running"]:
        sp = spotipy.Spotify(auth=token_info['access_token'])
        user_profile = sp.current_user()

        active_sync_state["token_info"] = token_info
        active_sync_state["user_id"] = user_profile['id']

        # Add the job to the scheduler
        active_sync_state["job"] = scheduler.add_job(sync_job, 'interval', seconds=15, id='sync_job')
        sync_status["is_running"] = True
        add_log("🚀 Sync process started.")
        # Perform an initial sync immediately
        await sync_job()

async def stop_sync_task():
    if sync_status["is_running"]:
        if active_sync_state.get("job"):
            active_sync_state["job"].remove()
            active_sync_state["job"] = None

        # Reset state
        sync_status["is_running"] = False
        sync_status["playlist_id"] = None
        sync_status["playlist_url"] = None
        active_sync_state["token_info"] = None
        active_sync_state["user_id"] = None
        add_log("🛑 Sync process stopped.")

@app.on_event("startup")
async def startup_event():
    scheduler.start()
    add_log("Scheduler started.")

@app.on_event("shutdown")
async def shutdown_event():
    await stop_sync_task()
    scheduler.shutdown()
    logging.info("Scheduler shut down.")


# --- FastAPI Routes ---
@app.get("/", response_class=HTMLResponse)
async def root(request: Request):
    token_info = get_token_from_session(request)
    user_profile = None
    if token_info:
        oauth_manager = create_spotify_oauth()
        # Ensure token is fresh before rendering the page
        if oauth_manager.is_token_expired(token_info):
            try:
                token_info = oauth_manager.refresh_access_token(token_info['refresh_token'])
                request.session[TOKEN_INFO_SESSION_KEY] = token_info
            except Exception:
                # If refresh fails, clear session and force re-login
                request.session.clear()
                return RedirectResponse(url="/")

        sp = spotipy.Spotify(auth=token_info['access_token'])
        user_profile = sp.current_user()

    return templates.TemplateResponse(
        "index.html", {"request": request, "user": user_profile, "sync_status": sync_status}
    )

@app.get("/login")
async def login():
    auth_url = create_spotify_oauth().get_authorize_url()
    return RedirectResponse(auth_url)

@app.get("/callback")
async def callback(request: Request):
    code = request.query_params.get("code")
    try:
        token_info = create_spotify_oauth().get_access_token(code, check_cache=False)
        request.session[TOKEN_INFO_SESSION_KEY] = token_info
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Could not retrieve access token: {e}")
    return RedirectResponse(url="/")

@app.get("/logout")
async def logout(request: Request):
    request.session.clear()
    await stop_sync_task() # Stop sync on logout
    return RedirectResponse(url="/")

@app.post("/start-sync")
async def start_sync_endpoint(request: Request):
    await start_sync_task(request)
    return JSONResponse({"message": "Sync started."})

@app.post("/stop-sync")
async def stop_sync_endpoint():
    await stop_sync_task()
    return JSONResponse({"message": "Sync stopped."})

@app.get("/sync-status")
async def get_sync_status():
    return JSONResponse(sync_status)
