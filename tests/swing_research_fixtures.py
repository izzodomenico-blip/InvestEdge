"""Synthetic metadata only; no market observations, secrets or provider IDs."""

from backend.app.swing_research.contracts import (
    INPUT_KINDS,
    DataContext,
    InputRef,
    ResearchManifest,
    ResourceLimits,
    canonical_hash,
)


def manifest(**changes):
    values = {
        "context": DataContext("SYNTHETIC", "SYNTHETIC", "SYNTHETIC"),
        "inputs": tuple(InputRef(kind, canonical_hash({"fixture": kind})) for kind in INPUT_KINDS),
        "software_hash": "a" * 64,
        "resources": ResourceLimits(max_disk_bytes=8_388_608),
    }
    return ResearchManifest(**(values | changes))


def request(name):
    return canonical_hash({"synthetic_request": name})


def registry(tmp_path):
    from backend.app.swing_research.registry import Registry

    inputs = tmp_path / "input"
    inputs.mkdir(exist_ok=True)
    return Registry(input_root=inputs, output_root=tmp_path / "registry")
