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

  if (!domain) return (
    <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', height: '100dvh', color: '#555', fontSize: 14 }}>
      Chargement…
    </div>
  )

  const sirene_ok = domain.sirene_actif && domain.sirene_nom_correspond
  const jours_post = domain.jours_post_drop
  const timing = !jours_post
    ? '📆 Domaine pas encore tombé'
    : jours_post <= 30
    ? `🔥 Drop récent (J+${jours_post}) — fenêtre idéale`
    : jours_post <= 90
    ? `⏳ Drop il y a J+${jours_post} — encore exploitable`
    : `❄️ Drop il y a J+${jours_post} — intérêt réduit`

  return (
    <div className="detail-page">
      <header className="detail-header">
        <button onClick={() => navigate('/domaines')} className="back-btn">← Retour</button>
        <span className="detail-domain-name">
          {domain.flag_prudence ? '🟠 ' : '🎯 '}{domain.domain}
        </span>
      </header>

      <div className="detail-body">
        <div className="detail-grid">

          {/* Valorisation */}
          <div className="card">
            <h3 className="card-title">Valorisation</h3>
            <div className="big-price">
              {domain.prix_estime_min ? `${domain.prix_estime_min} – ${domain.prix_estime_max} €` : '—'}
            </div>
            <div className="score-bar">
              <div className="score-progress" style={{ width: `${domain.score || 0}%`, background: scoreGradient(domain.score) }} />
            </div>
            <p className="score-label">Score : {domain.score ?? '—'}/100</p>
            <p className="timing">{timing}</p>
          </div>

          {/* SIRENE */}
          <div className="card">
            <h3 className="card-title">SIRENE</h3>
            {sirene_ok ? (
              <>
                <p style={{ color: '#4ade80', fontWeight: 600, marginBottom: 10 }}>✅ Entreprise active — correspondance confirmée</p>
                <DataRow label="Dénomination" value={domain.sirene_denomination} />
                <DataRow label="Catégorie" value={domain.sirene_categorie_entreprise || 'TPE/indépendant'} />
                {(domain.dirigeant_prenom || domain.dirigeant_nom) &&
                  <DataRow label="Dirigeant" value={`${domain.dirigeant_prenom || ''} ${domain.dirigeant_nom || ''}`.trim()} />}
                <DataRow label="Autre site actif" value={domain.has_autre_site ? '⚠️ Oui — urgence réduite' : '✅ Non'} />
                <a
                  className="ext-link"
                  href={`https://annuaire-entreprises.data.gouv.fr/rechercher?terme=${encodeURIComponent(domain.sirene_denomination || domain.domain)}`}
                  target="_blank" rel="noopener noreferrer"
                >
                  Fiche Annuaire Entreprises →
                </a>
              </>
            ) : (
              <p style={{ color: '#555', fontSize: 13 }}>❌ Aucune entreprise active identifiée</p>
            )}
          </div>

          {/* Profil SEO */}
          <div className="card">
            <h3 className="card-title">Profil SEO</h3>
            <DataRow label="OpenPageRank" value={domain.page_rank != null ? `${domain.page_rank}/10` : '—'} />
            <DataRow label="Domaines référents" value={domain.ref_domains ?? '—'} />
            <DataRow label="Snapshots Wayback" value={domain.wayback_snapshots ?? '—'} />
            <DataRow label="Pages Common Crawl" value={domain.common_crawl_pages ?? '—'} />
          </div>

          {/* Risques */}
          <div className="card">
            <h3 className="card-title">Risques</h3>
            <DataRow label="Marque INPI" value={domain.inpi_marque_deposee ? '⚠️ Déposée' : '✅ Non déposée'} />
            <DataRow label="Flag prudence" value={domain.flag_prudence ? '🟠 Approche raisonnable' : '—'} />
            <DataRow label="Pivot PBN" value={domain.pivot_thematique_detecte ? '⚠️ Détecté' : '✅ Non détecté'} />
            <DataRow label="Blacklist" value={domain.domaine_blackliste ? '⛔ Blacklisté' : '✅ OK'} />
          </div>

        </div>

        {/* Suivi */}
        <div className="card">
          <h3 className="card-title">Suivi</h3>
          <label className="field-label-sm">Statut</label>
          <select className="suivi-select" value={statut} onChange={e => setStatut(e.target.value)}>
            {STATUTS.map(st => <option key={st} value={st}>{st.replace('_', ' ')}</option>)}
          </select>
          <label className="field-label-sm">Notes</label>
          <textarea
            className="notes-textarea"
            value={notes}
            onChange={e => setNotes(e.target.value)}
            placeholder="Ajouter des notes sur ce domaine…"
            rows={4}
          />
          <button onClick={handleSave} className="save-btn" disabled={saving}>
            {saving ? 'Enregistrement…' : saved ? '✓ Enregistré' : 'Enregistrer'}
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

function scoreGradient(score) {
  if (!score) return '#333'
  if (score >= 70) return '#22c55e'
  if (score >= 40) return '#f59e0b'
  return '#ef4444'
}
