from __future__ import annotations

from collections.abc import Callable

from app.config.schemas import DataSource, SourceKind
from app.errors import ConnectorNotImplemented, SourceDisabled
from app.security.ssrf import guard_endpoint


def fetch_news_source(source: DataSource, reader: Callable[[DataSource], object]) -> object:
    """Fetch only an enabled news source after the SSRF check.

    The M0 reader does not open a network connection.
    """
    if source.kind is not SourceKind.news:
        raise ConnectorNotImplemented()
    if not source.enabled:
        raise SourceDisabled()
    guard_endpoint(source.connector.value, source.endpoint)
    return reader(source)


def unavailable_reader(source: DataSource) -> None:
    raise ConnectorNotImplemented()
