"""Unit tests for domain profiles and topology presets."""

import pytest
from pathlib import Path
from cascade_shield.graph.profiles import (
    DOMAIN_KEYS,
    build_topology,
    get_scenarios,
    get_scenario_names,
    build_failure_scenarios,
    export_profile_yaml,
    load_profile_yaml,
)


def test_domain_profiles_exist():
    assert set(DOMAIN_KEYS) == {"ecommerce", "banking", "streaming", "saas"}


@pytest.mark.parametrize("domain", DOMAIN_KEYS)
def test_build_topology_valid(domain: str):
    graph = build_topology(domain)
    assert graph.service_count >= 8
    assert graph.edge_count >= 10

    # Validate topology has no cycles or invalid backup references
    errors = graph.validate()
    assert errors == [], f"Validation errors in {domain}: {errors}"


@pytest.mark.parametrize("domain", DOMAIN_KEYS)
def test_scenarios_for_domain(domain: str):
    scenarios = get_scenarios(domain)
    assert len(scenarios) == 4

    names = get_scenario_names(domain)
    assert len(names) == 4

    for name in names:
        failure_scenarios = build_failure_scenarios(domain, name)
        assert len(failure_scenarios) >= 1
        for fs in failure_scenarios:
            assert fs.target_service_id != ""
            assert fs.duration_ticks >= 1
            assert 0.0 <= fs.severity <= 1.0


def test_invalid_domain():
    with pytest.raises(ValueError, match="Unknown domain"):
        build_topology("invalid_domain")

    with pytest.raises(ValueError, match="Unknown domain"):
        get_scenarios("invalid_domain")

    with pytest.raises(ValueError, match="Scenario 'Fake' not found"):
        build_failure_scenarios("ecommerce", "Fake")


def test_yaml_export_and_import(tmp_path: Path):
    yaml_file = tmp_path / "test_ecommerce.yaml"
    export_profile_yaml("ecommerce", yaml_file)
    assert yaml_file.exists()

    loaded_graph = load_profile_yaml(yaml_file)
    original_graph = build_topology("ecommerce")

    assert loaded_graph.service_count == original_graph.service_count
    assert loaded_graph.edge_count == original_graph.edge_count
    assert sorted(loaded_graph.service_ids) == sorted(original_graph.service_ids)
