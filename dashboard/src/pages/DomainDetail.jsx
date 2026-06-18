import { useEffect, useState } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { supabase } from '../lib/supabase.js'

const STATUTS = ['nouveau', 'backorder_pose', 'acquis', 'contacte', 'vendu', 'rejete']

export default function DomainDetail() {
  const { id } = useParams()
  const navigate = useNavigate()
  const [domain, setDomain] = useState(null)
  const [notes, setNotes] = useState('')
  const [statut, setStatut] = useState('')
  const [saving, setSaving] = useState(false)
  const [saved, setSaved] = useState(false)

  useEffect(() => {
    supabase.from('domains_scanned').select('*').eq('id', id).single().then(({ data }) => {
      if (data) {
        setDomain(data)
        setNotes(data.notes || '')
        setStatut(data.statut || 'nouveau')
      }
    })
  }, [id])

  async function handleSave() {
    setSaving(true)
    await supabase.from('domains_scanned').update({ notes, statut }).eq('id', id)
    setSaving(false)
    setSaved(true)
    setTimeout(() => setSaved(false), 2000)
  }

  if (!domain) {
    return (
      <div className="loading-state" style={{ minHeight: '100dvh' }}>
        <span className="spinner" />
        Chargement…
      </div>
    )
  }

  const sirene_ok = domain.sirene_actif && domain.sirene_nom_correspond
  const score = domain.score || 0
  const scoreColor = score >= 70 ? '#22d3a8' : score >= 40 ? '#f59e0b' : '#f43f5e'

  const jours_post = domain.jours_post_drop
  let timingClass = 'ok', timingText = '📆 Domaine pas encore tombé'
  if (jours_post != null) {
    if (jours_post === 0) { timingClass = 'urgent'; timingText = '🔥 Vient de tomber — fenêtre idéale' }
    else if (jours_post <= 30) { timingClass = 'urgent'; timingText = `🔥 J+${jours_post} — fenêtre idéale de contact` }
    else if (jours_post <= 90) { timingClass = 'hot'; timingText = `⏳ J+${jours_post} — encore exploitable` }
    else { timingClass = 'ok'; timingText = `❄️ J+${jours_post} — intérêt réduit` }
  }

  return (
    <div className="detail-page">
      {/* ── Header ── */}
      <header className="detail-header">
        <button onClick={() => navigate('/domaines')} className="back-btn">
          ← Retour
        </button>
        <span className="detail-domain">
          {domain.flag_prudence ? '🟠 ' : ''}
          <span>{domain.domain}</span>
        </span>
        {domain.alerte_telegram_envoyee && (
          <span style={{
            marginLeft: 'auto',
            fontSize: 10,
            color: 'var(--amber)',
            background: 'rgba(245,158,11,0.1)',
            border: '1px solid rgba(245,158,11,0.25)',
            borderRadius: 4,
            padding: '3px 8px',
            letterSpacing: '0.06em',
            flexShrink: 0,
          }}>
            ⚡ ALERTE ENVOYÉE
          </span>
        )}
      </header>

      {/* ── Body ── */}
      <div className="detail-body">
        <div className="detail-grid">

          {/* Valorisation */}
          <div className="card" style={{ '--card-accent': scoreColor }}>
            <div className="card-title">
              <span className="card-title-icon">◎</span>
              VALORISATION
              <span className="card-title-line" />
            </div>

            <div className="big-price">
              {domain.prix_estime_min
                ? `${domain.prix_estime_min} – ${domain.prix_estime_max} €`
                : '—'}
            </div>

            <div className="score-bar-full">
              <div
                className="score-bar-fill"
                style={{ width: `${score}%`, background: scoreColor }}
              />
            </div>
            <div className="score-text">
              <span style={{ color: scoreColor, fontWeight: 600 }}>Score : {score}/100</span>
              <span>{score >= 70 ? '▲ Excellent' : score >= 40 ? '◆ Moyen' : '▼ Faible'}</span>
            </div>

            <div className={`timing-tag ${timingClass}`} style={timingTagStyle(timingClass)}>
              {timingText}
            </div>
          </div>

          {/* SIRENE */}
          <div className="card" style={{ '--card-accent': sirene_ok ? 'var(--green)' : 'var(--text-3)' }}>
            <div className="card-title">
              <span className="card-title-icon">◈</span>
              SIRENE
              <span className="card-title-line" />
            </div>

            {sirene_ok ? (
              <>
                <div style={{ color: 'var(--green)', fontWeight: 600, fontSize: 13, marginBottom: 14 }}>
                  ✓ Entreprise active — correspondance confirmée
                </div>
                <DataRow label="Dénomination" value={domain.sirene_denomination} />
                <DataRow label="Catégorie" value={domain.sirene_categorie_entreprise || 'TPE/indépendant'} />
                {(domain.dirigeant_prenom || domain.dirigeant_nom) && (
                  <DataRow
                    label="Dirigeant"
                    value={`${domain.dirigeant_prenom || ''} ${domain.dirigeant_nom || ''}`.trim()}
                  />
                )}
                <DataRow
                  label="Autre site actif"
                  value={domain.has_autre_site
                    ? <span style={{ color: 'var(--amber)' }}>⚠ Oui — urgence réduite</span>
                    : <span style={{ color: 'var(--green)' }}>✓ Non</span>
                  }
                />
                <a
                  className="ext-link"
                  href={`https://annuaire-entreprises.data.gouv.fr/rechercher?terme=${encodeURIComponent(domain.sirene_denomination || domain.domain)}`}
                  target="_blank"
                  rel="noopener noreferrer"
                >
                  ↗ Annuaire Entreprises
                </a>
              </>
            ) : (
              <div style={{ color: 'var(--text-3)', fontSize: 13 }}>
                ✕ Aucune entreprise active identifiée
              </div>
            )}
          </div>

          {/* SEO */}
          <div className="card" style={{ '--card-accent': 'var(--blue)' }}>
            <div className="card-title">
              <span className="card-title-icon">◇</span>
              PROFIL SEO
              <span className="card-title-line" />
            </div>
            <DataRow
              label="OpenPageRank"
              value={domain.page_rank != null
                ? <PrBar value={domain.page_rank} max={10} />
                : '—'}
            />
            <DataRow label="Domaines référents" value={domain.ref_domains ?? '—'} />
            <DataRow label="Snapshots Wayback"  value={domain.wayback_snapshots ?? '—'} />
            <DataRow label="Pages Common Crawl" value={domain.common_crawl_pages ?? '—'} />
            <DataRow label="TLD" value={
              <span style={{ color: domain.domain?.endsWith('.fr') ? 'var(--cyan)' : 'var(--text-2)' }}>
                {domain.domain?.endsWith('.fr') ? '.fr (+5 pts bonus)' : domain.domain?.split('.').pop() || '—'}
              </span>
            } />
          </div>

          {/* Risques */}
          <div className="card" style={{ '--card-accent': (domain.inpi_marque_deposee || domain.domaine_blackliste || domain.pivot_thematique_detecte) ? 'var(--red)' : 'var(--green)' }}>
            <div className="card-title">
              <span className="card-title-icon">⚠</span>
              RISQUES
              <span className="card-title-line" />
            </div>
            <DataRow label="Marque INPI" value={
              domain.inpi_marque_deposee
                ? <span style={{ color: 'var(--amber)' }}>⚠ Déposée</span>
                : <span style={{ color: 'var(--green)' }}>✓ Non déposée</span>
            } />
            <DataRow label="Flag prudence" value={
              domain.flag_prudence
                ? <span style={{ color: 'var(--amber)' }}>🟠 Approche raisonnable</span>
                : <span style={{ color: 'var(--text-3)' }}>—</span>
            } />
            <DataRow label="Pivot PBN" value={
              domain.pivot_thematique_detecte
                ? <span style={{ color: 'var(--red)' }}>⚠ Détecté</span>
                : <span style={{ color: 'var(--green)' }}>✓ Non détecté</span>
            } />
            <DataRow label="Blacklist" value={
              domain.domaine_blackliste
                ? <span style={{ color: 'var(--red)' }}>⛔ Blacklisté</span>
                : <span style={{ color: 'var(--green)' }}>✓ OK</span>
            } />
            {domain.flag_prudence && (
              <div style={{
                marginTop: 12,
                padding: '10px 12px',
                background: 'rgba(245,158,11,0.08)',
                border: '1px solid rgba(245,158,11,0.2)',
                borderRadius: 5,
                fontSize: 11,
                color: 'var(--amber)',
                lineHeight: 1.5,
              }}>
                Marque + SIRENE actif détectés : proposer un prix raisonnable rapidement (voir VOIE C).
              </div>
            )}
          </div>
        </div>

        {/* Suivi */}
        <div className="card" style={{ '--card-accent': 'var(--purple)' }}>
          <div className="card-title">
            <span className="card-title-icon">▸</span>
            SUIVI & ACTIONS
            <span className="card-title-line" />
          </div>

          <label className="field-label-sm">Statut du domaine</label>
          <select
            className="suivi-select"
            value={statut}
            onChange={e => setStatut(e.target.value)}
          >
            {STATUTS.map(st => (
              <option key={st} value={st}>{st.replace(/_/g, ' ')}</option>
            ))}
          </select>

          <label className="field-label-sm">Notes internes</label>
          <textarea
            className="notes-textarea"
            value={notes}
            onChange={e => setNotes(e.target.value)}
            placeholder="Prix négocié, contact entreprise, backorder posé…"
            rows={4}
          />

          <button
            onClick={handleSave}
            className={`save-btn${saved ? ' saved' : ''}`}
            disabled={saving}
          >
            {saving ? '⟳ Enregistrement…' : saved ? '✓ Enregistré' : '▸ Sauvegarder'}
          </button>
        </div>
      </div>
    </div>
  )
}

