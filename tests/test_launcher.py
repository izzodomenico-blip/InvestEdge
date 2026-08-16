from __future__ import annotations

import os
import shutil
import sqlite3
import subprocess
from pathlib import Path

import pytest

ROOT_DIR = Path(__file__).resolve().parents[1]
LAUNCHER_PATH = ROOT_DIR / "scripts" / "launcher.ps1"
EXPECTED_SHA256 = "B5C050D121CAA341E0B935677E58F99A0EE6E4C15622FBA754A3D7E797027687"

HASH_PROBE = r"""
$ErrorActionPreference = "Stop"
$tokens = $null
$parseErrors = $null
$ast = [Management.Automation.Language.Parser]::ParseFile(
    $env:INVESTEDGE_LAUNCHER_PATH,
    [ref]$tokens,
    [ref]$parseErrors
)
if ($parseErrors.Count -ne 0) {
    throw "launcher.ps1 non analizzabile"
}
$hashFunction = $ast.Find({
    param($node)
    $node -is [Management.Automation.Language.FunctionDefinitionAst] -and
        $node.Name -eq "Get-FileHash256"
}, $true)
if ($null -eq $hashFunction) {
    throw "Get-FileHash256 non trovata"
}
Invoke-Expression $hashFunction.Extent.Text
function Get-FileHash { throw "SENTINEL_GET_FILE_HASH_UNAVAILABLE" }
$actual = Get-FileHash256 -Path $env:INVESTEDGE_HASH_FIXTURE
if ($actual -ne $env:INVESTEDGE_EXPECTED_HASH) {
    throw "Hash inatteso: $actual"
}
"HASH_WITHOUT_GET_FILE_HASH=PASS"
"""

DB_PATH_PROBE = r"""
$ErrorActionPreference = "Stop"
$tokens = $null
$parseErrors = $null
$ast = [Management.Automation.Language.Parser]::ParseFile(
    $env:INVESTEDGE_LAUNCHER_PATH,
    [ref]$tokens,
    [ref]$parseErrors
)
if ($parseErrors.Count -ne 0) {
    throw "launcher.ps1 non analizzabile"
}
foreach ($name in @("Resolve-EffectiveDbPath", "Test-DbNeedsAutomaticSeed")) {
    $definition = $ast.Find({
        param($node)
        $node -is [Management.Automation.Language.FunctionDefinitionAst] -and
            $node.Name -eq $name
    }, $true)
    if ($null -eq $definition) {
        throw "$name non trovata"
    }
    Invoke-Expression $definition.Extent.Text
}
if (Test-Path -LiteralPath $env:INVESTEDGE_DEFAULT_DB_FIXTURE) {
    throw "La fixture del DB predefinito deve essere assente"
}
$resolved = Resolve-EffectiveDbPath -Python $env:INVESTEDGE_VENV_PYTHON -Root $env:INVESTEDGE_PROJECT_ROOT
if ([System.IO.Path]::GetFullPath($resolved) -ne [System.IO.Path]::GetFullPath($env:INVESTEDGE_CUSTOM_DB)) {
    throw "Path DB effettivo inatteso: $resolved"
}
if (Test-DbNeedsAutomaticSeed -Db $resolved) {
    throw "Un DB custom esistente non deve richiedere seed automatico"
}
"CUSTOM_DB_PRESERVED=PASS"
"""

SERVER_EXIT_PROBE = r"""
$ErrorActionPreference = "Stop"
$tokens = $null
$parseErrors = $null
$ast = [Management.Automation.Language.Parser]::ParseFile(
    $env:INVESTEDGE_LAUNCHER_PATH,
    [ref]$tokens,
    [ref]$parseErrors
)
if ($parseErrors.Count -ne 0) {
    throw "launcher.ps1 non analizzabile"
}
$definition = $ast.Find({
    param($node)
    $node -is [Management.Automation.Language.FunctionDefinitionAst] -and
        $node.Name -eq "Invoke-InvestEdgeServer"
}, $true)
if ($null -eq $definition) {
    throw "Invoke-InvestEdgeServer non trovata"
}
Invoke-Expression $definition.Extent.Text
$serverExitCode = 1
$cleanup = {
    Set-Content -LiteralPath $env:INVESTEDGE_CLEANUP_MARKER -Value "cleanup-ran"
}
Invoke-InvestEdgeServer `
    -Python $env:INVESTEDGE_FAKE_SERVER `
    -Root $env:INVESTEDGE_PROJECT_ROOT `
    -Port 8123 `
    -Cleanup $cleanup `
    -ExitCode ([ref]$serverExitCode)
if (-not (Test-Path -LiteralPath $env:INVESTEDGE_CLEANUP_MARKER)) {
    throw "Cleanup non eseguito"
}
exit $serverExitCode
"""


