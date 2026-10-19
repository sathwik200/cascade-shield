#!/usr/bin/env python3
"""Generate YAML topology files for all domain profiles."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from cascade_shield.graph.profiles import DOMAIN_KEYS, export_profile_yaml

YAML_MAP = {
    "ecommerce": "ecommerce_topology.yaml",
    "banking": "banking_topology.yaml",
    "streaming": "streaming_topology.yaml",
    "saas": "saas_topology.yaml",
}

def main():
    config_dir = Path("config")
    for domain in DOMAIN_KEYS:
        filename = YAML_MAP.get(domain, f"{domain}_topology.yaml")
        path = config_dir / filename
        export_profile_yaml(domain, path)
        print(f"Exported {domain} -> {path}")

if __name__ == "__main__":
    main()
