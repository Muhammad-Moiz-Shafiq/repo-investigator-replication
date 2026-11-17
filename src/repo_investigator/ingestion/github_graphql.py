from gql import Client
from gql.transport.httpx import HTTPXTransport

GITHUB_GRAPHQL_URL = "https://api.github.com/graphql"
REQUEST_TIMEOUT_SECONDS = 60


def make_github_client(github_pat: str) -> Client:
    transport = HTTPXTransport(
        url=GITHUB_GRAPHQL_URL,
        headers={"Authorization": f"Bearer {github_pat}"},
        timeout=REQUEST_TIMEOUT_SECONDS,
    )
    return Client(transport=transport, fetch_schema_from_transport=False)
