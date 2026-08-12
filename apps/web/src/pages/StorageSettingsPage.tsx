import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Cloud, ShieldCheck } from "lucide-react";
import { useEffect, useState, type FormEvent } from "react";

import { PageHeader } from "../components/PageHeader";
import { Button } from "../components/ui/button";
import { Card } from "../components/ui/card";
import { Input } from "../components/ui/input";
import { Select } from "../components/ui/select";
import { api } from "../lib/api";
import type { StorageSettings, StorageTestResult } from "../lib/types";

export function StorageSettingsPage() {
  const queryClient = useQueryClient();
  const [form, setForm] = useState({
    backend: "oss" as StorageSettings["backend"],
    local_storage_path: "./data/storage",
    bucket: "",
    endpoint: "",
    internal_endpoint: "",
    use_internal_endpoint: false,
    region: "cn-shanghai",
    force_path_style: false,
    key_prefix: "",
    access_key: "",
    secret_key: "",
  });
  const { data } = useQuery({
    queryKey: ["storage-settings"],
    queryFn: () => api<StorageSettings>("/settings/storage"),
  });
  useEffect(() => {
    if (!data) return;
    setForm((current) => ({
      ...current,
      backend: data.backend,
      local_storage_path: data.local_storage_path,
      bucket: data.bucket,
      endpoint: data.endpoint ?? "",
      internal_endpoint: data.internal_endpoint ?? "",
      use_internal_endpoint: data.use_internal_endpoint,
      region: data.region,
      force_path_style: data.force_path_style,
      key_prefix: data.key_prefix,
    }));
  }, [data]);

  const save = useMutation({
    mutationFn: () =>
      api<StorageSettings>("/settings/storage", {
        method: "PUT",
        body: JSON.stringify({
          ...form,
          endpoint: form.endpoint || null,
          internal_endpoint: form.internal_endpoint || null,
          access_key: form.access_key || null,
          secret_key: form.secret_key || null,
          clear_access_key: false,
          clear_secret_key: false,
        }),
      }),
    onSuccess: async () => {
      setForm((current) => ({ ...current, access_key: "", secret_key: "" }));
      await queryClient.invalidateQueries({ queryKey: ["storage-settings"] });
    },
  });
  const test = useMutation({
    mutationFn: () =>
      api<StorageTestResult>("/settings/storage/test", {
        method: "POST",
      }),
  });
  const remote = form.backend !== "local";

  function submit(event: FormEvent) {
    event.preventDefault();
    save.mutate();
  }

  return (
    <>
      <PageHeader
        eyebrow="Administration"
        title="对象存储"
        description="配置 S3、阿里云 OSS 或腾讯云 COS。访问密钥使用 AES-GCM 加密保存，API 永不回传明文。"
      />
      <div className="grid gap-5 xl:grid-cols-[minmax(0,1.35fr)_minmax(320px,.65fr)]">
        <Card className="p-6">
          <div className="flex items-center gap-3">
            <Cloud className="text-violet-500" />
            <div>
              <h2 className="font-semibold">存储连接</h2>
              <p className="text-xs text-[var(--muted)]">
                当前配置来源：{data?.source === "database" ? "数据库" : "部署环境"}
              </p>
            </div>
          </div>
          <form className="mt-6 space-y-4" onSubmit={submit}>
            <label className="block text-sm">
              <span className="mb-1.5 block text-[var(--muted)]">存储类型</span>
              <Select
                ariaLabel="存储类型"
                value={form.backend}
                onValueChange={(value) =>
                  setForm({
                    ...form,
                    backend: value as StorageSettings["backend"],
                    force_path_style:
                      value === "s3" ? form.force_path_style : false,
                  })
                }
                options={[
                  { value: "oss", label: "阿里云 OSS" },
                  { value: "cos", label: "腾讯云 COS" },
                  { value: "s3", label: "S3-compatible / MinIO" },
                  { value: "local", label: "本地文件（仅开发）" },
                ]}
              />
            </label>
            {!remote ? (
              <label className="block text-sm">
                <span className="mb-1.5 block text-[var(--muted)]">本地目录</span>
                <Input
                  value={form.local_storage_path}
                  onChange={(event) =>
                    setForm({ ...form, local_storage_path: event.target.value })
                  }
                  required
                />
              </label>
            ) : (
              <>
                <div className="grid gap-4 md:grid-cols-2">
                  <label className="block text-sm">
                    <span className="mb-1.5 block text-[var(--muted)]">Bucket</span>
                    <Input
                      value={form.bucket}
                      onChange={(event) => setForm({ ...form, bucket: event.target.value })}
                      required
                    />
                  </label>
                  <label className="block text-sm">
                    <span className="mb-1.5 block text-[var(--muted)]">Region</span>
                    <Input
                      value={form.region}
                      onChange={(event) => setForm({ ...form, region: event.target.value })}
                      required
                    />
                  </label>
                </div>
                <label className="block text-sm">
                  <span className="mb-1.5 block text-[var(--muted)]">公网 Endpoint</span>
                  <Input
                    type="url"
                    value={form.endpoint}
                    onChange={(event) => setForm({ ...form, endpoint: event.target.value })}
                    placeholder="https://oss-cn-shanghai.aliyuncs.com"
                    required
                  />
                </label>
                <label className="block text-sm">
                  <span className="mb-1.5 block text-[var(--muted)]">
                    内网 Endpoint（可选）
                  </span>
                  <Input
                    type="url"
                    value={form.internal_endpoint}
                    onChange={(event) =>
                      setForm({ ...form, internal_endpoint: event.target.value })
                    }
                    placeholder="https://oss-cn-shanghai-internal.aliyuncs.com"
                  />
                </label>
                <div className="grid gap-4 md:grid-cols-2">
                  <label className="block text-sm">
                    <span className="mb-1.5 block text-[var(--muted)]">
                      Access Key {data?.has_access_key ? "（留空保留）" : ""}
                    </span>
                    <Input
                      type="password"
                      autoComplete="new-password"
                      value={form.access_key}
                      onChange={(event) =>
                        setForm({ ...form, access_key: event.target.value })
                      }
                    />
                  </label>
                  <label className="block text-sm">
                    <span className="mb-1.5 block text-[var(--muted)]">
                      Secret Key {data?.has_secret_key ? "（留空保留）" : ""}
                    </span>
                    <Input
                      type="password"
                      autoComplete="new-password"
                      value={form.secret_key}
                      onChange={(event) =>
                        setForm({ ...form, secret_key: event.target.value })
                      }
                    />
                  </label>
                </div>
                <label className="block text-sm">
                  <span className="mb-1.5 block text-[var(--muted)]">对象键前缀</span>
                  <Input
                    value={form.key_prefix}
                    onChange={(event) =>
                      setForm({ ...form, key_prefix: event.target.value })
                    }
                    placeholder="SynapseKB"
                  />
                </label>
                <div className="flex flex-wrap gap-5 text-sm text-[var(--muted)]">
                  <label className="flex items-center gap-2">
                    <input
                      type="checkbox"
                      checked={form.use_internal_endpoint}
                      disabled={!form.internal_endpoint}
                      onChange={(event) =>
                        setForm({
                          ...form,
                          use_internal_endpoint: event.target.checked,
                        })
                      }
                    />
                    服务端优先走内网
                  </label>
                  {form.backend === "s3" && (
                    <label className="flex items-center gap-2">
                      <input
                        type="checkbox"
                        checked={form.force_path_style}
                        onChange={(event) =>
                          setForm({ ...form, force_path_style: event.target.checked })
                        }
                      />
                      Path-style 地址
                    </label>
                  )}
                </div>
              </>
            )}
            <div className="flex items-center gap-3">
              <Button type="submit" disabled={save.isPending}>
                {save.isPending ? "保存中…" : "保存设置"}
              </Button>
              <Button
                type="button"
                variant="secondary"
                disabled={test.isPending || save.isPending}
                onClick={() => test.mutate()}
              >
                {test.isPending ? "测试中…" : "测试已保存配置"}
              </Button>
            </div>
            {save.error && <p className="text-sm text-red-500">{save.error.message}</p>}
            {save.isSuccess && <p className="text-sm text-emerald-500">设置已保存</p>}
          </form>
        </Card>
        <Card className="p-6">
          <ShieldCheck className="text-cyan-500" />
          <h2 className="mt-4 font-semibold">安全与路径隔离</h2>
          <p className="mt-2 text-sm leading-6 text-[var(--muted)]">
            连通性测试会在配置前缀下写入一个随机小文件，校验读取后立即删除。公网
            Endpoint 专用于浏览器预签名；开启内网模式后，Worker 的读写走内网地址。
          </p>
          {test.error && <p className="mt-5 text-sm text-red-500">{test.error.message}</p>}
          {test.data && (
            <div className="mt-5 rounded-xl bg-[var(--surface-hover)] p-4 text-sm">
              <p className="font-medium text-emerald-500">连接成功</p>
              <p className="mt-2 text-[var(--muted)]">
                {test.data.backend.toUpperCase()} · {test.data.bucket || "本地目录"} ·{" "}
                {test.data.latency_ms} ms
              </p>
              <p className="mt-1 text-xs text-[var(--muted)]">
                浏览器直传：
                {test.data.presigned_upload_supported ? "支持" : "仅限 API 中转"}
              </p>
            </div>
          )}
        </Card>
      </div>
    </>
  );
}
