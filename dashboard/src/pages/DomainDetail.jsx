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

  if (!domain) return <div style={s.loading}>Chargement…</div>

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
    <div style={s.page}>
      <header style={s.header}>
        <button onClick={() => navigate('/domaines')} style={s.back}>← Retour</button>
        <span style={s.domain}>{domain.flag_prudence ? '🟠 ' : '🎯 '}{domain.domain}</span>
      </header>

      <div style={s.body}>
        <div style={s.grid}>

          {/* Bloc prix + score */}
          <div style={s.card}>
            <h3 style={s.cardTitle}>Valorisation</h3>
            <div style={s.bigPrice}>
              {domain.prix_estime_min ? `${domain.prix_estime_min} – ${domain.prix_estime_max} €` : '—'}
            </div>
            <div style={s.scoreBar}>
              <div style={{...s.scoreProgress, width: `${domain.score || 0}%`, background: scoreGradient(domain.score)}} />
            </div>
            <p style={s.scoreLabel}>Score : {domain.score ?? '—'}/100</p>
            <p style={s.timing}>{timing}</p>
          </div>

          {/* Bloc SIRENE */}
          <div style={s.card}>
            <h3 style={s.cardTitle}>SIRENE</h3>
            {sirene_ok ? (
              <>
                <p style={{color: '#4ade80', fontWeight: 600, marginBottom: 8}}>✅ Entreprise active — correspondance confirmée</p>
                <Row label="Dénomination" value={domain.sirene_denomination} />
                <Row label="Catégorie" value={domain.sirene_categorie_entreprise || 'TPE/indépendant'} />
                {domain.dirigeant_prenom || domain.dirigeant_nom
                  ? <Row label="Dirigeant" value={`${domain.dirigeant_prenom || ''} ${domain.dirigeant_nom || ''}`.trim()} />
                  : null}
                <Row label="Autre site actif" value={domain.has_autre_site ? '⚠️ Oui — urgence réduite' : '✅ Non — aucune présence web'} />
                <a
                  href={`https://annuaire-entreprises.data.gouv.fr/rechercher?terme=${encodeURIComponent(domain.sirene_denomination || domain.domain)}`}
                  target="_blank" rel="noopener noreferrer" style={s.link}
                >Fiche Annuaire Entreprises →</a>
              </>
            ) : (
              <p style={{color: '#6b7280'}}>❌ Aucune entreprise active identifiée</p>
            )}
          </div>

          {/* Bloc SEO */}
          <div style={s.card}>
            <h3 style={s.cardTitle}>Profil SEO</h3>
            <Row label="OpenPageRank" value={domain.page_rank != null ? `${domain.page_rank}/10` : '—'} />
            <Row label="Domaines référents" value={domain.ref_domains ?? '—'} />
            <Row label="Snapshots Wayback" value={domain.wayback_snapshots ?? '—'} />
            <Row label="Pages Common Crawl" value={domain.common_crawl_pages ?? '—'} />
          </div>

          {/* Bloc risques */}
          <div style={s.card}>
            <h3 style={s.cardTitle}>Risques</h3>
            <Row label="Marque INPI" value={domain.inpi_marque_deposee ? '⚠️ Déposée' : '✅ Non déposée'} />
            <Row label="Flag prudence" value={domain.flag_prudence ? '🟠 Oui — approche raisonnable' : '—'} />
            <Row label="Pivot PBN" value={domain.pivot_thematique_detecte ? '⚠️ Détecté' : '✅ Non détecté'} />
            <Row label="Blacklist/spam" value={domain.domaine_blackliste ? '⛔ Blacklisté' : '✅ OK'} />
          </div>

        </div>

        {/* Statut + notes */}
        <div style={s.card}>
          <h3 style={s.cardTitle}>Suivi</h3>
          <div style={s.row}>
            <div style={{flex: 1}}>
              <label style={s.label}>Statut</label>
              <select style={s.select} value={statut} onChange={e => setStatut(e.target.value)}>
                {STATUTS.map(st => <option key={st} value={st}>{st.replace('_', ' ')}</option>)}
              </select>
            </div>
          </div>
          <label style={s.label}>Notes</label>
          <textarea
            style={s.textarea}
            value={notes}
            onChange={e => setNotes(e.target.value)}
            placeholder="Ajouter des notes sur ce domaine…"
            rows={4}
          />
          <button onClick={handleSave} style={s.saveBtn} disabled={saving}>
            {saving ? 'Enregistrement…' : saved ? '✓ Enregistré' : 'Enregistrer'}
          </button>
        </div>
      </div>
    </div>
  )
}

function Row({ label, value }) {
  return (
    <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 8, fontSize: 13 }}>
      <span style={{ color: '#666' }}>{label}</span>
      <span style={{ color: '#e5e5e5', fontWeight: 500 }}>{value ?? '—'}</span>
    </div>
  )
}

function scoreGradient(score) {
  if (!score) return '#333'
  if (score >= 70) return '#22c55e'
  if (score >= 40) return '#f59e0b'
  return '#ef4444'
}

const s = {
  page: { minHeight: '100vh', background: '#0f0f0f', color: '#e5e5e5' },
  loading: { display: 'flex', alignItems: 'center', justifyContent: 'center', height: '100vh', color: '#555' },
  header: { display: 'flex', alignItems: 'center', gap: 16, padding: '16px 24px', borderBottom: '1px solid #1e1e1e', background: '#141414' },
  back: { background: 'none', border: '1px solid #333', color: '#888', padding: '6px 14px', borderRadius: 6, cursor: 'pointer', fontSize: 12 },
  domain: { fontSize: 18, fontWeight: 700, color: '#fff' },
  body: { padding: 24, maxWidth: 960, margin: '0 auto' },
  grid: { display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(280px, 1fr))', gap: 16, marginBottom: 16 },
  card: { background: '#1a1a1a', border: '1px solid #2a2a2a', borderRadius: 10, padding: 20, marginBottom: 0 },
  cardTitle: { fontSize: 11, color: '#555', textTransform: 'uppercase', letterSpacing: '0.08em', marginBottom: 16, fontWeight: 600 },
  bigPrice: { fontSize: 28, fontWeight: 700, color: '#22c55e', marginBottom: 16 },
  scoreBar: { height: 6, background: '#222', borderRadius: 3, overflow: 'hidden', marginBottom: 8 },
  scoreProgress: { height: '100%', borderRadius: 3, transition: 'width 0.3s' },
  scoreLabel: { fontSize: 13, color: '#888', marginBottom: 8 },
  timing: { fontSize: 13, color: '#aaa', marginTop: 4 },
  link: { display: 'inline-block', marginTop: 12, color: '#3b82f6', fontSize: 13, textDecoration: 'none' },
  label: { display: 'block', fontSize: 11, color: '#555', textTransform: 'uppercase', letterSpacing: '0.05em', marginBottom: 6, marginTop: 16 },
  select: { background: '#111', border: '1px solid #333', color: '#e5e5e5', padding: '8px 12px', borderRadius: 8, fontSize: 13, width: '100%' },
  textarea: { width: '100%', background: '#111', border: '1px solid #333', color: '#e5e5e5', padding: '10px 12px', borderRadius: 8, fontSize: 13, resize: 'vertical', outline: 'none', fontFamily: 'inherit' },
  saveBtn: { marginTop: 12, background: '#2563eb', color: '#fff', border: 'none', padding: '10px 24px', borderRadius: 8, fontSize: 14, fontWeight: 600, cursor: 'pointer' },
  row: { display: 'flex', gap: 16 }
}
