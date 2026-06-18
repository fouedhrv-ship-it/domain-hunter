import './style.css'
import React from 'react'
import ReactDOM from 'react-dom/client'
import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom'
import Login from './pages/Login.jsx'
import Domaines from './pages/Domaines.jsx'
import DomainDetail from './pages/DomainDetail.jsx'
import { AuthProvider, useAuth } from './AuthContext.jsx'

function ProtectedRoute({ children }) {
  const { session, loading } = useAuth()
  if (loading) return <div style={styles.loading}>Chargement…</div>
  if (!session) return <Navigate to="/login" replace />
  return children
}

const styles = {
  loading: { display: 'flex', alignItems: 'center', justifyContent: 'center', height: '100vh', color: '#888', fontSize: 14 }
}

ReactDOM.createRoot(document.getElementById('root')).render(
  <React.StrictMode>
    <AuthProvider>
      <BrowserRouter>
        <Routes>
          <Route path="/login" element={<Login />} />
          <Route path="/domaines" element={<ProtectedRoute><Domaines /></ProtectedRoute>} />
          <Route path="/domaines/:id" element={<ProtectedRoute><DomainDetail /></ProtectedRoute>} />
          <Route path="*" element={<Navigate to="/domaines" replace />} />
        </Routes>
      </BrowserRouter>
    </AuthProvider>
  </React.StrictMode>
)
