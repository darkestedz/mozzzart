"""
analytics.py — Database & Analytics Layer for MozZzart Player (v5.8.0)

Handles local SQLite database storage for tracking user play counts globally 
and across specific playlist contexts, plus logging recommendation history 
for Google Gemini 3.5 Flash BYOK filter exclusions.
"""

import os
import sqlite3
import datetime
import logging

logger = logging.getLogger("MozZzartAnalytics")

def get_db_path():
    """Gets the path to the portable SQLite database in the app folder."""
    from utils import get_app_dir
    return os.path.join(get_app_dir(), "analytics.db")

def get_db_connection():
    """Establishes and returns a connection to the SQLite database."""
    db_path = get_db_path()
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn

def initialize_db():
    """Initializes the SQLite tables if they do not exist."""
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        
        # play_counts Table: track_path, title, artist, playlist_name, play_count, last_played_timestamp
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS play_counts (
            track_path TEXT,
            title TEXT,
            artist TEXT,
            playlist_name TEXT,
            play_count INTEGER DEFAULT 0,
            last_played_timestamp TEXT,
            PRIMARY KEY (track_path, playlist_name)
        )
        """)
        
        # recommendation_history Table: title, artist, timestamp_generated
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS recommendation_history (
            title TEXT,
            artist TEXT,
            timestamp_generated TEXT,
            PRIMARY KEY (title, artist)
        )
        """)
        
        # favorites Table: track_path, title, artist, timestamp_added
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS favorites (
            track_path TEXT PRIMARY KEY,
            title TEXT,
            artist TEXT,
            timestamp_added TEXT
        )
        """)
        
        # track_languages Table: track_path, language
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS track_languages (
            track_path TEXT PRIMARY KEY,
            language TEXT
        )
        """)
        
        conn.commit()
    except Exception as e:
        logger.error(f"Error initializing analytics database: {e}")
    finally:
        conn.close()

def get_track_language(track_path):
    """
    Returns the user-assigned Whisper language for a specific track path.
    Returns None if not set or if set to 'Auto-Detect'.
    """
    conn = get_db_connection()
    lang = None
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT language FROM track_languages WHERE track_path = ?", (track_path,))
        row = cursor.fetchone()
        if row:
            lang = row[0]
    except Exception as e:
        logger.error(f"Error getting track language: {e}")
    finally:
        conn.close()
    return lang

def set_track_language(track_path, language):
    """
    Saves or updates the user-assigned Whisper language for a track.
    If language is 'Auto-Detect' or None, it deletes the record.
    """
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        if language is None or language == "Auto-Detect":
            cursor.execute("DELETE FROM track_languages WHERE track_path = ?", (track_path,))
        else:
            lang_code = language.lower()
            cursor.execute("INSERT OR REPLACE INTO track_languages (track_path, language) VALUES (?, ?)", (track_path, lang_code))
        conn.commit()
    except Exception as e:
        logger.error(f"Error setting track language: {e}")
    finally:
        conn.close()

def parse_track_meta(file_path):
    """
    Extracts the Title and Artist from an audio track's metadata using Mutagen.
    Falls back to parsing the file name as 'Artist - Title' if metadata is absent.
    """
    title = None
    artist = None
    try:
        import mutagen
        audio = mutagen.File(file_path)
        if audio:
            # Check common ID3v2 tags
            if "TIT2" in audio:
                title = audio["TIT2"].text[0]
            elif "title" in audio:
                title = audio["title"][0]
                
            if "TPE1" in audio:
                artist = audio["TPE1"].text[0]
            elif "artist" in audio:
                artist = audio["artist"][0]
    except Exception as e:
        logger.debug(f"Mutagen tag extraction failed or skipped for {file_path}: {e}")

    # Fallback: parse filename
    filename = os.path.splitext(os.path.basename(file_path))[0]
    if not title or not artist:
        if " - " in filename:
            parts = filename.split(" - ", 1)
            f_artist = parts[0].strip()
            f_title = parts[1].strip()
            if not artist:
                artist = f_artist
            if not title:
                title = f_title
        else:
            if not title:
                title = filename.strip()
            if not artist:
                artist = "Unknown Artist"
                
    return artist, title

def increment_play_count(track_path, playlist_name):
    """
    Increments the play count of a track in both the Global scope
    and the specific active playlist context.
    """
    initialize_db()
    
    # 1. Global context increment
    _increment_single_context(track_path, "Global")
    
    # 2. Specific context increment
    if playlist_name and playlist_name != "Global":
        _increment_single_context(track_path, playlist_name)

