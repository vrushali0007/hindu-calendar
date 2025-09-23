# hinducalendar

Generate Hindu calendar events (.ics) via a CLI or FastAPI server.

## Year range defaults

Both the CLI (`src/cli.py`) and the `/ics` API endpoint now treat the
`year` argument as optional. When you omit it, the tools automatically use the
current calendar year. You can still supply `--year`/`year` to start from a
different year, and pair it with `--year-to`/`year_to` to extend the range. If
you pass an end year, ensure it is not earlier than the start year.
