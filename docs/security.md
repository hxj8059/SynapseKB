# 安全模型

- 密码使用 Argon2id；Access JWT 短期有效，Refresh Token 旋转且只通过 HttpOnly、SameSite
  Cookie 传输；HTTPS 模式额外启用 `Secure`，显式 HTTP 兼容模式无法使用该标记。
- 模型密钥使用主密钥派生的 AES-256-GCM 加密，日志不输出密钥内容。
- PAT 使用至少 32 字节随机数，只展示一次；数据库保存 SHA-256 Hash。
- 所有资源访问在应用服务层校验，API、Worker、Agent、Wiki 和 MCP 共享同一授权策略。
- 上传同时校验扩展名、MIME、文件签名和大小；对象键由系统生成，禁止用户提供路径。
- URL 导入解析 DNS，拒绝私网、回环、链路本地、保留地址和重定向后的地址。
- Markdown 渲染使用白名单清洗，禁止脚本、事件属性和危险 URL Scheme。
- SQL 使用 SQLAlchemy 参数绑定；时间字段仅从枚举映射，不能由请求直接拼接。
- API/MCP 分别限流；MCP 额外校验 Bearer Token、Origin、Scope 和审计。
- Compose 只向 Nginx 暴露公网端口；只有显式启用 `TRUST_PROXY_HEADERS` 时 API
  才使用 Nginx 覆盖后的 `X-Real-IP` 做登录限流，禁止把 API 容器同时直接暴露公网。
- 普通日志不包含文档全文、Prompt 全文、Cookie、Authorization、API Key 或 OCR 原始响应。

生产环境默认要求 HTTPS。仅当管理员显式设置 `ALLOW_INSECURE_HTTP=true` 时，系统才允许
`production` 使用公网 IP + HTTP；此时 Refresh Cookie 会适配 HTTP，Host/Origin/Token/Scope
校验仍然有效，但网络链路不再保护登录凭证、PAT、查询、引用和文档内容。该模式应配合严格
安全组、固定来源 IP、短期 PAT 和更低限流，并尽快迁移到 HTTPS。

无论是否启用 HTTP 兼容模式，都必须配置数据库/对象存储备份、对象版本策略、主密钥离线备份
和定期恢复演练。
URL 抓取仍应配合云防火墙/安全组禁止访问实例元数据和内网网段，形成应用校验之外的
第二道出站边界。
