#!/usr/bin/env python3
"""
System Health Monitor
=====================
Monitors CPU, memory, disk usage, and running processes.
Sends alerts to console and/or a log file when thresholds are exceeded.

Usage:
    python3 system_health_monitor.py [--log /path/to/logfile] [--interval 60]
"""

import argparse
import datetime
import logging
import os
import platform
import subprocess
import sys
import time


# ─── Configurable Thresholds ──────────────────────────────────────────────────
THRESHOLDS = {
    "cpu_percent":    80.0,   # Alert if CPU usage > 80%
    "memory_percent": 80.0,   # Alert if memory usage > 80%
    "disk_percent":   85.0,   # Alert if any disk partition > 85%
    "zombie_count":   5,      # Alert if zombie processes > 5
}


# ─── Logging Setup ────────────────────────────────────────────────────────────
def setup_logging(log_file: str | None) -> logging.Logger:
    logger = logging.getLogger("HealthMonitor")
    logger.setLevel(logging.DEBUG)
    fmt = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # Always log to console
    ch = logging.StreamHandler(sys.stdout)
    ch.setFormatter(fmt)
    logger.addHandler(ch)

    # Optionally log to file
    if log_file:
        os.makedirs(os.path.dirname(os.path.abspath(log_file)), exist_ok=True)
        fh = logging.FileHandler(log_file)
        fh.setFormatter(fmt)
        logger.addHandler(fh)

    return logger


# ─── Metric Collection ────────────────────────────────────────────────────────
def get_cpu_usage() -> float:
    """Return CPU usage percentage (averaged over 1 second)."""
    try:
        import psutil
        return psutil.cpu_percent(interval=1)
    except ImportError:
        # Fallback: parse /proc/stat on Linux
        def read_cpu():
            with open("/proc/stat") as f:
                line = f.readline()
            vals = list(map(int, line.split()[1:]))
            idle = vals[3]
            total = sum(vals)
            return idle, total

        i1, t1 = read_cpu()
        time.sleep(1)
        i2, t2 = read_cpu()
        idle_delta  = i2 - i1
        total_delta = t2 - t1
        return 100.0 * (1.0 - idle_delta / total_delta) if total_delta else 0.0


def get_memory_usage() -> dict:
    """Return memory stats as a dict."""
    try:
        import psutil
        m = psutil.virtual_memory()
        return {
            "total_gb":   round(m.total / 1024**3, 2),
            "used_gb":    round(m.used  / 1024**3, 2),
            "free_gb":    round(m.available / 1024**3, 2),
            "percent":    m.percent,
        }
    except ImportError:
        # Fallback: parse /proc/meminfo
        info = {}
        with open("/proc/meminfo") as f:
            for line in f:
                key, val = line.split(":")
                info[key.strip()] = int(val.strip().split()[0])  # kB
        total = info.get("MemTotal", 1)
        free  = info.get("MemAvailable", 0)
        used  = total - free
        return {
            "total_gb": round(total / 1024**2, 2),
            "used_gb":  round(used  / 1024**2, 2),
            "free_gb":  round(free  / 1024**2, 2),
            "percent":  round(100.0 * used / total, 1),
        }


def get_disk_usage() -> list[dict]:
    """Return disk usage for all mounted partitions."""
    results = []
    try:
        import psutil
        for part in psutil.disk_partitions(all=False):
            try:
                usage = psutil.disk_usage(part.mountpoint)
                results.append({
                    "mountpoint": part.mountpoint,
                    "total_gb":   round(usage.total / 1024**3, 2),
                    "used_gb":    round(usage.used  / 1024**3, 2),
                    "free_gb":    round(usage.free  / 1024**3, 2),
                    "percent":    usage.percent,
                })
            except PermissionError:
                continue
    except ImportError:
        # Fallback: parse df output
        out = subprocess.check_output(["df", "-BG", "--output=target,size,used,avail,pcent"],
                                       text=True)
        for line in out.strip().splitlines()[1:]:
            parts = line.split()
            if len(parts) < 5:
                continue
            results.append({
                "mountpoint": parts[0],
                "total_gb":   float(parts[1].rstrip("G")),
                "used_gb":    float(parts[2].rstrip("G")),
                "free_gb":    float(parts[3].rstrip("G")),
                "percent":    float(parts[4].rstrip("%")),
            })
    return results


