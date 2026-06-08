#!/usr/bin/env python3
"""
Application Health Checker
===========================
Checks the uptime/availability of one or more HTTP(S) endpoints.
Determines if an application is 'up' or 'down' based on HTTP status codes
and optional response-body validation.

Usage:
    python3 app_health_checker.py --urls https://example.com https://api.example.com/health
    python3 app_health_checker.py --config health_config.json --interval 60
    python3 app_health_checker.py --urls http://localhost:4499 --interval 30 --log health.log
"""

import argparse
import datetime
import json
import logging
import os
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Optional


# ─── Data Structures ──────────────────────────────────────────────────────────
@dataclass
class CheckResult:
    url: str
    status: str               # "UP" | "DOWN" | "DEGRADED"
    http_code: Optional[int]
    response_time_ms: float
    error: Optional[str]
    timestamp: str = field(default_factory=lambda: datetime.datetime.now().isoformat())

    def is_up(self) -> bool:
        return self.status == "UP"


@dataclass
class EndpointConfig:
    url: str
    name: str = ""
    timeout: int = 10
    expected_status: list[int] = field(default_factory=lambda: [200])
    expected_body: Optional[str] = None   # substring that must appear in response


# ─── Health Check Logic ───────────────────────────────────────────────────────
def check_endpoint(cfg: EndpointConfig) -> CheckResult:
    """Perform a single HTTP check against the endpoint."""
    start = time.monotonic()
    try:
        req = urllib.request.Request(
            cfg.url,
            headers={"User-Agent": "AppHealthChecker/1.0"},
        )
        with urllib.request.urlopen(req, timeout=cfg.timeout) as resp:
            elapsed_ms = (time.monotonic() - start) * 1000
            code       = resp.status
            body       = resp.read(4096).decode("utf-8", errors="replace")

            # Check body content if expected_body is set
            if cfg.expected_body and cfg.expected_body not in body:
                return CheckResult(
                    url=cfg.url,
                    status="DEGRADED",
                    http_code=code,
                    response_time_ms=round(elapsed_ms, 2),
                    error=f"Expected body substring '{cfg.expected_body}' not found",
                )

            if code in cfg.expected_status:
                return CheckResult(
                    url=cfg.url,
                    status="UP",
                    http_code=code,
                    response_time_ms=round(elapsed_ms, 2),
                    error=None,
                )
            else:
                return CheckResult(
                    url=cfg.url,
                    status="DOWN",
                    http_code=code,
                    response_time_ms=round(elapsed_ms, 2),
                    error=f"Unexpected HTTP status {code} (expected: {cfg.expected_status})",
                )

    except urllib.error.HTTPError as e:
        elapsed_ms = (time.monotonic() - start) * 1000
        return CheckResult(
            url=cfg.url,
            status="DOWN",
            http_code=e.code,
            response_time_ms=round(elapsed_ms, 2),
            error=f"HTTP error {e.code}: {e.reason}",
        )
    except urllib.error.URLError as e:
        elapsed_ms = (time.monotonic() - start) * 1000
        return CheckResult(
            url=cfg.url,
            status="DOWN",
            http_code=None,
            response_time_ms=round(elapsed_ms, 2),
            error=f"Connection error: {e.reason}",
        )
    except TimeoutError:
        elapsed_ms = (time.monotonic() - start) * 1000
        return CheckResult(
            url=cfg.url,
            status="DOWN",
            http_code=None,
            response_time_ms=round(elapsed_ms, 2),
            error=f"Timed out after {cfg.timeout}s",
        )
    except Exception as e:
        elapsed_ms = (time.monotonic() - start) * 1000
        return CheckResult(
            url=cfg.url,
            status="DOWN",
            http_code=None,
            response_time_ms=round(elapsed_ms, 2),
            error=str(e),
        )


# ─── Reporting ────────────────────────────────────────────────────────────────
STATUS_ICON = {"UP": "✅", "DOWN": "❌", "DEGRADED": "⚠️ "}

