from icalendar import Calendar, Event
from datetime import datetime, timedelta 
from uuid import uuid4
def build_test_calendar():
    cal = Calendar()
    cal.add('prodid', '-//Hindu Calendar (Test)//vrushali//EN')
    cal.add('version', '2.0')

    # Create a simple all-day event for today to validate .ics rendering
    today = datetime.now().date()

    ev = Event()
    ev.add('uid', f"{uuid4()}@hinducalendar")
    ev.add('summary', 'Test Calendar Setup ✅')
    ev.add('dtstart', today)                # all-day start
    ev.add('dtend', today + timedelta(days=1))
    ev.add('description', 'First generated event to verify .ics works.')
    cal.add_component(ev)

    return cal.to_ical()

if __name__ == "__main__":
    ics_bytes = build_test_calendar()
    with open('site/test-calendar.ics', 'wb') as f:
        f.write(ics_bytes)
    print("Wrote site/test-calendar.ics")
