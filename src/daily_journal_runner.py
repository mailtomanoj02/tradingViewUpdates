"""Entrypoint: daily trade journal job (Mon-Fri, after 21:30 IST).

Sends the daily journal email for each instrument, appends to the
persisted log, and additionally sends weekly/monthly/yearly rollup emails
on the last trading day of the week/month/year.

Run with: python -m src.daily_journal_runner
"""

from dotenv import load_dotenv

from .journal_runner import run_daily_journal

load_dotenv()

if __name__ == "__main__":
    run_daily_journal()
