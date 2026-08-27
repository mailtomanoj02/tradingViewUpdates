"""Entrypoint: Asia Sweep Reversals journal job (daily + period rollups).

Run with: python -m src.asia_sweep_journal_check_runner
"""

from dotenv import load_dotenv

from .asia_sweep_journal_runner import run_asia_sweep_journal

load_dotenv()

if __name__ == "__main__":
    run_asia_sweep_journal()
