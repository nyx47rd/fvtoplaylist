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
from app.spotify import run_sync_logic, get_playlist_songs_for_display, remove_specific_songs, add_specific_songs
from pydantic import BaseModel
from typing import List, Optional
import spotipy

# --- Basic Setup ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

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
            # This might happen if the token is invalid or expired
            request.session.clear()
            # Redirect to self to clear the view
            return RedirectResponse(url="/")

    return templates.TemplateResponse(
        "index.html", {"request": request, "user": user_profile, "token_info": token_info}
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

class TokenInfo(BaseModel):
    access_token: str
    token_type: str
    expires_in: int
    scope: str
    expires_at: int
    refresh_token: str

class PlaylistSongsRequest(BaseModel):
    playlist_id: str

class DeleteSongsRequest(BaseModel):
    playlist_id: str
    track_ids: List[str]

class AddSongsRequest(BaseModel):
    playlist_id: str
    track_uris: List[str]

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

@app.post("/api/set-token")
async def set_token(request: Request, token_info: TokenInfo):
    """
    Allows the frontend to set the token from LocalStorage to re-establish a session.
    """
    # Validate the token by making a simple request to the Spotify API
    try:
        sp = spotipy.Spotify(auth=token_info.access_token)
        user_profile = sp.current_user()
        # If the above call succeeds, the token is valid.
        # Store it in the server-side session.
        request.session[config.TOKEN_INFO_SESSION_KEY] = token_info.dict()
        return JSONResponse({"success": True, "user": user_profile})
    except spotipy.exceptions.SpotifyException:
        # The token is invalid or expired
        return JSONResponse({"success": False}, status_code=401)

@app.post("/api/playlist-songs")
async def get_playlist_songs_endpoint(request: Request, req_body: PlaylistSongsRequest):
    token_info = get_token_from_session(request)
    if not token_info:
        raise HTTPException(status_code=401, detail="Not authenticated")
    sp = get_spotify_client(token_info)
    songs = get_playlist_songs_for_display(sp, req_body.playlist_id)
    return JSONResponse(songs)

@app.post("/api/delete-songs")
async def delete_songs_endpoint(request: Request, req_body: DeleteSongsRequest):
    token_info = get_token_from_session(request)
    if not token_info:
        raise HTTPException(status_code=401, detail="Not authenticated")
    sp = get_spotify_client(token_info)
    logs = []
    success = remove_specific_songs(sp, req_body.playlist_id, req_body.track_ids, logs)
    return JSONResponse({"success": success, "log": logs})

@app.post("/api/add-songs")
async def add_songs_endpoint(request: Request, req_body: AddSongsRequest):
    token_info = get_token_from_session(request)
    if not token_info:
        raise HTTPException(status_code=401, detail="Not authenticated")
    sp = get_spotify_client(token_info)
    logs = []
    success = add_specific_songs(sp, req_body.playlist_id, req_body.track_uris, logs)
    return JSONResponse({"success": success, "log": logs})
