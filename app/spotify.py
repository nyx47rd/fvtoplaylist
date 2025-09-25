import spotipy
import datetime

from app.core import config

# Moved from main.py to resolve circular import
TARGET_PLAYLIST_NAME = "Liked Songs Sync ✨"

def add_log(log_list: list, message: str):
    """A helper function to add a timestamped log message."""
    timestamp = datetime.datetime.now().strftime("%H:%M:%S")
    log_list.insert(0, f"[{timestamp}] {message}")

def _find_or_create_playlist(sp: spotipy.Spotify, user_id: str, logs: list) -> tuple[str | None, str | None]:
    """Finds the target playlist by name, or creates it if it doesn't exist."""
    playlist_id = None
    playlist_url = None
    playlists = sp.user_playlists(user_id)
    for p in playlists['items']:
        if p['name'] == TARGET_PLAYLIST_NAME:
            playlist_id = p['id']
            playlist_url = p['external_urls']['spotify']
            break
    if not playlist_id:
        try:
            playlist = sp.user_playlist_create(user_id, TARGET_PLAYLIST_NAME, public=True)
            playlist_id = playlist['id']
            playlist_url = playlist['external_urls']['spotify']
            add_log(logs, f"✅ Created new playlist: '{TARGET_PLAYLIST_NAME}'")
        except spotipy.exceptions.SpotifyException as e:
            add_log(logs, f"🚨 Could not create playlist: {e.msg}")
            return None, None

    return playlist_id, playlist_url

def _get_all_liked_tracks(sp: spotipy.Spotify, logs: list) -> dict:
    """Fetches all tracks from the user's 'Liked Songs' library."""
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
    return liked_tracks

def _get_all_playlist_tracks(sp: spotipy.Spotify, playlist_id: str, logs: list) -> set:
    """Fetches all track IDs from a given playlist."""
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
    return playlist_track_ids

def _remove_tracks(sp: spotipy.Spotify, playlist_id: str, track_ids: list, logs: list):
    """Removes a list of tracks from a playlist."""
    if not track_ids:
        return
    add_log(logs, f"Removing {len(track_ids)} song(s) that are no longer liked...")
    for i in range(0, len(track_ids), 100):
        chunk = track_ids[i:i + 100]
        sp.playlist_remove_all_occurrences_of_items(playlist_id, chunk)
    add_log(logs, f"🗑️ Successfully removed {len(track_ids)} song(s).")

def _add_tracks(sp: spotipy.Spotify, playlist_id: str, track_uris: list, logs: list):
    """Adds a list of tracks to a playlist, preserving order."""
    if not track_uris:
        return
    add_log(logs, f"Adding {len(track_uris)} new song(s) to the playlist...")
    chunks = [track_uris[i:i + 100] for i in range(0, len(track_uris), 100)]
    for chunk in reversed(chunks):
        sp.playlist_add_items(playlist_id, chunk, position=0)
    add_log(logs, f"✅ Successfully synced {len(track_uris)} new song(s).")


def run_sync_logic(sp: spotipy.Spotify, user_id: str, ignored_track_ids: list = None) -> dict:
    """
    Orchestrates the entire sync process.
    1. Finds/creates the playlist.
    2. Fetches liked songs and playlist songs.
    3. Calculates differences, excluding ignored tracks.
    4. Removes and adds tracks as needed.
    Returns a dictionary with the results.
    """
    if ignored_track_ids is None:
        ignored_track_ids = []
    sync_result = {
        "playlist_name": TARGET_PLAYLIST_NAME,
        "playlist_id": None,
        "playlist_url": None,
        "synced_count": 0,
        "logs": [],
    }
    logs = sync_result["logs"]
    add_log(logs, "🚀 Manual sync process started.")

    try:
        playlist_id, playlist_url = _find_or_create_playlist(sp, user_id, logs)
        if not playlist_id:
            add_log(logs, "🚨 Halting sync due to playlist creation failure.")
            return sync_result

        sync_result["playlist_id"] = playlist_id
        sync_result["playlist_url"] = playlist_url

        liked_tracks = _get_all_liked_tracks(sp, logs)
        playlist_track_ids = _get_all_playlist_tracks(sp, playlist_id, logs)

        # Exclude ignored tracks from the "liked" list
        ignored_set = set(ignored_track_ids)
        if ignored_set:
            add_log(logs, f"Ignoring {len(ignored_set)} track(s) based on user preference.")

        liked_track_ids = {track_id for track_id in liked_tracks.keys() if track_id not in ignored_set}

        tracks_to_add_uris = [uri for track_id, uri in liked_tracks.items() if track_id in liked_track_ids and track_id not in playlist_track_ids]
        tracks_to_remove_ids = list(playlist_track_ids - liked_track_ids)

        _remove_tracks(sp, playlist_id, tracks_to_remove_ids, logs)
        _add_tracks(sp, playlist_id, tracks_to_add_uris, logs)

        sync_result["synced_count"] = len(tracks_to_add_uris)

        if not tracks_to_add_uris and not tracks_to_remove_ids:
            add_log(logs, "✅ Playlist is already up-to-date. No changes made.")

    except spotipy.exceptions.SpotifyException as e:
        add_log(logs, f"🚨 Spotify API Error: {e.msg}")
    except Exception as e:
        add_log(logs, f"🚨 An unexpected error occurred: {e}")

    return sync_result


def remove_last_x_songs(sp: spotipy.Spotify, playlist_id: str, num_to_delete: int, logs: list) -> dict:
    """
    Removes the last X songs from the end of a playlist (the oldest added songs) and returns their IDs.
    """
    if num_to_delete <= 0:
        add_log(logs, "Number of songs to delete must be positive.")
        return {"success": False, "log": logs}

    add_log(logs, f"Attempting to delete the last {num_to_delete} song(s) from the playlist...")

    try:
        # Check total tracks to avoid unnecessary processing
        playlist_info = sp.playlist(playlist_id, fields='tracks.total')
        total_tracks = playlist_info['tracks']['total']
        if total_tracks < num_to_delete:
            add_log(logs, f"🚨 Cannot delete {num_to_delete} songs, playlist only has {total_tracks}.")
            return {"success": False, "log": logs}

        # Fetch only the first 'num_to_delete' tracks, which are the last in playlist order
        results = sp.playlist_items(playlist_id, limit=num_to_delete, offset=0, fields='items(track(id,uri,name))')

        tracks_to_delete = []
        for item in results['items']:
            if item.get('track') and item['track'].get('id'):
                tracks_to_delete.append({
                    "id": item['track']['id'],
                    "uri": item['track']['uri'],
                    "name": item['track']['name']
                })

        if not tracks_to_delete:
            add_log(logs, "Could not find any tracks to delete.")
            return {"success": False, "log": logs}

        track_ids_to_delete = [t['id'] for t in tracks_to_delete]

        sp.playlist_remove_all_occurrences_of_items(playlist_id, track_ids_to_delete)

        track_names = ", ".join([t['name'] for t in tracks_to_delete])
        add_log(logs, f"✅ Successfully deleted {len(tracks_to_delete)} song(s): {track_names}")

        return {"success": True, "deleted_track_ids": track_ids_to_delete, "log": logs}

    except spotipy.exceptions.SpotifyException as e:
        add_log(logs, f"🚨 Spotify API Error during deletion: {e.msg}")
        return {"success": False, "log": logs}
    except Exception as e:
        add_log(logs, f"🚨 An unexpected error occurred during deletion: {e}")
        return {"success": False, "log": logs}
