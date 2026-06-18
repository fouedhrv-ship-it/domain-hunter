-- Schéma Domain Hunter — à exécuter une seule fois dans l'éditeur SQL Supabase

create table if not exists domains_scanned (
  id bigint generated always as identity primary key,
  domain text not null unique,
  date_scan timestamptz not null default now(),
  score int,
  prix_estime_min numeric,
  prix_estime_max numeric,
  sirene_actif boolean default false,
  sirene_nom_correspond boolean default false,
  sirene_denomination text,
  sirene_categorie_entreprise text,
  page_rank int,
  ref_domains int,
  wayback_snapshots int,
  inpi_marque_deposee boolean default false,
  flag_prudence boolean default false,
  pivot_thematique_detecte boolean default false,
  domaine_blackliste boolean default false,
  jours_avant_drop int,
  alerte_telegram_envoyee boolean default false,
  dirigeant_nom text,
  dirigeant_prenom text,
  has_autre_site boolean default false,
  jours_post_drop int,
  statut text default 'nouveau',
  notes text
);

-- Sécurité RLS : seuls les utilisateurs connectés peuvent lire/écrire
alter table domains_scanned enable row level security;

create policy "Accès complet aux utilisateurs connectés"
  on domains_scanned for all
  using (auth.role() = 'authenticated');

-- Index pour les filtrages fréquents du dashboard
create index if not exists idx_domains_score on domains_scanned(score desc);
create index if not exists idx_domains_prix on domains_scanned(prix_estime_min desc);
create index if not exists idx_domains_statut on domains_scanned(statut);
create index if not exists idx_domains_sirene on domains_scanned(sirene_actif, sirene_nom_correspond);
