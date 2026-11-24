import { BrowserRouter, Route, Routes } from "react-router-dom";

import { AppShell } from "@/components/AppShell";
import { AuthProvider, RequireAuth, RequirePermission } from "@/features/auth/AuthContext";
import { AdminAgentsPage } from "@/pages/AdminAgentsPage";
import { AdminDocumentsPage } from "@/pages/AdminDocumentsPage";
import { AdminPage } from "@/pages/AdminPage";
import { AdminSettingsPage } from "@/pages/AdminSettingsPage";
import { AdminUsersPage } from "@/pages/AdminUsersPage";
import { ChatPage } from "@/pages/ChatPage";
import { HomePage } from "@/pages/HomePage";
import { LoginPage } from "@/pages/LoginPage";
import { NotFoundPage } from "@/pages/NotFoundPage";

export function App() {
  return (
    <BrowserRouter>
      <AuthProvider>
        <Routes>
          <Route element={<AppShell />}>
            <Route index element={<HomePage />} />
            <Route path="login" element={<LoginPage />} />
            <Route element={<RequireAuth />}>
              <Route path="chat" element={<ChatPage />} />
              <Route element={<RequirePermission permission="metrics.read" />}>
                <Route path="admin" element={<AdminPage />} />
              </Route>
              <Route element={<RequirePermission permission="users.read" />}>
                <Route path="admin/users" element={<AdminUsersPage />} />
                <Route path="admin/settings" element={<AdminSettingsPage />} />
              </Route>
              <Route element={<RequirePermission permission="agents.manage" />}>
                <Route path="admin/agents" element={<AdminAgentsPage />} />
              </Route>
              <Route element={<RequirePermission permission="docs.upload" />}>
                <Route path="admin/documents" element={<AdminDocumentsPage />} />
              </Route>
            </Route>
            <Route path="*" element={<NotFoundPage />} />
          </Route>
        </Routes>
      </AuthProvider>
    </BrowserRouter>
  );
}
