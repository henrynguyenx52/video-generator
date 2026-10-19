# Motion Lab

A Python video-generation studio inspired by the observable workflow of
[Kling AI's creations page](https://kling.ai/app/creations/grid?taskId=new).
It supports text-to-video, image-to-video, configurable aspect ratios and
durations, asynchronous jobs, progress polling, a creations grid, downloads,
and persistent job history.

The default provider renders a short MP4 from the prompt locally, so the full
product flow works without an API key. It reads the subject, setting, time of
day, color, weather, and motion from the words in the prompt. An optional
Replicate adapter can call a real video model.

## Run it

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload
```

Open <http://127.0.0.1:8000>.

### Use a real AI model

Set a Replicate model whose inputs include `prompt`, `duration`,
`aspect_ratio`, and optionally `image`, `negative_prompt`, and `seed`:

```bash
export VIDEO_PROVIDER=replicate
export REPLICATE_API_TOKEN=your_token
export REPLICATE_MODEL=owner/model:version
uvicorn app.main:app --reload
```

Model input contracts differ. If the chosen model uses different field names,
adapt `build_replicate_video()` in `app/main.py`.

## Tests

```bash
pytest -q
```

## Reverse-engineering evidence

Investigation date: 2026-10-19. Scope: public, logged-out web application and
its client assets. No credentials, private APIs, or generated content were
accessed.

### Direct observations

1. Opening the target URL loads a page titled “Kling AI: Next-Gen AI Video &
   AI Image Generator,” a “Kling AI Creations Grid” heading, and an
   authentication dialog. The grid therefore exists as a distinct product
   surface, while generation requires authentication.
2. Loaded client assets include named modules for `VideoPlayer`,
   `VideoKeyframeExtractor`, `VideoClip`, `ClipSlider`, `upload`,
   `use-creations-preferences`, `submit`, and `video-effective-duration`.
   These names establish media upload/playback, video editing utilities,
   creation preferences, submission, and duration handling in the shipped UI.
3. The shipped submission module contains the states `QUEUING`, `generating`,
   `failed`, and success; starts polling after submission; carries a numeric
   task ID; displays queue and generation ETAs; and distinguishes free,
   membership, and priority-ticket queues.
4. The same module passes `taskInfo` and `priceInfo` during submission and
   handles point/ticket insufficiency, membership requirements, concurrency
   limits, and a full free queue. This establishes a metered asynchronous job
   pipeline.
5. Shipped navigation strings link separate prompt guides for text-to-video,
   image-to-video, video extension, and motion control.
6. The loaded app performs profile/features, points, memberships, tags, and
   elements requests before authentication completes. The exact generation
   request was not observable without signing in.

### Inferences used in this implementation

- Submission creates a server-side task rather than holding one HTTP request
  open.
- The client polls task state and renders queue/generation progress until the
  video is ready.
- Finished media is shown in a creations grid with playback and download.
- Image-to-video first uploads or attaches source media.

These are high-confidence behavioral inferences from the client modules and
state transitions, not claims about Kling's private model architecture.

### Unknowns and deliberate differences

- The authenticated request schema, internal model, scheduler, storage layout,
  moderation pipeline, and progress algorithm were not observed.
- Motion Lab uses its own API and visual design. It does not call private Kling
  endpoints or copy Kling code.
- Local prompt mode illustrates the words in the prompt. It is deterministic
  and does not run a diffusion model. Configure the Replicate adapter for real
  model inference.
- Jobs run in-process. Production deployment should move work to Celery,
  Dramatiq, RQ, or a managed queue and store records in PostgreSQL.

### REA environment limitation

REA was requested and its readiness check was run. The installed setup could
not provide browser evidence in this session because Cursor MCP registration
was missing/stale and Node 25.6.0 is unsupported by the installed REA package
(supported lines: Node 22.19+, 24.11+, or 26+). Fixing registration requires
running REA setup and restarting Cursor. Consequently, the evidence above is
from passive browser inspection and shipped web assets, and is intentionally
not labeled as REA Evidence IDs.
