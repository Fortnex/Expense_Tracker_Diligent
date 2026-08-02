"""Stress test for the Smart Expense Tracker API.

Run the server first:
    uvicorn src.main:app --port 8000

Then in another terminal:
    python scripts/stress_test.py

What it does:
    1. Fires many concurrent valid POST /expenses requests
    2. Fires many concurrent invalid POST /expenses requests (bad category,
       negative amount, blank title) and checks they're all correctly rejected
    3. Hammers GET /expenses, GET /expenses?category=, and the totals
       endpoint concurrently
    4. Fires many concurrent DELETE requests at the SAME expense id to check
       for race conditions (exactly one should succeed with 204, the rest
       should get a clean 404 -- not a crash or a double-delete)
    5. Verifies consistency: total expense count == sum of per-category
       counts from the totals endpoint
    6. Prints a summary report: status code counts, latency percentiles,
       and pass/fail on each correctness check

This intentionally sends a mix of valid and invalid requests concurrently,
since that's closer to what a real, messy client population looks like than
firing only "happy path" requests.
"""
from __future__ import annotations

import argparse
import asyncio
import random
import statistics
import time

import httpx

CATEGORIES = [
    "Food", "Transport", "Entertainment", "Utilities", "Health",
    "Shopping", "Bills", "Education", "Travel", "Other",
]


def percentile(data: list[float], pct: float) -> float:
    if not data:
        return 0.0
    data = sorted(data)
    k = (len(data) - 1) * pct
    f, c = int(k), min(int(k) + 1, len(data) - 1)
    if f == c:
        return data[f]
    return data[f] + (k - f) * (data[c] - data[f])


class Report:
    def __init__(self):
        self.timings: dict[str, list[float]] = {}
        self.status_counts: dict[str, dict[int, int]] = {}
        self.checks: list[tuple[str, bool, str]] = []

    def record(self, label: str, elapsed: float, status: int):
        self.timings.setdefault(label, []).append(elapsed)
        self.status_counts.setdefault(label, {}).setdefault(status, 0)
        self.status_counts[label][status] += 1

    def check(self, name: str, passed: bool, detail: str = ""):
        self.checks.append((name, passed, detail))

    def print_summary(self):
        print("\n" + "=" * 70)
        print("STRESS TEST SUMMARY")
        print("=" * 70)

        for label, times in self.timings.items():
            n = len(times)
            print(f"\n[{label}]  n={n}")
            print(f"  status codes: {self.status_counts[label]}")
            if times:
                print(
                    f"  latency (s)  min={min(times):.4f}  "
                    f"p50={percentile(times, 0.5):.4f}  "
                    f"p95={percentile(times, 0.95):.4f}  "
                    f"p99={percentile(times, 0.99):.4f}  "
                    f"max={max(times):.4f}"
                )

        print("\n" + "-" * 70)
        print("CORRECTNESS CHECKS")
        print("-" * 70)
        all_passed = True
        for name, passed, detail in self.checks:
            status = "PASS" if passed else "FAIL"
            all_passed = all_passed and passed
            line = f"  [{status}] {name}"
            if detail:
                line += f"  -- {detail}"
            print(line)

        print("\n" + "=" * 70)
        print("OVERALL: " + ("ALL CHECKS PASSED" if all_passed else "SOME CHECKS FAILED"))
        print("=" * 70)
        return all_passed


async def timed_request(client: httpx.AsyncClient, method: str, url: str, report: Report, label: str, **kwargs):
    start = time.perf_counter()
    try:
        resp = await client.request(method, url, **kwargs)
        elapsed = time.perf_counter() - start
        report.record(label, elapsed, resp.status_code)
        return resp
    except Exception as e:
        elapsed = time.perf_counter() - start
        report.record(label, elapsed, -1)
        print(f"  !! request error on {label}: {e}")
        return None


