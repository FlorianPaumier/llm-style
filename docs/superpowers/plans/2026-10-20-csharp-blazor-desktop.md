# C# / Blazor Web and Desktop Implementation Plan

> **For agentic workers:** Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox syntax for tracking. Implementation is separate from this planning request.

**Goal:** Reproduce the current working-tree feature set in C#, with a Blazor website and standalone macOS/Windows applications sharing their UI and application logic.

**Architecture:** Use a DDD modular monolith with Clean Architecture: Domain → Application, Infrastructure implementing Application ports, and Web/Desktop composition roots. Share Razor components through a Razor class library. The web host uses ASP.NET Core with Interactive Server; the desktop host uses .NET MAUI Blazor Hybrid and invokes the same local application services directly. Keep SQLite, Ollama, Open-Meteo, and the existing HTTP API contract.

**Tech Stack:** Latest stable .NET 10 SDK, ASP.NET Core/Blazor 10, MAUI 10, Microsoft.Data.Sqlite 10, System.Text.Json, HttpClient; xUnit v3 (current stable package), Microsoft.Testing.Platform, bUnit, existing Playwright suite. Use TDD for business behavior and adapters. Resolve compatible stable test-tool versions at implementation time.

**Spec:** User request on 2026-10-20: replicate current project advancement using C# and Blazor for web and desktop; Linux may be omitted; use latest stack versions. Parity references: current `README.md`, `MOBILE_API.md`, source and tests, including uncommitted work.

## Global constraints

- Desktop targets macOS (Mac Catalyst) and Windows. Linux desktop is omitted. The web host can still run on supported .NET server platforms.
- Use stable releases, no preview baseline. On 2026-10-20, .NET 10 is stable; .NET 11 is RC2. Official servicing tables list runtime 10.0.13 and MAUI 10.0.110. These are not SDK version numbers.
- At execution, resolve the newest stable compatible SDK/workload/packages, pin SDK in `dotnet/global.json`, workload set and NuGet versions, and record required Xcode/Windows tooling. Recheck if execution occurs after .NET 11 ships.
- Retain local-first behavior. No hosted AI, account system, cloud sync, camera mirror, AR try-on, or UI redesign in this migration.
- Existing working-tree changes are part of the baseline. Do not reset them or use HEAD alone as the parity reference.
- Never test against or automatically migrate the user's live database/images. Python and C# must use separate data directories during development.
- Preserve API routes, snake_case JSON, status codes, validation errors, null-versus-absent update semantics, and legacy recommendation fields.
- Preserve the current HTTP API for phone clients. Desktop standalone mode does not automatically publish a LAN server.

## Review focus

1. Older SQLite databases and Windows-style image paths must import without lost IDs, photos, history, settings, or persona ownership (task 3).
2. Malformed model output, invalid candidate IDs, and weather/model failures must preserve retry/fallback behavior (tasks 4–5).
3. Multi-item images and mixed-success bulk uploads must preserve independent photo ownership and per-photo errors (task 5).
4. MAUI suspension, interrupted requests, and process restarts must not leave a permanently busy UI or replay a save automatically (tasks 5–7).
5. Partial updates and repeated worn actions must keep absent/null distinctions and avoid double-counting (tasks 2–3).

## Current parity inventory

