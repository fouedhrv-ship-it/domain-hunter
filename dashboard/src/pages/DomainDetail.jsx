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

  async function toggleFavori() {
    const nouveau = !domain.favori
    setDomain(prev => ({ ...prev, favori: nouveau }))
    await supabase.from('domains_scanned').update({ favori: nouveau }).eq('id', id)
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
  const enEnchere = domain.source === 'webexpire' && domain.webexpire_lien

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
        <span style={{
          fontSize: 10, padding: '3px 8px', borderRadius: 4, letterSpacing: '0.06em',
          background: sirene_ok ? 'rgba(34,211,168,0.1)' : 'rgba(56,189,248,0.1)',
          color: sirene_ok ? 'var(--green)' : 'var(--blue)',
          border: `1px solid ${sirene_ok ? 'rgba(34,211,168,0.25)' : 'rgba(56,189,248,0.25)'}`,
        }}>
          {sirene_ok ? '💰 REVENTE' : '🔗 SEO'}
        </span>
        <button
          className={`favori-btn${domain.favori ? ' active' : ''}`}
          onClick={toggleFavori}
          title={domain.favori ? 'Retirer des favoris' : 'Ajouter aux favoris (surveillance temps réel)'}
          style={{ fontSize: 20 }}
        >
          {domain.favori ? '★' : '☆'}
        </button>
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

          {/* Valorisation — commun aux deux filtres */}
          <div className="card" style={{ '--card-accent': scoreColor }}>
            <div className="card-title">
              <span className="card-title-icon">◎</span>
              ESTIMATION À LA REVENTE
              <span className="card-title-line" />
            </div>

            <div className="big-price">
              {domain.prix_estime_min
                ? `${domain.prix_estime_min} – ${domain.prix_estime_max} €`
                : '—'}
            </div>

            {!sirene_ok && (
              <div className="score-bar-full">
                <div className="score-bar-fill" style={{ width: `${score}%`, background: scoreColor }} />
              </div>
            )}
            {!sirene_ok && (
              <div className="score-text">
                <span style={{ color: scoreColor, fontWeight: 600 }}>Score : {score}/100</span>
                <span>{score >= 70 ? '▲ Excellent' : score >= 40 ? '◆ Moyen' : '▼ Faible'}</span>
              </div>
            )}

            <div className={`timing-tag ${timingClass}`} style={timingTagStyle(timingClass)}>
              {timingText}
            </div>

            {domain.badge_surpaye && (
              <div style={{ marginTop: 10 }} className="badge-surpaye">
                🚩 SURPAYÉ — le prix demandé dépasse la valeur estimée
              </div>
            )}
          </div>

          {/* Enchère WebExpire — commun, affiché si une enchère existe */}
          <div className="card" style={{ '--card-accent': enEnchere ? 'var(--cyan)' : 'var(--text-3)' }}>
            <div className="card-title">
              <span className="card-title-icon">⚡</span>
              ENCHÈRE WEBEXPIRE
              <span className="card-title-line" />
            </div>
            {enEnchere ? (
              <>
                <DataRow label="Prix actuel" value={domain.webexpire_prix_actuel != null ? `${domain.webexpire_prix_actuel}€` : '—'} />
                <DataRow label="Délai" value={domain.delai_enchere || '—'} />
                <a className="ext-link" href={domain.webexpire_lien} target="_blank" rel="noopener noreferrer">
                  ↗ Voir l'enchère sur WebExpire
                </a>
              </>
            ) : domain.source === 'catchdoms' ? (
              <>
                <div style={{ color: 'var(--text-3)', fontSize: 13, marginBottom: 10 }}>
                  ✕ Pas d'enchère active sur WebExpire — listé via CatchDoms
                </div>
                <DataRow label="Score CatchDoms" value={domain.catchdoms_score ?? '—'} />
                <DataRow label="Enchère max" value={domain.catchdoms_max_bid ? `${domain.catchdoms_max_bid}€` : '—'} />
                {domain.catchdoms_purchase_url && (
                  <a className="ext-link" href={domain.catchdoms_purchase_url} target="_blank" rel="noopener noreferrer">
                    ↗ Voir sur {domain.catchdoms_purchase_platform || 'CatchDoms'}
                  </a>
                )}
              </>
            ) : (
              <div style={{ color: 'var(--text-3)', fontSize: 13 }}>✕ Non listé sur WebExpire</div>
            )}
          </div>

          {sirene_ok ? (
            <ReventeCards domain={domain} />
          ) : (
            <SeoCards domain={domain} />
          )}
        </div>

        {/* Racheter */}
        <BuyCard domain={domain} />

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

/* ── Cartes spécifiques Filtre 1 (SEO / vente de liens) ──────────────────── */
function SeoCards({ domain }) {
  return (
    <>
      {/* Présence web & Wayback */}
      <div className="card" style={{ '--card-accent': 'var(--blue)' }}>
        <div className="card-title">
          <span className="card-title-icon">◇</span>
          PRÉSENCE WEB
          <span className="card-title-line" />
        </div>
        <DataRow label="Contenu Common Crawl" value={
          domain.common_crawl_pages > 0
            ? <span style={{ color: 'var(--green)' }}>✅ {domain.common_crawl_pages} pages</span>
            : <span style={{ color: 'var(--red)' }}>❌ Aucun contenu indexé</span>
        } />
        <DataRow label="Snapshots Wayback" value={domain.wayback_snapshots ?? '—'} />
        <DataRow label="TLD" value={
          <span style={{ color: domain.domain?.endsWith('.fr') ? 'var(--cyan)' : 'var(--text-2)' }}>
            {domain.domain?.endsWith('.fr') ? '.fr (+5 pts bonus)' : domain.domain?.split('.').pop() || '—'}
          </span>
        } />
      </div>

      {/* Métriques d'autorité */}
      <div className="card" style={{ '--card-accent': 'var(--purple)' }}>
        <div className="card-title">
          <span className="card-title-icon">◆</span>
          MÉTRIQUES D'AUTORITÉ
          <span className="card-title-line" />
        </div>
        <DataRow label="Trust Flow (TF)" value={domain.trust_flow ?? '—'} />
        <DataRow label="Citation Flow (CF)" value={domain.citation_flow ?? '—'} />
        <DataRow label="Domain Authority (DA)" value={domain.domain_authority ?? '—'} />
        <DataRow label="Backlinks (RD)" value={domain.ref_domains ?? '—'} />
      </div>

      {/* Stats WebExpire (VI/TR/KW/NB) — utilisées pour l'estimation SEO */}
      {domain.source === 'webexpire' && (
        <div className="card" style={{ '--card-accent': 'var(--cyan)' }}>
          <div className="card-title">
            <span className="card-title-icon">📊</span>
            STATS WEBEXPIRE
            <span className="card-title-line" />
          </div>
          <DataRow label="Visites (VI)" value={domain.webexpire_visites ?? '—'} />
          <DataRow label="Trafic SEMrush (TR)" value={domain.webexpire_trafic ?? '—'} />
          <DataRow label="Mots-clés (KW)" value={domain.webexpire_mots_cles ?? '—'} />
          <DataRow label="NB" value={domain.webexpire_nb ?? '—'} />
        </div>
      )}

      {/* Risques */}
      <div className="card" style={{ '--card-accent': (domain.domaine_blackliste || domain.pivot_thematique_detecte) ? 'var(--red)' : 'var(--green)' }}>
        <div className="card-title">
          <span className="card-title-icon">⚠</span>
          RISQUES
          <span className="card-title-line" />
        </div>
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
      </div>
    </>
  )
}

/* ── Cartes spécifiques Filtre 2 (revente à l'ancien propriétaire) ──────── */
function ReventeCards({ domain }) {
  return (
    <>
      {/* SIRENE */}
      <div className="card" style={{ '--card-accent': 'var(--green)' }}>
        <div className="card-title">
          <span className="card-title-icon">◈</span>
          SIRENE
          <span className="card-title-line" />
        </div>
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
      </div>

      {/* Marque INPI + Mail + Recours */}
      <div className="card" style={{ '--card-accent': domain.inpi_marque_deposee ? 'var(--amber)' : 'var(--text-3)' }}>
        <div className="card-title">
          <span className="card-title-icon">⚖</span>
          MARQUE & CONTACT
          <span className="card-title-line" />
        </div>
        <DataRow label="Marque INPI" value={
          domain.inpi_marque_deposee
            ? <span style={{ color: 'var(--amber)' }}>⚠ Déposée</span>
            : <span style={{ color: 'var(--green)' }}>✓ Non déposée</span>
        } />
        <DataRow
          label="Mail ancien proprio"
          value={domain.email_contact
            ? <a href={`mailto:${domain.email_contact}`} style={{ color: 'var(--cyan)' }}>{domain.email_contact}</a>
            : <span style={{ color: 'var(--text-3)' }}>non trouvé</span>
          }
        />
        {domain.deja_reenregistre_tiers && (
          <div style={{
            marginTop: 10,
            padding: '10px 12px',
            background: 'rgba(244,63,94,0.08)',
            border: '1px solid rgba(244,63,94,0.2)',
            borderRadius: 5,
            fontSize: 11,
            color: 'var(--red)',
            lineHeight: 1.5,
          }}>
            ⚠ Déjà repris par un tiers{domain.registrar ? ` (${domain.registrar})` : ''} — recours possible via procédure PARL EXPERT (AFNIC, ~250€).
          </div>
        )}
        {domain.flag_prudence && (
          <div style={{
            marginTop: 10,
            padding: '10px 12px',
            background: 'rgba(245,158,11,0.08)',
            border: '1px solid rgba(245,158,11,0.2)',
            borderRadius: 5,
            fontSize: 11,
            color: 'var(--amber)',
            lineHeight: 1.5,
          }}>
            🟠 Marque + SIRENE actif détectés : proposer un prix raisonnable rapidement.
          </div>
        )}
      </div>

      {/* Présence web */}
      <div className="card" style={{ '--card-accent': 'var(--blue)' }}>
        <div className="card-title">
          <span className="card-title-icon">◇</span>
          PRÉSENCE WEB
          <span className="card-title-line" />
        </div>
        <DataRow label="Contenu Common Crawl" value={
          domain.common_crawl_pages > 0
            ? <span style={{ color: 'var(--green)' }}>✅ {domain.common_crawl_pages} pages</span>
            : <span style={{ color: 'var(--red)' }}>❌ Aucun contenu indexé</span>
        } />
        <DataRow label="Snapshots Wayback" value={domain.wayback_snapshots ?? '—'} />
        <DataRow label="Registrar" value={domain.registrar || '—'} />
      </div>
    </>
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

function BuyCard({ domain }) {
  const d = domain.domain
  const isWebexpire = domain.source === 'webexpire' && domain.webexpire_lien

  const links = isWebexpire
    ? [
        { label: '⚡ Enchérir sur WebExpire', url: domain.webexpire_lien, primary: true },
        { label: 'OVH — commander le domaine', url: `https://www.ovhcloud.com/fr/domains/` },
        { label: 'Gandi — vérifier disponibilité', url: `https://www.gandi.net/fr/domain/suggest?search=${d}` },
      ]
    : [
        { label: '◈ Backorder sur OVH', url: `https://www.ovhcloud.com/fr/domains/`, primary: true },
        { label: 'Gandi — vérifier disponibilité', url: `https://www.gandi.net/fr/domain/suggest?search=${d}` },
        { label: 'GoDaddy — rechercher', url: `https://fr.godaddy.com/domainsearch/find?domainToCheck=${d}` },
      ]

  return (
    <div className="card" style={{ '--card-accent': 'var(--cyan)' }}>
      <div className="card-title">
        <span className="card-title-icon">↗</span>
        RACHETER CE DOMAINE
        <span className="card-title-line" />
      </div>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
        {links.map(({ label, url, primary }) => (
          <a
            key={url}
            href={url}
            target="_blank"
            rel="noopener noreferrer"
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: 10,
              padding: '10px 14px',
              background: primary ? 'rgba(0,245,196,0.1)' : 'var(--bg-2)',
              border: `1px solid ${primary ? 'rgba(0,245,196,0.35)' : 'var(--border)'}`,
              borderRadius: 6,
              color: primary ? 'var(--cyan)' : 'var(--text-2)',
              textDecoration: 'none',
              fontSize: 13,
              fontWeight: primary ? 600 : 400,
              letterSpacing: '0.02em',
              transition: 'background 0.15s, border-color 0.15s',
            }}
            onMouseEnter={e => e.currentTarget.style.borderColor = 'var(--border-hi)'}
            onMouseLeave={e => e.currentTarget.style.borderColor = primary ? 'rgba(0,245,196,0.35)' : 'var(--border)'}
          >
            <span style={{ flex: 1 }}>{label}</span>
            <span style={{ fontSize: 11, opacity: 0.5 }}>↗</span>
          </a>
        ))}
      </div>
    </div>
  )
}

function timingTagStyle(cls) {
  if (cls === 'urgent') return { color: 'var(--red)', borderColor: 'rgba(244,63,94,0.3)', background: 'rgba(244,63,94,0.08)' }
  if (cls === 'hot')    return { color: 'var(--amber)', borderColor: 'rgba(245,158,11,0.3)', background: 'rgba(245,158,11,0.08)' }
  return { color: 'var(--text-2)', borderColor: 'var(--border)', background: 'transparent' }
}
