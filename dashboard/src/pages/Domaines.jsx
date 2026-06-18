import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { supabase } from '../lib/supabase.js'

const STATUTS = ['tous', 'nouveau', 'backorder_pose', 'acquis', 'contacte', 'vendu', 'rejete']

const STATUT_COLORS = {
  nouveau: '#3b82f6',
  backorder_pose: '#f59e0b',
  acquis: '#8b5cf6',
  contacte: '#06b6d4',
  vendu: '#22c55e',
  rejete: '#6b7280',
}

function Badge({ statut }) {
  return (
    <span style={{
      background: STATUT_COLORS[statut] + '22',
      color: STATUT_COLORS[statut] || '#888',
      border: `1px solid ${STATUT_COLORS[statut] || '#333'}44`,
      borderRadius: 4, padding: '2px 8px', fontSize: 11, fontWeight: 600, textTransform: 'uppercase'
    }}>{statut?.replace('_', ' ') || '—'}</span>
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

  async function logout() {
    await supabase.auth.signOut()
  }

  return (
    <div style={s.page}>
      <header style={s.header}>
        <span style={s.logo}>🎯 Domain Hunter</span>
        <button onClick={logout} style={s.logoutBtn}>Déconnexion</button>
      </header>

      <div style={s.filters}>
        <select style={s.select} value={filtreStatut} onChange={e => setFiltreStatut(e.target.value)}>
          {STATUTS.map(st => <option key={st} value={st}>{st === 'tous' ? 'Tous les statuts' : st.replace('_', ' ')}</option>)}
        </select>
        <label style={s.checkLabel}>
          <input type="checkbox" checked={filtreSirene} onChange={e => setFiltreSirene(e.target.checked)} />
          SIRENE actif uniquement
        </label>
        <label style={s.checkLabel}>
          <input type="checkbox" checked={filtrePrudence} onChange={e => setFiltrePrudence(e.target.checked)} />
          🟠 Prudence uniquement
        </label>
        <label style={s.checkLabel}>
          Score ≥
          <input type="number" value={scoreMin} min={0} max={100} style={s.scoreInput}
            onChange={e => setScoreMin(Number(e.target.value))} />
        </label>
        <span style={s.count}>{domaines.length} domaine{domaines.length !== 1 ? 's' : ''}</span>
      </div>

      {loading ? (
        <div style={s.empty}>Chargement…</div>
      ) : domaines.length === 0 ? (
        <div style={s.empty}>Aucun domaine trouvé avec ces filtres.</div>
      ) : (
        <div style={s.table}>
          <div style={s.tableHead}>
            <span style={{flex: 2}}>Domaine</span>
            <span style={{flex: 1}}>Prix estimé</span>
            <span style={{flex: 1}}>Score</span>
            <span style={{flex: 1.5}}>SIRENE</span>
            <span style={{flex: 1}}>Drop</span>
            <span style={{flex: 1}}>Statut</span>
          </div>
          {domaines.map(d => (
            <div key={d.id} style={s.row} onClick={() => navigate(`/domaines/${d.id}`)}>
              <span style={{flex: 2}}>
                {d.flag_prudence && '🟠 '}
                <strong style={{color: '#fff'}}>{d.domain}</strong>
              </span>
              <span style={{flex: 1, color: '#22c55e', fontWeight: 600}}>
                {d.prix_estime_min ? `${d.prix_estime_min}–${d.prix_estime_max}€` : '—'}
              </span>
              <span style={{flex: 1}}>
                <span style={{color: scoreColor(d.score)}}>{d.score ?? '—'}/100</span>
              </span>
              <span style={{flex: 1.5, fontSize: 12, color: '#888'}}>
                {d.sirene_actif && d.sirene_nom_correspond
                  ? <span style={{color: '#4ade80'}}>✅ {d.sirene_denomination?.slice(0, 22) || 'Actif'}</span>
                  : <span style={{color: '#666'}}>—</span>}
              </span>
              <span style={{flex: 1, fontSize: 12}}>
                {d.jours_avant_drop != null && d.jours_avant_drop > 0
                  ? <span style={{color: '#f59e0b'}}>{d.jours_avant_drop}j</span>
                  : d.jours_post_drop != null && d.jours_post_drop > 0
                  ? <span style={{color: dropColor(d.jours_post_drop)}}>J+{d.jours_post_drop}</span>
                  : '—'}
              </span>
              <span style={{flex: 1}}><Badge statut={d.statut} /></span>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

function scoreColor(score) {
  if (!score) return '#666'
  if (score >= 70) return '#22c55e'
  if (score >= 40) return '#f59e0b'
  return '#ef4444'
}

function dropColor(jours) {
  if (jours <= 30) return '#22c55e'
  if (jours <= 90) return '#f59e0b'
  return '#6b7280'
}

const s = {
  page: { minHeight: '100vh', background: '#0f0f0f', color: '#e5e5e5' },
  header: { display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '16px 24px', borderBottom: '1px solid #1e1e1e', background: '#141414' },
  logo: { fontSize: 18, fontWeight: 700, color: '#fff' },
  logoutBtn: { background: 'none', border: '1px solid #333', color: '#888', padding: '6px 14px', borderRadius: 6, cursor: 'pointer', fontSize: 12 },
  filters: { display: 'flex', alignItems: 'center', gap: 16, padding: '12px 24px', borderBottom: '1px solid #1e1e1e', background: '#111', flexWrap: 'wrap' },
  select: { background: '#1a1a1a', border: '1px solid #333', color: '#e5e5e5', padding: '6px 10px', borderRadius: 6, fontSize: 13 },
  checkLabel: { display: 'flex', alignItems: 'center', gap: 6, fontSize: 13, color: '#aaa', cursor: 'pointer' },
  scoreInput: { width: 52, marginLeft: 6, background: '#1a1a1a', border: '1px solid #333', color: '#e5e5e5', padding: '4px 8px', borderRadius: 6, fontSize: 13 },
  count: { marginLeft: 'auto', fontSize: 12, color: '#555' },
  table: { padding: '0 24px' },
  tableHead: { display: 'flex', gap: 16, padding: '10px 12px', borderBottom: '1px solid #1e1e1e', fontSize: 11, color: '#555', textTransform: 'uppercase', letterSpacing: '0.05em' },
  row: { display: 'flex', gap: 16, padding: '12px', borderBottom: '1px solid #181818', cursor: 'pointer', fontSize: 13, alignItems: 'center', transition: 'background 0.1s' },
  empty: { padding: 48, textAlign: 'center', color: '#555' }
}