| Area | Existing reference | Required behavior |
|---|---|---|
| Wardrobe | `models.py`, `categories.py`, `repo/items.py`, `frontend/wardrobe.*` | CRUD; category derives broad slot; garment compatibility; pagination/filter/sort; move items between personas; photo attach/replace/delete |
| People | `repo/personas.py`, `main.py`, `frontend/persona.js`, settings | Separate wardrobes/history; name, styling notes, gender; default-persona compatibility; deletion guards |
| Recommendations | `services/candidates.py`, `stylist.py`, `recommend.py` | Mood/occasion/activity; weather override; deterministic filtering and relaxation; layering/one-piece rules; weather-appropriate accessories; validated LLM selection, one retry then fallback |
| Variety and pair mode | `recommend.py`, `repo/history.py`, variety/options tests | Recent suggested outfits affect variety; fresh candidate sampling per request; 1–5 options API, 1/3/5 UI; coordinated personas; one weather fetch; insufficient wardrobes may repeat |
| Worn/history | `repo/history.py`, routes, `worn.spec.ts` | Suggestion history per person; mark only the selected option worn; idempotent worn marking and wear counts |
| Photo import | `services/classify.py`, `images.py`, `quickadd.py`, `api_quickadd.py` | Single/multiple garment classification, max 8 drafts/photo; review/edit/save; quick add all valid detected pieces; opaque tokens and thumbnails |
| Bulk queue | bulk routes, `frontend/wardrobe.js`, bulk/multi-photo tests | Max 20 photos/request; sequential batches and classification within each queue; progress, review, Save all, individual failures do not abort queue |
| Background work | `services/jobs.py`, async routes | queued/running/done/failed; progress; polling; two workers; in-memory jobs, finished-result TTL of one hour; restart loses jobs |
| Settings/weather | `config.py`, `repo/settings.py`, `services/weather.py` | City/model/vision-model/Ollama URL; effective defaults; partial reset semantics; weather failure gives 15°C assumption or manual override |
| Installation/API | `MOBILE_API.md`, `services/network.py`, PWA assets | Existing REST API, health/version, LAN URL/QR installation help, responsive browser layout; cached shell only, live operations require host |
| Sample data | `scripts/seed_wardrobe.py`, distribution tests | Repeatable two-person demo seed and garment distribution; temporary test data |

`MOBILE_API.md` and README are helpful inventories; source and regression tests resolve discrepancies. Do not copy illustrative client snippets without checking their payloads against the models.

## Target structure and service boundaries

```text
dotnet/
  LlmStyle.slnx
  global.json
  Directory.Packages.props
  src/
    LlmStyle.Domain/     # entities, value objects, taxonomy and pure outfit policies
    LlmStyle.Application/ # use cases, DTOs and required persistence/integration ports
    LlmStyle.Infrastructure/ # SQLite, photo files, jobs, Ollama and weather adapters
    LlmStyle.UI/         # Razor class library: pages, forms, queue, cards, CSS/assets
    LlmStyle.Web/        # ASP.NET Core API, Interactive Server host, PWA/install assets
    LlmStyle.Desktop/    # MAUI Blazor Hybrid, Mac Catalyst/Windows only
  tests/
    LlmStyle.Domain.Tests/
    LlmStyle.Application.Tests/
    LlmStyle.Infrastructure.Tests/
    LlmStyle.Web.Tests/
    LlmStyle.UI.Tests/
    Fixtures/           # synthetic databases, API cases and model responses
```

- `Domain` has no project references or framework dependencies. `Application` references Domain; `Infrastructure` references Application; `UI` references Application. Web/Desktop reference UI and Infrastructure as composition roots. No reverse references or domain dependencies on JSON/HTTP/SQLite/MAUI.
- UI invokes application use cases through a small `IStyleApp` facade defined in Application, with cancellation tokens. Define methods from existing page actions, not a generic CRUD abstraction. Infrastructure implements only the ports those use cases need.
- Use direct SQL with Microsoft.Data.Sqlite to preserve the existing schema; no EF Core conversion is needed. Wire infrastructure explicitly in each composition root, without a service locator.
- Final hosts register the same local implementation. Web API endpoints invoke those same services. Desktop stores data under its OS application-data directory and needs neither Python nor a separately running web server.
- During UI migration only, an HTTP implementation of `IStyleApp` connects the web UI to Python. Remove this temporary adapter once C# parity passes; a remote desktop connection mode is outside scope.
- Host-level render modes: web Interactive Server, desktop BlazorWebView. Do not embed `@rendermode` in shared components. Keep JS interop limited to browser file/drop/PWA needs.
- Photos need a host adapter: web returns existing photo URLs; desktop opens validated local image bytes through the supported BlazorWebView asset/resource mechanism. Do not expose arbitrary filesystem paths or assume `/api` exists in desktop mode.
- Long-lived UI/circuit services never hold a SQLite connection. Each operation/job opens its own connection; transactions cover related database writes. Configure WAL, foreign keys and busy timeout consistently.

## DDD model and TDD execution rules

Use one deployable modular monolith, not microservices. Organize features inside each layer using the existing vocabulary: People, Wardrobes, Outfit Recommendations and Worn History. These are initial model areas, not a mandate for separate services, databases, or bounded-context projects.

