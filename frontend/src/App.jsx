import { Route, Routes } from 'react-router'
import AppShell from './components/AppShell.jsx'
import AgentsPage from './pages/AgentsPage.jsx'
import CreateJobPage from './pages/CreateJobPage.jsx'
import HomePage from './pages/HomePage.jsx'
import JobBoardPage from './pages/JobBoardPage.jsx'
import JobPage from './pages/JobPage.jsx'
import NotFoundPage from './pages/NotFoundPage.jsx'
import OpsPage from './pages/OpsPage.jsx'
import ReceiptPage from './pages/ReceiptPage.jsx'

export default function App() {
  return (
    <Routes>
      <Route element={<AppShell />}>
        <Route index element={<HomePage />} />
        <Route path="jobs" element={<JobBoardPage />} />
        <Route path="new" element={<CreateJobPage />} />
        <Route path="jobs/:jobId" element={<JobPage />} />
        <Route path="jobs/:jobId/receipt" element={<ReceiptPage />} />
        <Route path="agents" element={<AgentsPage />} />
        <Route path="ops" element={<OpsPage />} />
        <Route path="*" element={<NotFoundPage />} />
      </Route>
    </Routes>
  )
}
