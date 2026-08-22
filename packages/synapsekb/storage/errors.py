from __future__ import annotations

from botocore.exceptions import (
    ClientError,
    ConnectTimeoutError,
    EndpointConnectionError,
    NoCredentialsError,
    PartialCredentialsError,
    ReadTimeoutError,
    SSLError,
)

_BACKEND_NAMES = {
    "s3": "S3-compatible 存储",
    "oss": "阿里云 OSS",
    "cos": "腾讯云 COS",
}

_CLIENT_ERROR_ADVICE = {
    "InvalidAccessKeyId": "请重新保存 Access Key，并确认密钥仍处于启用状态",
    "InvalidAccessKey": "请重新保存 Access Key，并确认密钥仍处于启用状态",
    "AuthFailure": "请检查 Access Key 和 Secret Key",
    "SignatureDoesNotMatch": "请检查 Secret Key、Region、Endpoint 和服务器系统时间",
    "AccessDenied": "当前凭证权限不足，请授予目标 Bucket 下对象的读、写和删除权限",
    "Forbidden": "当前凭证权限不足，请检查子账号策略和 Bucket 策略",
    "NoSuchBucket": "Bucket 不存在，或 Bucket 与 Region 不匹配",
    "PermanentRedirect": "Endpoint 或 Region 与 Bucket 所在地域不匹配",
    "AuthorizationHeaderMalformed": "Region 或 Endpoint 配置错误",
    "RequestTimeTooSkewed": "服务器系统时间偏差过大，请启用 NTP 时间同步",
    "RequestExpired": "服务器系统时间不准确，或请求在网络中停留过久",
    "BadRequest": "请使用不含 Bucket 名称的服务 Endpoint，并检查 Region",
    "InvalidRequest": "请使用不含 Bucket 名称的服务 Endpoint，并检查签名配置",
    "400": "请使用不含 Bucket 名称的服务 Endpoint，并检查 Region",
    "SlowDown": "云存储正在限流，请稍后重试",
    "ServiceUnavailable": "云存储服务暂时不可用，请稍后重试",
    "503": "云存储服务暂时不可用，请稍后重试",
}


def describe_storage_error(exc: Exception, *, backend: str) -> str:
    """Return an actionable error without exposing credentials or signed URLs."""

    name = _BACKEND_NAMES.get(backend, "对象存储")
    if isinstance(exc, ClientError):
        response = exc.response
        error = response.get("Error", {})
        metadata = response.get("ResponseMetadata", {})
        code = str(error.get("Code") or metadata.get("HTTPStatusCode") or "unknown")
        message = str(error.get("Message") or "请求被拒绝").strip()
        advice = _CLIENT_ERROR_ADVICE.get(code, "请检查 Bucket、Region、Endpoint、凭证和权限")
        request_id = metadata.get("RequestId")
        request_suffix = f"；Request ID：{request_id}" if request_id else ""
        return f"{name} 返回 {code}（{message}）；{advice}{request_suffix}"
    if isinstance(exc, (NoCredentialsError, PartialCredentialsError)):
        return f"{name}访问凭证不完整，请重新保存 Access Key 和 Secret Key"
    if isinstance(exc, EndpointConnectionError):
        return f"无法连接{name} Endpoint，请检查地址、DNS、防火墙和服务器出口网络"
    if isinstance(exc, (ConnectTimeoutError, ReadTimeoutError)):
        return f"连接{name}超时，请检查服务器出口网络、Endpoint 和云服务状态"
    if isinstance(exc, SSLError):
        return f"{name} HTTPS 证书校验失败，请检查 Endpoint 和服务器 CA 证书"
    return f"{name}连接测试失败（{type(exc).__name__}），请检查服务端日志"
