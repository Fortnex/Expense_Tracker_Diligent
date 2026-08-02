# AI Notes

I used Claude (Anthropic) throughout this project for the entire structure of the initial API, and then across several rounds of testing, bug fixing, and scope decisions. What I did throughout the project is described below.

## What was AI-generated vs. written by me

- The initial scaffold (the FastAPI app in `src/main.py`, Pydantic models
  in `src/models.py`, the JSON-file storage layer in `src/storage.py`, and
  the pytest suite in `tests/test_api.py`) was all generated with Claude.
- The bonus feature (search by title, `GET /expenses/search?q=`) was the
  one chosen for the assignment, given the time constraints over the past
  few days.
- `scripts/stress_test.py` was built with Claude to check for bottlenecks
  and surfaced a couple of issues with ID retrieval and the deletion
  operation, described further below.
- No code here was hand-written from scratch. Claude and Gemini were used
  throughout the project over a few hours to get things working. Some
  prior experience with APIs came from a past internship, and using AI
  tools for this kind of work was actively encouraged there.
- This file was formatted and indented with the help of ChatGPT.

## What I validated, tested, or changed, and why

The project was validated throughout, not just at the end.

- This is the 4th version of the project; only the final working version
  was uploaded.
- A number of concurrency issues came up around the deletion operation.
  Claude generated the stress test script specifically to validate that.
- Ran `pytest` after every round of changes (ended at 18 passing tests).
- Started the server locally and exercised every endpoint manually through
  Swagger UI (`/docs`) and `curl` after each change, not just through the
  automated tests.
- Ran the stress test script against the running server (200 concurrent
  valid POSTs, 60 concurrent invalid POSTs, 150 concurrent reads, a 10-way
  concurrent DELETE race) and checked the real server logs, not just the
  script's pass/fail summary.

**Bugs found through testing that the AI's first pass got wrong:**

A summary of the bugs faced throughout the project:

1. **DELETE crashed the server.** The original `DELETE /expenses/{id}`
   handler returned `JSONResponse(content=None, status_code=204)`. A `204
   No Content` response is not allowed to have a body, but this sent a
   4-byte `"null"` body anyway, which crashed the server with
   `LocalProtocolError: Too much data for declared Content-Length`. This
   only showed up in Swagger UI, not in the test suite: FastAPI's
   `TestClient` didn't surface it the same way the real ASGI server did.
   Fixed by returning a bare `Response(status_code=204)` with no body.

2. **Garbage category values were accepted.** Early on, `category` was a
   free-text string, so Swagger UI's default placeholder value (`"string"`)
   got saved as real data after clicking "Execute" without editing the
   example payload. The fix was to change `category` from a free string to
   a fixed `Enum` (Groceries, Leisure, Electronics, Utilities, Clothing,
   Health, Others-style list, in this project: Food, Transport,
   Entertainment, Utilities, Health, Shopping, Bills, Education, Travel,
   Other), so invalid values are now rejected with `422` and Swagger
   renders it as a dropdown instead of a free text box.

3. **The enum fix silently broke category filtering.** Adding the `Enum`
   introduced a new bug: Python's `str(enum_member)` returns
   `"Category.FOOD"` instead of `"Food"` for `str`-based Enums (it uses
   `Enum.__str__`, not `str.__str__`), which meant `GET /expenses?category=Food`
   started returning zero results. This wasn't predicted in advance. It
   showed up because the existing filter tests failed on the next `pytest`
   run after the enum change, which is the reason for re-running the full
   suite after every change rather than assuming an unrelated fix is safe.
   Fixed by explicitly reading `.value` off the enum member instead of
   relying on `str()`.

4. **Percentile math bug in the stress test script itself.** The first
   version of `scripts/stress_test.py` had a broken linear-interpolation
   formula for computing p95/p99 latency, which produced impossible
   negative latency values in the output. This was caught by reading the
   printed numbers, not just the pass/fail checks at the bottom. The
   interpolation formula was fixed and re-run to confirm sane (positive,
   monotonic) percentiles.

**Changes made by request, not because they were broken:**

- Added a `count` field alongside `total` in the category breakdown, and
  an `overall_count` in the totals summary, since the total amount alone
  didn't show how many expenses made up that total.
- Suppressed the auto-generated `422 Validation Error` block from every
  endpoint's Swagger docs (FastAPI adds it by default to any route with
  parameters). It was noise for a reviewer skimming the docs, and every
  endpoint already documents its real success/error responses separately.
- Added a `GET /categories` endpoint so the fixed list of valid categories
  is discoverable through the API itself, rather than left to trial and
  error against the enum.

## AI suggestions not used, and why

- After finishing the assignment, a much larger "Expense Tracker API"
  project spec was found online (JWT auth, multi-user accounts,
  PostgreSQL, Alembic migrations, Docker), which raised the question of
  whether to pull features from it. That was rejected: the actual
  assignment explicitly allows in-memory or local JSON storage, requires
  no database, and is scoped at roughly 4 hours. Adding auth and a real
  database would be scope creep against a brief that was deliberately kept
  small, and an over-built submission risks reading as a sign the brief
  wasn't read carefully, the same way an under-built one would.
- Additional bonus features beyond search (e.g. Docker, a monthly summary
  endpoint) were also skipped once one bonus was already implemented,
  since the instructions specifically said to pick **at most one**.

## Known limitations

- JSON file storage is not safe for concurrent multi-process writes. Fine
  for this scope (correctness under concurrent *requests* within a single
  process was confirmed via the stress test's delete-race check), but
  would need a real database or file locking to scale beyond a single
  server process.
- No authentication/authorization. Intentionally out of scope, since the
  assignment didn't ask for multi-user support.
- Categories are a fixed enum rather than user-defined, a deliberate
  trade-off to stop garbage input, at the cost of flexibility.
