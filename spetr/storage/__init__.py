"""
Módulo de Armazenamento e Persistência SQLite.
"""
from spetr.storage.database import SQLiteDatabase
from spetr.storage.repository import ElectionRepository

__all__ = ["SQLiteDatabase", "ElectionRepository"]
