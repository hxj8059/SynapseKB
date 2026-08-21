import { lazy, Suspense, useEffect } from "react";
import { Navigate, Outlet, Route, Routes } from "react-router-dom";

import { AppShell } from "./components/AppShell";
import { bootstrapSession } from "./lib/api";
import { useAuthStore } from "./stores/auth";
import { usePreferences } from "./stores/preferences";

const AgentsPage = lazy(() =>
  import("./pages/AgentsPage").then((module) => ({ default: module.AgentsPage })),
);
const ChatPage = lazy(() =>
  import("./pages/ChatPage").then((module) => ({ default: module.ChatPage })),
);
const HomePage = lazy(() =>
  import("./pages/HomePage").then((module) => ({ default: module.HomePage })),
);
const DocumentPreviewPage = lazy(() =>
  import("./pages/DocumentPreviewPage").then((module) => ({
    default: module.DocumentPreviewPage,
  })),
);
const KnowledgeBaseDetailPage = lazy(() =>
  import("./pages/KnowledgeBaseDetailPage").then((module) => ({
    default: module.KnowledgeBaseDetailPage,
  })),
);
const KnowledgeBasesPage = lazy(() =>
  import("./pages/KnowledgeBasesPage").then((module) => ({
    default: module.KnowledgeBasesPage,
  })),
);
const LoginPage = lazy(() =>
  import("./pages/LoginPage").then((module) => ({ default: module.LoginPage })),
);
const ModelsPage = lazy(() =>
  import("./pages/ModelsPage").then((module) => ({ default: module.ModelsPage })),
);
const OcrSettingsPage = lazy(() =>
  import("./pages/OcrSettingsPage").then((module) => ({
    default: module.OcrSettingsPage,
  })),
);
const SearchPage = lazy(() =>
  import("./pages/SearchPage").then((module) => ({ default: module.SearchPage })),
);
const StorageSettingsPage = lazy(() =>
  import("./pages/StorageSettingsPage").then((module) => ({
    default: module.StorageSettingsPage,
  })),
);
const SkillsPage = lazy(() =>
  import("./pages/SkillsPage").then((module) => ({ default: module.SkillsPage })),
);
const TasksPage = lazy(() =>
  import("./pages/TasksPage").then((module) => ({ default: module.TasksPage })),
);
const TokensPage = lazy(() =>
  import("./pages/TokensPage").then((module) => ({ default: module.TokensPage })),
);
const UsersPage = lazy(() =>
  import("./pages/UsersPage").then((module) => ({ default: module.UsersPage })),
);
const WikiPage = lazy(() =>
  import("./pages/WikiPage").then((module) => ({ default: module.WikiPage })),
);
const WikiGraphPage = lazy(() =>
  import("./pages/WikiGraphPage").then((module) => ({
    default: module.WikiGraphPage,
  })),
);

function Protected() {
  const { user, ready } = useAuthStore();
  if (!ready) {
    return <div className="min-h-screen bg-[var(--canvas)]" aria-label="正在加载" />;
  }
  return user ? <Outlet /> : <Navigate to="/login" replace />;
}

function AdminOnly() {
  const user = useAuthStore((state) => state.user);
  return user?.role === "admin" ? <Outlet /> : <Navigate to="/" replace />;
}

export default function App() {
  const theme = usePreferences((state) => state.theme);
  useEffect(() => {
    document.documentElement.classList.toggle("dark", theme === "dark");
  }, [theme]);
  useEffect(() => {
    void bootstrapSession();
  }, []);

  return (
    <Suspense fallback={<div className="min-h-screen bg-[var(--canvas)]" />}>
      <Routes>
        <Route path="/login" element={<LoginPage />} />
        <Route element={<Protected />}>
          <Route element={<AppShell />}>
            <Route index element={<HomePage />} />
            <Route path="knowledge-bases" element={<KnowledgeBasesPage />} />
            <Route path="knowledge-bases/:id" element={<KnowledgeBaseDetailPage />} />
            <Route path="documents/:id" element={<DocumentPreviewPage />} />
            <Route path="search" element={<SearchPage />} />
            <Route path="chat" element={<ChatPage />} />
            <Route path="agents" element={<AgentsPage />} />
            <Route path="wiki" element={<WikiPage />} />
            <Route path="wiki/graph" element={<WikiGraphPage />} />
            <Route path="tokens" element={<TokensPage />} />
            <Route path="skills" element={<SkillsPage />} />
            <Route element={<AdminOnly />}>
              <Route path="admin/models" element={<ModelsPage />} />
              <Route path="admin/ocr" element={<OcrSettingsPage />} />
              <Route path="admin/storage" element={<StorageSettingsPage />} />
              <Route path="admin/users" element={<UsersPage />} />
              <Route path="admin/tasks" element={<TasksPage />} />
            </Route>
          </Route>
        </Route>
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </Suspense>
  );
}
