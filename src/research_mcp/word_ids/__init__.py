# word_ids/__init__.py
import asyncio
import random
import sqlite3
from pathlib import Path

# Paths to the adjective and noun files
ADJECTIVES_FILE = Path(__file__).parent / "adjectives.txt"
NOUNS_FILE = Path(__file__).parent / "nouns.txt"


class WordIDGenerator:
    def __init__(self, db_connection):
        self.db_connection = db_connection
        self.adjectives = self._load_words(ADJECTIVES_FILE)
        self.nouns = self._load_words(NOUNS_FILE)
        self.lock = asyncio.Lock()

    def _load_words(self, filepath):
        with open(filepath, "r") as f:
            words = [line.strip().upper() for line in f if line.strip()]
        return words

    async def generate_result_id(self):
        async with self.lock:
            while True:
                adj = random.choice(self.adjectives)
                noun = random.choice(self.nouns)
                result_id = f"{adj}-{noun}"
                # Check if the ID already exists in the database
                cursor = self.db_connection.cursor()
                cursor.execute("SELECT 1 FROM results WHERE id=?", (result_id,))
                if not cursor.fetchone():
                    return result_id
