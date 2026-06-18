import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { supabase } from '../lib/supabase.js'

const STATUTS = ['tous', 'nouveau', 'backorder_pose', 'acquis', 'contacte', 'vendu', 'rejete']

const STATUT_COLORS = {
  nouveau:       '#3b82f6',
  backorder_pose:'#f59e0b',
  acquis:        '#8b5cf6',
  contacte:      '#06b6d4',
  vendu:         '#22c55e',
  rejete:        '#6b7280',
}

function Badge({ statut }) {
  const color = STATUT_COLORS[statut] || '#555'
  return (
    <span style={{
      background: color + '22',
      color,
      border: `1px solid ${color}44`,
      borderRadius: 4,
      padding: '3px 8px',
      fontSize: 11,
      fontWeight: 600,
      textTransform: 'uppercase',
      letterSpacing: '0.03em',
    }}>
      {statut?.replace('_', ' ') || '—'}
    </span>
  )
}

export default function Domaines() {
  const [domaines, setDomaines] = useState([])
  const [loading, setLoading] = useState(true)
  const [filtreStatut, setFiltreStatut] = useState('tous')
  const [filtreSirene, setFiltreSirene] = useState(false)
  const [filtrePrudence, setFiltrePrudence] = useState(false)
  const [scoreMin, setScoreMin] = useState(0)
  const navigate = useNavigate()

  async function fetchDomaines() {
    setLoading(true)
    let q = supabase
      .from('domains_scanned')
      .select('*')
      .order('prix_estime_min', { ascending: false })

    if (filtreStatut !== 'tous') q = q.eq('statut', filtreStatut)
    if (filtreSirene) q = q.eq('sirene_actif', true).eq('sirene_nom_correspond', true)
    if (filtrePrudence) q = q.eq('flag_prudence', true)
    if (scoreMin > 0) q = q.gte('score', scoreMin)

    const { data, error } = await q
    if (!error) setDomaines(data || [])
    setLoading(false)
  }

  useEffect(() => { fetchDomaines() }, [filtreStatut, filtreSirene, filtrePrudence, scoreMin])

  const [scanning, setScanning] = useState(false)
  const [scanMsg, setScanMsg] = useState('')

  async function logout() {
    await supabase.auth.signOut()
  }

  async function lancerScan() {
    setScanning(true)
    setScanMsg('')
    try {
      const { data: { session } } = await supabase.auth.getSession()
      const res = await fetch(
        `${import.meta.env.VITE_SUPABASE_URL}/functions/v1/trigger-scan`,
        {
          method: 'POST',
          headers: {
            'Authorization': `Bearer ${session.access_token}`,
            'Content-Type': 'application/json',
          },
        }
      )
      const json = await res.json()
      if (json.ok) {
        setScanMsg('✅ Scan lancé — résultats dans ~2 min')
        setTimeout(() => { fetchDomaines(); setScanMsg('') }, 120000)
      } else {
        setScanMsg(`❌ ${json.error || 'Erreur'}`)
      }
    } catch (e) {
      setScanMsg(`❌ ${e.message}`)
    } finally {
      setScanning(false)
    }
  }

  return (
    <div style={{ minHeight: '100dvh', background: '#0f0f0f', color: '#e5e5e5' }}>
      <header className="app-header">
        <span className="app-logo">🎯 Domain Hunter</span>
        <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
          <button
            onClick={lancerScan}
            disabled={scanning}
            className="scan-btn"
          >
            {scanning ? '⏳ Lancement…' : '▶ Lancer un scan'}
          </button>
          <button onClick={logout} className="logout-btn">Déconnexion</button>
        </div>
      </header>
      {scanMsg && (
        <div className="scan-msg">{scanMsg}</div>
      )}

      <div className="filters">
        <select className="filter-select" value={filtreStatut} onChange={e => setFiltreStatut(e.target.value)}>
          {STATUTS.map(st => (
            <option key={st} value={st}>{st === 'tous' ? 'Tous les statuts' : st.replace('_', ' ')}</option>
          ))}
        </select>
        <label className="filter-check">
          <input type="checkbox" checked={filtreSirene} onChange={e => setFiltreSirene(e.target.checked)} />
          SIRENE actif
        </label>
        <label className="filter-check">
          <input type="checkbox" checked={filtrePrudence} onChange={e => setFiltrePrudence(e.target.checked)} />
          🟠 Prudence
        </label>
        <label className="filter-check">
          Score ≥
          <input type="number" value={scoreMin} min={0} max={100} className="score-input"
            onChange={e => setScoreMin(Number(e.target.value))} />
        </label>
        <span className="filter-count">{domaines.length} domaine{domaines.length !== 1 ? 's' : ''}</span>
      </div>

      {loading ? (
        <div className="empty-state">Chargement…</div>
      ) : domaines.length === 0 ? (
        <div className="empty-state">Aucun domaine trouvé avec ces filtres.</div>
      ) : (
        <div className="domain-list">
          {/* En-tête visible uniquement sur desktop (masqué via CSS mobile) */}
          <div className="table-head">
            <span className="col-domain">Domaine</span>
            <span className="col-prix">Prix estimé</span>
            <span className="col-score">Score</span>
            <span className="col-sirene">SIRENE</span>
            <span className="col-drop">Drop</span>
            <span className="col-statut">Statut</span>
          </div>

          {domaines.map(d => (
            <div key={d.id} className="table-row" onClick={() => navigate(`/domaines/${d.id}`)}>

              {/* Colonne domaine */}
              <span className="col-domain">
                {d.flag_prudence && '🟠 '}
                <strong style={{ color: '#fff' }}>{d.domain}</strong>
              </span>

              {/* Prix — gros sur mobile */}
              <span className="col-prix">
                {d.prix_estime_min ? `${d.prix_estime_min}–${d.prix_estime_max}€` : '—'}
              </span>

              {/* Score + Drop groupés sur mobile via .mobile-meta */}
              <span className="col-score" style={{ color: scoreColor(d.score) }}>
                {d.score ?? '—'}/100
              </span>

              {/* SIRENE */}
              <span className="col-sirene">
                {d.sirene_actif && d.sirene_nom_correspond
                  ? <span style={{ color: '#4ade80' }}>✅ {d.sirene_denomination?.slice(0, 22) || 'Actif'}</span>
                  : <span style={{ color: '#444' }}>—</span>}
              </span>

              {/* Drop */}
              <span className="col-drop">
                {d.jours_avant_drop != null && d.jours_avant_drop > 0
                  ? <span style={{ color: '#f59e0b' }}>{d.jours_avant_drop}j</span>
                  : d.jours_post_drop != null && d.jours_post_drop > 0
                  ? <span style={{ color: dropColor(d.jours_post_drop) }}>J+{d.jours_post_drop}</span>
                  : <span style={{ color: '#444' }}>—</span>}
              </span>

              {/* Statut */}
              <span className="col-statut">
                <Badge statut={d.statut} />
              </span>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

function scoreColor(score) {
  if (!score) return '#555'
  if (score >= 70) return '#22c55e'
  if (score >= 40) return '#f59e0b'
  return '#ef4444'
}

function dropColor(jours) {
  if (jours <= 30) return '#22c55e'
  if (jours <= 90) return '#f59e0b'
  return '#6b7280'
}