- Model Persona and WardrobeItem as entities with identity; introduce value objects only for actual invariants (initial example: PersonaName, 1–50 Unicode characters, preserving Python whitespace behavior). Put garment/category and outfit-compatibility rules in pure domain policies. DTOs remain at application/API boundaries.
- Recommendations coordinate wardrobe reads, weather, deterministic policies, stylist output and history. Those orchestration steps belong in Application; network parsing/retries belong in adapters where transport-specific, while invalid outfit/retry/fallback policy stays explicit in the use case/domain boundary.
- Define aggregate/transaction boundaries from current invariants: an item owns its photo reference; persona deletion guards protect its wardrobe/history; marking worn and incrementing item wear counts must be atomic and idempotent. Do not force the entire wardrobe into an in-memory aggregate to update one item.
- Add repository/integration ports only when a use case requires them. No generic repositories, mediator/CQRS framework, event bus, domain-event infrastructure or separate read database for this migration.
- For every nontrivial behavior: choose a public domain/use-case/API seam → write one failing behavioral test → run and observe the intended failure → implement the minimum → rerun → simplify while green. Use vertical slices rather than writing the entire test suite before implementation.
- Domain tests exercise invariants and outfit rules without I/O. Application tests use deterministic in-memory fakes for required ports. Infrastructure tests use temporary real SQLite/files and fake HTTP handlers. API contract tests pin HTTP/JSON compatibility. UI tests pin queue and selection behavior; Playwright covers complete user workflows.
- Keep each slice independently reviewable. Add architecture checks that reject outward layer references; test no internal call sequences. Keep real Ollama and native-webview checks opt-in/separate from fast offline tests.
- Every task below inherits this red/green verification rule. API-validation adapters translate domain failures into the existing contract; a constructor exception is not an HTTP error policy.

## Initialization status — 2026-10-20

- Six-project scaffold created from MAUI 10.0.110's official shared web/hybrid template. Web uses Interactive Server; desktop targets Mac Catalyst ARM64 and Windows only.
- SDK 10.0.402 installed locally at `~/.dotnet`; stable package versions are centralized. xUnit's current package uses Microsoft.Testing.Platform, selected in global.json.
- First public domain seam: PersonaName. Tests were added and observed failing before implementation; they cover missing/oversized names, Unicode length, preservation and value equality.
- Verification: 8 domain tests pass on ARM64; web build passes with zero warnings/errors; running web host serves the shared page and `/api/health`; project-reference checks confirm the six layer boundaries. Native build attempted and stops at NETSDK1147 (missing `maui-maccatalyst`).
- Task 1 remains incomplete until native desktop builds and interaction smoke checks pass on both OSes. This machine currently has only Apple's Command Line Tools, not full Xcode or the MAUI workload. No claim of native execution yet.
- Initialization does not authorize or imply completion of tasks 2–8. Existing Python data and behavior remain untouched.
- Build follow-up: installed and updated `maui-maccatalyst` (workload set 10.0.402.1, MAUI 10.0.110). Web rebuild succeeds. Desktop restore and shared libraries build, then native build stops because no valid full Xcode developer path is available. This supersedes the earlier missing-workload status; task 1's native gate is still pending.
- UI-only follow-up requested by user: shared responsive Ask, Wardrobe, Settings and Get the App screens added with static examples and local SVG garment illustrations. Navigation/native inputs work; business actions are disabled and no API/persistence logic is connected. This is a presentation prototype, not completion of task 6's functional parity gates.

## Logic implementation status — 2026-10-20

The current shared UI is connected to local C# services. Domain contains garment/catalog/value validation and role-aware candidate/fallback policies. Application contains use cases, model-output validation/retry, photo workflows and contracts. Infrastructure provides SQLite/files/Ollama/Open-Meteo/jobs; both hosts register the same services.

Implemented: wardrobe CRUD/search/filter/sort/paging; persona CRUD/guards/notes/gender; settings merge/reset; live weather/cache/manual override; stylist prompts/validated LLM picks/retry/fallback; coordinated personas and 1–5 options; persisted recommendation histories and transactional worn marking; bounded photos with independent owned files; multi-item classification/review/Save all/quick add; sequential mixed-success queues; async API jobs/progress; copy-only CLI import; phone URL/QR/PWA reconnect page.

