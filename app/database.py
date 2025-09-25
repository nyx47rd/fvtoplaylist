import os
import psycopg2
import logging
import uuid
from app.core import config

logging.basicConfig(level=logging.INFO)

def get_db_connection():
    """Establishes a connection to the database."""
    try:
        conn = psycopg2.connect(config.DATABASE_URL)
        return conn
    except psycopg2.OperationalError as e:
        logging.error(f"Could not connect to database: {e}")
        return None

def initialize_db():
    """Initializes the database by creating the necessary tables if they don't exist."""
    conn = get_db_connection()
    if conn is None:
        logging.error("Database connection failed, cannot initialize.")
        return

    try:
        with conn.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS deleted_songs (
                    id SERIAL PRIMARY KEY,
                    user_id VARCHAR(255) NOT NULL,
                    playlist_id VARCHAR(255) NOT NULL,
                    song_id VARCHAR(255) NOT NULL,
                    song_uri VARCHAR(255) NOT NULL,
                    deleted_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
                    batch_id UUID NOT NULL
                );
            """)
            conn.commit()
            logging.info("Database initialized successfully.")
    except psycopg2.Error as e:
        logging.error(f"Error initializing database: {e}")
    finally:
        if conn:
            conn.close()

def log_deleted_songs(user_id, playlist_id, songs, batch_id):
    """Logs a batch of deleted songs to the database."""
    conn = get_db_connection()
    if not conn:
        return
    try:
        with conn.cursor() as cur:
            for song in songs:
                cur.execute(
                    """
                    INSERT INTO deleted_songs (user_id, playlist_id, song_id, song_uri, batch_id)
                    VALUES (%s, %s, %s, %s, %s)
                    """,
                    (user_id, playlist_id, song['id'], song['uri'], batch_id),
                )
            conn.commit()
    finally:
        if conn:
            conn.close()

def get_last_deleted_batch(user_id, playlist_id):
    """Retrieves the last batch of deleted songs for a user and playlist."""
    conn = get_db_connection()
    if not conn:
        return None, []

    try:
        with conn.cursor() as cur:
            # First, find the most recent batch_id for the user and playlist
            cur.execute(
                """
                SELECT batch_id FROM deleted_songs
                WHERE user_id = %s AND playlist_id = %s
                ORDER BY deleted_at DESC
                LIMIT 1
                """,
                (user_id, playlist_id)
            )
            result = cur.fetchone()
            if not result:
                return None, []

            batch_id = result[0]

            # Now, fetch all songs with that batch_id
            cur.execute(
                """
                SELECT song_id, song_uri FROM deleted_songs
                WHERE batch_id = %s
                """,
                (batch_id,)
            )
            songs = [{'id': row[0], 'uri': row[1]} for row in cur.fetchall()]
            return batch_id, songs
    finally:
        if conn:
            conn.close()

def clear_deleted_batch(batch_id):
    """Clears a batch of deleted songs from the database, typically after an undo."""
    conn = get_db_connection()
    if not conn:
        return
    try:
        with conn.cursor() as cur:
            cur.execute(
                "DELETE FROM deleted_songs WHERE batch_id = %s",
                (batch_id,)
            )
            conn.commit()
    finally:
        if conn:
            conn.close()

# We should call initialize_db() when the application starts.
# This can be done in main.py.