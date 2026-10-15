import ast
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]/'backend/app'


@pytest.mark.parametrize('name',['context','features','eligibility','quote_units','contracts'])
def test_pure_research_import_boundaries(name):
    tree = ast.parse((ROOT/'intraday_research'/f'{name}.py').read_text(encoding='utf-8'))
    forbidden = {'data_providers','features_daily','feature_store','score','technical_analysis','ml','socket','sqlite3','time','os'}
    for node in ast.walk(tree):
        names = [a.name for a in node.names] if isinstance(node,ast.Import) else [node.module or ''] if isinstance(node,ast.ImportFrom) else []
        assert all(not forbidden.intersection(n.split('.')) for n in names)


def test_data_layer_never_imports_research():
    for path in (ROOT/'intraday').glob('*.py'):
        tree = ast.parse(path.read_text(encoding='utf-8'))
        for node in ast.walk(tree):
            if isinstance(node,ast.ImportFrom):
                assert 'intraday_research' not in (node.module or '')
            elif isinstance(node,ast.Import):
                assert all('intraday_research' not in alias.name for alias in node.names)
