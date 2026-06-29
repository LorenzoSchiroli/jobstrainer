import { Routes, Route, Navigate } from 'react-router-dom'
import Login from './pages/Login'
import CV from './pages/CV'
import Search from './pages/Search'
import PrivateRoute from './components/PrivateRoute'
import AppLayout from './components/AppLayout'

export default function App() {
  return (
    <Routes>
      <Route path="/login" element={<Login />} />
      <Route path="/cv" element={<PrivateRoute><AppLayout><CV /></AppLayout></PrivateRoute>} />
      <Route path="/search" element={<PrivateRoute><AppLayout><Search /></AppLayout></PrivateRoute>} />
      <Route path="*" element={<Navigate to="/login" replace />} />
    </Routes>
  )
}
