import { lazy, Suspense } from "react";
import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";
import { AuthProvider, useAuth } from "./lib/auth";
import { ToastProvider } from "./components/ui/Toast";
import { AppLayout } from "./components/layout/AppLayout";
import { EmptyState, Spinner } from "./components/ui/primitives";
import Login from "./pages/Login";

const Dashboard = lazy(() => import("./pages/Dashboard"));
const Products = lazy(() => import("./pages/Products"));
const ProductDetail = lazy(() => import("./pages/ProductDetail"));
const Customers = lazy(() => import("./pages/Customers"));
const Warranties = lazy(() => import("./pages/Warranties"));
const ServiceRequests = lazy(() => import("./pages/ServiceRequests"));
const ServiceRequestDetail = lazy(() => import("./pages/ServiceRequestDetail"));
const RepairHistory = lazy(() => import("./pages/RepairHistory"));
const Inventory = lazy(() => import("./pages/Inventory"));
const Predictions = lazy(() => import("./pages/Predictions"));
const Analytics = lazy(() => import("./pages/Analytics"));
const ModelPerformance = lazy(() => import("./pages/ModelPerformance"));
const SettingsPage = lazy(() => import("./pages/Settings"));

function Shell() {
  const { user, loading } = useAuth();
  if (loading) return <Spinner label="Restoring session…" />;
  if (!user) return <Login />;
  return (
    <Suspense fallback={<Spinner />}>
      <Routes>
        <Route element={<AppLayout />}>
          <Route index element={<Dashboard />} />
          <Route path="products" element={<Products />} />
          <Route path="products/:id" element={<ProductDetail />} />
          <Route path="customers" element={<Customers />} />
          <Route path="warranties" element={<Warranties />} />
          <Route path="service-requests" element={<ServiceRequests />} />
          <Route path="service-requests/:id" element={<ServiceRequestDetail />} />
          <Route path="repairs" element={<RepairHistory />} />
          <Route path="inventory" element={<Inventory />} />
          <Route path="predictions" element={<Predictions />} />
          <Route path="analytics" element={<Analytics />} />
          <Route path="models" element={<ModelPerformance />} />
          <Route path="settings" element={<SettingsPage />} />
          <Route path="login" element={<Navigate to="/" replace />} />
          <Route path="*" element={<EmptyState title="Page not found" hint="Use the navigation on the left." />} />
        </Route>
      </Routes>
    </Suspense>
  );
}

export default function App() {
  return (
    <BrowserRouter future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
      <AuthProvider>
        <ToastProvider>
          <Shell />
        </ToastProvider>
      </AuthProvider>
    </BrowserRouter>
  );
}
