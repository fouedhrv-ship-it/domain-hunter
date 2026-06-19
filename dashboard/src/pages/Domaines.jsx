import { useEffect, useState, useCallback, useRef } from 'react'
import { useNavigate } from 'react-router-dom'
import { supabase } from '../lib/supabase.js'

const STATUTS = ['tous', 'nouveau', 'backorder_pose', 'acquis', 'contacte', 'vendu', 'rejete']

const STATUT_STYLE = {
  nouveau:        { bg: 'rgba(59,130,246,0.12)', color: '#60a5fa', border: 'rgba(59,130,246,0.25)' },
  backorder_pose: { bg: 'rgba(245,158,11,0.12)', color: '#fbbf24', border: 'rgba(245,158,11,0.25)' },
  acquis:         { bg: 'rgba(139,92,246,0.12)', color: '#a78bfa', border: 'rgba(139,92,246,0.25)' },
  contacte:       { bg: 'rgba(6,182,212,0.12)',  color: '#22d3ee', border: 'rgba(6,182,212,0.25)' },
  vendu:          { bg: 'rgba(34,197,94,0.12)',  color: '#4ade80', border: 'rgba(34,197,94,0.25)' },
  rejete:         { bg: 'rgba(107,114,128,0.10)', color: '#6b7280', border: 'rgba(107,114,128,0.2)' },
}

function StatutBadge({ statut }) {
  const s = STATUT_STYLE[statut] || STATUT_STYLE.rejete
  return (
    <span className="statut-badge" style={{ background: s.bg, color: s.color, border: `1px solid ${s.border}` }}>
      {statut?.replace(/_/g, ' ') || '—'}
    </span>
  )
}

function ScoreMini({ score }) {
  const color = score >= 70 ? '#22d3a8' : score >= 40 ? '#f59e0b' : '#f43f5e'
  return (
    <div className="score-mini">
      <span className="score-num" style={{ color }}>{score ?? '—'}<span style={{ color: 'var(--text-3)', fontSize: 10 }}>/100</span></span>
      <div className="score-track">
        <div className="score-fill" style={{ width: `${score || 0}%`, background: color }} />
      </div>
    </div>
  )
}

function DropBadge({ jours_avant, jours_post, source, delai }) {
  if (source === 'webexpire') {
    return (
      <span className="drop-badge urgent" style={{ background: 'rgba(0,245,196,0.1)', color: 'var(--cyan)', borderColor: 'rgba(0,245,196,0.3)' }}>
        ⚡ {delai || 'ENCHÈRE'}
      </span>
    )
  }
  if (jours_avant != null && jours_avant > 0) {
    return <span className="drop-badge hot">▼ {jours_avant}j</span>
  }
  if (jours_post != null && jours_post >= 0) {
    if (jours_post <= 30) return <span className="drop-badge urgent">🔥 J+{jours_post}</span>
    if (jours_post <= 90) return <span className="drop-badge hot">J+{jours_post}</span>
    return <span className="drop-badge ok">J+{jours_post}</span>
  }
  return <span style={{ color: 'var(--text-3)' }}>—</span>
}

function Clock() {
  const [time, setTime] = useState(() => new Date().toLocaleTimeString('fr-FR', { hour: '2-digit', minute: '2-digit', second: '2-digit' }))
  useEffect(() => {
    const t = setInterval(() => setTime(new Date().toLocaleTimeString('fr-FR', { hour: '2-digit', minute: '2-digit', second: '2-digit' })), 1000)
    return () => clearInterval(t)
  }, [])
  return <span className="header-clock">{time}</span>
}

