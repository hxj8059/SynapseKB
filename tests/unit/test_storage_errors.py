from botocore.exceptions import ClientError, EndpointConnectionError
from synapsekb.storage.errors import describe_storage_error


def _client_error(code: str, message: str = "rejected") -> ClientError:
    return ClientError(
        {
            "Error": {"Code": code, "Message": message},
            "ResponseMetadata": {"HTTPStatusCode": 403, "RequestId": "safe-request-id"},
        },
        "PutObject",
    )


def test_storage_error_explains_invalid_cos_key_without_credentials() -> None:
    message = describe_storage_error(_client_error("InvalidAccessKeyId"), backend="cos")

    assert "腾讯云 COS" in message
    assert "Access Key" in message
    assert "safe-request-id" in message
    assert "Secret Key" not in message


def test_storage_error_explains_cos_bad_endpoint() -> None:
    message = describe_storage_error(_client_error("400", "Bad Request"), backend="cos")

    assert "不含 Bucket 名称" in message
    assert "Region" in message


def test_storage_error_explains_endpoint_connection_failure() -> None:
    error = EndpointConnectionError(endpoint_url="https://example.invalid")

    message = describe_storage_error(error, backend="cos")

    assert "Endpoint" in message
    assert "DNS" in message
    assert "example.invalid" not in message
