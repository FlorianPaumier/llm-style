# llm-style — C# web and desktop

The shared Blazor screens now use real local C# services: wardrobe CRUD/search/filter/sort/pagination, multiple people, settings, weather-aware recommendations, coordinated outfits and options, history/worn tracking, photo review and quick add, and background API jobs. SQLite, photo storage, Ollama and Open-Meteo are implemented in Infrastructure. The Python app remains available as the migration reference.

## Run the web app

On this Apple Silicon machine, SDK 10.0.402 is installed in `~/.dotnet`:

```sh
export DOTNET_ROOT="$HOME/.dotnet"
export PATH="$DOTNET_ROOT:$PATH"
cd dotnet
dotnet run --project src/LlmStyle.Web --launch-profile http
```

Open [localhost:5103](http://localhost:5103). Start with an item in Wardrobe or upload photos. Set the city, Ollama URL and stylist/vision model names in Settings. Ollama must run separately with those models pulled. Weather or stylist outages produce an explained safe recommendation; photo-model failures are shown without inventing or auto-saving drafts.

The C# web host creates **`dotnet/data/llm_style.db` and `dotnet/data/images/`** by default. It does not open the Python app's `data/` directory. The desktop host uses MAUI's application-data directory; these are separate local stores, with no automatic sync. Override the web location with `LLM_STYLE_DATA_DIR` or `--data-dir`.

Defaults also accept `LLM_STYLE_CITY`, `LLM_STYLE_MODEL`, `LLM_STYLE_VISION_MODEL`, and `LLM_STYLE_OLLAMA_URL`. Stored settings override these defaults. `LLM_STYLE_CORS_ORIGINS` restricts browser origins; default is `*`, matching the existing trusted-local-network API. Public internet hosting and authentication are outside this migration.

## Import an existing wardrobe safely

Stop the Python app while importing so its photos remain consistent with its database. Choose a **new destination that does not exist**. The importer takes a SQLite backup, migrates the copy, copies referenced photos and refuses overwrites. The source database/photos remain unchanged.

From `dotnet/` on macOS:

```sh
dotnet run --project src/LlmStyle.Web -- \
  --import-from ../data \
  --data-dir "$HOME/Library/Application Support/llm-style-imported" \
  --urls http://localhost:5103
```

On later runs, omit `--import-from` and keep the same `--data-dir`. Back up the C# data directory before upgrades; stop its host or use a SQLite-consistent backup, rather than copying only the database while WAL writes are active. Rollback uses the original unchanged Python data. Newly claimed C# photos use item-ID/token filenames to avoid overwriting the previous photo before committing its new database reference.

## Tests and builds

Run from `dotnet/`, so global.json selects the pinned SDK feature band and Microsoft.Testing.Platform:

```sh
dotnet test --project tests/LlmStyle.Domain.Tests
dotnet test --project tests/LlmStyle.Infrastructure.Tests
dotnet test --project tests/LlmStyle.Web.Tests
dotnet build src/LlmStyle.Web
```

Tests use temporary databases and files. They cover domain constraints, actual SQLite persistence/migrations/import, concurrent partial updates and worn counting, HTTP contracts in Development/Production, jobs, model JSON, offline fallback, options/pair mode and photo ownership. Real external models are not required.

Browser workflows use a separate throwaway server/database and a local fake Ollama HTTP server:

```sh
cd ../e2e
npm install
npx playwright install chromium
node node_modules/@playwright/test/cli.js test --config playwright.dotnet.config.ts
```

Set `E2E_DOTNET` if the SDK executable is not at `~/.dotnet/dotnet`. The original Python browser suite still uses `playwright.config.ts`. The C# suite checks CRUD/reload/search, settings/people, wardrobe gaps, mixed-success photo queues/review/Save all/quick add, long mobile searches, and photo replacement during editor changes.

## Web API and phone installation

The existing `/api/items`, `/api/personas`, `/api/settings`, `/api/weather`, `/api/outfits/recommend`, `/api/history`, `/api/classify`, `/api/jobs`, `/api/app/download`, `/api/app/qr.svg`, and `/api/health` route families are available, including async recommendation/classification and bulk classification. JSON remains snake_case; settings/persona updates distinguish absent fields from null. See [MOBILE_API.md](../MOBILE_API.md) for client shapes.

Jobs are in memory: a restart loses pending work, and finished jobs expire after an hour. Single-photo async failures set the job to `failed`; bulk jobs finish with per-photo error rows. The UI cancels page-bound external requests on navigation and does not automatically replay a save. Draft photos expire after 24 hours and are swept on storage startup.

The Get the App page provides a local-network URL/QR and browser installation instructions. Deliberate LAN hosting requires binding the web host to a reachable interface, for example `--urls http://0.0.0.0:5103`. Full PWA installation requires HTTPS (or localhost on the current device); plain LAN HTTP may only open the website. The cached offline page explains reconnecting; live Interactive Server controls require the host/circuit. No offline live-data capability is claimed.

## Native desktop

The desktop project targets **Apple Silicon ARM64** (`net10.0-maccatalyst` / `maccatalyst-arm64`) and Windows. It registers the same Application/Infrastructure services locally and requires neither Python nor a separately running web server. Linux and Intel Mac desktop distributions are outside the current targets.

Install full compatible Xcode, launch it to finish setup/license, then on Mac:

```sh
sudo xcode-select --switch /Applications/Xcode.app/Contents/Developer
dotnet workload install maui-maccatalyst
dotnet build src/LlmStyle.Desktop -t:Run -f net10.0-maccatalyst -r maccatalyst-arm64
```

The Mac Catalyst workload is installed (workload set 10.0.402.1, MAUI 10.0.110). This machine currently has only Command Line Tools, so the native build stops at “Unable to locate a valid Xcode developer path.” The template's deployment floor is Mac Catalyst 17.0; use the selected workload's Xcode/OS requirements. Pin the workload/Xcode combination after a successful native build.

On Windows with the pinned .NET SDK:

```powershell
dotnet workload install maui-windows
dotnet build src/LlmStyle.Desktop -t:Run -f net10.0-windows10.0.19041.0
```

Native execution and signed distribution are unverified; Windows is unpackaged, and Mac signing/notarization and installers remain pending. Building the entire solution includes Desktop and requires its platform tooling. Web/test builds do not.

## Architecture and development

```text
Domain                       garment/value invariants and outfit policies; no project dependencies
Application → Domain         use cases, contracts and required ports
Infrastructure → Application SQLite/files/Ollama/weather/jobs adapters
UI → Application             shared Razor components and page-local state
Web/Desktop → UI + Infrastructure   composition roots
```

Domain owns category/role compatibility, warmth/formality rules and validated outfit picks. Application coordinates external results and fallback/history/photo workflows. SQLite operations use fresh connections; related writes use immediate transactions, while network calls remain async/cancellable. The singleton application service coordinates multi-step photo mutations; no Blazor circuit holds a database connection.

Develop through public domain/use-case/API/browser seams, observe failing behavior before the fix, implement the smallest passing change, and keep the suite green. Architecture tests prohibit outward Domain/Application references. No generic repositories, mediator framework, cloud sync or extra databases are introduced.

See the [migration plan](../docs/superpowers/plans/2026-10-20-csharp-blazor-desktop.md) for acceptance gates and remaining platform work. This implementation has regression evidence for its exercised workflows; it is not a claim that every Python edge case or native platform has been certified.
