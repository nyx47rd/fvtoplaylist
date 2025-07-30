import os
import secrets
import json
import logging
from fastapi import FastAPI, Request, Depends, HTTPException
from fastapi.responses import RedirectResponse, HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware
import spotipy
import firebase_admin
from firebase_admin import credentials

from app.core import config
from app.core.dependencies import create_spotify_oauth, get_token_from_session, get_spotify_client
from app.spotify import run_sync_logic
from app.ytmusic import routes as ytmusic_routes

# --- Basic Setup ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# --- Firebase Initialization ---
try:
    if config.FIREBASE_SERVICE_ACCOUNT_JSON:
        cred_dict = json.loads(config.FIREBASE_SERVICE_ACCOUNT_JSON)
        cred = credentials.Certificate(cred_dict)
        firebase_admin.initialize_app(cred)
        logging.info("Firebase initialized successfully.")
    else:
        logging.warning("FIREBASE_SERVICE_ACCOUNT_JSON not found. Firebase features will be disabled.")
except Exception as e:
    logging.error(f"Failed to initialize Firebase: {e}")

# --- FastAPI App Initialization ---
app = FastAPI()

# Include the YouTube Music router
app.include_router(ytmusic_routes.router, prefix="/ytmusic", tags=["YouTube Music"])

# Session Middleware Setup
if not config.APP_SECRET_KEY:
    logging.warning(
        "!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!\n"
        "!!! WARNING: APP_SECRET_KEY is not set in the environment. !!!\n"
        "!!! Using a temporary secret key for this session.           !!!\n"
        "!!! Sessions will NOT persist across application restarts.   !!!\n"
        "!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!"
    )
app.add_middleware(
    SessionMiddleware,
    secret_key=config.APP_SECRET_KEY or secrets.token_hex(32),
    https_only=True,
    same_site="lax"
)
templates = Jinja2Templates(directory="templates")

# --- FastAPI Routes ---
@app.get("/", response_class=HTMLResponse)
async def root(request: Request):
    token_info = get_token_from_session(request)
    user_profile = None
    if token_info:
        try:
            sp = get_spotify_client(token_info)
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
        request.session[config.TOKEN_INFO_SESSION_KEY] = token_info
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
            request.session[config.TOKEN_INFO_SESSION_KEY] = token_info
        except Exception as e:
            raise HTTPException(status_code=401, detail=f"Could not refresh token: {e}")

    sp = get_spotify_client(token_info)
    user_profile = sp.current_user()

    sync_result = run_sync_logic(sp, user_profile['id'])

    return JSONResponse(sync_result)
