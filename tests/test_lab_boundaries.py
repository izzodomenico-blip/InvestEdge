"""Confine sugli import (spec SP1 §4.3): `technical_analysis` resta solo per il grafico."""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
LAB_DIR = ROOT / "backend" / "app" / "lab"
SERVICES_DIR = ROOT / "backend" / "app" / "services"
FORBIDDEN_MODULE = "backend.app.services.technical_analysis"
GUARDED_SERVICES = (
    "scoring_engine.py",
    "backtest_engine.py",
    "ml_dataset_service.py",
    "ml_engine.py",
    "technical_analysis_service.py",
    "signals_service.py",
    "market_data_service.py",
)
# Riscritto nel Task 13 (ML), che rimuove la propria voce (il Task 10 ha rimosso `backtest_engine.py`).
PENDING_BOUNDARY = {"ml_dataset_service.py"}


def _guarded_files() -> list[Path]:
    return [*sorted(LAB_DIR.glob("*.py")), *(SERVICES_DIR / name for name in GUARDED_SERVICES)]


def _is_forbidden(module: str) -> bool:
    return module == FORBIDDEN_MODULE or module.startswith(f"{FORBIDDEN_MODULE}.")


def _forbidden_imports(path: Path) -> list[str]:
    """Import di `technical_analysis` (assoluti, `from package import modulo` o relativi al pacchetto services)."""
    package = "backend.app.services" if path.parent == SERVICES_DIR else "backend.app.lab"
    found: list[str] = []
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"), filename=str(path))):
        if isinstance(node, ast.Import):
            found.extend(alias.name for alias in node.names if _is_forbidden(alias.name))
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                base = package.rsplit(".", node.level - 1)[0] if node.level > 1 else package
                module = f"{base}.{node.module}" if node.module else base
            else:
                module = node.module or ""
            if _is_forbidden(module):
                found.append(module)
            else:
                found.extend(name for alias in node.names if _is_forbidden(name := f"{module}.{alias.name}"))
    return found


def test_guarded_modules_exist_and_detector_finds_the_chart_import() -> None:
    assert len(list(LAB_DIR.glob("*.py"))) >= 6
    assert all((SERVICES_DIR / name).is_file() for name in GUARDED_SERVICES)
    # `prices_service` usa `technical_analysis` per le sovrapposizioni del grafico: il rilevatore la vede.
    assert _forbidden_imports(SERVICES_DIR / "prices_service.py") == [FORBIDDEN_MODULE]


@pytest.mark.parametrize(
    "path",
    [
        pytest.param(
            path,
            id=f"{path.parent.name}/{path.name}",
            marks=(
                pytest.mark.xfail(strict=True, reason="riscritto nel Task 13")
                if path.parent == SERVICES_DIR and path.name in PENDING_BOUNDARY
                else ()
            ),
        )
        for path in _guarded_files()
    ],
)
def test_module_does_not_import_technical_analysis(path: Path) -> None:
    assert _forbidden_imports(path) == []
