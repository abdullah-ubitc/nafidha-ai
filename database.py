"""Database connection — shared singleton"""
import os
from motor.motor_asyncio import AsyncIOMotorClient
from pathlib import Path

ROOT_DIR = Path(__file__).parent

mongo_url = os.environ['MONGO_URL']
client = AsyncIOMotorClient(mongo_url)
db = client[os.environ['DB_NAME']]
