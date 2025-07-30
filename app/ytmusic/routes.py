from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

router = APIRouter()
templates = Jinja2Templates(directory="templates")

@router.get("/", response_class=HTMLResponse)
async def get_ytmusic_page(request: Request):
    """Renders the main page for the YouTube Music sync feature."""
    # We will add logic here to check if the user is logged into both
    # Spotify and Google.
    return templates.TemplateResponse("ytmusic.html", {"request": request, "user": "Placeholder User"})

@router.get("/login")
async def login_google():
    """Redirects the user to Google for OAuth authentication."""
    # This will be implemented in auth.py
    return {"message": "Redirect to Google OAuth will happen here."}

@router.get("/callback")
async def callback_google(request: Request):
    """Handles the OAuth callback from Google."""
    # This will be implemented in auth.py
    return {"message": "Handling Google OAuth callback."}

@router.post("/sync")
async def sync_to_ytmusic(request: Request):
    """
    Endpoint to start the synchronization process from Spotify to YouTube Music.
    """
    # This will call the logic in client.py
    return {"message": "Syncing from Spotify to YouTube Music will start here."}
