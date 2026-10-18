from urllib.parse import urlparse


def parse_gcs_uri(uri: str):
    parsed = urlparse(uri)

    if parsed.scheme != "gs":
        raise ValueError(f"Invalid GCS URI: {uri}")

    return {
        "bucket": parsed.netloc,
        "prefix": parsed.path.strip("/"),
    }
