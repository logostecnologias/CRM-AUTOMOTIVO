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
import AtendimentoPage from "@/pages/tenant/AtendimentoPage";
import DepartamentosPage from "@/pages/tenant/DepartamentosPage";
import UsersPage from "@/pages/tenant/UsersPage";
import SuperAdminDashboard from "@/pages/superadmin/SuperAdminDashboard";
import TenantsPage from "@/pages/superadmin/TenantsPage";
import "@/App.css";

const TENANT_ROLES = ["tenant_admin", "agent"];
const ADMIN_ONLY = ["tenant_admin"];

function App() {
  return (
    <AuthProvider>
      <BrowserRouter>
        <Routes>
          <Route path="/login" element={<LoginPage />} />

          {/* Tenant + Agent shell */}
          <Route
            path="/app"
            element={
              <ProtectedRoute roles={TENANT_ROLES}>
                <AppShell variant="tenant" />
              </ProtectedRoute>
            }
          >
            <Route index element={<TenantDashboard />} />
            <Route path="atendimento" element={<AtendimentoPage />} />
            <Route path="bots" element={<ProtectedRoute roles={ADMIN_ONLY}><BotsPage /></ProtectedRoute>} />
            <Route path="whatsapp" element={<ProtectedRoute roles={ADMIN_ONLY}><WhatsAppPage /></ProtectedRoute>} />
            <Route path="departments" element={<ProtectedRoute roles={ADMIN_ONLY}><DepartamentosPage /></ProtectedRoute>} />
            <Route path="users" element={<ProtectedRoute roles={ADMIN_ONLY}><UsersPage /></ProtectedRoute>} />
            <Route path="contacts" element={<ProtectedRoute roles={ADMIN_ONLY}><ContactsPage /></ProtectedRoute>} />
            <Route path="inbox" element={<ProtectedRoute roles={ADMIN_ONLY}><InboxPage /></ProtectedRoute>} />
            <Route path="settings" element={<SettingsPage />} />
          </Route>

          <Route
            path="/app/bots/:botId/flow/:flowId"
            element={
              <ProtectedRoute roles={ADMIN_ONLY}>
                <FlowEditorPage />
              </ProtectedRoute>
            }
          />

          <Route
            path="/admin"
            element={
              <ProtectedRoute roles={["super_admin"]}>
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
