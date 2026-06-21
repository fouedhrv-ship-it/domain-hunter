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

function SortHeader({ label, column, className, sort, onSort }) {
  const active = sort.column === column
  return (
    <span
      className={className}
      onClick={() => onSort(column)}
      style={{ cursor: 'pointer', userSelect: 'none', color: active ? 'var(--cyan)' : undefined }}
      title="Trier"
    >
      {label}{active ? (sort.asc ? ' ▲' : ' ▼') : ''}
    </span>
  )
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

function DropBadge({ jours_avant, jours_post, source, delai, deja_repris, en_enchere }) {
  if (en_enchere) {
    return (
      <span className="drop-badge urgent" style={{ background: 'rgba(245,158,11,0.1)', color: 'var(--amber)', borderColor: 'rgba(245,158,11,0.3)' }}>
        ⚡ {delai || 'AU ENCHÈRE'}
      </span>
    )
  }
  if (deja_repris) {
    return (
      <span className="drop-badge" style={{ background: 'rgba(244,63,94,0.1)', color: 'var(--red)', borderColor: 'rgba(244,63,94,0.3)' }}>
        ⚠ REPRIS
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

function DropStatusCell({ d }) {
  if (d.en_enchere_active) {
    return (
      <span className="drop-badge urgent" style={{ background: 'rgba(245,158,11,0.1)', color: 'var(--amber)', borderColor: 'rgba(245,158,11,0.3)' }}>
        ⚡ ENCHÈRE{d.jours_avant_fin_enchere != null ? ` · ${d.jours_avant_fin_enchere}j` : ''}
      </span>
    )
  }
  if (d.catchdoms_type === 'closeout') {
    return (
      <span className="drop-badge" style={{ background: 'rgba(148,163,184,0.1)', color: 'var(--text-2)', borderColor: 'rgba(148,163,184,0.25)' }}>
        📦 BACKORDER
      </span>
    )
  }
  if (d.jours_post_drop != null) {
    if (d.jours_post_drop <= 30) return <span className="drop-badge urgent">🔥 J+{d.jours_post_drop}</span>
    if (d.jours_post_drop <= 90) return <span className="drop-badge hot">J+{d.jours_post_drop}</span>
    return <span className="drop-badge ok">J+{d.jours_post_drop}</span>
  }
  return <span style={{ color: 'var(--text-3)' }}>—</span>
}

function EnchereCell({ d }) {
  const enEnchereWebexpire = d.source === 'webexpire' && d.webexpire_lien
  if (enEnchereWebexpire) {
    return (
      <a
        href={d.webexpire_lien}
        target="_blank"
        rel="noopener noreferrer"
        onClick={e => e.stopPropagation()}
        style={{ display: 'block', fontSize: 12, color: 'var(--cyan)' }}
      >
        ↗ {d.webexpire_prix_actuel != null ? `${d.webexpire_prix_actuel}€` : 'enchère'}
        {d.badge_surpaye && <span className="badge-surpaye" style={{ marginLeft: 6 }}>SURPAYÉ</span>}
      </a>
    )
  }
  if (d.catchdoms_purchase_url) {
    return (
      <a
        href={d.catchdoms_purchase_url}
        target="_blank"
        rel="noopener noreferrer"
        onClick={e => e.stopPropagation()}
        style={{ display: 'block', fontSize: 12, color: 'var(--cyan)' }}
      >
        ↗ {d.catchdoms_purchase_platform || 'CatchDoms'}
        {d.catchdoms_max_bid != null && ` · ${d.catchdoms_max_bid}€`}
        {d.catchdoms_max_bid == null && d.catchdoms_price != null && ` · ${d.catchdoms_price}€ (prix fixe)`}
        {d.catchdoms_type === 'closeout' && <span className="badge-surpaye" style={{ marginLeft: 6, color: 'var(--text-2)', background: 'rgba(148,163,184,0.1)', border: '1px solid rgba(148,163,184,0.25)' }}>BACKORDER</span>}
      </a>
    )
  }
  return <span style={{ color: 'var(--text-3)', fontSize: 12 }}>❌ Non disponible</span>
}

function PresenceCell({ d }) {
  return (
    <span style={{ fontSize: 11, color: 'var(--text-2)' }}>
      {d.common_crawl_pages > 0 ? '✅ contenu' : '❌ vide'} · 📸 {d.wayback_snapshots ?? 0}
    </span>
  )
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
  const [tab, setTab] = useState('seo') // 'seo' | 'revente'
  const [domaines, setDomaines] = useState([])
  const [counts, setCounts] = useState({ seo: 0, revente: 0 })
  const [loading, setLoading] = useState(true)
  const [filtreStatut, setFiltreStatut] = useState('tous')
  const [filtrePrudence, setFiltrePrudence] = useState(false)
  const [filtreFavoris, setFiltreFavoris] = useState(false)
  const [scoreMin, setScoreMin] = useState(0)
  const [scanning, setScanning] = useState(false)
  const [scanMsg, setScanMsg] = useState('')
  const [polling, setPolling] = useState(false)
  const [resetting, setResetting] = useState(false)
  const [sort, setSort] = useState({ column: 'prix_estime_min', asc: false })
  const pollRef = useRef(null)
  const navigate = useNavigate()

  function handleSort(column) {
    setSort(prev => prev.column === column ? { column, asc: !prev.asc } : { column, asc: false })
  }

  const fetchCounts = useCallback(async () => {
    // SEO et Revente ne sont plus mutuellement exclusifs : un domaine peut
    // remplir les deux critères (ex. société active ET enchère SEO valide) et
    // apparaître dans les deux onglets. SEO = eligible_seo (calculé côté
    // hunter.py, indépendant de SIRENE — voir eligible_seo()). Revente =
    // société active OU site qui était actif, inchangé.
    const { count: c1 } = await supabase
      .from('domains_scanned').select('id', { count: 'exact', head: true })
      .eq('eligible_seo', true)
      .or('domain.ilike.%.fr,domain.ilike.%.com')
      .eq('jours_avant_drop', 0)
      .lte('jours_post_drop', 5)
    const { count: c2 } = await supabase
      .from('domains_scanned').select('id', { count: 'exact', head: true })
      .or('and(sirene_actif.eq.true,sirene_nom_correspond.eq.true),site_etait_actif.eq.true')
    setCounts({ seo: c1 || 0, revente: c2 || 0 })
  }, [])

  const fetchDomaines = useCallback(async () => {
    setLoading(true)
    let q = supabase
      .from('domains_scanned')
      .select('*')
      .order(sort.column, { ascending: sort.asc, nullsFirst: false })

    if (tab === 'revente') {
      q = q.or('and(sirene_actif.eq.true,sirene_nom_correspond.eq.true),site_etait_actif.eq.true')
    } else {
      // Onglet SEO : uniquement .fr/.com, et dropé depuis 5 jours max (au-delà,
      // plus pertinent pour la revente de liens — le squat a eu le temps de
      // jouer, on vise la fenêtre fraîche post-drop). jours_avant_drop=0 est
      // requis en plus de jours_post_drop<=5 : jours_post_drop vaut aussi 0
      // par défaut pour un domaine PAS ENCORE dropé (expiration WHOIS loin
      // dans le futur), jours_avant_drop=0 est le seul signal fiable de
      // "vraiment déjà tombé".
      q = q
        .eq('eligible_seo', true)
        .or('domain.ilike.%.fr,domain.ilike.%.com')
        .eq('jours_avant_drop', 0)
        .lte('jours_post_drop', 5)
    }

    if (filtreStatut !== 'tous') q = q.eq('statut', filtreStatut)
    if (filtrePrudence) q = q.eq('flag_prudence', true)
    if (filtreFavoris) q = q.eq('favori', true)
    if (scoreMin > 0) q = q.gte('score', scoreMin)

    const { data, error } = await q
    if (!error) setDomaines(data || [])
    setLoading(false)
  }, [tab, filtreStatut, filtrePrudence, filtreFavoris, scoreMin, sort])

  useEffect(() => { fetchDomaines(); fetchCounts() }, [fetchDomaines, fetchCounts])

  const [refreshing, setRefreshing] = useState(false)

  async function refreshAll() {
    setRefreshing(true)
    try {
      await Promise.all([fetchDomaines(), fetchCounts()])
    } finally {
      setRefreshing(false)
    }
  }

  async function logout() {
    await supabase.auth.signOut()
  }

  async function resetDomaines() {
    if (!window.confirm('Supprimer TOUS les domaines de la base ? Cette action est irréversible.')) return
    if (!window.confirm('Vraiment sûr ? Tout l\'historique de scan sera perdu définitivement.')) return

    setResetting(true)
    setScanMsg('')
    try {
      const { error } = await supabase.from('domains_scanned').delete().not('id', 'is', null)
      if (error) throw error
      setScanMsg('✓ Base vidée')
      setDomaines([])
      setCounts({ seo: 0, revente: 0 })
      setTimeout(() => setScanMsg(''), 3000)
    } catch (e) {
      setScanMsg(`ERREUR : ${e.message}`)
    } finally {
      setResetting(false)
    }
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

        const lastTs = domaines[0]?.updated_at || null
        let attempts = 0
        pollRef.current = setInterval(async () => {
          attempts++
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
            fetchCounts()
            if (hasNew) setTimeout(() => setScanMsg(''), 3000)
          }
        }, 10000)
      } else {
        setScanMsg(`ERREUR : ${json.error || 'Inconnu'}`)
      }
    } catch (e) {
      setScanMsg(`ERREUR : ${e.message}`)
    } finally {
      setScanning(false)
    }
  }

  const total       = domaines.length
  const enEnchere    = domaines.filter(d => d.en_enchere_active).length
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

        <button onClick={refreshAll} disabled={refreshing} className="refresh-btn" title="Actualiser les données">
          <span className={`scan-btn-icon${refreshing ? ' spin' : ''}`}>⟳</span>
          <span className="scan-btn-label">{refreshing ? 'Actualisation…' : 'Rafraîchir'}</span>
        </button>

        <button onClick={lancerScan} disabled={scanning} className="scan-btn">
          <span className="scan-btn-icon">{scanning ? '⟳' : '▶'}</span>
          <span className="scan-btn-label">{scanning ? 'Scan…' : 'Scanner'}</span>
        </button>

        <button onClick={resetDomaines} disabled={resetting} className="reset-btn" title="Vider tous les domaines de la base">
          <span className="scan-btn-icon">{resetting ? '⟳' : '🗑'}</span>
          <span className="scan-btn-label">{resetting ? 'Suppression…' : 'Vider'}</span>
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

      {/* ── Tabs : SEO (Filtre 1) / Revente (Filtre 2) ── */}
      <div className="tabs-bar">
        <button className={`tab-btn${tab === 'seo' ? ' active' : ''}`} onClick={() => setTab('seo')}>
          🔗 SEO / vente de liens
          <span className="tab-count">{counts.seo}</span>
        </button>
        <button className={`tab-btn${tab === 'revente' ? ' active' : ''}`} onClick={() => setTab('revente')}>
          💰 Revente à l'ancien propriétaire
          <span className="tab-count">{counts.revente}</span>
        </button>
      </div>

      {/* ── Stats bar ── */}
      <div className="stats-bar">
        <div className="stat-card" style={{ '--accent-color': 'var(--cyan)' }}>
          <div className="stat-label">◈ DOMAINES ({tab === 'seo' ? 'SEO' : 'REVENTE'})</div>
          <div className="stat-value">{total}</div>
          <div className="stat-sub">dans cet onglet</div>
        </div>
        <div className="stat-card" style={{ '--accent-color': 'var(--green)' }}>
          <div className="stat-label">⚡ EN ENCHÈRE ACTIVE</div>
          <div className="stat-value" style={{ color: 'var(--green)' }}>{enEnchere}</div>
          <div className="stat-sub">actuellement actives</div>
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

        {tab === 'revente' && (
          <label className="filter-check">
            <input type="checkbox" checked={filtrePrudence} onChange={e => setFiltrePrudence(e.target.checked)} />
            🟠 Prudence
          </label>
        )}
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
        ) : tab === 'seo' ? (
          <>
            <div className="table-head cols-seo">
              <span className="col-favori"></span>
              <SortHeader label="DOMAINE" column="domain" className="col-domain" sort={sort} onSort={handleSort} />
              <SortHeader label="ENCHÈRE" column="catchdoms_max_bid" className="col-enchere" sort={sort} onSort={handleSort} />
              <SortHeader label="TF" column="trust_flow" className="col-tf" sort={sort} onSort={handleSort} />
              <SortHeader label="RD" column="ref_domains" className="col-rd" sort={sort} onSort={handleSort} />
              <SortHeader label="TRAFIC" column="webexpire_trafic" className="col-traffic" sort={sort} onSort={handleSort} />
              <SortHeader label="PRÉSENCE WEB" column="common_crawl_pages" className="col-presence" sort={sort} onSort={handleSort} />
              <SortHeader label="SCORE" column="score" className="col-score" sort={sort} onSort={handleSort} />
              <SortHeader label="DROP" column="jours_post_drop" className="col-statut" sort={sort} onSort={handleSort} />
            </div>

            {domaines.map((d, i) => (
              <div
                key={d.id}
                className="table-row cols-seo"
                style={{ '--row-color': d.score >= 60 ? 'var(--cyan)' : 'var(--text-3)', animationDelay: `${i * 20}ms` }}
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
                  <span className="domain-name">{d.domain}</span>
                  <span className="domain-src">{d.source || 'EDN'}</span>
                </div>

                <div className="col-enchere"><EnchereCell d={d} /></div>

                <div className="col-tf">{d.trust_flow ?? '—'}</div>

                <div className="col-rd">{d.ref_domains ?? '—'}</div>

                <div className="col-traffic">{d.webexpire_trafic ?? '—'}</div>

                <div className="col-presence"><PresenceCell d={d} /></div>

                <div className="col-score">
                  <ScoreMini score={d.score} />
                </div>

                <div className="col-statut">
                  <DropStatusCell d={d} />
                </div>
              </div>
            ))}
          </>
        ) : (
          <>
            <div className="table-head cols-revente">
              <span className="col-favori"></span>
              <SortHeader label="DOMAINE" column="domain" className="col-domain" sort={sort} onSort={handleSort} />
              <SortHeader label="SIRENE" column="sirene_denomination" className="col-sirene" sort={sort} onSort={handleSort} />
              <SortHeader label="DIRIGEANT" column="dirigeant_nom" className="col-dirigeant" sort={sort} onSort={handleSort} />
              <SortHeader label="ENCHÈRE" column="catchdoms_max_bid" className="col-enchere" sort={sort} onSort={handleSort} />
              <SortHeader label="MAIL ANCIEN PROPRIO" column="email_contact" className="col-mail" sort={sort} onSort={handleSort} />
              <SortHeader label="DROP" column="jours_avant_drop" className="col-drop" sort={sort} onSort={handleSort} />
              <SortHeader label="EST. REVENTE" column="prix_estime_min" className="col-prix" sort={sort} onSort={handleSort} />
              <SortHeader label="SCORE CATCHDOMS" column="catchdoms_score" className="col-score" sort={sort} onSort={handleSort} />
            </div>

            {domaines.map((d, i) => {
              const sireneOk = d.sirene_actif && d.sirene_nom_correspond
              const rowColor = d.flag_prudence ? 'var(--amber)' : sireneOk ? 'var(--green)' : 'var(--blue)'
              return (
              <div
                key={d.id}
                className="table-row cols-revente"
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
                  {d.deja_reenregistre_tiers && (
                    <span className="domain-src" style={{ color: 'var(--red)' }}>⚠ repris par un tiers</span>
                  )}
                </div>

                <div className="col-sirene">
                  {sireneOk ? (
                    <div className="sirene-tag">
                      <span style={{ color: 'var(--green)' }}>✓</span>
                      <span className="name">{d.sirene_denomination || 'Actif'}</span>
                    </div>
                  ) : (
                    <div className="sirene-tag" title="Société non identifiée — site actif détecté avant le drop">
                      <span style={{ color: 'var(--blue)' }}>🌐</span>
                      <span className="name" style={{ color: 'var(--blue)' }}>Site actif (société ?)</span>
                    </div>
                  )}
                </div>

                <div className="col-dirigeant" style={{ fontSize: 12, color: 'var(--text-2)' }}>
                  {(d.dirigeant_prenom || d.dirigeant_nom)
                    ? `${d.dirigeant_prenom || ''} ${d.dirigeant_nom || ''}`.trim()
                    : <span style={{ color: 'var(--text-3)' }}>—</span>}
                </div>

                <div className="col-enchere"><EnchereCell d={d} /></div>

                <div className="col-mail" style={{ fontSize: 11, overflow: 'hidden', textOverflow: 'ellipsis' }}>
                  {d.email_contact
                    ? <span style={{ color: 'var(--cyan)' }}>{d.email_contact}</span>
                    : <span style={{ color: 'var(--text-3)' }}>non trouvé</span>}
                </div>

                <div className="col-drop">
                  <DropBadge
                    jours_avant={d.jours_avant_drop}
                    jours_post={d.jours_post_drop}
                    source={d.source}
                    delai={d.delai_enchere}
                    deja_repris={d.deja_reenregistre_tiers}
                    en_enchere={d.en_enchere_active}
                  />
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
                </div>

                <div className="col-score">
                  <ScoreMini score={d.catchdoms_score} />
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
