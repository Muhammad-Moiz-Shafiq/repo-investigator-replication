from collections.abc import Callable, Iterator
from datetime import datetime
from typing import Any

from gql import Client
from gql.dsl import DocumentNode
from gql.transport.exceptions import TransportConnectionFailed, TransportServerError
from tenacity import retry, retry_if_exception, stop_after_attempt, wait_exponential


def _is_transient(exc: BaseException) -> bool:
    if isinstance(exc, TransportConnectionFailed):
        return True
    return isinstance(exc, TransportServerError) and (exc.code is None or exc.code >= 500)


_retry_on_transient_error = retry(
    retry=retry_if_exception(_is_transient),
    stop=stop_after_attempt(5),
    wait=wait_exponential(multiplier=2, min=2, max=60),
    reraise=True,
)


@_retry_on_transient_error
def _execute_with_retry(client: Client, query: DocumentNode, variables: dict[str, Any]) -> dict:
    return client.execute(query, variable_values=variables)


def paginate(
    client: Client,
    query: DocumentNode,
    base_variables: dict[str, Any],
    extract_page: Callable[[dict], tuple[list[dict], dict]],
) -> Iterator[dict]:
    """Walks every page of a GitHub GraphQL connection, yielding one node at a time.

    extract_page(result) must return (nodes, page_info) for the connection
    this query targets, since the nesting differs per query. Transient
    network errors (timeouts, connection drops, 5xx responses) are retried
    with exponential backoff before giving up, since a multi-minute
    ingestion run over hundreds of pages will occasionally hit one.
    """
    after = None
    while True:
        result = _execute_with_retry(client, query, {**base_variables, "after": after})
        nodes, page_info = extract_page(result)
        yield from nodes
        if not page_info["hasNextPage"]:
            break
        after = page_info["endCursor"]


def stop_before_cutoff(
    nodes: Iterator[dict],
    created_at_key: str,
    cutoff: datetime,
) -> Iterator[dict]:
    """For connections with no server-side date filter (e.g. pull requests),
    stops consuming pages once results are ordered-descending and cross the
    cutoff date, rather than filtering after fetching everything.
    """
    for node in nodes:
        created_at = datetime.fromisoformat(node[created_at_key].replace("Z", "+00:00"))
        if created_at < cutoff:
            return
        yield node