def _increment_single_context(track_path, playlist_name):
    """Helper method to increment play count for a single context."""
    artist, title = parse_track_meta(track_path)
    now = datetime.datetime.now().isoformat()
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT play_count FROM play_counts WHERE track_path = ? AND playlist_name = ?",
            (track_path, playlist_name)
        )
        row = cursor.fetchone()
        if row:
            new_count = row[0] + 1
            cursor.execute(
                "UPDATE play_counts SET play_count = ?, last_played_timestamp = ?, title = ?, artist = ? WHERE track_path = ? AND playlist_name = ?",
                (new_count, now, title, artist, track_path, playlist_name)
            )
        else:
            cursor.execute(
                "INSERT INTO play_counts (track_path, title, artist, playlist_name, play_count, last_played_timestamp) VALUES (?, ?, ?, ?, 1, ?)",
                (track_path, title, artist, playlist_name, now)
            )
        conn.commit()
        logger.info(f"Incremented play count for '{title}' by '{artist}' in context '{playlist_name}'.")
    except Exception as e:
        logger.error(f"Failed to increment play count for {track_path} in {playlist_name}: {e}")
    finally:
        conn.close()

def get_top_played_tracks(limit=50, playlist_name="Global"):
    """Returns the top played tracks sorted by play count descending."""
    initialize_db()
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT track_path, title, artist, playlist_name, play_count, last_played_timestamp FROM play_counts WHERE playlist_name = ? ORDER BY play_count DESC LIMIT ?",
            (playlist_name, limit)
        )
        rows = cursor.fetchall()
        return [dict(r) for r in rows]
    except Exception as e:
        logger.error(f"Failed to fetch top played tracks: {e}")
        return []
    finally:
        conn.close()

def add_to_recommendation_history(title, artist):
    """Saves a track title and artist combination into the AI recommended history."""
    initialize_db()
    now = datetime.datetime.now().isoformat()
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(
            "INSERT OR IGNORE INTO recommendation_history (title, artist, timestamp_generated) VALUES (?, ?, ?)",
            (title, artist, now)
        )
        conn.commit()
        logger.info(f"Logged recommendation history: '{title}' - '{artist}'")
    except Exception as e:
        logger.error(f"Failed to add to recommendation history: {e}")
    finally:
        conn.close()

def get_recommendation_history():
    """Retrieves all tracks previously recommended by the AI."""
    initialize_db()
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT title, artist FROM recommendation_history")
        rows = cursor.fetchall()
        return [{"title": r[0], "artist": r[1]} for r in rows]
    except Exception as e:
        logger.error(f"Failed to retrieve recommendation history: {e}")
        return []
    finally:
        conn.close()

def clear_recommendation_history():
    """Deletes all entries from recommendation history to reset the AI algorithm."""
    initialize_db()
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM recommendation_history")
        conn.commit()
        logger.info("Recommendation history cleared successfully.")
        return True
    except Exception as e:
        logger.error(f"Failed to clear recommendation history: {e}")
        return False
    finally:
        conn.close()

def toggle_favorite(track_path, title, artist):
    """
    Checks if a track_path exists in the favorites table.
    If it exists, delete it (unfavorite). If it doesn't, insert it.
    Returns True if favorited, False if unfavorited.
    """
    initialize_db()
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT 1 FROM favorites WHERE track_path = ?", (track_path,))
        row = cursor.fetchone()
        if row:
            cursor.execute("DELETE FROM favorites WHERE track_path = ?", (track_path,))
            conn.commit()
            logger.info(f"Removed from favorites: '{title}' by '{artist}'")
            return False
        else:
            now = datetime.datetime.now().isoformat()
            cursor.execute(
                "INSERT INTO favorites (track_path, title, artist, timestamp_added) VALUES (?, ?, ?, ?)",
                (track_path, title, artist, now)
            )
            conn.commit()
            logger.info(f"Added to favorites: '{title}' by '{artist}'")
            return True
    except Exception as e:
        logger.error(f"Failed to toggle favorite for {track_path}: {e}")
        return False
    finally:
        conn.close()

def is_track_favorite(track_path):
    """Returns a boolean indicating if the track path is present in favorites."""
    initialize_db()
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT 1 FROM favorites WHERE track_path = ?", (track_path,))
        row = cursor.fetchone()
        return row is not None
    except Exception as e:
        logger.error(f"Failed to check favorite status for {track_path}: {e}")
        return False
    finally:
        conn.close()

def get_all_favorites():
    """Queries and returns a list of dictionaries [{'title': title, 'artist': artist, 'track_path': path}] representing all favorited items."""
    initialize_db()
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT title, artist, track_path FROM favorites ORDER BY timestamp_added DESC")
        rows = cursor.fetchall()
        return [{"title": r[0], "artist": r[1], "track_path": r[2]} for r in rows]
    except Exception as e:
        logger.error(f"Failed to fetch all favorites: {e}")
        return []
    finally:
        conn.close()

def delete_track_data(track_path):
    """Deletes all persistent analytics data associated with a track path (favorites, play counts)."""
    initialize_db()
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM favorites WHERE track_path = ?", (track_path,))
        cursor.execute("DELETE FROM play_counts WHERE track_path = ?", (track_path,))
        conn.commit()
        logger.info(f"Cleared persistent analytics database records for: {track_path}")
        return True
    except Exception as e:
        logger.error(f"Failed to delete track analytics data for {track_path}: {e}")
        return False
    finally:
        conn.close()

