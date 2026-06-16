import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom'
import Layout from './components/Layout'
import Calibration from './pages/Calibration'
import ChangePassword from './pages/ChangePassword'
import Dashboard from './pages/Dashboard'
import Jobs from './pages/Jobs'
import Login from './pages/Login'
import News from './pages/News'
import Models from './pages/Models'
import Simulations from './pages/Simulations'
import Snapshots from './pages/Snapshots'
import { useAuth } from './hooks/useAuth'

function RequireAuth({ children }: { children: React.ReactNode }) {
  const { data, isLoading, isError } = useAuth()

  if (isLoading) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-gray-950 text-gray-400">
        Cargando…
      </div>
    )
  }
  if (isError) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-gray-950 text-red-400">
        No se puede conectar con el servidor.
      </div>
    )
  }
  if (!data?.authenticated) {
    return <Navigate to="/login" replace />
  }
  if (data.must_change_password) {
    return <Navigate to="/change-password" replace />
  }
  return <>{children}</>
}

export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/login" element={<Login />} />
        <Route path="/change-password" element={<ChangePassword />} />
        <Route
          element={
            <RequireAuth>
              <Layout />
            </RequireAuth>
          }
        >
          <Route index element={<Dashboard />} />
          <Route path="models" element={<Models />} />
          <Route path="simulations" element={<Simulations />} />
          <Route path="snapshots" element={<Snapshots />} />
          <Route path="calibration" element={<Calibration />} />
          <Route path="jobs" element={<Jobs />} />
          <Route path="news" element={<News />} />
        </Route>
      </Routes>
    </BrowserRouter>
  )
}
