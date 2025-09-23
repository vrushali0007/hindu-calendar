# hinducalendar

This project builds Hindu calendar `.ics` files via both a command-line interface
and a FastAPI service. Coordinates (latitude/longitude) are required so that the
calendar events can be generated for the correct location.

## API usage

The FastAPI server exposes the `/ics` endpoint which mirrors the CLI flags.
Request parameters include latitude/longitude, year range, tradition filters, and
more. By default you must explicitly provide both `lat` and `lon`, but you can
also ask the server to autodetect coordinates from the request IP by passing
`auto_location=true`.

If auto-detection fails the API returns an HTTP 400 with a helpful error message
so the caller can retry with manually supplied coordinates.

### Example

```http
GET /ics?year=2025&auto_location=true HTTP/1.1
Host: example.com
```

## CLI usage

Use the CLI when you prefer to generate calendar files locally. The
`--auto-location` flag mirrors the API behaviour and overrides any
user-provided `--lat`/`--lon` options.

```bash
python -m src.cli --year 2025 --auto-location
```

If auto-detection fails, re-run the command with explicit coordinates using the
`--lat` and `--lon` flags.
