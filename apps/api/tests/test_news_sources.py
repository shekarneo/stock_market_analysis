from pathlib import Path
import pytest
from app.news.ingest import (
    DEFAULT_SOURCES,
    add_news_source,
    delete_news_source,
    get_active_news_feeds,
    load_news_sources,
    reset_news_sources,
    toggle_news_source,
)


def test_default_sources_loaded_when_no_file(tmp_path: Path):
    target = tmp_path / "sources.json"
    sources = load_news_sources(target)
    assert len(sources) == len(DEFAULT_SOURCES)
    assert sources[0]["id"] == "economic_times_markets"
    assert all(s["enabled"] is True for s in sources)


def test_toggle_news_source(tmp_path: Path):
    target = tmp_path / "sources.json"
    sources = load_news_sources(target)
    assert sources[0]["enabled"] is True

    # Disable first source
    updated = toggle_news_source(sources[0]["id"], enabled=False, path=target)
    assert updated["enabled"] is False

    # Check active feeds excludes disabled source
    active = get_active_news_feeds(target)
    assert len(active) == len(DEFAULT_SOURCES) - 1
    assert not any(f[0] == sources[0]["id"] for f in active)

    # Re-enable
    updated_again = toggle_news_source(sources[0]["id"], enabled=True, path=target)
    assert updated_again["enabled"] is True
    assert len(get_active_news_feeds(target)) == len(DEFAULT_SOURCES)


def test_add_and_delete_news_source(tmp_path: Path):
    target = tmp_path / "sources.json"
    
    # Add custom feed
    new_feed = add_news_source("NDTV Profit", "https://ndtvprofit.example/rss", enabled=True, path=target)
    assert new_feed["id"] == "ndtv_profit"
    assert new_feed["name"] == "NDTV Profit"
    assert new_feed["is_default"] is False

    all_sources = load_news_sources(target)
    assert len(all_sources) == len(DEFAULT_SOURCES) + 1

    # Delete custom feed
    deleted = delete_news_source("ndtv_profit", path=target)
    assert deleted is True

    all_sources_after = load_news_sources(target)
    assert len(all_sources_after) == len(DEFAULT_SOURCES)


def test_add_invalid_url_raises_value_error(tmp_path: Path):
    target = tmp_path / "sources.json"
    with pytest.raises(ValueError, match="Feed URL must start with"):
        add_news_source("Invalid Feed", "ftp://invalid-protocol.com", path=target)


def test_reset_news_sources(tmp_path: Path):
    target = tmp_path / "sources.json"
    add_news_source("Extra Feed", "https://extra.example/rss", path=target)
    assert len(load_news_sources(target)) == len(DEFAULT_SOURCES) + 1

    reset = reset_news_sources(path=target)
    assert len(reset) == len(DEFAULT_SOURCES)
    assert all(s["is_default"] is True for s in reset)
