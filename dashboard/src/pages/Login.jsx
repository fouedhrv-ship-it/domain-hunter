import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { supabase } from '../lib/supabase.js'

export default function Login() {
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)
  const navigate = useNavigate()

  async function handleSubmit(e) {
    e.preventDefault()
    setLoading(true)
    setError('')
    const { error } = await supabase.auth.signInWithPassword({ email, password })
    if (error) {
      setError(error.message)
      setLoading(false)
    } else {
      navigate('/domaines')
    }
  }

  return (
    <div className="login-page">
      <div className="login-card">
        <div className="login-badge">
          <span className="login-badge-dot" />
          SYSTÈME SÉCURISÉ
        </div>
        <h1 className="login-title">Domain<span>Hunter</span></h1>
        <p className="login-sub">// accès tableau de bord privé</p>
        <form onSubmit={handleSubmit}>
          <div className="field">
            <label className="field-label">Identifiant</label>
            <input
              className="field-input"
              type="email"
              value={email}
              onChange={e => setEmail(e.target.value)}
              required
              autoFocus
              autoComplete="email"
              placeholder="utilisateur@domaine.com"
            />
          </div>
          <div className="field">
            <label className="field-label">Mot de passe</label>
            <input
              className="field-input"
              type="password"
              value={password}
              onChange={e => setPassword(e.target.value)}
              required
              autoComplete="current-password"
              placeholder="••••••••"
            />
          </div>
          {error && <div className="error-msg">{error}</div>}
          <button className="submit-btn" type="submit" disabled={loading}>
            {loading ? '⟳ Authentification…' : '▶ Accéder au système'}
          </button>
        </form>
      </div>
    </div>
  )
}
