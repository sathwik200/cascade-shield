"""Unit tests for cascade_shield.experiment.runner."""

import pytest
from pathlib import Path
from cascade_shield.experiment.runner import ExperimentRunner, POLICIES, POLICY_LABELS


def test_run_single_scenario():
    runner = ExperimentRunner()
    result = runner.run_scenario(domain="ecommerce", scenario_name="Database Outage", duration=10, seed=42)

    assert result.domain == "ecommerce"
    assert result.scenario == "Database Outage"
    assert set(result.policy_results.keys()) == set(POLICIES)

    for p in POLICIES:
        pr = result.policy_results[p]
        assert pr.policy == p
        assert pr.domain == "ecommerce"
        assert pr.scenario == "Database Outage"
        assert len(pr.metrics_history) == 11  # initial snapshot + 10 ticks
        assert 0.0 <= pr.min_availability <= 1.0
        assert 0.0 <= pr.avg_availability <= 1.0

    assert result.winner in set(POLICIES) | {"tie"}


def test_run_all_scenarios_for_domain():
    runner = ExperimentRunner()
    results = runner.run_all_scenarios(domain="ecommerce", duration=5, seed=42)
    assert len(results) == 4


def test_benchmark_and_exports(tmp_path: Path):
    runner = ExperimentRunner()
    # Run benchmark for 1 domain for speed
    bench = runner.run_benchmark(domains=["ecommerce"], duration=6, seed=42)

    assert bench.total_scenarios == 4
    assert sum(bench.wins.values()) + bench.ties == 4

    csv_path = tmp_path / "bench.csv"
    json_path = tmp_path / "bench.json"
    md_path = tmp_path / "bench.md"

    runner.export_csv(bench, csv_path)
    runner.export_json(bench, json_path)
    report = runner.export_markdown(bench, md_path)

    assert csv_path.exists()
    assert json_path.exists()
    assert md_path.exists()
    assert "Cascade Shield Benchmark Report" in report
