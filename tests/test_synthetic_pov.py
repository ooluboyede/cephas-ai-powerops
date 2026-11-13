from powerops.pov.synthetic import (
    DATASET_LABEL,
    classify_loading_risk,
    generate_synthetic_pov_dataset,
)


def test_synthetic_dataset_is_reproducible() -> None:
    first = generate_synthetic_pov_dataset(seed=7)
    second = generate_synthetic_pov_dataset(seed=7)
    assert first.to_dict() == second.to_dict()


def test_dataset_is_explicitly_synthetic_and_uses_demo_identifiers() -> None:
    dataset = generate_synthetic_pov_dataset(seed=11)
    payload = dataset.to_dict()
    assert payload["dataset_label"] == DATASET_LABEL
    assert all(item["feeder_id"].startswith("DEMO-") for item in payload["feeders"])
    assert all(
        item["transformer_id"].startswith("DEMO-")
        for item in payload["transformers"]
    )
    assert all(
        item["source_classification"] == DATASET_LABEL
        for collection in (
            payload["feeders"],
            payload["transformers"],
            payload["outages"],
            payload["energy_reconciliation"],
        )
        for item in collection
    )


def test_transformer_loading_percentage_matches_source_values() -> None:
    dataset = generate_synthetic_pov_dataset(seed=13)
    for transformer in dataset.transformers:
        expected = round(
            transformer.peak_load_kva / transformer.rated_capacity_kva * 100,
            1,
        )
        assert transformer.loading_pct == expected


def test_loading_risk_thresholds_are_explicit() -> None:
    assert classify_loading_risk(0) == "normal"
    assert classify_loading_risk(84.9) == "normal"
    assert classify_loading_risk(85) == "elevated"
    assert classify_loading_risk(100) == "elevated"
    assert classify_loading_risk(100.1) == "high"


def test_energy_gap_is_reproducible_arithmetic_not_loss_label() -> None:
    dataset = generate_synthetic_pov_dataset(seed=17)
    for record in dataset.energy_reconciliation:
        assert record.unreconciled_gap_mwh == round(
            record.energy_input_mwh - record.billed_energy_mwh, 2
        )
        assert record.unreconciled_gap_mwh >= 0


def test_generator_rejects_unbounded_fixture_dimensions() -> None:
    import pytest

    with pytest.raises(ValueError):
        generate_synthetic_pov_dataset(feeder_count=0)
    with pytest.raises(ValueError):
        generate_synthetic_pov_dataset(transformers_per_feeder=11)
    with pytest.raises(ValueError):
        generate_synthetic_pov_dataset(days=91)


def test_loading_risk_rejects_non_finite_values() -> None:
    import math

    import pytest

    for value in (math.nan, math.inf, -math.inf, -0.1):
        with pytest.raises(ValueError):
            classify_loading_risk(value)


def test_outage_timestamps_and_durations_are_consistent() -> None:
    from datetime import datetime

    dataset = generate_synthetic_pov_dataset(seed=23)
    reference_time = datetime.fromisoformat(dataset.reference_time)
    for outage in dataset.outages:
        started = datetime.fromisoformat(outage.started_at)
        restored = datetime.fromisoformat(outage.restored_at)
        assert restored > started
        assert restored <= reference_time
        assert int((restored - started).total_seconds() / 60) == (
            outage.duration_minutes
        )


def test_energy_reconciliation_never_exceeds_input() -> None:
    dataset = generate_synthetic_pov_dataset(seed=29)
    for record in dataset.energy_reconciliation:
        assert record.energy_input_mwh > 0
        assert record.billed_energy_mwh >= 0
        assert record.billed_energy_mwh <= record.energy_input_mwh
        assert record.unreconciled_gap_mwh >= 0
