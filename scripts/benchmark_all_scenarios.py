#!/usr/bin/env python3
"""Benchmark all 16 scenarios across 4 domain profiles.

Compares three policies:
1. No Containment
2. Simple Circuit Breaker
3. Cascade Shield

Exports results to benchmark_results/ in CSV, JSON, and Markdown formats.

Usage:
    PYTHONPATH=. python3 scripts/benchmark_all_scenarios.py
"""

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from cascade_shield.experiment.runner import ExperimentRunner, POLICY_LABELS
from cascade_shield.graph.profiles import DOMAIN_KEYS


def main():
    print("=" * 70)
    print("Cascade Shield - Full Benchmark Suite")
    print("=" * 70)

    runner = ExperimentRunner()
    start_time = time.time()

    print(f"\nRunning benchmark across {len(DOMAIN_KEYS)} domains...")
    results = runner.run_benchmark(duration=30, seed=42)

    elapsed = time.time() - start_time
    print(f"\nBenchmark completed in {elapsed:.2f}s")
    print(f"Total scenarios: {results.total_scenarios}")

    # Export results
    out_dir = Path("benchmark_results")
    out_dir.mkdir(exist_ok=True)

    csv_path = out_dir / "benchmark_results.csv"
    json_path = out_dir / "benchmark_results.json"
    md_path = out_dir / "benchmark_report.md"

    runner.export_csv(results, csv_path)
    runner.export_json(results, json_path)
    report = runner.export_markdown(results, md_path)

    print(f"\nResults exported to:")
    print(f"  CSV:      {csv_path}")
    print(f"  JSON:     {json_path}")
    print(f"  Markdown: {md_path}")

    # Print summary
    print("\n" + "=" * 70)
    print("RESULTS SUMMARY")
    print("=" * 70)
    for policy, count in results.wins.items():
        label = POLICY_LABELS.get(policy, policy)
        print(f"  {label:25s}: {count} wins")
    print(f"  {'Ties':25s}: {results.ties}")

    print("\n" + "-" * 70)
    print(f"{'Domain':<15} {'Scenario':<30} {'Winner':<25} {'Shield Min Avail':>16}")
    print("-" * 70)
    for sr in results.scenarios:
        cs_result = sr.policy_results.get("cascade_shield")
        cs_avail = f"{cs_result.min_availability:.4f}" if cs_result else "N/A"
        winner_label = POLICY_LABELS.get(sr.winner, sr.winner)
        print(f"{sr.domain:<15} {sr.scenario:<30} {winner_label:<25} {cs_avail:>16}")

    print("=" * 70)
    return 0


if __name__ == "__main__":
    sys.exit(main())
