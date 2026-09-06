import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Check, Plus, ShieldCheck, X } from "lucide-react";
import { useState } from "react";
import { PageHeader } from "../components/PageHeader";
import { Button } from "../components/ui/button";
import { Card } from "../components/ui/card";
import { Input } from "../components/ui/input";
import { MultiSelect, Select } from "../components/ui/select";
import { api } from "../lib/api";
import type { User } from "../lib/types";
import { useAuthStore } from "../stores/auth";

type Approval = { id: string; user_id: string; requested_by_id: string; status: string; created_at: string; review_note: string | null };
type Membership = { id: string; name: string; visibility: string; member_ids: string[] };
const roles = [{ value: "user", label: "普通用户" }, { value: "admin", label: "管理员" }, { value: "super_admin", label: "超级管理员" }];

function PermissionRow({ kb, users }: { kb: Membership; users: User[] }) {
  const client = useQueryClient();
  const [draft, setDraft] = useState(kb);
  const save = useMutation({
    mutationFn: () => api(`/users/knowledge-base-permissions/${kb.id}`, { method: "PUT", body: JSON.stringify({ visibility: draft.visibility, member_ids: draft.member_ids }) }),
    onSuccess: () => { client.invalidateQueries({ queryKey: ["knowledge-base-permissions"] }); client.invalidateQueries({ queryKey: ["knowledge-bases"] }); },
  });
  return <div className="border-t border-[var(--border)] px-5 py-4">
    <div className="grid items-center gap-3 lg:grid-cols-[1fr_180px_2fr_auto]">
      <span className="font-medium">{kb.name}</span>
      <Select ariaLabel={`${kb.name}可见范围`} value={draft.visibility} onValueChange={(visibility) => setDraft({ ...draft, visibility })} options={[{ value: "users", label: "指定成员" }, { value: "all", label: "所有用户" }]} />
      <MultiSelect ariaLabel={`${kb.name}成员`} value={draft.member_ids} onValueChange={(member_ids) => setDraft({ ...draft, member_ids })} disabled={draft.visibility === "all"} placeholder="选择可访问的成员"
        options={users.filter((u) => u.is_active && u.approval_status !== "pending" && u.approval_status !== "rejected").map((u) => ({ value: u.id, label: u.display_name, description: u.email }))} />
      <Button variant="secondary" disabled={save.isPending} onClick={() => save.mutate()}>{save.isPending ? "保存中…" : "保存权限"}</Button>
    </div>
    {draft.visibility === "all" && <p className="mt-2 text-xs text-[var(--muted)]">所有已审批用户均可访问；部门资料请选择“指定成员”。</p>}
    {save.error && <p role="alert" className="mt-2 text-sm text-red-500">{save.error.message}</p>}
    {save.isSuccess && <p role="status" className="mt-2 text-sm text-emerald-600">权限已保存</p>}
  </div>;
}

