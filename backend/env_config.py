"""
Environment loading helpers for the backend.

The project includes a .env.example and depends on python-dotenv, so local
development expects .env values to be loaded automatically from the backend
directory.
"""

from pathlib import Path

from dotenv import load_dotenv


def ensure_env_loaded() -> None:
    """Load backend .env files once for local development."""
    backend_dir = Path(__file__).resolve().parent
    load_dotenv(backend_dir / ".env")
    load_dotenv(backend_dir / ".env.local")
