# Prism

## Local Startup

Prism has three local application processes:

- Frontend: Vite dev server on `5173`
- Backend: FastAPI backend on `5175`
- Engine: FastAPI engine on `5180`

The backend can start the engine automatically. Use one of the following startup modes.

### Mode A: Backend Starts Engine Automatically

Use this when you only need one backend console.

```powershell
cd h:\Agent\Project\Prism\prism
python -m backend.run
```

Do not run `python -m engine.run` separately in this mode, because the backend will already start the engine and occupy port `5180`.

Start the frontend in another terminal:

```powershell
cd h:\Agent\Project\Prism\prism\frontend
pnpm.cmd dev -- --host 127.0.0.1 --port 5173
```

### Mode B: Start Engine And Backend Separately

Use this when you want to see engine logs and backend logs in separate consoles.

Terminal 1, start the engine:

```powershell
cd h:\Agent\Project\Prism\prism
python -m engine.run
```

Terminal 2, start the backend without auto-starting the engine:

```powershell
cd h:\Agent\Project\Prism\prism
$env:SKIP_ENGINE='1'
python -m backend.run
```

Terminal 3, start the frontend:

```powershell
cd h:\Agent\Project\Prism\prism\frontend
pnpm.cmd dev -- --host 127.0.0.1 --port 5173
```

## Port Conflict Checks

If startup fails with `WinError 10048`, the port is already occupied. Check the relevant port:

```powershell
netstat -ano | findstr ":5175 "
netstat -ano | findstr ":5180 "
```

Then inspect the owning process:

```powershell
Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -match 'backend.run|engine.run' } | Select-Object ProcessId,CommandLine
```

Stop a stale process by PID:

```powershell
Stop-Process -Id <PID>
```
