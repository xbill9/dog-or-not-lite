#!/usr/bin/env python3
"""
Score the scanner against the fixture set.

This is the only thing here that measures the model rather than the plumbing.
It posts every image in fixtures/ to a running /api/scan and compares `is_dog`
against the hand-checked answer in fixtures/fixtures.json -- the expectations
were verified by eye before being committed, which is the only reason they are
worth anything.

    ./check.py                                  # against a local server
    ./check.py --url https://<service>.aws      # against the deployed one
    ./check.py --min-rate 0.9                   # non-zero exit below 90%

Stdlib only, so it runs against a deployed URL from anywhere without installing
anything.
"""

import argparse
import base64
import json
import pathlib
import sys
import time
import urllib.error
import urllib.request

FIXTURES = pathlib.Path(__file__).parent / "fixtures"


def scan(url: str, image: bytes, timeout: float) -> dict:
    body = json.dumps({"image": base64.b64encode(image).decode()}).encode()
    req = urllib.request.Request(
        f"{url.rstrip('/')}/api/scan",
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read())


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="http://127.0.0.1:8080")
    ap.add_argument("--min-rate", type=float, default=0.0)
    ap.add_argument("--timeout", type=float, default=45.0)
    args = ap.parse_args()

    manifest = json.loads((FIXTURES / "fixtures.json").read_text())
    passed = failed = errored = 0
    latencies = []

    print(f"{'fixture':<16} {'expected':<9} {'got':<9} {'subject':<26} {'ms':>6}")
    print("-" * 72)

    for name, truth in sorted(manifest.items()):
        path = FIXTURES / name
        started = time.monotonic()
        try:
            verdict = scan(args.url, path.read_bytes(), args.timeout)
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            print(f"{name:<16} {'ERROR':<9} {exc}")
            errored += 1
            continue

        ms = round((time.monotonic() - started) * 1000)
        latencies.append(ms)
        want = truth["is_dog"]
        got = verdict.get("is_dog")
        ok = want == got
        passed += ok
        failed += not ok

        mark = "  " if ok else "<-"
        print(
            f"{name:<16} {'DOG' if want else 'NOT A DOG':<9} "
            f"{'DOG' if got else 'NOT A DOG':<9} "
            f"{verdict.get('subject', '?'):<26} {ms:>6} {mark}"
        )

    total = passed + failed
    rate = passed / total if total else 0.0
    median = sorted(latencies)[len(latencies) // 2] if latencies else 0

    print("-" * 72)
    print(
        f"{passed}/{total} correct ({rate:.0%}), {errored} errored, median {median} ms"
    )

    if errored:
        return 2
    if rate < args.min_rate:
        print(f"below --min-rate {args.min_rate:.0%}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
