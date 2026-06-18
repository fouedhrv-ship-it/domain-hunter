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
        <h1 className="login-title">🎯 Domain Hunter</h1>
        <p className="login-sub">Tableau de bord privé</p>
        <form onSubmit={handleSubmit}>
          <div className="field">
            <label className="field-label">Email</label>
            <input className="field-input" type="email" value={email} onChange={e => setEmail(e.target.value)} required autoFocus />
          </div>
          <div className="field">
            <label className="field-label">Mot de passe</label>
            <input className="field-input" type="password" value={password} onChange={e => setPassword(e.target.value)} required />
          </div>
          {error && <p className="error-msg">{error}</p>}
          <button className="submit-btn" type="submit" disabled={loading}>
            {loading ? 'Connexion…' : 'Se connecter'}
          </button>
        </form>
      </div>
    </div>
  )
}
