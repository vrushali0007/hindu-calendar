# Calendar Automation System

A geo aware calendar that handles complex data and calculations and adjusts festival dates and Rahu Kaal to the user location and provides ICS feeds for Apple and Google Calendar.

## What this project delivers
1. Coverage for more than thirty major festivals and daily Rahu Kaal
2. Location specific rules using sunrise sunset tithi and nakshatra logic with the de421 ephemeris
3. One click calendar subscription through ICS
4. A simple site for quick checks with no extra clicks

## Quick start
```bash
git clone https://github.com/vrushali0007/hindu-calendar.git
cd hindu-calendar
python -m venv .venv
source .venv/bin/activate    # on Windows use .venv\Scripts\activate
pip install -r requirements.txt
python cli.py