async def run_stress_test(base_url: str, n_valid: int, n_invalid: int, n_reads: int):
    report = Report()

    async with httpx.AsyncClient(base_url=base_url, timeout=10.0) as client:
        # 0. sanity check server is up
        try:
            r = await client.get("/")
            assert r.status_code == 200
        except Exception as e:
            print(f"Could not reach server at {base_url}: {e}")
            print("Make sure it's running: uvicorn src.main:app --port 8000")
            return False

        print(f"Target: {base_url}")
        print(f"Plan: {n_valid} valid POSTs, {n_invalid} invalid POSTs, "
              f"{n_reads} concurrent reads, then a delete race test.\n")

        # 1. Concurrent valid POSTs
        print(f"Firing {n_valid} concurrent valid POST /expenses ...")
        valid_payloads = [
            {
                "title": f"Stress item {i}",
                "amount": round(random.uniform(1, 500), 2),
                "category": random.choice(CATEGORIES),
                "date": "2026-01-15",
            }
            for i in range(n_valid)
        ]
        results = await asyncio.gather(*[
            timed_request(client, "POST", "/expenses", report, "valid_post", json=p)
            for p in valid_payloads
        ])
        created_ids = [r.json()["id"] for r in results if r is not None and r.status_code == 201]
        report.check(
            "all valid POSTs returned 201",
            len(created_ids) == n_valid,
            f"{len(created_ids)}/{n_valid} succeeded",
        )

        # 2. Concurrent invalid POSTs (should ALL be rejected, none crash)
        print(f"Firing {n_invalid} concurrent invalid POST /expenses (should all be 422) ...")
        bad_payloads = []
        for i in range(n_invalid):
            kind = i % 3
            if kind == 0:
                bad_payloads.append({"title": "Bad", "amount": -5, "category": "Food", "date": "2026-01-15"})
            elif kind == 1:
                bad_payloads.append({"title": "   ", "amount": 5, "category": "Food", "date": "2026-01-15"})
            else:
                bad_payloads.append({"title": "Bad", "amount": 5, "category": "NotACategory", "date": "2026-01-15"})
        invalid_results = await asyncio.gather(*[
            timed_request(client, "POST", "/expenses", report, "invalid_post", json=p)
            for p in bad_payloads
        ])
        rejected = sum(1 for r in invalid_results if r is not None and r.status_code == 422)
        report.check(
            "all invalid POSTs correctly rejected with 422",
            rejected == n_invalid,
            f"{rejected}/{n_invalid} rejected",
        )

        # 3. Concurrent reads while data exists
        print(f"Firing {n_reads} concurrent reads (list / filter / totals) ...")
        read_tasks = []
        for i in range(n_reads):
            kind = i % 3
            if kind == 0:
                read_tasks.append(timed_request(client, "GET", "/expenses", report, "list_all"))
            elif kind == 1:
                cat = random.choice(CATEGORIES)
                read_tasks.append(timed_request(client, "GET", f"/expenses?category={cat}", report, "filter_by_category"))
            else:
                read_tasks.append(timed_request(client, "GET", "/expenses/totals/summary", report, "totals"))
        read_results = await asyncio.gather(*read_tasks)
        read_ok = sum(1 for r in read_results if r is not None and r.status_code == 200)
        report.check(
            "all reads returned 200",
            read_ok == n_reads,
            f"{read_ok}/{n_reads} returned 200",
        )

        # 4. Consistency check: overall_count matches sum of per-category counts
        totals_resp = await client.get("/expenses/totals/summary")
        totals = totals_resp.json()
        sum_of_category_counts = sum(c["count"] for c in totals["by_category"])
        report.check(
            "overall_count matches sum of per-category counts",
            totals["overall_count"] == sum_of_category_counts,
            f"overall_count={totals['overall_count']}, sum={sum_of_category_counts}",
        )

        list_resp = await client.get("/expenses")
        actual_count = len(list_resp.json())
        report.check(
            "totals overall_count matches actual number of stored expenses",
            totals["overall_count"] == actual_count,
            f"overall_count={totals['overall_count']}, actual list length={actual_count}",
        )

        # 5. Race condition test: N concurrent DELETEs on the SAME id.
        # Exactly one should succeed (204); the rest should 404 cleanly.
        if created_ids:
            target_id = created_ids[0]
            n_racers = 10
            print(f"Firing {n_racers} concurrent DELETE requests at the SAME id ({target_id}) ...")
            delete_results = await asyncio.gather(*[
                timed_request(client, "DELETE", f"/expenses/{target_id}", report, "delete_race")
                for _ in range(n_racers)
            ])
            statuses = [r.status_code for r in delete_results if r is not None]
            successes = statuses.count(204)
            not_found = statuses.count(404)
            report.check(
                "exactly one concurrent delete succeeded (204), rest got 404",
                successes == 1 and not_found == n_racers - 1,
                f"204s={successes}, 404s={not_found}, other={len(statuses) - successes - not_found}",
            )

            confirm = await client.get(f"/expenses/{target_id}")
            report.check(
                "deleted expense is really gone (404 on GET)",
                confirm.status_code == 404,
                f"got {confirm.status_code}",
            )

    return report.print_summary()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Stress test the Expense Tracker API")
    parser.add_argument("--url", default="http://127.0.0.1:8000", help="Base URL of the running server")
    parser.add_argument("--valid", type=int, default=200, help="Number of concurrent valid POSTs")
    parser.add_argument("--invalid", type=int, default=60, help="Number of concurrent invalid POSTs")
    parser.add_argument("--reads", type=int, default=150, help="Number of concurrent GET requests")
    args = parser.parse_args()

    passed = asyncio.run(run_stress_test(args.url, args.valid, args.invalid, args.reads))
    raise SystemExit(0 if passed else 1)
