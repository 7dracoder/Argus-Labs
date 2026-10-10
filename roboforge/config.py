"""Load local backend configuration without overriding deployment variables."""
from pathlib import Path

from dotenv import load_dotenv

ENV_FILE = Path(__file__).resolve().parent.parent / ".env"


def load_environment(path: Path | None = None) -> bool:
    # Explicit location avoids accidentally loading a parent directory's secrets.
    # Keep dollar signs in credentials literal instead of interpolating them.
    return load_dotenv(path if path is not None else ENV_FILE,
                       override=False, interpolate=False, encoding="utf-8")