def get_process_stats() -> dict:
    """Return running process count, zombie count, top-5 by CPU."""
    try:
        import psutil
        procs = list(psutil.process_iter(["pid", "name", "status", "cpu_percent", "memory_percent"]))
        # A second call to get accurate cpu_percent (needs two samples)
        time.sleep(0.5)
        procs = list(psutil.process_iter(["pid", "name", "status", "cpu_percent", "memory_percent"]))

        total   = len(procs)
        zombies = sum(1 for p in procs if p.info["status"] == psutil.STATUS_ZOMBIE)
        top5    = sorted(procs, key=lambda p: p.info["cpu_percent"] or 0, reverse=True)[:5]
        top5_info = [
            {"pid": p.pid, "name": p.info["name"], "cpu%": p.info["cpu_percent"],
             "mem%": round(p.info["memory_percent"] or 0, 2)}
            for p in top5
        ]
        return {"total": total, "zombies": zombies, "top_cpu": top5_info}
    except ImportError:
        # Fallback: use ps
        out = subprocess.check_output(
            ["ps", "ax", "-o", "pid,comm,stat,%cpu,%mem", "--sort=-%cpu"],
            text=True
        )
        lines = out.strip().splitlines()[1:]
        total   = len(lines)
        zombies = sum(1 for l in lines if "Z" in l.split()[2])
        top5    = []
        for line in lines[:5]:
            parts = line.split(None, 4)
            top5.append({"pid": parts[0], "name": parts[1],
                         "cpu%": float(parts[3]), "mem%": float(parts[4])})
        return {"total": total, "zombies": zombies, "top_cpu": top5}


# ─── Health Check & Alerting ──────────────────────────────────────────────────
def check_health(logger: logging.Logger) -> bool:
    """Run all health checks, log results, return True if all healthy."""
    all_ok = True
    separator = "─" * 60
    logger.info(separator)
    logger.info(f"Health Check — {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    logger.info(f"Host: {platform.node()}  |  OS: {platform.system()} {platform.release()}")
    logger.info(separator)

    # CPU
    cpu = get_cpu_usage()
    cpu_ok = cpu <= THRESHOLDS["cpu_percent"]
    level = logging.INFO if cpu_ok else logging.WARNING
    logger.log(level, f"CPU Usage     : {cpu:.1f}%  (threshold: {THRESHOLDS['cpu_percent']}%)"
               + ("" if cpu_ok else "  ⚠ ALERT: CPU usage is high!"))
    if not cpu_ok:
        all_ok = False

    # Memory
    mem = get_memory_usage()
    mem_ok = mem["percent"] <= THRESHOLDS["memory_percent"]
    level = logging.INFO if mem_ok else logging.WARNING
    logger.log(level, f"Memory Usage  : {mem['percent']:.1f}%  "
               f"({mem['used_gb']} GB / {mem['total_gb']} GB)  "
               f"(threshold: {THRESHOLDS['memory_percent']}%)"
               + ("" if mem_ok else "  ⚠ ALERT: Memory usage is high!"))
    if not mem_ok:
        all_ok = False

    # Disk
    for disk in get_disk_usage():
        disk_ok = disk["percent"] <= THRESHOLDS["disk_percent"]
        level = logging.INFO if disk_ok else logging.WARNING
        logger.log(level,
                   f"Disk [{disk['mountpoint']:15s}]: {disk['percent']:.1f}%  "
                   f"({disk['used_gb']} GB / {disk['total_gb']} GB)  "
                   f"(threshold: {THRESHOLDS['disk_percent']}%)"
                   + ("" if disk_ok else "  ⚠ ALERT: Disk space low!"))
        if not disk_ok:
            all_ok = False

    # Processes
    procs = get_process_stats()
    zombie_ok = procs["zombies"] <= THRESHOLDS["zombie_count"]
    logger.info(f"Processes     : {procs['total']} running, {procs['zombies']} zombie"
                + ("" if zombie_ok else f"  ⚠ ALERT: Too many zombies! (>{THRESHOLDS['zombie_count']})"))
    if not zombie_ok:
        all_ok = False

    logger.info("Top 5 by CPU  :")
    for p in procs["top_cpu"]:
        logger.info(f"    PID {p['pid']:>6}  {p['name']:<25} CPU: {p['cpu%']:>5.1f}%  MEM: {p['mem%']:>5.2f}%")

    logger.info(separator)
    status = "✅ ALL SYSTEMS HEALTHY" if all_ok else "⚠  ALERTS DETECTED – review above"
    logger.info(status)
    logger.info(separator)
    return all_ok


# ─── Entry Point ──────────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(description="System Health Monitor")
    parser.add_argument("--log",      default=None,  help="Path to log file (optional)")
    parser.add_argument("--interval", type=int, default=0,
                        help="Repeat interval in seconds (0 = run once and exit)")
    parser.add_argument("--cpu",    type=float, default=THRESHOLDS["cpu_percent"],
                        help="CPU alert threshold %%")
    parser.add_argument("--memory", type=float, default=THRESHOLDS["memory_percent"],
                        help="Memory alert threshold %%")
    parser.add_argument("--disk",   type=float, default=THRESHOLDS["disk_percent"],
                        help="Disk alert threshold %%")
    args = parser.parse_args()

    # Override thresholds from CLI
    THRESHOLDS["cpu_percent"]    = args.cpu
    THRESHOLDS["memory_percent"] = args.memory
    THRESHOLDS["disk_percent"]   = args.disk

    logger = setup_logging(args.log)

    if args.interval > 0:
        logger.info(f"Running in continuous mode (every {args.interval}s). Press Ctrl+C to stop.")
        try:
            while True:
                check_health(logger)
                time.sleep(args.interval)
        except KeyboardInterrupt:
            logger.info("Monitor stopped by user.")
    else:
        ok = check_health(logger)
        sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
