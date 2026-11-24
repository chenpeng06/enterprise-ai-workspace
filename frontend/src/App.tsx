import { BrowserRouter, Route, Routes } from "react-router-dom";

import { AppShell } from "@/components/AppShell";
import { AdminPage } from "@/pages/AdminPage";
import { ChatPage } from "@/pages/ChatPage";
import { HomePage } from "@/pages/HomePage";
import { NotFoundPage } from "@/pages/NotFoundPage";

export function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route element={<AppShell />}>
          <Route index element={<HomePage />} />
          <Route path="chat" element={<ChatPage />} />
          <Route path="admin" element={<AdminPage />} />
          <Route path="*" element={<NotFoundPage />} />
        </Route>
      </Routes>
    </BrowserRouter>
  );
}
