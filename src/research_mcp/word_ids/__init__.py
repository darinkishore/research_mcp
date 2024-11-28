# word_ids/__init__.py
import random
from pathlib import Path

from sqlalchemy import select

from research_mcp.db import Result, db


# Paths to the adjective and noun files
ADJECTIVES_FILE = Path(__file__).parent / 'adjectives.txt'
NOUNS_FILE = Path(__file__).parent / 'nouns.txt'


class WordIDGenerator:
    def __init__(self):
        self.adjectives = self._load_words(ADJECTIVES_FILE)
        self.nouns = self._load_words(NOUNS_FILE)

    def _load_words(self, filepath):
        with open(filepath) as f:
            words = [line.strip().lower() for line in f if line.strip()]
        return words

    async def generate_result_id(self):
        while True:
            adj = random.choice(self.adjectives)
            noun = random.choice(self.nouns)
            result_id = f'{adj}-{noun}'
            # Check if the ID already exists in the database
            async with db() as session:
                stmt = select(Result).where(Result.id == result_id)
                existing_result = await session.execute(stmt)
                if not existing_result.scalars().first():
                    return result_id
