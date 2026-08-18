# Deployment and Laravel integration

The pipeline generates course records and posts them to your Laravel API. It never
connects to MySQL directly — your application stays the only writer to its own database,
so model events, observers, slug generation and cache invalidation all still run.

```
coursegen container                     your Laravel app
───────────────────                     ────────────────
generate  →  artifacts/*.json
                    │
                validate
                    │
                 publish  ──── HTTPS ──→  POST /api/courses  →  MySQL  →  Blade
```

Generation and publishing are separate steps. Courses are written to disk first, so you
can generate today and publish whenever the endpoint is ready, without regenerating.

## Running with Docker

Only Docker Desktop is required. No Python installation.

```bash
cp .env.example .env          # then add your Perplexity key
docker compose build
```

Compose writes container status lines to the same stream as the output, so pipe through
`2>/dev/null` when reading the JSON in a script.

```bash
docker compose run --rm coursegen courses docs/indian_ug_courses_171.xlsx
docker compose run --rm coursegen pilot docs/indian_ug_courses_171.xlsx --count 10
docker compose run --rm coursegen publish --dry-run
docker compose run --rm coursegen publish
```

Generated files appear in `./artifacts` on the host, not inside the container.

The image runs as a non-root user and contains no credentials. `.env` is excluded from
the build context and mounted at runtime, so keys never end up in an image layer.

### Reaching Laravel from the container

| Where Laravel runs | `LARAVEL_ENDPOINT` |
|---|---|
| Same machine, outside Docker | `http://host.docker.internal:8000/api/courses` |
| Same Docker network | `http://laravel:80/api/courses` |
| Remote server | `https://portal.example.com/api/courses` |

`host.docker.internal` is already mapped in `docker-compose.yml`, including on Linux.

## Large runs

A full catalogue takes hours: six calls per course, throttled to protect the API rate
limit. A thousand courses is roughly six thousand requests.

Runs resume. A course whose `run.json` already says `validated` is skipped, so if a run
is interrupted, start it again and it continues from where it stopped rather than paying
for the same courses twice.

```bash
docker compose run --rm coursegen pilot docs/courses.xlsx --count 1000
# interrupted at course 700 -- run the same command again
docker compose run --rm coursegen pilot docs/courses.xlsx --count 1000
```

Flagged courses are not skipped: they are retried on the next run, since a rule or prompt
fix may now let them through. Use `--force` only when you want to regenerate courses that
already passed.

Two settings matter at this scale:

```
REQUEST_INTERVAL_SECONDS=2   # raise if you see HTTP 429
GENERATION_MAX_ATTEMPTS=3    # attempts per section before flagging
```

## Course durations

`config/durations.json` fixes how long each course runs. Two numbers matter per entry:

- `min_years` / `max_years` — the whole programme as a family experiences it, internship
  included. This is what the page shows as the duration.
- `academic_years` — how many taught years the curriculum tabs show. Lower wherever the
  programme ends in an internship rather than another year of subjects.

MBBS is the clearest case: `5.5` years total, `4` taught years. Without this split the
generator was asked for a fifth year of subjects that does not exist, and filled it by
repeating year one.

Check what a course list resolves to before generating:

```bash
docker compose run --rm coursegen durations docs/courses.xlsx
docker compose run --rm coursegen durations --course MBBS
```

Courses the file does not cover are listed under `unpinned`; those fall back to a
model-generated duration, exactly as before. Add an entry to fix one:

```json
"exact": {
  "bachelor of medical laboratory technology": {
    "min_years": 3, "max_years": 4, "academic_years": 4
  }
}
```

Exact names match first, then `patterns` in order, so put specific rules above broad ones.

## Configuring the endpoint

Five settings in `.env` describe your API. Defaults suit a token-authenticated
`POST` that accepts the course object directly.

```
LARAVEL_ENDPOINT=https://portal.example.com/api/courses
LARAVEL_API_TOKEN=your-token
LARAVEL_METHOD=POST              # PUT appends /{course_id} to the URL
LARAVEL_PAYLOAD_KEY=             # set to e.g. "course" to wrap the body
LARAVEL_AUTH_HEADER=Authorization
LARAVEL_AUTH_SCHEME=Bearer       # blank sends the raw token
```

**Bare body** (default):

```json
{ "course_id": "crs_mbbs", "course_name": "MBBS", "fees": { ... } }
```

**Wrapped body** with `LARAVEL_PAYLOAD_KEY=course`:

```json
{ "course": { "course_id": "crs_mbbs", ... } }
```

For an API key header instead of a bearer token:

```
LARAVEL_AUTH_HEADER=X-Api-Key
LARAVEL_AUTH_SCHEME=
```

## What the publisher sends

Only courses whose `run.json` says `validated`. Anything flagged during validation is
held back and never reaches your API.

Each course is sent once. A checksum of the document is recorded in
`artifacts/_published.json`, so re-running `publish` skips anything unchanged and re-sends
only what you have regenerated. `--force` overrides this.

## How responses are treated

| Response | Meaning | Action |
|---|---|---|
| `2xx` | Accepted | Recorded; not sent again |
| `422`, `400`, `409`, `404` | Your API rejected the payload | Reported with the response body, not retried |
| `429`, `5xx` | Temporary | Retried with exponential backoff |
| `401`, `403` | Credential rejected | The whole run stops immediately |

A `422` means the two schemas disagree, which retrying cannot fix. The response body is
kept in the summary so the mismatch is visible.

If your API returns `{"id": 123}` or `{"data": {"id": 123}}`, that id is recorded
alongside the course.

## Suggested Laravel side

An idempotent endpoint keyed on `course_id` makes re-runs safe:

```php
Route::middleware('auth:sanctum')->post('/courses', function (Request $request) {
    $data = $request->validate([
        'course_id'   => ['required', 'string', 'max:64'],
        'slug'        => ['required', 'string', 'max:80'],
        'course_name' => ['required', 'string', 'max:90'],
        'category'    => ['required', 'string'],
    ]);

    $course = Course::updateOrCreate(
        ['course_id' => $data['course_id']],
        ['payload' => $request->all(), 'status' => 'draft'] + $data,
    );

    return response()->json(['id' => $course->id], $course->wasRecentlyCreated ? 201 : 200);
});
```

Two things worth doing on your side:

**Store courses as `draft` on arrival.** The records are machine-generated and reviewed
afterwards; publishing straight to live means unreviewed pages become public.

**Keep `updateOrCreate` keyed on `course_id`.** Without it, a re-run duplicates the
catalogue rather than updating it.

## Checking the integration before a full run

```bash
docker compose run --rm coursegen publish --dry-run
```

Lists what would be sent and to where, without making a request. Then publish one course:

```bash
docker compose run --rm coursegen publish --course-id crs_mbbs
```

Once that lands correctly, run the full set.
