# Bahi

Your TallyPrime books on your phone, from your own server.

- `server/`: the Docker app (Python standard library only). It stores synced data and serves the phone web app.
- `agent/`: PowerShell sync agent for the Tally PC (Windows). It runs every 10 minutes via Task Scheduler.
- `unraid/bahi.xml`: Unraid Docker template.
- `tests/mock_tally.py`: a simulated Tally XML server used for testing.

The image is built automatically to `ghcr.io/bdlnaredi/bahi:latest` on every push to `main`.
See `server/README.md` for setup.
