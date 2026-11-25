# Spotify Language Organizer

A local Python and FastAPI application that reads your liked tracks on Spotify, identifies each song's actual language from its lyrics, and organizes them into clean, language-specific playlists without creating duplicates on repeated runs.

## How it works

The Spotify Web API does not expose a track's language. Trying to guess it from track titles or artist genres leads to frequent mistakes: short titles are ambiguous, and artists often release songs in languages other than the one associated with their main market.

This project avoids those pitfalls with a four-stage pipeline:

1. **Ingestion and deduplication**: Fetches your liked tracks and collapses duplicate releases using the ISRC code as the primary key and normalized `artist + title` as a fallback.
2. **Lyrics lookup and language detection**: Queries the open LRCLIB API for lyrics and runs them through `lingua-language-detector`. A track is only assigned to a language playlist when model confidence reaches 85% or higher (or 70%–85% when the ISRC country prefix corroborates the result). Instrumental, missing-lyrics, or low-confidence tracks are left out or optionally placed in a review playlist.
3. **Cleanup**: Scans your existing playlists and either updates the managed ones in place (preserving their URL, cover image, and followers while removing any stray duplicates) or deletes and recreates them from scratch. Third-party and unrelated personal playlists are never touched.
4. **Population**: Writes tracks in batches that respect Spotify API limits (100 items per playlist request, 40 URIs per library removal request) and automatically handles `429` rate limits and token refreshes.

Classification results and OAuth tokens are stored in a local SQLite database (`spotify_organizer.db`), so subsequent runs only fetch lyrics for newly liked tracks.

## Prerequisites

- Python 3.11 or newer
- A Spotify account with an active Premium subscription (required by Spotify for apps running in Development Mode)
- A registered app in the [Spotify Developer Dashboard](https://developer.spotify.com/dashboard)

## Spotify app setup

In your app settings on the Spotify Developer Dashboard:

1. Under **Redirect URIs**, add:
   `http://127.0.0.1:8000/auth/callback`
   Spotify requires the explicit `127.0.0.1` loopback address rather than `localhost`.
2. Under **User Management**, add the email address of your Spotify account if it is not listed yet.
3. Copy your **Client ID** and **Client Secret**.

## Running locally

The fastest way to get started is the launch script. On its first run, it checks your Python version, creates `.venv`, installs dependencies, prompts for your Spotify credentials to populate `.env`, starts the server, and opens the web UI in your browser:

```bash
git clone https://github.com/your-username/spotify-organizer.git
cd spotify-organizer
chmod +x install.sh start.sh
./start.shIf you only want to set up the environment without launching the server (for example, to run tests):Bash./install.sh        # runtime dependencies
./install.sh --dev  # includes pytestTo run the server with auto-reload during development:Bash./start.sh --devIf you prefer manual setup (or are running PowerShell on Windows without Git Bash or WSL):Powershellpython -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
copy .env.example .env
# Fill in SPOTIFY_CLIENT_ID and SPOTIFY_CLIENT_SECRET in .env
uvicorn app.main:app --host 127.0.0.1 --port 8000Then open http://127.0.0.1:8000 in your browser.UsageWeb UIWith the application running at http://127.0.0.1:8000:Click Connect with Spotify and authorize access to your account.Choose how existing playlists should be handled (replace_tracks updates them in place; hard_delete removes and recreates them).Run Dry Run (Simulate) first to inspect the language breakdown without modifying anything in your Spotify library.Click Organize playlists when you are ready to apply the changes. Progress and per-language counts update live on screen.REST APIInteractive API documentation is available at http://127.0.0.1:8000/docs. You can also trigger runs directly:Bashcurl -X POST http://127.0.0.1:8000/organize/run \
  -H "Content-Type: application/json" \
  -d '{
    "cleanup_mode": "replace_tracks",
    "dry_run": true,
    "create_quarantine_playlist": false
  }'The endpoint returns a job_id immediately and executes in the background. Poll its status via GET /organize/jobs/<job_id>.Request options (POST /organize/run)FieldDefaultBehaviorcleanup_modereplace_tracksreplace_tracks keeps the existing playlist ID, link, and cover while removing extra duplicates. hard_delete unfollows all matching managed playlists and creates fresh ones.public_playlistsfalseControls whether newly created playlists are public or private.create_quarantine_playlistfalsePlaces tracks with missing lyrics or confidence below threshold into a separate review playlist.dry_runfalseClassifies tracks and populates the local cache without touching your Spotify playlists.force_reclassifyfalseIgnores cached results and re-fetches lyrics for all tracks.Other endpointsGET /health — basic health check.GET /auth/status — returns whether a Spotify account is currently connected.DELETE /cache — clears cached track classifications while keeping OAuth tokens intact.Running testsBash./install.sh --dev
.venv/bin/pytest -vThe test suite covers text normalization, SQLite caching, language classification, Spotify 401/429 retry handling, batch chunking, playlist cleanup logic, and API guards.Customization and API notesThis project targets the 2026 Spotify Web API endpoints for Development Mode apps (POST /me/playlists, /playlists/{id}/items, and DELETE /me/library). To add more target languages or rename the generated playlists, edit target_playlists in app/config.py.Code---
