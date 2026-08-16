from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import dotenv

import backend.app.config as config_module
from backend.app.config import Settings


def test_config_uses_process_database_path(tmp_path, monkeypatch) -> None:
    database_path = tmp_path / "process.db"
    monkeypatch.setenv("INVESTEDGE_DB_PATH", str(database_path))

    settings = Settings.from_env()

    assert settings.database_path == database_path


def test_config_uses_process_environment(monkeypatch) -> None:
    monkeypatch.setenv("INVESTEDGE_ENV", "process-test")

    settings = Settings.from_env()

    assert settings.app_env == "process-test"


def test_config_uses_process_cors_origins(monkeypatch) -> None:
    monkeypatch.setenv("INVESTEDGE_CORS_ORIGINS", "https://app.example.test,https://admin.example.test")

    settings = Settings.from_env()

    assert settings.cors_origins[-2:] == ["https://app.example.test", "https://admin.example.test"]


def test_config_process_values_override_dotenv_files(tmp_path, monkeypatch) -> None:
    root_env = tmp_path / ".env"
    backend_env = tmp_path / "backend" / ".env"
    backend_env.parent.mkdir()
    root_env.write_text(
        "INVESTEDGE_DB_PATH=root.db\nINVESTEDGE_ENV=root\nINVESTEDGE_CORS_ORIGINS=https://root.example.test\n",
        encoding="utf-8",
    )
    backend_env.write_text(
        "INVESTEDGE_DB_PATH=backend.db\nINVESTEDGE_ENV=backend\nINVESTEDGE_CORS_ORIGINS=https://backend.example.test\n",
        encoding="utf-8",
    )
    process_database_path = tmp_path / "process.db"
    monkeypatch.setenv("INVESTEDGE_DB_PATH", str(process_database_path))
    monkeypatch.setenv("INVESTEDGE_ENV", "process")
    monkeypatch.setenv("INVESTEDGE_CORS_ORIGINS", "https://process.example.test")

    real_load_dotenv = dotenv.load_dotenv

    def load_temp_dotenv(dotenv_path, *args, **kwargs):
        source = backend_env if Path(dotenv_path).parent.name == "backend" else root_env
        return real_load_dotenv(source, *args, **kwargs)

    monkeypatch.setattr(dotenv, "load_dotenv", load_temp_dotenv)
    module_name = "_investedge_config_precedence_test"
    spec = importlib.util.spec_from_file_location(module_name, config_module.__file__)
    assert spec is not None
    assert spec.loader is not None
    isolated_config = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = isolated_config
    try:
        spec.loader.exec_module(isolated_config)
    finally:
        sys.modules.pop(module_name, None)

    settings = isolated_config.Settings.from_env()

    assert settings.database_path == process_database_path
    assert settings.app_env == "process"
    assert settings.cors_origins[-1] == "https://process.example.test"
