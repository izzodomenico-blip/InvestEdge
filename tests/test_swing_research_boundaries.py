import ast
import subprocess
import sys
from pathlib import Path

import pytest
from swing_research_fixtures import manifest, registry, request

from backend.app.swing_research.contracts import SwingError
from backend.app.swing_research.registry import Registry

PACKAGE = Path(__file__).resolve().parents[1] / "backend/app/swing_research"


def test_package_import_is_stdlib_only_and_never_loads_app_services(tmp_path):
    script = """
import sys
from pathlib import Path
import backend.app.swing_research.contracts
import backend.app.swing_research.registry
import backend.app.swing_research.datasets
import backend.app.swing_research.calendar
import backend.app.swing_research.universe
import backend.app.swing_research.events
assert not any(x in sys.modules for x in ['sqlite3','dotenv','backend.app.config','backend.app.database','backend.app.lab','backend.app.intraday','backend.app.intraday_research'])
"""
    subprocess.run([sys.executable, "-c", script], cwd=PACKAGE.parents[2], check=True, capture_output=True)
    assert not list(tmp_path.iterdir())


def test_static_imports_are_stdlib_or_same_package():
    for path in PACKAGE.glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names = [x.name.split(".")[0] for x in node.names]
            elif isinstance(node, ast.ImportFrom):
                if node.level:
                    continue
                names = [(node.module or "").split(".")[0]]
            else:
                continue
            assert all(name in sys.stdlib_module_names or name == "__future__" for name in names)


@pytest.mark.parametrize("value", [r"\\synthetic.invalid\share\input", r"\\?\C:\synthetic-input", "relative-input"])
def test_dataset_roots_reject_remote_device_and_relative_before_probe(tmp_path, monkeypatch, value):
    from swing_research_fixtures import data_record, local_packet

    from backend.app.swing_research.contracts import ResourceLimits
    from backend.app.swing_research.datasets import Dataset

    _, packet = local_packet(tmp_path, [data_record()])
    original = Path.is_symlink

    def forbidden(path):
        if str(path).startswith("\\\\"):
            pytest.fail("remote root was probed")
        return original(path)

    monkeypatch.setattr(Path, "is_symlink", forbidden)
    with pytest.raises(SwingError, match="^INVALID_PATH$"):
        Dataset(value, packet, expected_hash=packet.dataset_hash, resources=ResourceLimits(8_388_608))


@pytest.mark.parametrize("kind", ["same", "nested", "reverse", "traversal", "relative", "database"])
def test_paths_must_be_dedicated_nonoverlapping_and_no_database(tmp_path, kind):
    source = tmp_path / "input"
    source.mkdir()
    output = tmp_path / "registry"
    if kind == "same":
        output = source
    elif kind == "nested":
        output = source / "output"
    elif kind == "reverse":
        source = tmp_path
    elif kind == "traversal":
        output = tmp_path / "child" / ".." / "registry"
    elif kind == "relative":
        output = Path("relative-registry")
    else:
        output = tmp_path / "data" / "investedge.db"
    with pytest.raises(SwingError):
        Registry(input_root=source, output_root=output)


def test_output_may_not_reuse_unknown_directory_contents(tmp_path):
    source = tmp_path / "input"
    source.mkdir()
    target = tmp_path / "registry"
    target.mkdir()
    sentinel = target / "user-document.txt"
    sentinel.write_text("preserve", encoding="utf-8")
    with pytest.raises(SwingError):
        Registry(input_root=source, output_root=target).snapshot()
    assert sentinel.read_text() == "preserve"


def test_hardlinked_registry_record_is_rejected(tmp_path):
    import os

    r = registry(tmp_path)
    r.register(manifest(), request_id=request("register"), now_ns=1)
    record = next((tmp_path / "registry").glob("*.json"))
    os.link(record, tmp_path / "alias")
    with pytest.raises(SwingError):
        r.snapshot()


def test_input_tree_remains_untouched_and_snapshot_is_immutable(tmp_path):
    from dataclasses import FrozenInstanceError

    source = tmp_path / "input"
    source.mkdir()
    evidence = source / "fixture.txt"
    evidence.write_text("synthetic")
    r = Registry(input_root=source, output_root=tmp_path / "registry")
    s = r.register(manifest(), request_id=request("register"), now_ns=1)
    assert evidence.read_text() == "synthetic" and list(source.iterdir()) == [evidence]
    with pytest.raises(FrozenInstanceError):
        s.holdout_state = "CONTAMINATED"


def test_errors_do_not_echo_input_strings(tmp_path):
    source = tmp_path / "input"
    source.mkdir()
    with pytest.raises(SwingError) as error:
        Registry(input_root=source, output_root="synthetic-sensitive-relative-path")
    assert str(error.value) == "INVALID_PATH"


@pytest.mark.parametrize("value", [r"\\synthetic.invalid\share\registry", r"\\?\C:\synthetic-registry"])
def test_unc_and_device_roots_are_rejected_before_filesystem_access(tmp_path, monkeypatch, value):
    source = tmp_path / "input"
    source.mkdir()
    original = Path.is_symlink

    def forbid_remote_probe(path):
        if str(path).startswith("\\\\"):
            pytest.fail("UNC/device path reached filesystem inspection")
        return original(path)

    monkeypatch.setattr(Path, "is_symlink", forbid_remote_probe)
    with pytest.raises(SwingError, match="^INVALID_PATH$"):
        Registry(input_root=source, output_root=value)
