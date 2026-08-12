import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Plus } from "lucide-react";
import { useState, type FormEvent } from "react";

import { PageHeader } from "../components/PageHeader";
import { Button } from "../components/ui/button";
import { Card } from "../components/ui/card";
import { Input } from "../components/ui/input";
import { Select } from "../components/ui/select";
import { api } from "../lib/api";
import type { User } from "../lib/types";

export function UsersPage() {
  const client = useQueryClient();
  const [creating, setCreating] = useState(false);
  const [form, setForm] = useState({
    email: "",
    display_name: "",
    password: "",
    role: "user",
    timezone: "Asia/Shanghai",
  });
  const { data = [] } = useQuery({
    queryKey: ["users"],
    queryFn: () => api<User[]>("/users"),
  });
  const create = useMutation({
    mutationFn: () =>
      api<User>("/users", { method: "POST", body: JSON.stringify(form) }),
    onSuccess: () => {
      client.invalidateQueries({ queryKey: ["users"] });
      setCreating(false);
      setForm({ ...form, email: "", display_name: "", password: "" });
    },
  });
  const update = useMutation({
    mutationFn: ({
      id,
      patch,
    }: {
      id: string;
      patch: { role?: string; is_active?: boolean };
    }) =>
      api<User>(`/users/${id}`, {
        method: "PATCH",
        body: JSON.stringify(patch),
      }),
    onSuccess: () => client.invalidateQueries({ queryKey: ["users"] }),
  });

  function submit(event: FormEvent) {
    event.preventDefault();
    create.mutate();
  }

  return (
    <>
      <PageHeader
        eyebrow="Administration"
        title="用户管理"
        description="管理员和普通用户两类角色；所有资源权限均由服务端执行。"
        actions={
          <Button onClick={() => setCreating((value) => !value)}>
            <Plus size={15} />
            新建用户
          </Button>
        }
      />
      {creating && (
        <Card className="mb-5 p-5">
          <form className="grid gap-3 md:grid-cols-3" onSubmit={submit}>
            <Input
              type="email"
              placeholder="邮箱"
              value={form.email}
              onChange={(event) => setForm({ ...form, email: event.target.value })}
              required
            />
            <Input
              placeholder="显示名称"
              value={form.display_name}
              onChange={(event) =>
                setForm({ ...form, display_name: event.target.value })
              }
              required
            />
            <Input
              type="password"
              placeholder="初始密码（至少 12 位）"
              value={form.password}
              onChange={(event) => setForm({ ...form, password: event.target.value })}
              required
              minLength={12}
            />
            <Select
              ariaLabel="用户角色"
              value={form.role}
              onValueChange={(value) => setForm({ ...form, role: value })}
              options={[
                { value: "user", label: "普通用户" },
                { value: "admin", label: "管理员" },
              ]}
            />
            <Button type="submit" disabled={create.isPending}>
              创建
            </Button>
          </form>
          {create.error && <p className="mt-3 text-sm text-red-500">{create.error.message}</p>}
        </Card>
      )}
      <Card className="overflow-hidden">
        <div className="divide-y divide-[var(--border)]">
          {data.map((user) => (
            <div
              key={user.id}
              className="grid gap-3 px-5 py-4 sm:grid-cols-[1fr_1fr_150px_110px] sm:items-center"
            >
              <div className="font-medium">{user.display_name}</div>
              <div className="text-sm text-[var(--muted)]">{user.email}</div>
              <Select
                ariaLabel={`${user.display_name}角色`}
                size="sm"
                value={user.role}
                onValueChange={(value) => {
                  if (window.confirm("确认修改该用户角色？")) {
                    update.mutate({
                      id: user.id,
                      patch: { role: value },
                    });
                  }
                }}
                options={[
                  { value: "user", label: "普通用户" },
                  { value: "admin", label: "管理员" },
                ]}
              />
              <Button
                variant="secondary"
                size="sm"
                onClick={() => {
                  if (
                    window.confirm(
                      user.is_active ? "确认停用该用户？" : "确认重新启用该用户？",
                    )
                  ) {
                    update.mutate({
                      id: user.id,
                      patch: { is_active: !user.is_active },
                    });
                  }
                }}
              >
                {user.is_active ? "停用" : "启用"}
              </Button>
            </div>
          ))}
        </div>
      </Card>
    </>
  );
}