function DataRow({ label, value }) {
  return (
    <div className="data-row">
      <span className="data-label">{label}</span>
      <span className="data-value">{value ?? '—'}</span>
    </div>
  )
}

function PrBar({ value, max }) {
  const pct = (value / max) * 100
  const color = value >= 5 ? '#22d3a8' : value >= 3 ? '#f59e0b' : '#f43f5e'
  return (
    <span style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
      <span style={{ color, fontWeight: 600 }}>{value}/{max}</span>
      <span style={{
        display: 'inline-block',
        width: 60, height: 4,
        background: 'rgba(255,255,255,0.06)',
        borderRadius: 2,
        overflow: 'hidden',
      }}>
        <span style={{
          display: 'block',
          width: `${pct}%`,
          height: '100%',
          background: color,
          borderRadius: 2,
        }} />
      </span>
    </span>
  )
}

function timingTagStyle(cls) {
  if (cls === 'urgent') return { color: 'var(--red)', borderColor: 'rgba(244,63,94,0.3)', background: 'rgba(244,63,94,0.08)' }
  if (cls === 'hot')    return { color: 'var(--amber)', borderColor: 'rgba(245,158,11,0.3)', background: 'rgba(245,158,11,0.08)' }
  return { color: 'var(--text-2)', borderColor: 'var(--border)', background: 'transparent' }
}