Regression evidence includes temporary real SQLite/files, fake HTTP clients, Development and Production API hosts, and isolated Playwright workflows with a local fake vision HTTP server. Browser checks cover real save/edit/reload/search/delete, settings/people/gaps, mixed-photo review/quick add, long mobile input and changing the editor during a delayed file transfer. The read-only independent review found five concrete issues; each was reproduced and fixed, with concurrent settings patches additionally protected.

Implementation choices: disable web prerendering so editable forms cannot lose early input during interactive hydration; use short per-operation SQLite connections with immediate transactions around related writes; coordinate multi-step item/photo mutations in the singleton application service; claim photos under a unique owned filename before switching their DB reference. No mediator framework, generic repository, extra database or cloud service was added.

Still pending: full native execution/packaging on Mac and Windows (full Xcode is absent here), live-model/manual photo-quality checks, exhaustive certification of every Python/mobile edge case and historical database variant, and a C# replacement for the optional 500-item development seed script. The existing Python app/seed remain intact. These acceptance gates remain open; this status does not mark the whole migration/cutover plan complete.

Run/import/test instructions and data-directory isolation are documented in `dotnet/README.md`. The C# web app starts with a separate local wardrobe; it does not automatically import the user's Python data.

## Task 1: Prove the shared web/desktop stack

**Create:** solution, pinned tooling, six projects above; `UI/Pages/Ask.razor`; platform smoke checklist in `dotnet/README.md`.

- [ ] Start from Microsoft's `maui-blazor-web` template with Server interactivity, align project names with the structure, remove Android/iOS targets, and add Domain/Application/Infrastructure projects with inward-only references. Resolve current compatible stable versions before pinning.
- [ ] Render one shared page in the browser, Windows WebView2 and Mac Catalyst. Exercise navigation, a file selection/drop, image display, and a cancellable fake long operation.
- [ ] Build desktop on matching OS runners; record supported OS versions, Apple Silicon/Intel architecture scope, and required Xcode/WebView2 versions from the selected workload. Do not promise an untested architecture.
- [ ] Gate: packaged development apps launch on Mac and Windows; shared page works in browser; no Python dependency in the desktop skeleton. Stop architecture work if this fails and resolve the failing platform first.

## Task 2: Freeze API and behavioral fixtures

**Create:** `tests/Fixtures/api/`, `Application/Contracts/`, `Application/IStyleApp.cs`, `Web.Tests/ContractTests.cs`.
**Read:** all registered routes in `backend/app/main.py` and `api_quickadd.py`, models, existing pytest and browser tests.

- [ ] Run the existing offline pytest suite and Playwright suite in isolated directories. Record baseline failures separately; no assumed green baseline.
- [ ] Capture synthetic request/response fixtures for every route, pagination envelope, async result variant, invalid input, and legacy recommendation fields.
- [ ] Add C# contract tests for category/type mismatch, numeric bounds, unknown fields, absent/null settings and persona updates, missing resources, photo tokens, and HTTP error shape. Use presence-aware DTO handling where null alone cannot express the contract.
- [ ] Define the smallest typed UI facade for items/personas/settings/recommendations/history/classification/jobs/photos. Preserve the existing strings and JSON names instead of silently changing enum serialization.
- [ ] Gate: fixture cases are reviewed against current source and can run against either server with a configurable base URL.

## Task 3: Port persistence and CRUD without changing the schema

**Create:** `Infrastructure/Storage/Database.cs`, `Items.cs`, `Personas.cs`, `History.cs`, `Settings.cs`, `Photos.cs`; `Web/Endpoints/` CRUD/settings/history/photo endpoints; `Infrastructure.Tests/StorageTests.cs`.

- [ ] Build synthetic old/current databases using the Python initialization code. Port additive migrations, default persona/settings seeds, category backfill, gender, basename normalization and all current columns.
- [ ] Port parameterized queries, field validation and persona-delete guards. Preserve default-persona lookup, filtering/sorting allowlists and transaction boundaries. Make worn counting idempotent under repeated/concurrent calls.
- [ ] Preserve extension/token validation, 10 MiB image limit, per-item ownership and stale-draft sweep. Test that deleting/replacing one item's photo leaves other items intact.
- [ ] Add explicit import of a stopped application's copied database plus image directory into the C# data directory. Use a SQLite-consistent backup, validate on the copy, and leave source files untouched. Do not copy only the main DB file while WAL writes are active.
- [ ] Gate: migration/import tests preserve IDs, counts, JSON history, ownership and image checksums; repeat migration is harmless; failed import leaves source and previous destination usable; CRUD contract cases pass.

