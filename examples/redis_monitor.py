#!/usr/bin/env python3

import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Dict, List, Optional

import click


def _now() -> str:
    return time.strftime("%H:%M:%S")


def docker_compose_file_default() -> str:
    # Default to examples/docker-compose.yml relative to this script location
    here = Path(__file__).resolve().parent
    compose = here / "docker-compose.yml"
    return str(compose)


def _clean_output(text: str) -> str:
    # Drop docker compose WARN blocks (including wrapped lines) and empty lines
    lines: list[str] = []
    skipping_warn = False
    for ln in text.splitlines():
        s = ln.strip()
        if not s:
            # stop skipping warn after a blank line
            skipping_warn = False
            continue
        if s.startswith("WARN[") or s.startswith("WARNING"):
            skipping_warn = True
            continue
        if skipping_warn:
            # skip wrapped lines that belong to the warn message
            continue
        # also skip known compose warning fragments if they appear standalone
        if "the attribute `version` is obsolete" in s:
            continue
        lines.append(s)
    return "\n".join(lines)


def run_redis_cli(compose_file: str, args: List[str]) -> str:
    cmd = [
        "docker",
        "compose",
        "-f",
        compose_file,
        "exec",
        "-T",
        "redis",
        "redis-cli",
        "--raw",
    ] + args
    try:
        out = subprocess.check_output(cmd, stderr=subprocess.STDOUT)
        return _clean_output(out.decode("utf-8", errors="ignore"))
    except subprocess.CalledProcessError as e:
        return _clean_output(e.output.decode("utf-8", errors="ignore"))


def list_session_keys(compose_file: str, prefix: str) -> List[str]:
    out = run_redis_cli(compose_file, ["KEYS", f"{prefix}:session:*"])
    if not out:
        return []
    keys = [line.strip() for line in out.splitlines() if line.strip()]
    # Filter to only our prefix to avoid stray noise
    return [k for k in keys if k.startswith(f"{prefix}:")]


def list_event_keys(compose_file: str, prefix: str) -> List[str]:
    out = run_redis_cli(compose_file, ["KEYS", f"{prefix}:events:*"])
    if not out:
        return []
    keys = [line.strip() for line in out.splitlines() if line.strip()]
    return [k for k in keys if k.startswith(f"{prefix}:")]


def get_session_json(compose_file: str, key: str) -> Dict:
    out = run_redis_cli(compose_file, ["GET", key])
    try:
        # Extract JSON object if warning or noise surrounds it
        if not out:
            return {}
        start = out.find("{")
        end = out.rfind("}")
        if start != -1 and end != -1 and end >= start:
            return json.loads(out[start : end + 1])
        return json.loads(out)
    except Exception:
        return {"raw": out}


def stream_len(compose_file: str, key: str) -> int:
    out = run_redis_cli(compose_file, ["XLEN", key])
    try:
        # Use the last numeric token
        tokens = [t for t in out.split() if t.isdigit()]
        return int(tokens[-1]) if tokens else int(out)
    except Exception:
        return 0


def stream_tail(compose_file: str, key: str, count: int) -> List[str]:
    out = run_redis_cli(compose_file, ["XREVRANGE", key, "+", "-", "COUNT", str(count)])
    return [line for line in out.splitlines() if line]


def clear_session(compose_file: str, prefix: str, session_id: str) -> None:
    run_redis_cli(compose_file, ["DEL", f"{prefix}:session:{session_id}", f"{prefix}:events:{session_id}"])


def clear_all(compose_file: str, prefix: str) -> None:
    keys = run_redis_cli(compose_file, ["KEYS", f"{prefix}:*"])
    ks = [k for k in keys.splitlines() if k and k.startswith(f"{prefix}:")]
    if ks:
        run_redis_cli(compose_file, ["DEL", *ks])


def monitor(compose_file: str, prefix: str, interval: float, tail: int) -> None:
    while True:
        print(f"\n[{_now()}] Redis monitor prefix='{prefix}' (compose={compose_file})")
        s_keys = list_session_keys(compose_file, prefix)
        e_keys = list_event_keys(compose_file, prefix)
        if not s_keys and not e_keys:
            print("  No sessions or event streams found.")
        idx = 1
        # Show sessions first
        for skey in sorted(s_keys):
            sid = skey.split(":")[-1]
            sess = get_session_json(compose_file, skey)
            status = str(sess.get("status", "UNKNOWN"))
            ev_key = f"{prefix}:events:{sid}"
            length = stream_len(compose_file, ev_key)
            print(f"  [{idx:02d}] {sid}  status={status:<12}  events={length}")
            if tail > 0 and length > 0:
                entries = stream_tail(compose_file, ev_key, tail)
                for line in entries[::-1]:
                    print(f"      - {line}")
            idx += 1
        # If there are event streams without session entries, show them too
        for ekey in sorted(e_keys):
            sid = ekey.split(":")[-1]
            skey = f"{prefix}:session:{sid}"
            if skey in s_keys:
                continue
            length = stream_len(compose_file, ekey)
            print(f"  [{idx:02d}] {sid}  status={'UNKNOWN':<12}  events={length}")
            if tail > 0 and length > 0:
                entries = stream_tail(compose_file, ekey, tail)
                for line in entries[::-1]:
                    print(f"      - {line}")
            idx += 1
        try:
            time.sleep(interval)
        except KeyboardInterrupt:
            break


@click.command()
@click.option("--compose-file", default=docker_compose_file_default(), help="Path to docker-compose.yml for Redis")
@click.option("--prefix", default="mcp", help="Key prefix used by storage")
@click.option("--interval", default=2.0, type=float, help="Polling interval seconds")
@click.option("--tail", default=5, type=int, help="Tail N recent events per session")
@click.option("--clear", default=None, help="Clear a session by ID, or 'all' to clear all keys with prefix")
def main(compose_file: str, prefix: str, interval: float, tail: int, clear: Optional[str]) -> None:
    if clear:
        if clear == "all":
            clear_all(compose_file, prefix)
            print("Cleared all keys with prefix:", prefix)
            return
        clear_session(compose_file, prefix, clear)
        print("Cleared:", clear)
        return
    monitor(compose_file, prefix, interval, tail)


if __name__ == "__main__":
    main()


