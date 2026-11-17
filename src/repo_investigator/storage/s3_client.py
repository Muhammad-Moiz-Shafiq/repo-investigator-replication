import gzip
import json

from supabase import Client, create_client


def make_storage_client(supabase_url: str, service_role_key: str) -> Client:
    return create_client(supabase_url, service_role_key)


def upload_json(client: Client, bucket: str, path: str, data: list[dict]) -> None:
    # gzip is lossless, so this only changes storage size, not content. mtime=0
    # keeps the compressed bytes identical across reruns of the same data.
    payload = gzip.compress(json.dumps(data).encode("utf-8"), mtime=0)
    client.storage.from_(bucket).upload(
        path,
        payload,
        file_options={"content-type": "application/gzip", "upsert": "true"},
    )