export function UsersPage() {
  const currentUser = useAuthStore((state) => state.user);
  const superAdmin = currentUser?.role === "super_admin";
  const client = useQueryClient();
  const [tab, setTab] = useState("accounts");
  const [creating, setCreating] = useState(false);
  const [notice, setNotice] = useState("");
  const [form, setForm] = useState({ email: "", display_name: "", password: "", role: "user", timezone: "Asia/Shanghai" });
  const { data: users = [], error } = useQuery({ queryKey: ["users"], queryFn: () => api<User[]>("/users") });
  const approvals = useQuery({ queryKey: ["user-approvals"], queryFn: () => api<Approval[]>("/users/approvals"), refetchInterval: 30000 });
  const memberships = useQuery({ queryKey: ["knowledge-base-permissions"], queryFn: () => api<Membership[]>("/users/knowledge-base-permissions"), enabled: tab === "permissions" });
  const refreshUsers = () => { client.invalidateQueries({ queryKey: ["users"] }); client.invalidateQueries({ queryKey: ["user-approvals"] }); };
  const create = useMutation({
    mutationFn: () => api<User>("/users", { method: "POST", body: JSON.stringify(form) }),
    onSuccess: (created) => { refreshUsers(); setCreating(false); setForm({ ...form, email: "", display_name: "", password: "" }); setNotice(created.approval_status === "pending" ? "申请已提交，超级管理员批准后账号才能登录。" : "账号已创建。"); },
  });
  const update = useMutation({
    mutationFn: ({ id, patch }: { id: string; patch: { role?: string; is_active?: boolean } }) => api<User>(`/users/${id}`, { method: "PATCH", body: JSON.stringify(patch) }), onSuccess: refreshUsers,
  });
  const review = useMutation({
    mutationFn: ({ id, decision }: { id: string; decision: string }) => api(`/users/approvals/${id}/review`, { method: "POST", body: JSON.stringify({ decision }) }), onSuccess: refreshUsers,
  });
  const pending = approvals.data?.filter((a) => a.status === "pending").length ?? 0;
  const nameOf = (id: string) => users.find((u) => u.id === id)?.display_name ?? id;
  return <>
    <PageHeader eyebrow="Administration" title="账号管理" description="管理员提交新增账号申请，超级管理员审批；集中管理各知识库的可见成员。"
      actions={<Button onClick={() => setCreating(!creating)}><Plus size={15} />{superAdmin ? "新建用户" : "申请添加用户"}</Button>} />
    <div className="mb-5 flex flex-wrap gap-2" role="tablist" aria-label="账号管理">
      {[{ id: "accounts", label: "账号" }, { id: "approvals", label: `账号审批${pending ? ` · ${pending}` : ""}` }, { id: "permissions", label: "知识库权限" }].map((item) =>
        <Button key={item.id} role="tab" aria-selected={tab === item.id} variant={tab === item.id ? "primary" : "secondary"} onClick={() => setTab(item.id)}>{item.label}</Button>)}
    </div>
    {notice && <p role="status" className="mb-4 text-sm text-emerald-600">{notice}</p>}
    {[error, update.error, review.error, approvals.error, memberships.error].filter(Boolean).map((e, i) => <p role="alert" key={i} className="mb-4 text-sm text-red-500">{e?.message}</p>)}
    {creating && <Card className="mb-5 p-5"><form className="grid gap-3 md:grid-cols-3" onSubmit={(event) => { event.preventDefault(); create.mutate(); }}>
      <Input aria-label="邮箱" type="email" placeholder="邮箱" value={form.email} onChange={(event) => setForm({ ...form, email: event.target.value })} required />
      <Input aria-label="显示名称" placeholder="显示名称" value={form.display_name} onChange={(event) => setForm({ ...form, display_name: event.target.value })} required />
      <Input aria-label="初始密码" type="password" autoComplete="new-password" placeholder="初始密码（至少 12 位）" value={form.password} onChange={(event) => setForm({ ...form, password: event.target.value })} required minLength={12} />
      {superAdmin && <Select ariaLabel="用户角色" value={form.role} onValueChange={(role) => setForm({ ...form, role })} options={roles} />}
      <Button type="submit" disabled={create.isPending}>{superAdmin ? "创建" : "提交审批"}</Button>
    </form>{create.error && <p role="alert" className="mt-3 text-sm text-red-500">{create.error.message}</p>}</Card>}
    {tab === "accounts" && <Card className="divide-y divide-[var(--border)] overflow-hidden">{users.map((user) => {
      const approved = !user.approval_status || user.approval_status === "approved";
      return <div key={user.id} className="grid items-center gap-3 px-5 py-4 sm:grid-cols-[1fr_1fr_160px_110px]">
        <div><p className="font-medium">{user.display_name}</p><p className="mt-1 text-xs text-[var(--muted)]">{!approved ? user.approval_status === "pending" ? "待审批" : "已拒绝" : user.is_active ? "已启用" : "已停用"}</p></div>
        <span className="break-all text-sm text-[var(--muted)]">{user.email}</span>
        <Select ariaLabel={`${user.display_name}角色`} value={user.role} options={roles} disabled={!superAdmin || !approved || update.isPending}
          onValueChange={(role) => { if (window.confirm("确认修改该用户角色？")) update.mutate({ id: user.id, patch: { role } }); }} />
        <Button variant="secondary" size="sm" disabled={!approved || update.isPending || (!superAdmin && user.role !== "user") || user.id === currentUser?.id}
          onClick={() => { if (window.confirm(user.is_active ? "确认停用该用户？" : "确认启用该用户？")) update.mutate({ id: user.id, patch: { is_active: !user.is_active } }); }}>{user.is_active ? "停用" : "启用"}</Button>
      </div>;
    })}</Card>}
    {tab === "approvals" && <Card className="divide-y divide-[var(--border)] overflow-hidden">
      <p className="p-5 text-sm text-[var(--muted)]"><ShieldCheck className="mr-2 inline" size={16} />{superAdmin ? "待审批账号无法登录或创建 API Key。" : "这里显示你提交的申请，审批由超级管理员完成。"}</p>
      {approvals.data?.length === 0 && <p className="p-5 text-sm text-[var(--muted)]">暂无审批请求</p>}
      {approvals.data?.map((a) => <div key={a.id} className="flex flex-wrap items-center justify-between gap-3 p-5">
        <div><p className="font-medium">{nameOf(a.user_id)}</p><p className="mt-1 text-xs text-[var(--muted)]">申请人：{nameOf(a.requested_by_id)} · {new Date(a.created_at).toLocaleString()}</p></div>
        {a.status === "pending" && superAdmin ? <div className="flex gap-2">
          <Button disabled={review.isPending} onClick={() => review.mutate({ id: a.id, decision: "approved" })}><Check size={15} />批准</Button>
          <Button variant="secondary" disabled={review.isPending} onClick={() => review.mutate({ id: a.id, decision: "rejected" })}><X size={15} />拒绝</Button>
        </div> : <span className="text-sm text-[var(--muted)]">{a.status === "pending" ? "待审批" : a.status === "approved" ? "已批准" : "已拒绝"}</span>}
      </div>)}
    </Card>}
    {tab === "permissions" && <Card className="overflow-hidden"><p className="p-5 text-sm text-[var(--muted)]">管理员及超级管理员保留全库管理权限。普通用户仅能访问开放给全员或已加入的知识库；App、Agent 和 MCP 使用同一权限规则。</p>
      {memberships.data?.map((kb) => <PermissionRow key={`${kb.id}:${kb.visibility}:${kb.member_ids.join(",")}`} kb={kb} users={users} />)}
    </Card>}
  </>;
}
