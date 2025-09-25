import os
import secrets
import logging
from fastapi import FastAPI, Request, Depends, HTTPException
from fastapi.responses import RedirectResponse, HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware
import spotipy

from app.core import config
from app.core.dependencies import create_spotify_oauth, get_token_from_session, get_spotify_client
from app.spotify import run_sync_logic, remove_last_x_songs, undo_last_deletion
from app.database import initialize_db
from pydantic import BaseModel

# --- Basic Setup ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# --- Database Initialization ---
initialize_db()

# --- FastAPI App Initialization ---
app = FastAPI()

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
@app.get("/privacy", response_class=HTMLResponse)
async def privacy_policy(request: Request):
    """Renders the privacy policy page."""
    return templates.TemplateResponse("privacy.html", {"request": request})


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

class DeleteSongsRequest(BaseModel):
    playlist_id: str
    num_to_delete: int

class UndoDeleteRequest(BaseModel):
    playlist_id: str

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


@app.post("/delete-songs")
async def delete_songs_endpoint(request: Request, delete_request: DeleteSongsRequest):
    token_info = get_token_from_session(request)
    if not token_info:
        raise HTTPException(status_code=401, detail="Not authenticated")

    sp = get_spotify_client(token_info)
    user_profile = sp.current_user()

    result = remove_last_x_songs(
        sp,
        user_id=user_profile['id'],
        playlist_id=delete_request.playlist_id,
        num_to_delete=delete_request.num_to_delete,
        logs=[]
    )

    return JSONResponse(result)


@app.post("/undo-delete")
async def undo_delete_endpoint(request: Request, undo_request: UndoDeleteRequest):
    token_info = get_token_from_session(request)
    if not token_info:
        raise HTTPException(status_code=401, detail="Not authenticated")

    sp = get_spotify_client(token_info)
    user_profile = sp.current_user()

    result = undo_last_deletion(
        sp,
        user_id=user_profile['id'],
        playlist_id=undo_request.playlist_id,
        logs=[]
    )

    return JSONResponse(result)