export default function Domaines() {
  const [domaines, setDomaines] = useState([])
  const [loading, setLoading] = useState(true)
  const [filtreStatut, setFiltreStatut] = useState('tous')
  const [filtreSirene, setFiltreSirene] = useState(false)
  const [filtrePrudence, setFiltrePrudence] = useState(false)
  const [filtreFavoris, setFiltreFavoris] = useState(false)
  const [scoreMin, setScoreMin] = useState(0)
  const [scanning, setScanning] = useState(false)
  const [scanMsg, setScanMsg] = useState('')
  const [polling, setPolling] = useState(false)
  const pollRef = useRef(null)
  const navigate = useNavigate()

  const fetchDomaines = useCallback(async () => {
    setLoading(true)
    let q = supabase
      .from('domains_scanned')
      .select('*')
      .order('prix_estime_min', { ascending: false })

    if (filtreStatut !== 'tous') q = q.eq('statut', filtreStatut)
    if (filtreSirene) q = q.eq('sirene_actif', true).eq('sirene_nom_correspond', true)
    if (filtrePrudence) q = q.eq('flag_prudence', true)
    if (filtreFavoris) q = q.eq('favori', true)
    if (scoreMin > 0) q = q.gte('score', scoreMin)

    const { data, error } = await q
    if (!error) setDomaines(data || [])
    setLoading(false)
  }, [filtreStatut, filtreSirene, filtrePrudence, filtreFavoris, scoreMin])

  useEffect(() => { fetchDomaines() }, [fetchDomaines])

  async function logout() {
    await supabase.auth.signOut()
  }

  async function toggleFavori(e, d) {
    e.stopPropagation()
    const nouveau = !d.favori
    setDomaines(prev => prev.map(x => x.id === d.id ? { ...x, favori: nouveau } : x))
    await supabase.from('domains_scanned').update({ favori: nouveau }).eq('id', d.id)
  }

  function stopPolling() {
    if (pollRef.current) {
      clearInterval(pollRef.current)
      pollRef.current = null
    }
    setPolling(false)
  }

  useEffect(() => () => stopPolling(), [])

  async function lancerScan() {
    setScanning(true)
    setScanMsg('')
    stopPolling()

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
        setScanMsg('Scan en cours — actualisation automatique…')
        setPolling(true)

        // Snapshot du dernier updated_at connu avant le scan
        const lastTs = domaines[0]?.updated_at || null

        let attempts = 0
        pollRef.current = setInterval(async () => {
          attempts++
          // Récupère le domaine le plus récemment mis à jour
          const { data } = await supabase
            .from('domains_scanned')
            .select('updated_at')
            .order('updated_at', { ascending: false })
            .limit(1)
            .single()

          const newTs = data?.updated_at || null
          const hasNew = newTs && newTs !== lastTs

          if (hasNew || attempts >= 20) {
            stopPolling()
            setScanMsg(hasNew ? '✓ Nouvelles données disponibles' : '')
            fetchDomaines()
            if (hasNew) setTimeout(() => setScanMsg(''), 3000)
          }
        }, 10000) // vérifie toutes les 10s
      } else {
        setScanMsg(`ERREUR : ${json.error || 'Inconnu'}`)
      }
    } catch (e) {
      setScanMsg(`ERREUR : ${e.message}`)
    } finally {
      setScanning(false)
    }
  }

  // Stats calculées
  const total      = domaines.length
  const sireneCount = domaines.filter(d => d.sirene_actif && d.sirene_nom_correspond).length
  const alertCount  = domaines.filter(d => d.alerte_telegram_envoyee).length
  const valeurTotal = domaines.reduce((sum, d) => sum + (d.prix_estime_min || 0), 0)

  return (
    <div className="app-root">
      {/* ── Header ── */}
      <header className="app-header">
        <div className="header-logo">
          <span className="header-logo-icon">◈</span>
          <div>
            <div className="header-logo-text">Domain<span>Hunter</span></div>
            <div className="header-logo-ver">v2.0 // SYSTÈME ACTIF</div>
          </div>
        </div>

        <div className="header-status">
          <span className="status-dot" />
          EN LIGNE
        </div>

        <div className="header-spacer" />
        <Clock />

        <button onClick={lancerScan} disabled={scanning} className="scan-btn">
          <span className="scan-btn-icon">{scanning ? '⟳' : '▶'}</span>
          <span className="scan-btn-label">{scanning ? 'Scan…' : 'Scanner'}</span>
        </button>

        <button onClick={logout} className="logout-btn">
          ⏻ Quitter
        </button>
      </header>

      {/* ── Scan message ── */}
      {scanMsg && (
        <div className="scan-msg">
          <span className="status-dot" style={{ background: scanMsg.startsWith('ERR') ? 'var(--red)' : scanMsg.startsWith('✓') ? 'var(--green)' : 'var(--cyan)' }} />
          {scanMsg}
          {polling && <span style={{ color: 'var(--text-3)', marginLeft: 8 }}>— vérif. toutes les 10s</span>}
        </div>
      )}

      {/* ── Stats bar ── */}
      <div className="stats-bar">
        <div className="stat-card" style={{ '--accent-color': 'var(--cyan)' }}>
          <div className="stat-label">◈ DOMAINES SCANNÉS</div>
          <div className="stat-value">{total}</div>
          <div className="stat-sub">dans la base</div>
        </div>
        <div className="stat-card" style={{ '--accent-color': 'var(--green)' }}>
          <div className="stat-label">✓ SIRENE ACTIF</div>
          <div className="stat-value" style={{ color: 'var(--green)' }}>{sireneCount}</div>
          <div className="stat-sub">entreprises actives</div>
        </div>
        <div className="stat-card" style={{ '--accent-color': 'var(--amber)' }}>
          <div className="stat-label">⚡ ALERTES ENVOYÉES</div>
          <div className="stat-value" style={{ color: 'var(--amber)' }}>{alertCount}</div>
          <div className="stat-sub">via Telegram</div>
        </div>
        <div className="stat-card" style={{ '--accent-color': 'var(--purple)' }}>
          <div className="stat-label">◎ VALEUR PIPELINE</div>
          <div className="stat-value" style={{ color: 'var(--purple)' }}>
            {valeurTotal >= 1000 ? `${(valeurTotal / 1000).toFixed(1)}k` : valeurTotal}€
          </div>
          <div className="stat-sub">estimation basse</div>
        </div>
      </div>

      {/* ── Filters ── */}
      <div className="filters">
        <span className="filter-label">FILTRES //</span>
        <select
          className="filter-select"
          value={filtreStatut}
          onChange={e => setFiltreStatut(e.target.value)}
        >
          {STATUTS.map(st => (
            <option key={st} value={st}>
              {st === 'tous' ? 'Tous statuts' : st.replace(/_/g, ' ')}
            </option>
          ))}
        </select>

        <span className="filter-sep" />

        <label className="filter-check">
          <input type="checkbox" checked={filtreSirene} onChange={e => setFiltreSirene(e.target.checked)} />
          SIRENE actif
        </label>
        <label className="filter-check">
          <input type="checkbox" checked={filtrePrudence} onChange={e => setFiltrePrudence(e.target.checked)} />
          🟠 Prudence
        </label>
        <label className="filter-check">
          <input type="checkbox" checked={filtreFavoris} onChange={e => setFiltreFavoris(e.target.checked)} />
          ★ Favoris
        </label>

        <span className="filter-sep" />

        <div className="score-wrapper">
          Score ≥
          <input
            type="number"
            value={scoreMin}
            min={0} max={100}
            className="score-input"
            onChange={e => setScoreMin(Number(e.target.value))}
          />
        </div>

        <div className="filter-count">
          <span>{total}</span> résultat{total !== 1 ? 's' : ''}
        </div>
      </div>

      {/* ── Domain list ── */}
      <div className="domain-list">
        {loading ? (
          <div className="loading-state">
            <span className="spinner" />
            Chargement des données…
          </div>
        ) : domaines.length === 0 ? (
          <div className="empty-state">
            <span className="empty-icon">◈</span>
            <span className="empty-title">Aucun domaine trouvé</span>
            <span className="empty-sub">Modifiez les filtres ou lancez un scan</span>
          </div>
        ) : (
          <>
            <div className="table-head">
              <span className="col-favori"></span>
              <span className="col-domain">DOMAINE</span>
              <span className="col-metrics">TF · CF · DA · RD</span>
              <span className="col-prix">PRIX ESTIMÉ</span>
              <span className="col-score">SCORE</span>
              <span className="col-sirene">SIRENE</span>
              <span className="col-drop">DROP</span>
              <span className="col-statut">STATUT</span>
            </div>

            {domaines.map((d, i) => {
              const sirene_ok = d.sirene_actif && d.sirene_nom_correspond
              const rowColor = d.flag_prudence
                ? 'var(--amber)'
                : sirene_ok
                ? 'var(--green)'
                : d.score >= 60
                ? 'var(--cyan)'
                : 'var(--text-3)'

              return (
                <div
                  key={d.id}
                  className="table-row"
                  style={{ '--row-color': rowColor, animationDelay: `${i * 20}ms` }}
                  onClick={() => navigate(`/domaines/${d.id}`)}
                >
                  <div className="col-favori">
                    <button
                      className={`favori-btn${d.favori ? ' active' : ''}`}
                      onClick={e => toggleFavori(e, d)}
                      title={d.favori ? 'Retirer des favoris' : 'Ajouter aux favoris (surveillance temps réel)'}
                    >
                      {d.favori ? '★' : '☆'}
                    </button>
                  </div>

                  <div className="col-domain">
                    <span className="domain-name">
                      {d.flag_prudence ? '🟠 ' : ''}{d.domain}
                    </span>
                    <span className="domain-src">{d.source || 'EDN'}</span>
                  </div>

                  <div className="col-metrics">
                    <div className="metrics-line">
                      <span>TF <span className="metric-val">{d.trust_flow ?? '—'}</span></span>
                      <span>CF <span className="metric-val">{d.citation_flow ?? '—'}</span></span>
                      <span>DA <span className="metric-val">{d.domain_authority ?? '—'}</span></span>
                      <span>RD <span className="metric-val">{d.ref_domains ?? '—'}</span></span>
                    </div>
                    {d.badge_surpaye && <span className="badge-surpaye">🚩 SURPAYÉ</span>}
                  </div>

                  <div className="col-prix">
                    {d.prix_estime_min ? (
                      <>
                        <span className="price-value">{d.prix_estime_min}€</span>
                        <span className="price-range">— {d.prix_estime_max}€</span>
                      </>
                    ) : (
                      <span style={{ color: 'var(--text-3)' }}>—</span>
                    )}
                    {d.webexpire_lien && (
                      <a
                        href={d.webexpire_lien}
                        target="_blank"
                        rel="noopener noreferrer"
                        onClick={e => e.stopPropagation()}
                        style={{ display: 'block', fontSize: 10, color: 'var(--cyan)', marginTop: 2 }}
                      >
                        ↗ {d.webexpire_prix_actuel ? `${d.webexpire_prix_actuel}€ enchère` : 'voir enchère'}
                      </a>
                    )}
                  </div>

                  <div className="col-score">
                    <ScoreMini score={d.score} />
                  </div>

                  <div className="col-sirene">
                    {sirene_ok ? (
                      <div className="sirene-tag">
                        <span style={{ color: 'var(--green)' }}>✓</span>
                        <span className="name">{d.sirene_denomination || 'Actif'}</span>
                      </div>
                    ) : (
                      <span style={{ color: 'var(--text-3)', fontSize: 12 }}>—</span>
                    )}
                  </div>

                  <div className="col-drop">
                    <DropBadge
                      jours_avant={d.jours_avant_drop}
                      jours_post={d.jours_post_drop}
                      source={d.source}
                      delai={d.delai_enchere}
                    />
                  </div>

                  <div className="col-statut">
                    <StatutBadge statut={d.statut} />
                  </div>
                </div>
              )
            })}
          </>
        )}
      </div>
    </div>
  )
}