def test_launcher_hash_works_without_get_file_hash(tmp_path: Path) -> None:
    powershell = shutil.which("powershell.exe") or shutil.which("powershell")
    if powershell is None:
        pytest.skip("Windows PowerShell non disponibile")

    fixture = tmp_path / "hash-sentinel.bin"
    fixture.write_bytes(b"InvestEdge-task11-hash-sentinel")
    environment = os.environ.copy()
    environment.update(
        {
            "INVESTEDGE_LAUNCHER_PATH": str(LAUNCHER_PATH),
            "INVESTEDGE_HASH_FIXTURE": str(fixture),
            "INVESTEDGE_EXPECTED_HASH": EXPECTED_SHA256,
        }
    )

    completed = subprocess.run(
        [
            powershell,
            "-NoProfile",
            "-NonInteractive",
            "-ExecutionPolicy",
            "Bypass",
            "-Command",
            HASH_PROBE,
        ],
        cwd=ROOT_DIR,
        env=environment,
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert completed.returncode == 0, (
        f"stdout:\n{completed.stdout}\nstderr:\n{completed.stderr}"
    )
    assert "HASH_WITHOUT_GET_FILE_HASH=PASS" in completed.stdout


def test_launcher_preserves_existing_custom_database_when_default_is_absent(tmp_path: Path) -> None:
    powershell = shutil.which("powershell.exe") or shutil.which("powershell")
    if powershell is None:
        pytest.skip("Windows PowerShell non disponibile")

    custom_database = tmp_path / "custom" / "legacy.db"
    custom_database.parent.mkdir()
    with sqlite3.connect(custom_database) as connection:
        connection.execute("CREATE TABLE sentinel (value TEXT NOT NULL)")
        connection.execute("INSERT INTO sentinel (value) VALUES ('preserved')")

    environment = os.environ.copy()
    environment.update(
        {
            "INVESTEDGE_LAUNCHER_PATH": str(LAUNCHER_PATH),
            "INVESTEDGE_PROJECT_ROOT": str(ROOT_DIR),
            "INVESTEDGE_VENV_PYTHON": str(ROOT_DIR / "backend" / ".venv" / "Scripts" / "python.exe"),
            "INVESTEDGE_DB_PATH": str(custom_database),
            "INVESTEDGE_CUSTOM_DB": str(custom_database),
            "INVESTEDGE_DEFAULT_DB_FIXTURE": str(tmp_path / "default-absent" / "investedge.db"),
        }
    )

    completed = subprocess.run(
        [
            powershell,
            "-NoProfile",
            "-NonInteractive",
            "-ExecutionPolicy",
            "Bypass",
            "-Command",
            DB_PATH_PROBE,
        ],
        cwd=ROOT_DIR,
        env=environment,
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert completed.returncode == 0, (
        f"stdout:\n{completed.stdout}\nstderr:\n{completed.stderr}"
    )
    assert "CUSTOM_DB_PRESERVED=PASS" in completed.stdout
    with sqlite3.connect(custom_database) as connection:
        assert connection.execute("SELECT value FROM sentinel").fetchone()[0] == "preserved"


def test_launcher_propagates_server_exit_code_after_cleanup(tmp_path: Path) -> None:
    powershell = shutil.which("powershell.exe") or shutil.which("powershell")
    if powershell is None:
        pytest.skip("Windows PowerShell non disponibile")

    fake_server = tmp_path / "fake-server.cmd"
    fake_server.write_text("@exit /b 23\n", encoding="ascii")
    cleanup_marker = tmp_path / "cleanup.marker"
    environment = os.environ.copy()
    environment.update(
        {
            "INVESTEDGE_LAUNCHER_PATH": str(LAUNCHER_PATH),
            "INVESTEDGE_PROJECT_ROOT": str(ROOT_DIR),
            "INVESTEDGE_FAKE_SERVER": str(fake_server),
            "INVESTEDGE_CLEANUP_MARKER": str(cleanup_marker),
        }
    )

    completed = subprocess.run(
        [
            powershell,
            "-NoProfile",
            "-NonInteractive",
            "-ExecutionPolicy",
            "Bypass",
            "-Command",
            SERVER_EXIT_PROBE,
        ],
        cwd=ROOT_DIR,
        env=environment,
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert completed.returncode == 23, (
        f"stdout:\n{completed.stdout}\nstderr:\n{completed.stderr}"
    )
    assert cleanup_marker.read_text(encoding="utf-8-sig").strip() == "cleanup-ran"
