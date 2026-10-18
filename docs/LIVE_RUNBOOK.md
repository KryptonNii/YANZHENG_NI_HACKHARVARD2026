# TrialPilot live mode on Windows

The normal mode uses external data sources and the configured Claude API. Keep
`DEMO_OFFLINE=0` in the root `.env`. The web app must use `VITE_MOCK_API=0`.
Do not commit `.env` or put an API key in a `VITE_` variable.
Protocol extraction defaults to Claude Sonnet 5.5 (`claude-sonnet-5-5`); the
backend reads an explicit model override from `EXTRACT_MODEL` in `.env`.

## Start the local application

The Python environment at `api/.venv` and the packages in `web/node_modules` must
already be installed. Double-click `sysup.cmd` in the repository root to start
both services. It loads the saved `.env`, forces live mode, disables sample
design seeding, and uses API **8008** / web **5181**. The servers run without extra
console windows and keep running after the launcher closes. It does not open a
browser automatically; visit [TrialPilot](http://127.0.0.1:5181/).

Each `sysup.cmd` launch forcibly stops any processes listening on API **8008**
and web **5181**, including healthy TrialPilot services or other applications,
then starts both services fresh. Logs and PID metadata are saved under
`var/services/`. To inspect readiness without starting or stopping services or
changing files, use the read-only check:

```cmd
api\.venv\Scripts\python.exe scripts\start_services.py --check
```

The launcher preserves the configured database and cache paths. Windows restarts
stop these services; double-click `sysup.cmd` again after signing in. It does not
install a Windows startup task or service.

For foreground logs and Ctrl+C control, the PowerShell launcher remains available.
These commands start processes in two separate terminals; leave those terminals
open while using the application.

From the repository root, start the API in the first terminal:

```powershell
.\scripts\start-live.ps1 -Service Api
```

In the second terminal:

```powershell
.\scripts\start-live.ps1 -Service Web
```

Open [TrialPilot](http://127.0.0.1:5181/). The launcher sets live mode explicitly,
loads the root `.env` for the API, and sends frontend API requests to
`http://127.0.0.1:8008`. It also sets `TP_SEED_FIXTURE_DESIGNS=0` so a fresh
database does not receive sample trial designs at startup. It does not print the
API key. Check the API configuration:

```powershell
Invoke-RestMethod http://127.0.0.1:8008/api/health | Select-Object status, offline
```

Expected: `status` is `ok`, and `offline` is `False`. This confirms the running
backend mode; it does not itself call Claude or verify an external data source.
Import a new trial and inspect the source and extraction status in the app to
verify an actual external request. Previously imported records can remain cached.

## Restart and keep settings

Rerun `sysup.cmd` to forcibly stop listeners on both service ports and restart
the application. For foreground services, rerun the corresponding PowerShell
command: `-Service Api` forcibly stops any listener on `-ApiPort`, and
`-Service Web` does the same on `-WebPort`, before starting its service. This
also replaces healthy services and other applications using those ports. Ctrl+C
still stops a foreground service in its owning terminal.

To use a different pair of ports, pass the same values in both commands:

```powershell
.\scripts\start-live.ps1 -Service Api -ApiPort 8009 -WebPort 5182
.\scripts\start-live.ps1 -Service Web -ApiPort 8009 -WebPort 5182
```

The script preserves the configured database and cache locations. It creates no
temporary demo database and does not erase existing records. `TP_DB_PATH` and
`TP_DATA_DIR` inherited from the terminal override `.env`; use fresh terminals if
you previously configured temporary demo paths. With no path overrides, the API
stores its database at `var/trialpilot.sqlite`.

Live mode stays configured across restarts through `.env` and the launcher.
Changing `.env` requires restarting the API. The PowerShell foreground services
stop when their terminals close. With `sysup.cmd`, closing the launcher window
leaves the servers running. Neither launcher installs an automatically started
Windows service.

## Docker alternative

`docker compose up --build -d` defaults to live mode and has an
`unless-stopped` restart policy. Its database persists in the `tp-data` volume.
The compose app opens at [port 8000](http://127.0.0.1:8000/) by default. An explicit
`DEMO_OFFLINE=1` in the shell or `.env` still selects offline mode. Docker must be
installed and running; this Windows launcher does not install or start Docker.

## Data availability

Live mode permits actual registry, geocoding, and model requests. Individual
requests can still use a cache or return a source error, so inspect their
provenance and status. Live mode does not turn a simulated operations feed or
stored demonstration records into measured site data.