## Task 4: Port the recommendation engine

**Create:** `Domain/Outfits/Candidates.cs`, `OutfitPolicy.cs`, `Application/Recommendations/RecommendOutfits.cs`, `Infrastructure/Ollama/Stylist.cs`; `Infrastructure/Integrations/OllamaClient.cs`, `WeatherClient.cs`; matching Domain/Application/Infrastructure tests.
**Read:** taxonomy, candidates, stylist, recommendation, weather, provider source and all corresponding pytest tests.

- [ ] Port taxonomy/roles, warmth/formality bands, candidate caps, relaxation order, layers/one-pieces, accessories and fallback ordering from the actual code.
- [ ] Port prompts, structured-response extraction, candidate-ID validation, retry/fallback, persona notes/gender, shared weather fetch, recent-history avoidance and option coordination. Use HttpClient directly against Ollama; no agent framework is required.
- [ ] Match existing configured defaults, model timeouts and weather caching/error handling. Inject fake HTTP handlers, time and seeded sampling for tests; Python and .NET PRNGs differ, so compare fixed candidate fixtures and invariants unless exact historical sampling is required.
- [ ] Gate: test empty/missing slots, wardrobe exhaustion, hot/cold accessories, layering, invalid model IDs/JSON, retry exhaustion, unavailable weather/Ollama, manual temperature, pair mode, option variety and correct persona histories. Real-model checks remain separate and opt-in.

## Task 5: Port photo workflows and background jobs

**Create:** `Infrastructure/Photos/Classifier.cs`, `Application/Wardrobes/QuickAdd.cs`, `Infrastructure/Jobs/JobStore.cs`; remaining classify/recommend/job endpoints; Application/Infrastructure/Web tests.

- [ ] Match multi-object extraction, draft validation, max 8 items, retry behavior, single-photo and quick-add response shapes. Preserve independent image ownership for each detected garment.
- [ ] Implement in-process jobs with queued/running/done/failed results and progress; retain two workers and one-hour finished-job retention. Each bulk job classifies its photos serially, matching the current queue behavior rather than launching all images in parallel.
- [ ] Preserve max 20 photos/request, upload validation and per-photo failure reporting. Client chunks larger selections sequentially; failed files remain visible and do not discard successful drafts.
- [ ] Add bounded UI polling with cancellation/disposal. After restart or expired job returns missing, show an interrupted/expired state; never automatically replay a mutating upload/save. Persistent resumable jobs are not part of parity.
- [ ] Gate: mixed valid/invalid photos, partial model drafts, >20-photo selection, duplicate save protection in UI, progress, expired jobs and restart/interruption tests pass. Classifier failures produce no falsely successful item/photo records.

## Task 6: Rebuild the existing UI once

**Create:** `UI/Pages/{Ask,Wardrobe,Settings,Install}.razor`, only necessary shared form/card/queue components and assets; UI tests.
**Temporary:** `Web/PythonStyleApp.cs` using HttpClient during early UI work.
**Later modify:** `e2e/playwright.config.ts` to select Python or C# host; keep `serve_test.py` and original frontend intact through parity.

- [ ] Reuse the existing CSS, icons, page layout and wording; port interactions into Razor rather than redesigning them. Keep accessible labels, keyboard actions, confirmation dialogs and responsive behavior.
- [ ] Implement wardrobe CRUD/search/filter/sort/pagination, persona switching, full photo queue/review/Save all/quick add, Ask inputs and 1/3/5 options, coordinated outfits, worn marking, settings and people management.
- [ ] Exercise against Python through the temporary facade, then register C# services when tasks 3–5 pass. Use the same facade interface for desktop direct services; UI cannot access SQLite or platform paths itself.
- [ ] Retain the web API/install endpoints, QR generation through one maintained compatible QR dependency if needed, manifest/icons and cache behavior. Interactive Server requires a live host/circuit: provide an explicit offline/reconnecting message and a cached static shell/help page. No offline live-data claim. Test PWA installation over HTTPS/localhost; plain LAN HTTP does not guarantee service-worker installation.
- [ ] Gate: bUnit covers queue state/error recovery and option-specific worn action; existing Playwright workflows pass against C# with only necessary route/DOM harness adaptations. Keep independent API parity tests so UI adaptations cannot hide contract drift.

