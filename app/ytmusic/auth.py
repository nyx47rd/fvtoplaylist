from google_auth_oauthlib.flow import Flow
from firebase_admin import firestore
from fastapi import HTTPException

from ..core import config

def create_google_oauth_flow():
    """Creates a Google OAuth Flow instance."""
    return Flow.from_client_config(
        client_config={
            "web": {
                "client_id": config.GOOGLE_CLIENT_ID,
                "client_secret": config.GOOGLE_CLIENT_SECRET,
                "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                "token_uri": "https://oauth2.googleapis.com/token",
                "redirect_uris": [config.GOOGLE_REDIRECT_URI],
            }
        },
        scopes=config.YT_SCOPES,
        redirect_uri=config.GOOGLE_REDIRECT_URI
    )

def get_google_auth_url():
    """Generates the Google authentication URL."""
    flow = create_google_oauth_flow()
    authorization_url, _ = flow.authorization_url(
        access_type='offline',
        prompt='consent',
        include_granted_scopes='true'
    )
    return authorization_url

def exchange_code_for_credentials(code: str):
    """Exchanges an authorization code for Google API credentials."""
    flow = create_google_oauth_flow()
    flow.fetch_token(code=code)
    credentials = flow.credentials
    # Convert credentials to a dictionary to store in Firestore
    return {
        'token': credentials.token,
        'refresh_token': credentials.refresh_token,
        'token_uri': credentials.token_uri,
        'client_id': credentials.client_id,
        'client_secret': credentials.client_secret,
        'scopes': credentials.scopes
    }

def save_credentials_to_firestore(spotify_user_id: str, google_creds: dict):
    """Saves Google credentials to Firestore, linked to a Spotify user ID."""
    if not spotify_user_id:
        raise ValueError("Cannot save credentials without a valid Spotify user ID.")
    try:
        db = firestore.client()
        user_doc_ref = db.collection('users').document(spotify_user_id)
        user_doc_ref.set({
            'google_credentials': google_creds
        }, merge=True) # merge=True adds the field without overwriting other data
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Could not save credentials to Firestore: {e}")

def get_credentials_from_firestore(spotify_user_id: str) -> dict | None:
    """Retrieves Google credentials from Firestore for a given Spotify user ID."""
    if not spotify_user_id:
        return None
    try:
        db = firestore.client()
        user_doc_ref = db.collection('users').document(spotify_user_id)
        doc = user_doc_ref.get()
        if doc.exists:
            return doc.to_dict().get('google_credentials')
        return None
    except Exception as e:
        # Log the error in a real app
        print(f"Error getting credentials from Firestore: {e}")
        return None
