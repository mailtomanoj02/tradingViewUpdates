"""Entrypoint: session check -> fetch -> signal -> email, for EURUSD (5m).

Run with: python -m src.eurusd_runner
"""

from dotenv import load_dotenv

from .runner import run

load_dotenv()

if __name__ == "__main__":
    run("EURUSD", "5m")
