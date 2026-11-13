"""Deterministic, explicitly synthetic utility data for offline PoV demonstrations.

This module does not connect to utility systems, persist customer data, or expose
an HTTP endpoint. Generated records are demonstration fixtures only.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from math import isfinite
from random import Random
from typing import Final, Literal

DATASET_LABEL: Final[str] = "SYNTHETIC_NOT_CUSTOMER_DATA"
REFERENCE_TIME: Final[datetime] = datetime(
    2026, 10, 31, 23, 59, tzinfo=timezone(timedelta(hours=1), name="WAT")
)
RiskLevel = Literal["normal", "elevated", "high"]


@dataclass(frozen=True, slots=True)
class FeederRecord:
    """Synthetic feeder operating snapshot; not a measured utility record."""

    feeder_id: str
    name: str
    nominal_voltage_kv: int
    rated_capacity_mw: float
    demand_mw: float
    loading_pct: float
    outage_count_30d: int
    source_classification: str = DATASET_LABEL


@dataclass(frozen=True, slots=True)
class TransformerRecord:
    """Synthetic transformer loading snapshot; not an asset-health diagnosis."""

    transformer_id: str
    feeder_id: str
    rated_capacity_kva: int
    peak_load_kva: float
    loading_pct: float
    risk_level: RiskLevel
    source_classification: str = DATASET_LABEL


@dataclass(frozen=True, slots=True)
class OutageRecord:
    """Synthetic outage event for demonstrating incident analysis workflows."""

    outage_id: str
    feeder_id: str
    started_at: str
    restored_at: str
    duration_minutes: int
    cause_code: str
    source_classification: str = DATASET_LABEL


@dataclass(frozen=True, slots=True)
class EnergyReconciliationRecord:
    """Synthetic energy balance; the gap is not automatically a loss estimate."""

    feeder_id: str
    period_start: str
    energy_input_mwh: float
    billed_energy_mwh: float
    unreconciled_gap_mwh: float
    source_classification: str = DATASET_LABEL


@dataclass(frozen=True, slots=True)
class SyntheticPoVDataset:
    """Complete deterministic synthetic dataset for a presentation environment."""

    dataset_label: str
    reference_time: str
    seed: int
    feeders: tuple[FeederRecord, ...]
    transformers: tuple[TransformerRecord, ...]
    outages: tuple[OutageRecord, ...]
    energy_reconciliation: tuple[EnergyReconciliationRecord, ...]

    def to_dict(self) -> dict[str, object]:
        """Return JSON-serialisable data while preserving provenance labels."""
        return {
            "dataset_label": self.dataset_label,
            "reference_time": self.reference_time,
            "seed": self.seed,
            "feeders": [asdict(record) for record in self.feeders],
            "transformers": [asdict(record) for record in self.transformers],
            "outages": [asdict(record) for record in self.outages],
            "energy_reconciliation": [
                asdict(record) for record in self.energy_reconciliation
            ],
        }


def classify_loading_risk(loading_pct: float) -> RiskLevel:
    """Classify a loading indicator, not the physical health or fault state."""
    if not isfinite(loading_pct) or loading_pct < 0:
        raise ValueError("loading_pct must be finite and non-negative")
    if loading_pct > 100:
        return "high"
    if loading_pct >= 85:
        return "elevated"
    return "normal"


def generate_synthetic_pov_dataset(
    *,
    seed: int = 20261113,
    feeder_count: int = 6,
    transformers_per_feeder: int = 3,
    days: int = 14,
) -> SyntheticPoVDataset:
    """Generate repeatable synthetic feeder, transformer, outage and energy data.

    Counts are bounded so accidental configuration cannot create an unbounded
    fixture. The fixed reference time keeps generated results reproducible.
    """
    if not 1 <= feeder_count <= 50:
        raise ValueError("feeder_count must be between 1 and 50")
    if not 1 <= transformers_per_feeder <= 10:
        raise ValueError("transformers_per_feeder must be between 1 and 10")
    if not 1 <= days <= 90:
        raise ValueError("days must be between 1 and 90")

    rng = Random(seed)
    feeders: list[FeederRecord] = []
    transformers: list[TransformerRecord] = []
    outages: list[OutageRecord] = []
    energy: list[EnergyReconciliationRecord] = []
    voltage_options = (11, 33)
    transformer_capacity_options = (500, 750, 1000, 1500, 2000)
    cause_options = ("equipment", "weather", "vegetation", "third_party", "unknown")

    for feeder_index in range(1, feeder_count + 1):
        feeder_id = f"DEMO-FDR-{feeder_index:03d}"
        capacity = float(rng.randint(12, 24))
        demand = round(capacity * rng.uniform(0.48, 1.08), 2)
        feeders.append(
            FeederRecord(
                feeder_id=feeder_id,
                name=f"DEMO Distribution Feeder {feeder_index:03d}",
                nominal_voltage_kv=rng.choice(voltage_options),
                rated_capacity_mw=capacity,
                demand_mw=demand,
                loading_pct=round(demand / capacity * 100, 1),
                outage_count_30d=rng.randint(0, 8),
            )
        )

        for transformer_index in range(1, transformers_per_feeder + 1):
            transformer_id = (
                f"DEMO-TX-{feeder_index:03d}-{transformer_index:02d}"
            )
            transformer_capacity = rng.choice(transformer_capacity_options)
            peak_load = round(
                transformer_capacity * rng.uniform(0.42, 1.12), 1
            )
            loading = round(peak_load / transformer_capacity * 100, 1)
            transformers.append(
                TransformerRecord(
                    transformer_id=transformer_id,
                    feeder_id=feeder_id,
                    rated_capacity_kva=transformer_capacity,
                    peak_load_kva=peak_load,
                    loading_pct=loading,
                    risk_level=classify_loading_risk(loading),
                )
            )

        for day_offset in range(days):
            period_start = REFERENCE_TIME - timedelta(days=day_offset + 1)
            energy_input = round(rng.uniform(80, 220), 2)
            billed_energy = round(energy_input * rng.uniform(0.68, 0.96), 2)
            energy.append(
                EnergyReconciliationRecord(
                    feeder_id=feeder_id,
                    period_start=period_start.date().isoformat(),
                    energy_input_mwh=energy_input,
                    billed_energy_mwh=billed_energy,
                    unreconciled_gap_mwh=round(
                        energy_input - billed_energy, 2
                    ),
                )
            )

        outage_count = rng.randint(0, 4)
        for outage_index in range(1, outage_count + 1):
            start_offset = rng.randint(240, 30 * 24 * 60)
            started = REFERENCE_TIME - timedelta(minutes=start_offset)
            duration = rng.randint(20, 240)
            restored = started + timedelta(minutes=duration)
            outages.append(
                OutageRecord(
                    outage_id=(
                        f"DEMO-OUT-{feeder_index:03d}-{outage_index:02d}"
                    ),
                    feeder_id=feeder_id,
                    started_at=started.isoformat(),
                    restored_at=restored.isoformat(),
                    duration_minutes=duration,
                    cause_code=rng.choice(cause_options),
                )
            )

    return SyntheticPoVDataset(
        dataset_label=DATASET_LABEL,
        reference_time=REFERENCE_TIME.isoformat(),
        seed=seed,
        feeders=tuple(feeders),
        transformers=tuple(transformers),
        outages=tuple(outages),
        energy_reconciliation=tuple(energy),
    )
