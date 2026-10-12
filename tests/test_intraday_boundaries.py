from __future__ import annotations

import ast
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[1]


def test_replay_is_pure_and_cannot_import_provider_db_clock_or_trading():
    source = ROOT / 'backend/app/intraday/replay.py'
    assert source.exists(), 'Replay module missing'
    tree = ast.parse(source.read_text(encoding='utf-8'))
    allowed = {'__future__', 'copy', 'hashlib', 'json', 'collections', 'dataclasses', 'typing',
               'backend.app.intraday.contracts'}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            assert all(alias.name in allowed for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            assert node.module in allowed
        elif isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            assert node.func.id not in {'__import__', 'eval', 'exec', 'open', 'compile'}


@pytest.mark.parametrize('name', ['store', 'aggregate', 'news', 'events', 'replay'])
def test_intraday_evidence_does_not_import_daily_score_legacy_news_or_orders(name):
    path = ROOT / f'backend/app/intraday/{name}.py'
    assert path.exists()
    tree = ast.parse(path.read_text(encoding='utf-8'))
    forbidden = ('backend.app.lab', 'backend.app.services.news', 'backend.app.services.ml',
                 'backend.app.services.analysis', 'backend.app.brokers', 'backend.app.trading')
    for node in ast.walk(tree):
        names = [alias.name for alias in node.names] if isinstance(node, ast.Import) else (
            [node.module or ''] if isinstance(node, ast.ImportFrom) else [])
        assert not any(value.startswith(forbidden) for value in names)


def test_aggregation_remains_pure_without_metadata_provider_dependency():
    tree = ast.parse((ROOT / 'backend/app/intraday/aggregate.py').read_text(encoding='utf-8'))
    assert not any(isinstance(node, ast.ImportFrom) and 'data_providers' in (node.module or '')
                   for node in ast.walk(tree))
