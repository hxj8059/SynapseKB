# 对象存储配置

生产环境必须使用 HTTPS 对象存储；本地文件存储仅用于开发。SynapseKB 通过统一的
S3 API 适配器实现上传、下载、删除和预签名直传，不把云厂商密钥发送给前端。

管理员登录后可在“对象存储”页面修改运行时配置并执行读写测试。Access Key 和
Secret Key 使用 AES-GCM 加密写入 `system_settings`；留空表示保留原密钥。`.env`
参数是首次启动和数据库尚未配置时的回退值。数据库已有加密配置后，生产环境不要求
把同一密钥再复制到 `.env`；运行时仍会校验对象存储类型、凭证和 HTTPS Endpoint。

## 通用 S3 或 MinIO

```dotenv
STORAGE_BACKEND=s3
STORAGE_ENDPOINT=https://s3.example.com
STORAGE_REGION=us-east-1
STORAGE_BUCKET=synapsekb
STORAGE_ACCESS_KEY=...
STORAGE_SECRET_KEY=...
STORAGE_FORCE_PATH_STYLE=false
```

MinIO 开发环境可使用路径寻址；生产公网服务应使用 HTTPS。

## 阿里云 OSS

OSS 的 S3 兼容接口使用虚拟主机寻址：

```dotenv
STORAGE_BACKEND=oss
STORAGE_ENDPOINT=https://oss-cn-hangzhou.aliyuncs.com
STORAGE_REGION=cn-hangzhou
STORAGE_BUCKET=your-bucket
STORAGE_ACCESS_KEY=...
STORAGE_SECRET_KEY=...
```

请按 Bucket 所在地域替换 endpoint。账号权限只授予目标 Bucket 所需的对象读写操作。
页面还可以填写 `*-internal.aliyuncs.com` 内网 Endpoint；服务端读写可走内网，
浏览器预签名 URL 始终使用公网 Endpoint。对象键前缀用于将 SynapseKB 限制在
Bucket 的指定目录，例如 `SynapseKB`。

## 腾讯云 COS

COS 的 S3 兼容接口同样使用虚拟主机寻址：

```dotenv
STORAGE_BACKEND=cos
STORAGE_ENDPOINT=https://cos.ap-shanghai.myqcloud.com
STORAGE_REGION=ap-shanghai
STORAGE_BUCKET=your-bucket-1250000000
STORAGE_ACCESS_KEY=...
STORAGE_SECRET_KEY=...
```

COS Bucket 名需要包含 APPID。建议使用子账号密钥、最小权限策略和服务端加密。
`STORAGE_ENDPOINT` 必须填写地域级服务地址，不要填写形如
`https://<bucket>.cos.<region>.myqcloud.com` 的 Bucket 访问 URL；虚拟主机寻址会自动拼接
Bucket 名称。

## 生产检查

- 对象存储 endpoint 必须为 HTTPS；`PUBLIC_BASE_URL` 默认也必须为 HTTPS，仅可按部署文档显式
  启用公网 IP + HTTP 兼容模式。
- 密钥只放在部署环境或密钥管理服务中，不写入仓库。
- `CREDENTIAL_MASTER_KEY` 必须固定、安全备份；丢失后无法解密运行时凭据。
- CORS 仅允许实际 Web Origin 执行 `GET`、`PUT` 和 `HEAD`，不要使用通配 Origin；IP + HTTP
  部署必须包含完整 Origin（例如 `http://203.0.113.10:8088`），同时允许 `Content-Type` 及
  实际使用的 `x-cos-*` / `x-oss-*` 请求头。
- 生命周期策略应覆盖失败上传产生的孤立对象。
- 启用版本控制或定期复制，并按恢复文档验证下载和恢复流程。
