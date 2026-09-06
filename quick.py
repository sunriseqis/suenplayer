"""
suenplayer — Speed testing module (quick.py)

Implements the user-specified probe algorithm:
- QUICK_TIMEOUT = 5.0s (connection + first-byte timeout)
- QUICK_CONCURRENCY = 64 (global thread pool)
- QUICK_MAX_SECONDS = 2.0s (max streaming time per URL)
- QUICK_MAX_BYTES = 4MB (max bytes to pull)
- QUICK_MIN_STABLE_SECONDS = 1.0s + 12% variation (smart early exit)

Scoring (user-specified weights):
- Rate 50%: 20 Mbps = full score, linear 0~1
- Latency 30%: <=50ms = full, >=1000ms = 0, linear decay
- Stability 20%: >=10 consecutive successes = full, linear 0~1
- Resolution is NOT in scoring (metadata only)
"""

from __future__ import annotations

import hashlib
import time
import urllib.parse
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from typing import Callable, Iterable, Optional

import requests

import config

# Global thread pool for all quick operations
_executor: Optional[ThreadPoolExecutor] = None


def _get_executor() -> ThreadPoolExecutor:
    global _executor
    if _executor is None or _executor._shutdown:
        _executor = ThreadPoolExecutor(
            max_workers=config.QUICK_CONCURRENCY,
            thread_name_prefix="quick_probe",
        )
    return _executor


def shutdown_executor():
    global _executor
    if _executor is not None:
        _executor.shutdown(wait=False)
        _executor = None


@dataclass
class ProbeResult:
    """Result of probing a single URL."""

    url: str
    url_hash: str = ""
    success: bool = False
    latency_ms: float = 0.0
    rate_mbps: float = 0.0
    bytes_downloaded: int = 0
    duration_seconds: float = 0.0
    resolution: str = ""          # e.g. "1920x1080"
    stability_score: float = 0.0   # 0~1, computed externally from history
    total_score: float = 0.0       # 0~1, computed externally
    error: str = ""
    probed_at: float = field(default_factory=time.time)

    def __post_init__(self):
        if not self.url_hash:
            self.url_hash = hashlib.sha256(self.url.encode()).hexdigest()[:16]


def _safe_requests_session() -> requests.Session:
    """Create a session with timeouts preset."""
    s = requests.Session()
    # Use the user-specified timeout for connection + first-byte
    s.timeout = config.QUICK_TIMEOUT  # type: ignore[attr-defined]
    return s


def _is_m3u8_url(url: str) -> bool:
    return ".m3u8" in url.lower() or url.lower().endswith(".m3u8")


def _probe_latency(session: requests.Session, url: str) -> tuple[bool, float, str]:
    """Measure TTFB (Time To First Byte) latency in ms.

    Returns (success, latency_ms, error_message).
    """
    # 读超时放宽到 10s：部分资源站建立连接后首字节有慢启动爬坡，
    # 5s 一刀切会把慢源误判为无源（与直播侧同款问题）
    last_err = ""
    for attempt in range(2):
        try:
            start = time.perf_counter()
            # Try HEAD first; if not supported fallback to GET with Range=0-0
            try:
                resp = session.head(url, allow_redirects=True,
                                    timeout=(config.QUICK_TIMEOUT, 10))
                if resp.status_code == 405:
                    raise requests.exceptions.RequestException("HEAD not allowed")
            except Exception:
                resp = session.get(
                    url,
                    headers={"Range": "bytes=0-0"},
                    stream=True,
                    allow_redirects=True,
                    timeout=(config.QUICK_TIMEOUT, 10),
                )
                # Consume just the first byte to measure TTFB
                _ = next(resp.iter_content(chunk_size=1), None)
            elapsed_ms = (time.perf_counter() - start) * 1000
            return True, elapsed_ms, ""
        except Exception as e:
            last_err = str(e)
            if attempt == 0:
                time.sleep(0.5)
    return False, 0.0, last_err


