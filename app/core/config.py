import os
from dotenv import load_dotenv

load_dotenv()

# --- App Secrets ---
APP_SECRET_KEY = os.getenv("APP_SECRET_KEY")

# --- Spotify API Configuration ---
SPOTIPY_CLIENT_ID = os.getenv("SPOTIPY_CLIENT_ID")
SPOTIPY_CLIENT_SECRET = os.getenv("SPOTIPY_CLIENT_SECRET")
SPOTIPY_REDIRECT_URI = os.getenv("SPOTIPY_REDIRECT_URI")
SPOTIPY_SCOPES = "user-library-read playlist-modify-public playlist-modify-private"
TOKEN_INFO_SESSION_KEY = "spotify_token_info"

# --- Firebase Configuration ---
FIREBASE_SERVICE_ACCOUNT_JSON = os.getenv("FIREBASE_SERVICE_ACCOUNT_JSON")
