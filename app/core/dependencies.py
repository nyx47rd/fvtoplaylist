from fastapi import Request, HTTPException
from spotipy.oauth2 import SpotifyOAuth
import spotipy

from . import config

# --- Spotify Dependencies ---

def create_spotify_oauth() -> SpotifyOAuth:
    """Creates a SpotifyOAuth object from configuration."""
    return SpotifyOAuth(
        client_id=config.SPOTIPY_CLIENT_ID,
        client_secret=config.SPOTIPY_CLIENT_SECRET,
        redirect_uri=config.SPOTIPY_REDIRECT_URI,
        scope=config.SPOTIPY_SCOPES,
        cache_handler=None
    )

def get_token_from_session(request: Request) -> dict | None:
    """Dependency to get Spotify token info from the current session."""
    return request.session.get(config.TOKEN_INFO_SESSION_KEY)

def get_spotify_client(token_info: dict) -> spotipy.Spotify:
    """Initializes a Spotipy client from token info."""
    if not token_info:
        raise HTTPException(status_code=401, detail="Invalid Spotify token info.")
    return spotipy.Spotify(auth=token_info['access_token'])