def _probe_speed(
    session: requests.Session, url: str
) -> tuple[bool, float, int, float, str]:
    """Probe download speed by pulling up to MAX_BYTES for MAX_SECONDS.

    Returns (success, rate_mbps, bytes_downloaded, duration_seconds, error).
    Implements smart early-exit: if bitrate is stable (<=12% variation)
    for >=1.0s, compute and exit early.
    """
    try:
        headers = {"Range": "bytes=0-"}
        start = time.perf_counter()
        resp = session.get(
            url,
            headers=headers,
            stream=True,
            allow_redirects=True,
            timeout=(config.QUICK_TIMEOUT, config.QUICK_TIMEOUT),
        )
        resp.raise_for_status()

        chunks: list[tuple[float, int]] = []  # (elapsed_since_start, cumulative_bytes)
        total_bytes = 0
        chunk_buffer = bytearray()
        stable_start_time: Optional[float] = None
        last_rate: Optional[float] = None

        for chunk in resp.iter_content(chunk_size=65536):
            if not chunk:
                continue
            chunk_buffer.extend(chunk)
            total_bytes += len(chunk)
            now = time.perf_counter()
            elapsed = now - start

            # Record sample every ~0.2s for stability detection
            if not chunks or (elapsed - chunks[-1][0]) >= 0.2:
                chunks.append((elapsed, total_bytes))

            # Hard limits: time or bytes
            if elapsed >= config.QUICK_MAX_SECONDS:
                break
            if total_bytes >= config.QUICK_MAX_BYTES:
                break

            # Smart early-exit: check stability
            if len(chunks) >= 3 and elapsed >= config.QUICK_MIN_STABLE_SECONDS:
                # Compute short-term rate from last 3 samples
                t2, b2 = chunks[-1]
                t1, b1 = chunks[-3]
                dt = t2 - t1
                if dt > 0:
                    rate_mbps = (b2 - b1) * 8 / (dt * 1024 * 1024)
                    if last_rate is not None:
                        variation = (
                            abs(rate_mbps - last_rate) / last_rate * 100
                            if last_rate > 0
                            else 0
                        )
                        if variation <= config.QUICK_STABLE_VARIATION_PCT:
                            if stable_start_time is None:
                                stable_start_time = t1
                            elif (t2 - stable_start_time) >= config.QUICK_MIN_STABLE_SECONDS:
                                # Stable for long enough — early exit
                                duration = elapsed
                                rate = total_bytes * 8 / (duration * 1024 * 1024)
                                return True, rate, total_bytes, duration, ""
                        else:
                            stable_start_time = None
                    last_rate = rate_mbps

        end = time.perf_counter()
        duration = end - start
        if duration <= 0:
            duration = 0.001
        rate = total_bytes * 8 / (duration * 1024 * 1024)
        return True, rate, total_bytes, duration, ""
    except Exception as e:
        return False, 0.0, 0, 0.0, str(e)


def probe_page_reachability(
    url: str,
    stability_score: float = 0.0,
) -> ProbeResult:
    """Probe a page URL for HTTP reachability only (no speed test).
    Page URLs do not participate in 50-30-20 stream scoring.
    Returns success=True with score=0 if the page responds with HTTP 2xx/3xx.
    """
    if not url or not url.startswith(("http://", "https://")):
        return ProbeResult(url=url, success=False, error="invalid url")

    session = _safe_requests_session()
    try:
        start = time.perf_counter()
        resp = session.head(
            url, allow_redirects=True, timeout=config.QUICK_TIMEOUT,
        )
        if resp.status_code == 405:
            resp = session.get(
                url, headers={"Range": "bytes=0-0"}, stream=True,
                allow_redirects=True, timeout=config.QUICK_TIMEOUT,
            )
        latency_ms = (time.perf_counter() - start) * 1000
        if resp.status_code < 400:
            return ProbeResult(
                url=url, success=True,
                latency_ms=latency_ms, rate_mbps=0.0,
                resolution="", stability_score=stability_score, total_score=0.0,
            )
        return ProbeResult(
            url=url, success=False,
            error=f"HTTP {resp.status_code}",
        )
    except Exception as e:
        return ProbeResult(url=url, success=False, error=str(e))


def probe_single_url(
    url: str,
    resolution_hint: str = "",
    stability_score: float = 0.0,
) -> ProbeResult:
    """Probe a single URL: measure latency + speed.

    Args:
        url: The URL to probe.
        resolution_hint: Pre-known resolution (e.g. "1920x1080").
        stability_score: Pre-computed stability score (0~1).
    """
    if not url or not url.startswith(("http://", "https://")):
        return ProbeResult(url=url, success=False, error="invalid url")

    session = _safe_requests_session()

    # Step 1: latency
    lat_ok, latency_ms, lat_err = _probe_latency(session, url)
    if not lat_ok:
        return ProbeResult(
            url=url,
            success=False,
            latency_ms=0.0,
            error=f"latency probe failed: {lat_err}",
        )

    # Step 2: speed (only if latency succeeded)
    spd_ok, rate_mbps, bytes_dl, duration_s, spd_err = _probe_speed(session, url)
    if not spd_ok:
        # Latency succeeded but speed failed — still record latency
        return ProbeResult(
            url=url,
            success=False,
            latency_ms=latency_ms,
            error=f"speed probe failed: {spd_err}",
        )

    return ProbeResult(
        url=url,
        success=True,
        latency_ms=latency_ms,
        rate_mbps=rate_mbps,
        bytes_downloaded=bytes_dl,
        duration_seconds=duration_s,
        resolution=resolution_hint,
        stability_score=stability_score,
    )


