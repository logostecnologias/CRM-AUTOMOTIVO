import { BrowserRouter, Routes, Route, Navigate } from "react-router-dom";
import { AuthProvider } from "@/context/AuthContext";
import ProtectedRoute from "@/components/ProtectedRoute";
import AppShell from "@/components/AppShell";
import LoginPage from "@/pages/Login";
import TenantDashboard from "@/pages/tenant/TenantDashboard";
import BotsPage from "@/pages/tenant/BotsPage";
import FlowEditorPage from "@/pages/tenant/FlowEditorPage";
import ContactsPage from "@/pages/tenant/ContactsPage";
import InboxPage from "@/pages/tenant/InboxPage";
import WhatsAppPage from "@/pages/tenant/WhatsAppPage";
import SettingsPage from "@/pages/tenant/SettingsPage";
import SuperAdminDashboard from "@/pages/superadmin/SuperAdminDashboard";
import TenantsPage from "@/pages/superadmin/TenantsPage";
import "@/App.css";

function App() {
  return (
    <AuthProvider>
      <BrowserRouter>
        <Routes>
          <Route path="/login" element={<LoginPage />} />

          {/* Tenant admin routes */}
          <Route
            path="/app"
            element={
              <ProtectedRoute role="tenant_admin">
                <AppShell variant="tenant" />
              </ProtectedRoute>
            }
          >
            <Route index element={<TenantDashboard />} />
            <Route path="bots" element={<BotsPage />} />
            <Route path="whatsapp" element={<WhatsAppPage />} />
            <Route path="contacts" element={<ContactsPage />} />
            <Route path="inbox" element={<InboxPage />} />
            <Route path="settings" element={<SettingsPage />} />
          </Route>

          {/* Flow editor is fullscreen, outside the shell */}
          <Route
            path="/app/bots/:botId/flow/:flowId"
            element={
              <ProtectedRoute role="tenant_admin">
                <FlowEditorPage />
              </ProtectedRoute>
            }
          />

          {/* Super admin routes */}
          <Route
            path="/admin"
            element={
              <ProtectedRoute role="super_admin">
                <AppShell variant="admin" />
              </ProtectedRoute>
            }
          >
            <Route index element={<SuperAdminDashboard />} />
            <Route path="tenants" element={<TenantsPage />} />
          </Route>

          <Route path="/" element={<Navigate to="/login" replace />} />
          <Route path="*" element={<Navigate to="/login" replace />} />
        </Routes>
      </BrowserRouter>
    </AuthProvider>
  );
}

export default App;
