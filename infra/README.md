# Local Alpha Studio runtime

`docker compose up -d --wait` applies every tracked SQL migration and then
starts the API, durable worker, PostgreSQL, Redis, and Vite web services. Host
ports bind to `127.0.0.1` only. Redis uses an append-only file and the worker
uses a recoverable processing list, so an interrupted job is reclaimed after a
restart. The LEAN worker is disabled by default and can be included with
`docker compose --profile lean up`.

Use `start-studio.cmd` on Windows. `start-studio.ps1 -Build` rebuilds the API
and worker image after Python dependency changes.