def compute_scores(results: list[ProbeResult]) -> list[ProbeResult]:
    """Compute total_score for each ProbeResult using the user-specified formula.

    Rate (50%): 20 Mbps = 1.0, linear 0~1
    Latency (30%): <=50ms = 1.0, >=1000ms = 0, linear decay
    Stability (20%): >=10 consecutive successes = 1.0, linear 0~1
    """
    for r in results:
        if not r.success:
            r.total_score = 0.0
            continue

        # Rate score
        rate_score = min(1.0, r.rate_mbps / config.RATE_FULL_SCORE_MBPS)

        # Latency score
        if r.latency_ms <= config.LATENCY_FULL_SCORE_MS:
            latency_score = 1.0
        elif r.latency_ms >= config.LATENCY_ZERO_SCORE_MS:
            latency_score = 0.0
        else:
            latency_score = 1.0 - (
                (r.latency_ms - config.LATENCY_FULL_SCORE_MS)
                / (config.LATENCY_ZERO_SCORE_MS - config.LATENCY_FULL_SCORE_MS)
            )

        # Stability score
        stability_score = min(1.0, r.stability_score)

        r.total_score = (
            config.WEIGHT_RATE * rate_score
            + config.WEIGHT_LATENCY * latency_score
            + config.WEIGHT_STABILITY * stability_score
        )

    # Sort by total_score descending
    results.sort(key=lambda x: x.total_score, reverse=True)
    return results


def rank_lines(
    results: list[ProbeResult],
) -> tuple[Optional[ProbeResult], list[ProbeResult], list[ProbeResult]]:
    """Rank probed lines into Primary / Backup1 / Backup2.

    Returns (primary, [backup1, backup2], rest).
    """
    scored = compute_scores(results)
    successful = [r for r in scored if r.success]
    if not successful:
        return None, [], []
    primary = successful[0]
    backups = successful[1:3]
    rest = successful[3:]
    return primary, backups, rest


def probe_pages_concurrent(
    url_items: Iterable[tuple[str, str, float]],
    max_workers: Optional[int] = None,
) -> list[ProbeResult]:
    """Probe multiple page URLs for HTTP reachability concurrently.

    Args:
        url_items: Iterable of (url, _unused_resolution, stability_score).
        max_workers: Override concurrency.

    Returns:
        List of ProbeResult (success=True with score=0 if reachable).
    """
    items = list(url_items)
    total = len(items)
    if total == 0:
        return []

    workers = max_workers or config.QUICK_CONCURRENCY
    results: list[ProbeResult] = []

    with ThreadPoolExecutor(max_workers=min(workers, total)) as ex:
        futures = {
            ex.submit(probe_page_reachability, url, stab): (url, stab)
            for url, _res, stab in items
        }
        for fut in as_completed(futures):
            try:
                result = fut.result(timeout=config.QUICK_TIMEOUT + 2)
            except Exception as e:
                url, stab = futures[fut]
                result = ProbeResult(url=url, success=False, error=str(e))
            results.append(result)

    # Page results: keep as-is (score=0, no re-sorting here — caller merges
    # with stream results and uses rank_lines)
    return results


def probe_urls_concurrent(
    url_items: Iterable[tuple[str, str, float]],
    max_workers: Optional[int] = None,
    progress_callback: Optional[Callable[[int, int], None]] = None,
) -> list[ProbeResult]:
    """Probe multiple URLs concurrently.

    Args:
        url_items: Iterable of (url, resolution_hint, stability_score).
        max_workers: Override concurrency (default: config.QUICK_CONCURRENCY).
        progress_callback: Called with (done_count, total_count).

    Returns:
        List of ProbeResult, sorted by total_score descending.
    """
    items = list(url_items)
    total = len(items)
    if total == 0:
        return []

    workers = max_workers or config.QUICK_CONCURRENCY
    results: list[ProbeResult] = []
    done = 0

    with ThreadPoolExecutor(max_workers=min(workers, total)) as ex:
        futures = {
            ex.submit(probe_single_url, url, res, stab): (url, res, stab)
            for url, res, stab in items
        }
        for fut in as_completed(futures):
            try:
                result = fut.result(timeout=config.QUICK_TIMEOUT * 3 + 20 + config.QUICK_MAX_SECONDS + 2)
            except Exception as e:
                url, res, stab = futures[fut]
                result = ProbeResult(url=url, success=False, error=str(e))
            results.append(result)
            done += 1
            if progress_callback:
                progress_callback(done, total)

    return compute_scores(results)