def log_result(result: CheckResult, logger: logging.Logger):
    icon  = STATUS_ICON.get(result.status, "?")
    code  = f"HTTP {result.http_code}" if result.http_code else "No response"
    error = f"  → {result.error}" if result.error else ""
    level = logging.INFO if result.status == "UP" else logging.WARNING
    logger.log(
        level,
        f"{icon} [{result.status:8s}]  {result.url:<45}  "
        f"{code:<12}  {result.response_time_ms:7.1f} ms{error}",
    )


def print_summary(results: list[CheckResult], logger: logging.Logger):
    sep = "─" * 70
    total   = len(results)
    up      = sum(1 for r in results if r.status == "UP")
    down    = sum(1 for r in results if r.status == "DOWN")
    degraded= sum(1 for r in results if r.status == "DEGRADED")

    logger.info(sep)
    logger.info(
        f"Summary: {total} checked  |  {up} UP  |  {down} DOWN  |  {degraded} DEGRADED"
    )
    if down or degraded:
        logger.warning("⚠  One or more services need attention!")
    else:
        logger.info("✅ All services are operational.")
    logger.info(sep)


# ─── Config Loading ───────────────────────────────────────────────────────────
def load_config(path: str) -> list[EndpointConfig]:
    with open(path) as f:
        data = json.load(f)
    return [
        EndpointConfig(
            url=ep["url"],
            name=ep.get("name", ep["url"]),
            timeout=ep.get("timeout", 10),
            expected_status=ep.get("expected_status", [200]),
            expected_body=ep.get("expected_body"),
        )
        for ep in data.get("endpoints", [])
    ]


def setup_logging(log_file: Optional[str]) -> logging.Logger:
    logger = logging.getLogger("AppHealthChecker")
    logger.setLevel(logging.DEBUG)
    fmt = logging.Formatter("%(asctime)s [%(levelname)-7s] %(message)s",
                            datefmt="%Y-%m-%d %H:%M:%S")
    ch = logging.StreamHandler(sys.stdout)
    ch.setFormatter(fmt)
    logger.addHandler(ch)
    if log_file:
        os.makedirs(os.path.dirname(os.path.abspath(log_file)), exist_ok=True)
        fh = logging.FileHandler(log_file)
        fh.setFormatter(fmt)
        logger.addHandler(fh)
    return logger


# ─── Entry Point ──────────────────────────────────────────────────────────────
def run_checks(endpoints: list[EndpointConfig], logger: logging.Logger) -> list[CheckResult]:
    logger.info("─" * 70)
    logger.info(f"Application Health Check — {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    logger.info("─" * 70)
    results = []
    for ep in endpoints:
        result = check_endpoint(ep)
        log_result(result, logger)
        results.append(result)
    print_summary(results, logger)
    return results


def main():
    parser = argparse.ArgumentParser(description="Application Health Checker")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--urls", nargs="+", metavar="URL",
                       help="One or more URLs to check")
    group.add_argument("--config", metavar="FILE",
                       help="JSON config file with endpoint definitions")
    parser.add_argument("--interval", type=int, default=0,
                        help="Repeat interval in seconds (0 = run once)")
    parser.add_argument("--timeout", type=int, default=10,
                        help="HTTP timeout per request (seconds)")
    parser.add_argument("--log", default=None,
                        help="Path to log file")
    args = parser.parse_args()

    logger = setup_logging(args.log)

    if args.config:
        endpoints = load_config(args.config)
    else:
        endpoints = [
            EndpointConfig(url=url, name=url, timeout=args.timeout)
            for url in args.urls
        ]

    if args.interval > 0:
        logger.info(f"Running continuously every {args.interval}s. Ctrl+C to stop.")
        try:
            while True:
                run_checks(endpoints, logger)
                time.sleep(args.interval)
        except KeyboardInterrupt:
            logger.info("Health checker stopped.")
    else:
        results = run_checks(endpoints, logger)
        all_up = all(r.is_up() for r in results)
        sys.exit(0 if all_up else 1)


if __name__ == "__main__":
    main()
