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

# Import the refactored sync logic
from .spotify import run_sync_logic

# --- Basic Setup ---
load_dotenv()
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# --- FastAPI App Initialization ---
app = FastAPI()

# Session Middleware Setup
APP_SECRET_KEY = os.getenv("APP_SECRET_KEY")
if not APP_SECRET_KEY:
    APP_SECRET_KEY = secrets.token_hex(32)
    logging.warning(
        "!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!\n"
        "!!! WARNING: APP_SECRET_KEY is not set in the environment. !!!\n"
        "!!! Using a temporary secret key.                            !!!\n"
        "!!! Sessions will NOT persist across application restarts.   !!!\n"
        "!!! Set APP_SECRET_KEY in your .env file or environment.     !!!\n"
        "!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!"
    )

app.add_middleware(
    SessionMiddleware,
    secret_key=APP_SECRET_KEY,
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

def get_spotify_client(token_info: dict) -> spotipy.Spotify:
    """Initializes a Spotipy client."""
    return spotipy.Spotify(auth=token_info['access_token'])

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

    oauth_manager = create_spotify_oauth()
    if oauth_manager.is_token_expired(token_info):
        try:
            token_info = oauth_manager.refresh_access_token(token_info['refresh_token'])
            request.session[TOKEN_INFO_SESSION_KEY] = token_info
        except Exception as e:
            raise HTTPException(status_code=401, detail=f"Could not refresh token: {e}")

    sp = get_spotify_client(token_info)
    user_profile = sp.current_user()

    # Call the refactored sync logic
    sync_result = run_sync_logic(sp, user_profile['id'])

    return JSONResponse(sync_result)
