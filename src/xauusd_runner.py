"""Entrypoint: session check -> fetch -> signal -> email, for XAUUSD (3m).

Run with: python -m src.xauusd_runner
"""

from dotenv import load_dotenv

from .runner import run

load_dotenv()

if __name__ == "__main__":
    run("XAUUSD", "3m")
