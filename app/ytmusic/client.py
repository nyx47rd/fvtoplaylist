from ytmusicapi import YTMusic
from google.oauth2.credentials import Credentials
from ..core import config

# --- YouTube Music Client ---

def get_ytmusic_client(google_creds: dict) -> YTMusic:
    """
    Initializes the YTMusic client using credentials stored in Firestore.
    The credentials dictionary must be converted to a google.oauth2.credentials.Credentials object.
    """
    # The google-auth library expects specific keys. We map our stored creds to them.
    credentials = Credentials(
        token=google_creds.get('token'),
        refresh_token=google_creds.get('refresh_token'),
        token_uri=google_creds.get('token_uri'),
        client_id=google_creds.get('client_id'),
        client_secret=google_creds.get('client_secret'),
        scopes=google_creds.get('scopes')
    )

    # We need to refresh the credentials to make sure the token is valid
    if credentials.expired and credentials.refresh_token:
        from google.auth.transport.requests import Request
        credentials.refresh(Request())


    # The YTMusic library requires both the credentials object and a JSON representation.
    return YTMusic(auth=credentials.to_json(), oauth_credentials=credentials)

def search_song_on_ytmusic(ytmusic: YTMusic, spotify_track: dict) -> str | None:
    """
    Searches for a song on YouTube Music based on Spotify track info.
    Returns the videoId if found.
    """
    try:
        query = f"{spotify_track['name']} {spotify_track['artists'][0]['name']}"
        search_results = ytmusic.search(query, filter="songs", limit=1)
        if search_results and search_results[0]['videoId']:
            return search_results[0]['videoId']
        return None
    except Exception:
        # If search fails for any reason, return None
        return None

def find_or_create_ytmusic_playlist(ytmusic: YTMusic, playlist_name: str, spotify_playlist_description: str) -> str:
    """
    Finds a playlist by name. If it doesn't exist, it creates one.
    Returns the playlist ID.
    """
    playlists = ytmusic.get_library_playlists()
    for playlist in playlists:
        if playlist['title'] == playlist_name:
            return playlist['playlistId']

    # If not found, create it
    return ytmusic.create_playlist(
        title=playlist_name,
        description=spotify_playlist_description
    )

def add_tracks_to_ytmusic_playlist(ytmusic: YTMusic, playlist_id: str, video_ids: list):
    """
    Adds a list of videoIds to a YouTube Music playlist.
    Handles duplicates automatically by the API.
    """
    if not video_ids:
        return
    ytmusic.add_playlist_items(playlistId=playlist_id, videoIds=video_ids, duplicates=False)
