import { BrowserRouter, Route, Routes } from 'react-router-dom'
import Layout from './components/Layout'
import Calibration from './pages/Calibration'
import Dashboard from './pages/Dashboard'
import Jobs from './pages/Jobs'
import Models from './pages/Models'
import Simulations from './pages/Simulations'
import Snapshots from './pages/Snapshots'

export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route element={<Layout />}>
          <Route index element={<Dashboard />} />
          <Route path="models" element={<Models />} />
          <Route path="simulations" element={<Simulations />} />
          <Route path="snapshots" element={<Snapshots />} />
          <Route path="calibration" element={<Calibration />} />
          <Route path="jobs" element={<Jobs />} />
        </Route>
      </Routes>
    </BrowserRouter>
  )
}
