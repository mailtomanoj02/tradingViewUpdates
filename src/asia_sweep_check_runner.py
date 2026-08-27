"""Entrypoint: Asia Sweep Reversals live check for all 4 pairs.

Run with: python -m src.asia_sweep_check_runner
"""

from dotenv import load_dotenv

from .asia_sweep_runner import run_asia_sweep_check

load_dotenv()

if __name__ == "__main__":
    run_asia_sweep_check()
