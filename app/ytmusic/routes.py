from fastapi import APIRouter, Request, Depends
from fastapi.responses import HTMLResponse, RedirectResponse
import spotipy

from ..core.dependencies import get_token_from_session, get_spotify_client
from . import auth

router = APIRouter()
templates = Jinja2Templates(directory="templates")

# Dependency to get the current Spotify user's profile
def get_spotify_user(request: Request) -> dict:
    token_info = get_token_from_session(request)
    if not token_info:
        return None
    try:
        sp = get_spotify_client(token_info)
        return sp.current_user()
    except spotipy.exceptions.SpotifyException:
        # Could be an expired token, but for a dependency, better to just return None
        return None


@router.get("/", response_class=HTMLResponse)
async def get_ytmusic_page(request: Request, spotify_user: dict = Depends(get_spotify_user)):
    """Renders the main page for the YouTube Music sync feature."""
    if not spotify_user:
        return RedirectResponse(url="/?error=spotify_session_expired")

    # Check if the user has already linked their Google account
    google_creds = auth.get_credentials_from_firestore(spotify_user['id'])

    return templates.TemplateResponse("ytmusic.html", {
        "request": request,
        "user": spotify_user,
        "google_auth_linked": google_creds is not None
    })

@router.get("/login")
async def login_google():
    """Redirects the user to Google for OAuth authentication."""
    auth_url = auth.get_google_auth_url()
    return RedirectResponse(url=auth_url)

@router.get("/callback")
async def callback_google(request: Request, spotify_user: dict = Depends(get_spotify_user)):
    """Handles the OAuth callback from Google and saves credentials to Firestore."""
    if not spotify_user:
        return RedirectResponse(url="/?error=spotify_session_expired")

    code = request.query_params.get("code")

    # Exchange the code for credentials
    google_creds = auth.exchange_code_for_credentials(code)

    # Save the credentials to Firestore, linked to the Spotify user ID
    auth.save_credentials_to_firestore(spotify_user['id'], google_creds)

    return RedirectResponse(url="/ytmusic")


@router.post("/sync")
async def sync_to_ytmusic(request: Request, spotify_user: dict = Depends(get_spotify_user)):
    """
    Endpoint to start the synchronization process from Spotify to YouTube Music.
    """
    if not spotify_user:
        return {"error": "Spotify session expired"}, 401

    # The actual sync logic will be implemented in the next step
    # It will use the spotify_user['id'] to get both spotify and google credentials

    return {"message": "Syncing from Spotify to YouTube Music will start here."}
