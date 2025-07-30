from fastapi import APIRouter, Request, Depends, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
import spotipy

from app.core.dependencies import get_token_from_session, get_spotify_client
from app.spotify import _get_all_playlist_tracks, TARGET_PLAYLIST_NAME
from app.ytmusic import auth
from app.ytmusic import client as ytmusic_client

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
        return None


@router.get("/", response_class=HTMLResponse)
async def get_ytmusic_page(request: Request, spotify_user: dict = Depends(get_spotify_user)):
    """Renders the main page for the YouTube Music sync feature."""
    if not spotify_user:
        return RedirectResponse(url="/login")

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
    google_creds = auth.exchange_code_for_credentials(code)
    auth.save_credentials_to_firestore(spotify_user['id'], google_creds)

    return RedirectResponse(url="/ytmusic")


@router.post("/sync")
async def sync_to_ytmusic(request: Request, spotify_user: dict = Depends(get_spotify_user)):
    """
    Endpoint to start the synchronization process from Spotify to YouTube Music.
    """
    if not spotify_user:
        raise HTTPException(status_code=401, detail="Spotify session expired")

    # 1. Get credentials for both services
    spotify_token_info = get_token_from_session(request)
    google_creds = auth.get_credentials_from_firestore(spotify_user['id'])

    if not spotify_token_info or not google_creds:
        raise HTTPException(status_code=401, detail="Missing credentials for Spotify or Google.")

    sp = get_spotify_client(spotify_token_info)
    ytmusic = ytmusic_client.get_ytmusic_client(google_creds)

    logs = []

    try:
        # 2. Find the Spotify source playlist
        spotify_playlist_id = None
        spotify_playlist_description = ""
        playlists = sp.user_playlists(spotify_user['id'])
        for p in playlists['items']:
            if p['name'] == TARGET_PLAYLIST_NAME:
                spotify_playlist_id = p['id']
                spotify_playlist_description = p.get('description', 'Synced from Spotify.')
                break

        if not spotify_playlist_id:
            return JSONResponse({"logs": ["Source playlist 'Liked Songs Sync ✨' not found."]}, status_code=404)

        # 3. Get all tracks from the Spotify playlist
        spotify_tracks_results = sp.playlist_items(spotify_playlist_id)
        spotify_tracks = spotify_tracks_results['items']
        # Handle pagination for spotify playlist tracks
        while spotify_tracks_results['next']:
            spotify_tracks_results = sp.next(spotify_tracks_results)
            spotify_tracks.extend(spotify_tracks_results['items'])

        # 4. Find or create the YouTube Music destination playlist
        yt_playlist_name = f"Spotify Liked Songs ({spotify_user['display_name']})"
        yt_playlist_id = ytmusic_client.find_or_create_ytmusic_playlist(ytmusic, yt_playlist_name, spotify_playlist_description)

        # 5. Search for each song on YT Music and add to a list
        video_ids_to_add = []
        for item in spotify_tracks:
            track = item['track']
            if not track: continue

            video_id = ytmusic_client.search_song_on_ytmusic(ytmusic, track)
            if video_id:
                video_ids_to_add.append(video_id)
                logs.append(f"Found: {track['name']} → {video_id}")
            else:
                logs.append(f"Not Found: {track['name']}")

        # 6. Add all found tracks to the YT Music playlist
        ytmusic_client.add_tracks_to_ytmusic_playlist(ytmusic, yt_playlist_id, video_ids_to_add)
        logs.append(f"Successfully transferred {len(video_ids_to_add)} songs to YouTube Music playlist '{yt_playlist_name}'.")

    except Exception as e:
        logs.append(f"An error occurred: {e}")
        return JSONResponse({"logs": logs}, status_code=500)

    return JSONResponse({"logs": logs})
