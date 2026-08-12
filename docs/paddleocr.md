# PaddleOCR 官方云 API 配置

OCR Worker 使用 PaddleOCR 官方异步 HTTP API。默认服务地址为官方端点，
管理员通常只需要填写 Access Token；只有使用私有化网关或专属服务时才填写 Base URL。
客户端只依赖 HTTPX，不安装 Paddlex、OpenCV 或本地推理模型。

## 模型选择

- 普通图片：`PP-OCRv6`
- 扫描 PDF 或复杂版面：`PaddleOCR-VL-1.6`
- 表格/版面回退：`PP-StructureV3`

## 异步任务与恢复

SynapseKB 使用官方提交/查询模式：

```python
POST /api/v2/ocr/jobs
GET /api/v2/ocr/jobs/{job_id}
```

普通文字识别使用 `submit_ocr`，扫描文档和复杂版面使用
`submit_document_parsing`。云端 job ID 会立即写入 `processing_jobs.external_task_id`；
Worker 重启或 Dramatiq 重试后继续等待同一个任务，不会重复提交。取消信号会中断本地等待，
且取消后不会写入新的解析文本或 Chunk。

结果会统一转换为 Markdown，并为每页写入 `<!-- page:N -->` 标记，供分块和引用页码使用。

初始值可以通过 `PADDLEOCR_BASE_URL`（可选）、`PADDLEOCR_API_KEY` 提供。管理员也可以在
“OCR 设置”中覆盖 Base URL、加密 Access Token、默认模型、超时和跨 Worker 最大并发，
并上传不落库的测试文件执行真实异步任务。数据库配置存在时优先于环境变量。

令牌不写日志；数据库任务只保存云任务 ID、模型、耗时和错误摘要，不保存完整敏感正文。

官方参考：

- [PaddleOCR Python SDK](https://www.paddleocr.ai/latest/en/version3.x/inference_deployment/serving/paddleocr_official_api/python.html)
- [PaddleOCR CLI 与 Access Token](https://www.paddleocr.ai/latest/en/version3.x/inference_deployment/serving/paddleocr_official_api/cli.html)
