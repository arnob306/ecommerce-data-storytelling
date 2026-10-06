import yaml
import os

CONFIG_PATH = os.path.join(os.path.dirname(__file__), "..", "config", "kpis.yaml")

with open(CONFIG_PATH) as f:
    CONFIG = yaml.safe_load(f)


def test_kpis_config_loads():
    """kpis.yaml exists and is valid YAML."""
    assert CONFIG is not None


def test_kpis_key_exists():
    """kpis.yaml has a top-level 'kpis' key."""
    assert "kpis" in CONFIG


def test_at_least_one_kpi_defined():
    """At least one KPI is defined."""
    assert len(CONFIG["kpis"]) > 0


def test_each_kpi_has_formula():
    """Every KPI has a formula field."""
    for name, kpi in CONFIG["kpis"].items():
        assert "formula" in kpi, f"KPI '{name}' missing 'formula'"


def test_each_kpi_has_owner():
    """Every KPI has an owner field."""
    for name, kpi in CONFIG["kpis"].items():
        assert "owner" in kpi, f"KPI '{name}' missing 'owner'"


def test_each_kpi_has_thresholds():
    """Every KPI has a thresholds block."""
    for name, kpi in CONFIG["kpis"].items():
        assert "thresholds" in kpi, f"KPI '{name}' missing 'thresholds'"


def test_anomaly_sensitivity_is_valid():
    """anomaly_sensitivity is a float between 0 and 1 where defined."""
    for name, kpi in CONFIG["kpis"].items():
        sensitivity = kpi["thresholds"].get("anomaly_sensitivity")
        if sensitivity is not None:
            assert 0 < sensitivity < 1, (
                f"KPI '{name}' has invalid anomaly_sensitivity: {sensitivity}"
            )


def test_metadata_exists():
    """kpis.yaml has a metadata block."""
    assert "metadata" in CONFIG


def test_known_kpis_present():
    """Core KPIs expected in the mart tables are all defined."""
    core_kpis = [
        "total_revenue",
        "order_count",
        "units_sold",
        "active_customers",
        "revenue_per_order",
        "revenue_per_customer",
    ]
    for kpi in core_kpis:
        assert kpi in CONFIG["kpis"], f"Expected core KPI '{kpi}' not found"