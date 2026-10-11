from __future__ import annotations

import importlib

import pytest
from test_alpaca_market_provider import db, provider, response, settings
from test_intraday_news import article


def client(handler, **options):
    mod = importlib.import_module("backend.app.data_providers.alpaca_news")
    config = settings(**options)
    connection = db()
    return mod.AlpacaNewsProvider(provider(connection, config, handler))


def page(client, **changes):
    return client.get_page(start="2026-10-09T14:00:00.000000001Z", end="2026-10-09T15:00:00Z",
                           symbols=("AAPL",), **changes)


def test_news_page_keeps_explicit_bounded_query_and_no_body_in_cache():
    seen = []
    def handler(req):
        seen.append(req)
        return response({"news": [article()], "next_page_token": None})
    c = client(handler)
    result = page(c)
    query = dict(seen[0].url.params)
    assert query["include_content"] == "false" and query["exclude_contentless"] == "false"
    assert query["sort"] == "asc" and query["limit"] == "50"
    assert "content" not in result.payload["news"][0]
    assert page(c).from_cache and len(seen) == 1


def test_missing_terminal_token_never_means_complete_page():
    c = client(lambda req: response({"news": [article()]}))
    with pytest.raises(Exception, match="NEWS_PAGE_INVALID"):
        page(c)


def test_disabled_news_never_calls_transport():
    c = client(lambda req: pytest.fail("network"), enable_alpaca_data=False)
    with pytest.raises(Exception, match="REAL_DATA_DISABLED"):
        page(c)


@pytest.mark.parametrize("status,reason", [(401, "AUTHENTICATION_FAILED"), (403, "FEED_NOT_ENTITLED"), (429, "COOLDOWN")])
def test_news_uses_existing_governed_auth_and_budget(status, reason):
    calls = []
    c = client(lambda req: calls.append(req) or response({}, status=status))
    with pytest.raises(Exception, match="alpaca:"):
        page(c)
    assert calls
    if status in (401,403):
        with pytest.raises(Exception, match=reason):
            page(c)
        assert len(calls) == 1


def test_stream_decoder_exact_ns_and_unknown_language():
    mod = importlib.import_module("backend.app.data_providers.alpaca_news")
    result = mod.decode_news_row({"T":"n", **article()}, source="STREAM", rights=mod.NewsRights())
    assert result["published_at_ns"] % 1_000_000_000 == 1
    assert result["language"] is None and result["source_article_id"] == "101"


@pytest.mark.parametrize("value", [0, True, "101", -1])
def test_invalid_official_article_id_is_rejected(value):
    mod = importlib.import_module("backend.app.data_providers.alpaca_news")
    with pytest.raises(ValueError, match="NEWS_ROW_INVALID"):
        mod.decode_news_row(article(id=value), source="STREAM", rights=mod.NewsRights())


def test_untrusted_large_body_is_bounded_even_without_rights():
    mod = importlib.import_module("backend.app.data_providers.alpaca_news")
    with pytest.raises(ValueError, match="NEWS_ROW_INVALID"):
        mod.decode_news_row(article(content="x"*1_048_577), source="STREAM", rights=mod.NewsRights())


@pytest.mark.parametrize("url", [123, [], "https://example.com/?token=discard", "http://[invalid"])
def test_invalid_url_is_discarded_without_runtime_error(url):
    mod = importlib.import_module("backend.app.data_providers.alpaca_news")
    result = mod.decode_news_row(article(url=url), source="STREAM", rights=mod.NewsRights())
    assert result["url"] is None