## Task 7: Finish desktop integration and packaging

**Modify:** Desktop startup, `MauiProgram.cs`, platform metadata, photo adapter; add native-OS CI jobs and release instructions.

- [ ] Register application use cases, infrastructure and shared UI locally, using MAUI app-data paths. Import through task 3's safe-copy workflow. Desktop needs Ollama running but not Python or the web host; explain missing-model/server errors and retain fallback.
- [ ] Test file/drop handling, thumbnails, settings persistence, window resizing, keyboard access, suspend/resume and cancellation in both native webviews. Stop polling on disposed pages; keep save outcome explicit after interruptions.
- [ ] Gate with internet disabled: launch, browse/edit wardrobe, display photos and generate fallback recommendations. Local Ollama can still run; weather reports its assumption. Phone/web access uses the separate C# Web host, not the desktop process.
- [ ] Publish Windows MSIX and Mac Catalyst app/pkg; build and smoke-test on each native OS. Document signing identities, Windows signing and Mac signing/notarization; release distribution requires the appropriate credentials. No automatic updater in the first release.

## Task 8: Cut over after parity

**Modify:** README, MOBILE_API.md, e2e harness and deployment docs. **Remove:** temporary Python facade after parity.

- [ ] Port the sample seed to a dev-only C# command and run distribution assertions against isolated data. Reuse synthetic inputs, not a user's wardrobe.
- [ ] Run C# unit/integration/component tests; the adapted browser suite; native desktop smoke checks; one optional real Ollama stylist/vision round trip on each supported OS. Verify every parity inventory row has evidence.
- [ ] Restore an imported copy and compare data/photos/history. Verify original Python still opens its original unchanged data. Never run both implementations writing the same production directory during migration.
- [ ] Document separate web and standalone-desktop launch paths, local data locations, import/backup/rollback, Ollama model setup, supported OS/architectures and pinned tooling. Loopback remains default; deliberate LAN hosting retains the existing trusted-network model. Public internet hosting/authentication is a separate scope.
- [ ] Make C# the documented default only after these gates pass. Retain Python as the reference until cutover review; deleting the old app is a separate follow-up.

## Order and effort

Execute 1 → 2 → 3 → 4 → 5 → 6 → 7 → 8. The temporary Python-backed UI in task 6 can be brought forward after task 2 to obtain an early working screen.

Planning estimate for one developer familiar with both stacks: foundation/contracts 3–5 days; persistence/import 3–5; recommendations 4–6; photos/jobs 3–5; shared UI 5–8; packaging/cutover 4–7. Total approximately 5–8 focused weeks, excluding signing-account delays and baseline bug fixes. Re-estimate after the platform spike; this is not a delivery commitment.

## Sources checked on 2026-10-20

- [.NET support policy and current releases](https://dotnet.microsoft.com/en-us/platform/support/policy/dotnet-core)
- [MAUI support policy and current patches](https://dotnet.microsoft.com/en-us/platform/support/policy/maui)
- [Shared MAUI Blazor Hybrid and Blazor Web App template](https://learn.microsoft.com/en-us/aspnet/core/blazor/hybrid/tutorials/maui-blazor-web-app?view=aspnetcore-10.0)
- [Razor class library sharing](https://learn.microsoft.com/en-us/aspnet/core/blazor/hybrid/class-libraries?view=aspnetcore-10.0)
- [MAUI supported platforms](https://learn.microsoft.com/en-us/dotnet/maui/supported-platforms?view=net-maui-10.0)
- [Mac Catalyst publishing](https://learn.microsoft.com/en-us/dotnet/maui/mac-catalyst/deployment/?view=net-maui-10.0)

MAUI's support lifecycle is shorter than .NET LTS: MAUI 10 currently ends support May 11, 2027; .NET 10 ends November 14, 2028. Plan desktop workload upgrades separately.
