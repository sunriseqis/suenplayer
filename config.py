"""
suenplayer configuration constants.
All values are user-specified and must not be adjusted.
"""

# ─── Application Version ───────────────────────────────────────────────────

# Single source of truth for the application version. It also defines the
# JSON delivery standard number: when the app bumps to 2.2/3.2 the JSON
# generator/version fields are expected to follow the same number.
# Importing must stay compatible with older JSON formats (2.0 and earlier
# field structures are accepted as-is).
APP_VERSION = "2.1"

# ─── Speed Test Parameters (user-specified, fixed) ─────────────────────────

# HTTP connection and first-byte response timeout (seconds)
# URLs that fail to connect within this time are marked as failed.
QUICK_TIMEOUT = 5.0

# Global concurrency limit for all speed test operations
# (thread pool max workers for probe, health patrol, etc.)
QUICK_CONCURRENCY = 64

# ─── quick.py module parameters ────────────────────────────────────────────

# Max duration to sample a single stream (seconds)
QUICK_MAX_SECONDS = 2.0

# Max bytes to sample from a single stream
QUICK_MAX_BYTES = 4 * 1024 * 1024  # 4 MB

# Smart early-exit: if bitrate is stable (variation <= 12%) for this many
# seconds, we can compute bandwidth and exit early.
QUICK_MIN_STABLE_SECONDS = 1.0
QUICK_STABLE_VARIATION_PCT = 12.0  # 12%

# ─── Scoring Weights (user-specified, fixed) ───────────────────────────────

# Rate (bandwidth) weight: 50%
WEIGHT_RATE = 0.50

# Latency (TTFB) weight: 30%
WEIGHT_LATENCY = 0.30

# Stability (consecutive success count) weight: 20%
WEIGHT_STABILITY = 0.20

# ─── Scoring Normalization Boundaries ──────────────────────────────────────

# Rate: 20 Mbps = full score, linear 0~1
RATE_FULL_SCORE_MBPS = 20.0

# Latency: <= 50ms = full score, >= 1000ms = zero, linear decay
LATENCY_FULL_SCORE_MS = 50.0
LATENCY_ZERO_SCORE_MS = 1000.0

# Stability: >= 10 consecutive successes = full score, linear 0~1
STABILITY_FULL_SCORE = 10

# Resolution is NOT part of the scoring (metadata only)

# ─── Probe Cache & Health Patrol ───────────────────────────────────────────

# Probe cache reuse duration (seconds) — user did not specify;
# default is reasonable and configurable.
PROBE_CACHE_TTL_SECONDS = 1800  # 30 minutes

# Health patrol interval (seconds) — user did not specify;
# default is reasonable and configurable.
HEALTH_PATROL_INTERVAL_SECONDS = 300  # 5 minutes

# Max probe history per URL to keep (for stability calculation)
MAX_PROBE_HISTORY_PER_URL = 50

# ─── Fallback Chain ────────────────────────────────────────────────────────

# When all lines fail during play probe, try in this order:
# 1. Most recent successful probe cache (even if expired)
# 2. Backup lines (urls with is_backup=1)
# 3. Primary line (the best previously-ranked line)
# 4. Explicit error response

# ─── Live Streaming (live streaming defaults) ──────────────────────────────

# Live stream probe timeout (seconds) — TTFB + first chunk read
LIVE_PROBE_TIMEOUT = 10.0

# Live channel patrol interval (seconds) — each channel probed at most
# once per 4 hours (design 2.5.2)
LIVE_PROBE_INTERVAL_SECONDS = 4 * 3600

# Live probe ok threshold: delay below this (ms) counts as ok
LIVE_PROBE_OK_DELAY_MS = 500

# First chunk bytes to read when probing a live stream
LIVE_PROBE_FIRST_BYTES = 1024

# Default live source region when JSON has no region field
LIVE_DEFAULT_REGION = "default"

# Default live source generator when JSON has no generator field
LIVE_DEFAULT_GENERATOR = "unknown"

# Default group name when a channel has no group field (design 6.3)
LIVE_DEFAULT_GROUP = "未分组"

# ─── Auto Update (auto update defaults) ────────────────────────────────────

# Scheduler scan interval (seconds): how often auto_update_configs is
# checked for due configs (design 3.2.2 simplified scheme)
AUTO_UPDATE_SCAN_INTERVAL = 60

# Minimum allowed update interval per config (seconds) — design default 300
AUTO_UPDATE_MIN_INTERVAL = 300

# Default update interval per config (seconds) — design default 3600
AUTO_UPDATE_DEFAULT_INTERVAL = 3600

# Exponential backoff cap: multiplier is min(2 ** fail_count, this)
AUTO_UPDATE_MAX_BACKOFF_MULTIPLIER = 4

# Remote download timeout (seconds)
AUTO_UPDATE_FETCH_TIMEOUT = 30

# Max number of execution logs kept per config
AUTO_UPDATE_MAX_LOGS = 50

# ─── Download Tasks ────────────────────────────────────────────────────────

# Segment download retry attempts per HLS segment during mirroring
DOWNLOAD_SEGMENT_RETRY = 3

# Per-request timeout (seconds) for download worker HTTP calls
DOWNLOAD_HTTP_TIMEOUT = 15

# Interval (seconds) between task progress persistence writes
DOWNLOAD_PROGRESS_FLUSH_INTERVAL = 3.0

# Default User-Agent for download/proxy worker HTTP requests
DEFAULT_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) suenplayer"
