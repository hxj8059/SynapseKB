import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ScanText, UploadCloud } from "lucide-react";
import { useEffect, useState, type FormEvent } from "react";

import { PageHeader } from "../components/PageHeader";
import { Button } from "../components/ui/button";
import { Card } from "../components/ui/card";
import { Input } from "../components/ui/input";
import { Select } from "../components/ui/select";
import { api } from "../lib/api";
import type { OcrSettings, OcrTestResult } from "../lib/types";

export function OcrSettingsPage() {
  const client = useQueryClient();
  const [form, setForm] = useState({
    base_url: "",
    api_key: "",
    default_model: "PaddleOCR-VL-1.6",
    timeout_seconds: "600",
    max_concurrency: "2",
  });
  const [testFile, setTestFile] = useState<File | null>(null);
  const { data } = useQuery({
    queryKey: ["ocr-settings"],
    queryFn: () => api<OcrSettings>("/settings/ocr"),
  });
  useEffect(() => {
    if (!data) return;
    setForm((current) => ({
      ...current,
      base_url: data.base_url ?? "",
      default_model: data.default_model,
      timeout_seconds: String(data.timeout_seconds),
      max_concurrency: String(data.max_concurrency),
    }));
  }, [data]);

  const save = useMutation({
    mutationFn: () =>
      api<OcrSettings>("/settings/ocr", {
        method: "PUT",
        body: JSON.stringify({
          base_url: form.base_url || null,
          api_key: form.api_key || null,
          clear_api_key: false,
          default_model: form.default_model,
          timeout_seconds: Number(form.timeout_seconds),
          max_concurrency: Number(form.max_concurrency),
        }),
      }),
    onSuccess: async () => {
      setForm((current) => ({ ...current, api_key: "" }));
      await client.invalidateQueries({ queryKey: ["ocr-settings"] });
    },
  });
  const test = useMutation({
    mutationFn: async () => {
      if (!testFile) throw new Error("请先选择 PDF 或图片");
      const body = new FormData();
      body.set("file", testFile);
      return api<OcrTestResult>("/settings/ocr/test", {
        method: "POST",
        body,
      });
    },
  });

  function submit(event: FormEvent) {
    event.preventDefault();
    save.mutate();
  }

  return (
    <>
      <PageHeader
        eyebrow="Administration"
        title="OCR 设置"
        description="配置 PaddleOCR 官方云 API、默认模型、超时与并发。令牌加密保存且不会从 API 返回。"
      />
      <div className="grid gap-5 xl:grid-cols-2">
        <Card className="p-6">
          <div className="flex items-center gap-3">
            <ScanText className="text-violet-500" />
            <div>
              <h2 className="font-semibold">PaddleOCR 官方云接口</h2>
              <p className="text-xs text-[var(--muted)]">
                当前配置来源：{data?.source === "database" ? "数据库" : "部署环境"}
              </p>
            </div>
          </div>
          <form className="mt-6 space-y-4" onSubmit={submit}>
            <label className="block text-sm">
              <span className="mb-1.5 block text-[var(--muted)]">
                Base URL（可选）
              </span>
              <Input
                type="url"
                value={form.base_url}
                onChange={(event) => setForm({ ...form, base_url: event.target.value })}
                placeholder="留空使用 PaddleOCR 官方默认服务"
              />
              <span className="mt-1 block text-xs text-[var(--muted)]">
                仅私有化网关或专属服务需要填写。
              </span>
            </label>
            <label className="block text-sm">
              <span className="mb-1.5 block text-[var(--muted)]">
                Access Token {data?.has_api_key ? "（留空表示保留）" : ""}
              </span>
              <Input
                type="password"
                autoComplete="new-password"
                value={form.api_key}
                onChange={(event) => setForm({ ...form, api_key: event.target.value })}
              />
            </label>
            <label className="block text-sm">
              <span className="mb-1.5 block text-[var(--muted)]">默认模型</span>
              <Select
                ariaLabel="默认 OCR 模型"
                value={form.default_model}
                onValueChange={(value) => setForm({ ...form, default_model: value })}
                options={[
                  { value: "PP-OCRv6", label: "PP-OCRv6" },
                  { value: "PaddleOCR-VL-1.6", label: "PaddleOCR-VL-1.6" },
                  { value: "PP-StructureV3", label: "PP-StructureV3" },
                ]}
              />
            </label>
            <div className="grid grid-cols-2 gap-3">
              <label className="block text-sm">
                <span className="mb-1.5 block text-[var(--muted)]">超时（秒）</span>
                <Input
                  type="number"
                  min="10"
                  max="1800"
                  value={form.timeout_seconds}
                  onChange={(event) =>
                    setForm({ ...form, timeout_seconds: event.target.value })
                  }
                />
              </label>
              <label className="block text-sm">
                <span className="mb-1.5 block text-[var(--muted)]">最大并发</span>
                <Input
                  type="number"
                  min="1"
                  max="20"
                  value={form.max_concurrency}
                  onChange={(event) =>
                    setForm({ ...form, max_concurrency: event.target.value })
                  }
                />
              </label>
            </div>
            <Button disabled={save.isPending} type="submit">
              {save.isPending ? "保存中…" : "保存设置"}
            </Button>
            {save.error && <p className="text-sm text-red-500">{save.error.message}</p>}
            {save.isSuccess && <p className="text-sm text-emerald-500">设置已保存</p>}
          </form>
        </Card>

        <Card className="p-6">
          <div className="flex items-center gap-3">
            <UploadCloud className="text-cyan-500" />
            <div>
              <h2 className="font-semibold">真实接口测试</h2>
              <p className="text-xs text-[var(--muted)]">
                上传不超过 20 MB 的 PDF、PNG、JPEG 或 TIFF；测试文件不会持久化。
              </p>
            </div>
          </div>
          <input
            className="mt-6 block w-full text-sm"
            type="file"
            accept=".pdf,.png,.jpg,.jpeg,.tif,.tiff"
            onChange={(event) => setTestFile(event.target.files?.[0] ?? null)}
          />
          <Button
            className="mt-4"
            disabled={!testFile || test.isPending}
            onClick={() => test.mutate()}
          >
            {test.isPending ? "等待云端任务…" : "执行 OCR 测试"}
          </Button>
          {test.error && <p className="mt-4 text-sm text-red-500">{test.error.message}</p>}
          {test.data && (
            <div className="mt-5 rounded-xl bg-[var(--surface-hover)] p-4 text-sm">
              <p>
                任务 {test.data.task_id} · {test.data.page_count} 页
              </p>
              <pre className="mt-3 max-h-64 overflow-auto whitespace-pre-wrap text-xs text-[var(--muted)]">
                {test.data.markdown_preview || "接口未返回可预览文本"}
              </pre>
            </div>
          )}
        </Card>
      </div>
    </>
  );
}
