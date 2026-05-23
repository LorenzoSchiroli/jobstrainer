import { Routes, Route, Navigate } from 'react-router-dom'
import Login from './pages/Login'
import CV from './pages/CV'
import Search from './pages/Search'
import PrivateRoute from './components/PrivateRoute'

export default function App() {
  return (
    <Routes>
      <Route path="/login" element={<Login />} />
      <Route path="/cv" element={<PrivateRoute><CV /></PrivateRoute>} />
      <Route path="/search" element={<PrivateRoute><Search /></PrivateRoute>} />
      <Route path="*" element={<Navigate to="/login" replace />} />
    </Routes>
  )
}
