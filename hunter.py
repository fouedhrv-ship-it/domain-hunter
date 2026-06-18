"""
Domain Hunter — moteur de scan principal
Tourne toutes les 15 minutes via GitHub Actions.
Priorité : SIRENE actif > SEO.
"""

import os
import json
import time
import re
import unicodedata
import logging
from datetime import datetime, timezone
from typing import Optional

import requests
from bs4 import BeautifulSoup
from dateutil import parser as dateutil_parser

# ── Configuration ─────────────────────────────────────────────────────────────

def load_config() -> dict:
    # Valeurs par défaut (remplacées par config.json local ou env vars)
    cfg = {
        "prix_minimum_alerte": 500,
        "score_minimum_dashboard": 40,
        "tlds_autorises": [".fr", ".com", ".net"],
        "longueur_max_domaine": 15,
        "rd_max_backorder": 300,
        "wayback_snapshots_min": 10,
        "max_domaines_par_run": 350,
        "rate_limit_delay_seconds": 1,
    }
    # Charger config.json si présent (développement local)
    if os.path.exists("config.json"):
        with open("config.json", "r") as f:
            cfg.update(json.load(f))
    # Les variables d'environnement ont priorité (GitHub Actions)
    env_map = {
        "telegram_token":       "TELEGRAM_TOKEN",
        "telegram_chat_id":     "TELEGRAM_CHAT_ID",
        "openpagerank_api_key": "OPENPAGERANK_API_KEY",
        "insee_token":          "INSEE_TOKEN",
        "inpi_token":           "INPI_TOKEN",
        "supabase_url":         "SUPABASE_URL",
        "supabase_service_key": "SUPABASE_SERVICE_KEY",
        "edn_email":            "EDN_EMAIL",
        "edn_password":         "EDN_PASSWORD",
    }
    for key, env_var in env_map.items():
        val = os.environ.get(env_var)
        if val:
            cfg[key] = val
    return cfg

CONFIG = load_config()
DELAY = CONFIG.get("rate_limit_delay_seconds", 1)
MAX_DOMAINES = CONFIG.get("max_domaines_par_run", 350)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("hunter")

# ── Normalisation ─────────────────────────────────────────────────────────────

def normalise(texte: str) -> str:
    texte = unicodedata.normalize("NFKD", texte.lower()).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]", "", texte)

def nom_vers_domaine(denomination: str, ville: str = "") -> list[str]:
    formes_juridiques = r"\b(sarl|sas|sasu|eurl|sa|sci|snc|ei|eirl|association|assoc|asso)\b"
    nom = denomination.lower().strip()
    nom = re.sub(formes_juridiques, "", nom, flags=re.IGNORECASE)
    nom = unicodedata.normalize("NFKD", nom).encode("ascii", "ignore").decode()
    nom = re.sub(r"[^a-z0-9\s-]", "", nom).strip()
    nom = re.sub(r"\s+", "-", nom)
    nom = re.sub(r"-+", "-", nom).strip("-")
    if not nom:
        return []
    variantes = [f"{nom}.fr", f"{nom}.com"]
    if ville:
        ville_slug = re.sub(r"[^a-z0-9]", "-", unicodedata.normalize("NFKD", ville.lower()).encode("ascii", "ignore").decode()).strip("-")
        variantes.append(f"{nom}-{ville_slug}.fr")
    variantes.append(f"{nom}s.fr")
    return variantes

# ── ÉTAPE 1 — Collecte ────────────────────────────────────────────────────────

# ── Source WebExpire.fr (gratuite, sans login) ────────────────────────────────

def scraper_webexpire() -> list[dict]:
    """
    Scrape WebExpire.fr/encheres — liste publique de domaines .fr expirés.
    Colonnes : Nom | Fin | BL | RD | TF | CF | VI | TR | KW | NB | Enchère
    Pas besoin de login. ~50-100 domaines par page.
    """
    domaines = []
    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
        }
        r = requests.get("https://www.webexpire.fr/encheres", headers=headers, timeout=15)
        if r.status_code != 200:
            log.warning(f"WebExpire: status {r.status_code}")
            return []
        soup = BeautifulSoup(r.text, "lxml")
        rows = soup.find_all("tr", class_="auctions-table-row")
        for row in rows:
            cols = row.find_all("td")
            if len(cols) < 5:
                continue
            # Domaine = id de la ligne (format "befoot-fr" → "befoot.fr")
            row_id = row.get("id", "")
            # Convertir le dernier tiret en point pour le TLD
            if "-" in row_id:
                parts = row_id.rsplit("-", 1)
                domain_name = f"{parts[0]}.{parts[1]}"
            else:
                continue
            if "." not in domain_name:
                continue
            # Col 3 = BL (backlinks total), Col 4 = RD (referring domains)
            def col_int(idx):
                if len(cols) > idx:
                    m = re.search(r"(\d+)", cols[idx].get_text(strip=True))
                    return int(m.group(1)) if m else 0
                return 0
            bl = col_int(3)
            rd = col_int(4)
            tf = col_int(5)
            cf = col_int(6)
            # Col 2 = délai (ex: "7 jours", "3 heures")
            delai_txt = cols[2].get_text(strip=True)
            domaines.append({
                "domain": domain_name,
                "ref_domains": rd,
                "wayback_snapshots": bl,  # BL comme proxy wayback (seule métrique dispo sans API)
                "trust_flow": tf,
                "citation_flow": cf,
                "source": "webexpire",
                "delai_enchère": delai_txt,
            })
        log.info(f"WebExpire: {len(domaines)} domaines .fr collectés")
    except Exception as e:
        log.warning(f"WebExpire scraping: {e}")
    return domaines

EDN_SESSION: Optional[requests.Session] = None

def _make_edn_session() -> requests.Session:
    """Crée une session requests avec les bons headers pour ExpiredDomains.net."""
    s = requests.Session()
    s.headers.update({
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
        "Accept-Language": "fr-FR,fr;q=0.9,en;q=0.8",
    })
    return s

def _edn_session_valide(session: requests.Session) -> bool:
    """Vérifie qu'une session est bien connectée."""
    try:
        r = session.get("https://member.expireddomains.net/domains/expiredfr/", timeout=10)
        return "login" not in r.url.lower() and len(r.text) > 10000
    except Exception:
        return False

def login_expireddomains() -> Optional[requests.Session]:
    """
    Obtient une session authentifiée sur ExpiredDomains.net.
    Stratégie (dans l'ordre) :
      1. browser_cookie3 — lit les cookies directement depuis Chrome (dev local)
      2. Cookies stockés en env var EDN_SESSID + EDN_REME (GitHub Actions)
    """
    # Stratégie 1 : cookies Chrome (dev local uniquement)
    try:
        import browser_cookie3
        chrome_cookies = browser_cookie3.chrome(domain_name=".expireddomains.net")
        if chrome_cookies:
            session = _make_edn_session()
            for c in chrome_cookies:
                session.cookies.set(c.name, c.value, domain=c.domain)
            if _edn_session_valide(session):
                log.info("EDN : session via cookies Chrome (dev local)")
                return session
    except ImportError:
        pass  # browser_cookie3 absent → GitHub Actions
    except Exception as e:
        log.debug(f"EDN cookies Chrome: {e}")

    # Stratégie 2 : cookies stockés en variables d'environnement / config
    sessid = CONFIG.get("edn_sessid", "") or os.environ.get("EDN_SESSID", "")
    reme   = CONFIG.get("edn_reme",   "") or os.environ.get("EDN_REME",   "")
    if sessid or reme:
        session = _make_edn_session()
        if sessid:
            session.cookies.set("ExpiredDomainssessid", sessid, domain="member.expireddomains.net")
        if reme:
            session.cookies.set("reme", reme, domain=".expireddomains.net")
        if _edn_session_valide(session):
            log.info("EDN : session via cookies stockés (env/config)")
            return session
        log.warning("EDN : cookies EDN_SESSID/EDN_REME expirés — rafraîchir les secrets GitHub")
        return None

    log.warning("EDN : aucune méthode d'authentification disponible (EDN_SESSID/EDN_REME non configurés)")
    return None

def scrape_expireddomains(session: requests.Session, tld: str = "fr", pages: int = 5) -> list[dict]:
    """
    Scrape les domaines expirés depuis le compte ExpiredDomains.net.
    Colonnes du tableau :
      0=Domain  3=LE(length)  4=BL(backlinks)  5=DP  6=WBY  7=ABY  8=ACR(snapshots)
    """
    domaines = []
    url_map = {
        "fr":  "https://member.expireddomains.net/domains/expiredfr/",
        "com": "https://member.expireddomains.net/domains/expiredcom/",
        "net": "https://member.expireddomains.net/domains/expirednet/",
    }
    base_url = url_map.get(tld, url_map["fr"])

    def extraire_entier(texte: str) -> int:
        m = re.search(r"(\d+)", texte)
        return int(m.group(1)) if m else 0

    for page in range(1, pages + 1):
        try:
            params = {"start": (page - 1) * 25}
            r = session.get(base_url, params=params, timeout=15)
            if "login" in r.url.lower() or len(r.text) < 5000:
                log.warning(f"EDN .{tld} page {page}: session expirée ou page vide")
                break
            soup = BeautifulSoup(r.text, "lxml")
            table = soup.find("table")
            if not table:
                log.debug(f"EDN .{tld} page {page}: aucun tableau")
                break

            rows = table.find_all("tr")[1:]  # sauter l'en-tête
            page_count = 0
            for row in rows:
                cols = row.find_all("td")
                if len(cols) < 6:
                    continue
                # Colonne 0 : premier <a> dans la cellule = nom du domaine
                link = cols[0].find("a")
                if not link:
                    continue
                domain_name = link.get_text(strip=True).strip().lower()
                if not domain_name or "." not in domain_name:
                    continue
                # Col 4 = BL (referring domains)
                ref_domains = extraire_entier(cols[4].get_text(strip=True)) if len(cols) > 4 else 0
                # Col 8 = ACR (archive count ≈ wayback snapshots)
                wayback = extraire_entier(cols[8].get_text(strip=True)) if len(cols) > 8 else 0

                domaines.append({
                    "domain": domain_name,
                    "ref_domains": ref_domains,
                    "wayback_snapshots": wayback,
                })
                page_count += 1

            log.info(f"EDN .{tld} page {page} : {page_count} domaines")
            time.sleep(1.5)
        except Exception as e:
            log.warning(f"EDN scraping .{tld} page {page}: {e}")
            break

    return domaines

def scraper_expireddomains_net() -> list[dict]:
    """Source principale : scraping ExpiredDomains.net avec session authentifiée."""
    global EDN_SESSION
    if EDN_SESSION is None:
        EDN_SESSION = login_expireddomains()
    if EDN_SESSION is None:
        log.warning("EDN : scraping désactivé (pas de session valide)")
        return []

    tous = []
    for tld in ["fr", "com"]:
        domaines = scrape_expireddomains(EDN_SESSION, tld=tld, pages=5)
        tous.extend(domaines)
        time.sleep(2)

    log.info(f"ExpiredDomains.net : {len(tous)} domaines collectés (.fr + .com)")
    return tous

def recherche_inverse_sirene() -> list[dict]:
    """Source 0 : part de SIRENE → cherche si leur domaine expire bientôt.
    Utilise recherche-entreprises.api.gouv.fr — gratuit, sans clé API.
    """
    resultats = []
    # Cibles prioritaires : ETI/GE dans des secteurs à fort CPL
    requetes = [
        "categorie_entreprise:ETI activite_principale:64",   # finance
        "categorie_entreprise:ETI activite_principale:86",   # santé
        "categorie_entreprise:ETI activite_principale:68",   # immobilier
        "categorie_entreprise:GE activite_principale:35",    # énergie
        "categorie_entreprise:ETI activite_principale:62",   # informatique
    ]
    try:
        for q in requetes[:3]:  # limiter à 3 requêtes par run (quota temps)
            url = "https://recherche-entreprises.api.gouv.fr/search"
            params = {"q": q, "per_page": 25, "page": 1}
            r = requests.get(url, params=params, timeout=10)
            if r.status_code != 200:
                continue
            data = r.json()
            for ent in data.get("results", []):
                denomination = ent.get("nom_raison_sociale", "") or ent.get("nom_complet", "")
                categorie = ent.get("categorie_entreprise", "")
                commune = (ent.get("siege") or {}).get("libelle_commune", "")
                etat = (ent.get("siege") or {}).get("etat_administratif", "")
                if not denomination or etat != "A":
                    continue
                variantes = nom_vers_domaine(denomination, commune)
                for domaine in variantes:
                    rdap_data = rdap_lookup(domaine)
                    if rdap_data and rdap_data.get("expiry_date"):
                        jours = (rdap_data["expiry_date"] - datetime.now(timezone.utc)).days
                        if 0 < jours < 60:
                            resultats.append({
                                "domain": domaine,
                                "sirene_actif": True,
                                "sirene_nom_correspond": True,
                                "sirene_denomination": denomination,
                                "sirene_categorie_entreprise": categorie,
                                "expiry_date": rdap_data["expiry_date"].isoformat(),
                                "days_until_drop": jours,
                                "source": "sirene_inverse"
                            })
                time.sleep(DELAY)
    except Exception as e:
        log.warning(f"Recherche inverse SIRENE échouée: {e}")
    return resultats

def collecter_domaines() -> tuple[list[dict], list[dict]]:
    """Retourne (domaines_bruts, domaines_sirene_enrichis).
    Sources dans l'ordre :
      1. WebExpire.fr — domaines .fr en enchères, public, sans login (~50 domaines)
      2. ExpiredDomains.net — si session disponible (cookies Chrome ou secrets GitHub)
      3. SIRENE inversé — domaines générés depuis les entreprises actives
    """
    domaines_bruts = []

    # Source 1 : WebExpire.fr (toujours disponible, sans login)
    webexpire = scraper_webexpire()
    domaines_bruts.extend(webexpire)

    # Source 2 : ExpiredDomains.net (si session valide)
    edn = scraper_expireddomains_net()
    domaines_bruts.extend(edn)

    # Source 3 : recherche inversée SIRENE
    domaines_sirene = recherche_inverse_sirene()

    log.info(
        f"Collecte : {len(webexpire)} WebExpire + {len(edn)} EDN "
        f"+ {len(domaines_sirene)} SIRENE inversé = {len(domaines_bruts) + len(domaines_sirene)} total"
    )
    return domaines_bruts, domaines_sirene

# ── ÉTAPE 2 — Filtre rapide ───────────────────────────────────────────────────

def filtrer(domain: str, rd_scrape: int = 0) -> bool:
    nom = domain.rsplit(".", 1)[0] if "." in domain else domain
    tld = "." + domain.rsplit(".", 1)[1] if "." in domain else ""
    if len(nom) > CONFIG.get("longueur_max_domaine", 15):
        return False
    if "--" in nom:
        return False
    if nom.isdigit():
        return False
    if tld not in CONFIG.get("tlds_autorises", [".fr", ".com", ".net"]):
        return False
    rd_max = CONFIG.get("rd_max_backorder", 300)
    if rd_scrape and rd_scrape > rd_max:
        return False
    return True

# ── ÉTAPE 3A — RDAP ───────────────────────────────────────────────────────────

def rdap_lookup(domain: str) -> Optional[dict]:
    tld = domain.rsplit(".", 1)[-1] if "." in domain else ""
    if tld == "fr":
        url = f"https://rdap.nic.fr/domain/{domain}"
    elif tld == "com":
        url = f"https://rdap.verisign.com/com/v1/domain/{domain}"
    elif tld == "net":
        url = f"https://rdap.verisign.com/net/v1/domain/{domain}"
    else:
        return None
    try:
        r = requests.get(url, timeout=5)
        if r.status_code == 404:
            return {"status": "available"}
        r.raise_for_status()
        data = r.json()
        expiry_date = None
        for event in data.get("events", []):
            if event.get("eventAction") == "expiration":
                try:
                    expiry_date = dateutil_parser.parse(event["eventDate"]).replace(tzinfo=timezone.utc)
                except Exception:
                    pass
        registrar = ""
        for entity in data.get("entities", []):
            if "registrar" in entity.get("roles", []):
                registrar = entity.get("vcardArray", [None, []])[1]
                if isinstance(registrar, list):
                    for field in registrar:
                        if field[0] == "fn":
                            registrar = field[3]
                            break
        return {
            "expiry_date": expiry_date,
            "registrar": registrar,
            "status": data.get("status", [])
        }
    except Exception as e:
        log.debug(f"RDAP {domain}: {e}")
        return None

# ── ÉTAPE 3B — Wayback Machine ────────────────────────────────────────────────

def wayback_snapshots(domain: str) -> dict:
    try:
        url = f"http://web.archive.org/cdx/search/cdx?url={domain}&output=json&limit=1&fl=timestamp&fastLatest=true"
        r = requests.get(url, timeout=8)
        data = r.json()
        if len(data) > 1:
            return {"wayback_snapshots": 1, "date_derniere_archive": data[1][0]}
        url2 = f"http://web.archive.org/cdx/search/cdx?url={domain}/*&output=json&fl=timestamp&collapse=timestamp:6&limit=200"
        r2 = requests.get(url2, timeout=10)
        rows = r2.json()
        nb = max(0, len(rows) - 1)
        derniere = rows[-1][0] if nb > 0 else None
        return {"wayback_snapshots": nb, "date_derniere_archive": derniere}
    except Exception as e:
        log.debug(f"Wayback {domain}: {e}")
        return {"wayback_snapshots": 0, "date_derniere_archive": None}

# ── ÉTAPE 3C — OpenPageRank ───────────────────────────────────────────────────

def openpagerank(domain: str) -> dict:
    api_key = CONFIG.get("openpagerank_api_key", "")
    if not api_key or api_key.startswith("TA_"):
        return {"page_rank": 0}
    try:
        url = "https://openpagerank.com/api/v1.0/getPageRank"
        r = requests.get(url, params={"domains[0]": domain}, headers={"API-OPR": api_key}, timeout=8)
        data = r.json()
        pr = data.get("response", [{}])[0].get("page_rank_integer", 0) or 0
        return {"page_rank": int(pr)}
    except Exception as e:
        log.debug(f"OpenPageRank {domain}: {e}")
        return {"page_rank": 0}

# ── ÉTAPE 3D — INSEE SIRENE ───────────────────────────────────────────────────

def insee_sirene(domain: str) -> dict:
    """Vérifie si une entreprise française active correspond à ce domaine.
    Utilise recherche-entreprises.api.gouv.fr — gratuit, sans clé API.
    """
    nom_recherche = domain
    for ext in [".fr", ".com", ".net"]:
        nom_recherche = nom_recherche.replace(ext, "")
    nom_recherche = nom_recherche.replace("-", " ").strip()
    try:
        url = "https://recherche-entreprises.api.gouv.fr/search"
        params = {"q": nom_recherche, "per_page": 5}
        r = requests.get(url, params=params, timeout=8)
        if r.status_code != 200:
            return {"sirene_actif": False, "sirene_nom_correspond": False}
        data = r.json()
        for ent in data.get("results", []):
            denomination = ent.get("nom_raison_sociale", "") or ent.get("nom_complet", "")
            etat = (ent.get("siege") or {}).get("etat_administratif", "")
            if etat != "A" or not denomination:
                continue
            if normalise(nom_recherche) in normalise(denomination) or normalise(denomination) in normalise(nom_recherche):
                return {
                    "sirene_actif": True,
                    "sirene_nom_correspond": True,
                    "sirene_denomination": denomination,
                    "sirene_categorie_entreprise": ent.get("categorie_entreprise", ""),
                }
        return {"sirene_actif": False, "sirene_nom_correspond": False}
    except Exception as e:
        log.debug(f"SIRENE {domain}: {e}")
        return {"sirene_actif": False, "sirene_nom_correspond": False}

# ── ÉTAPE 3D2 — Annuaire Entreprises ─────────────────────────────────────────

def annuaire_entreprises(nom_recherche: str, domain: str) -> dict:
    try:
        url = f"https://recherche-entreprises.api.gouv.fr/search"
        r = requests.get(url, params={"q": nom_recherche, "limite": 3}, timeout=8)
        data = r.json()
        resultats = data.get("results", [])
        if not resultats:
            return {}
        ent = resultats[0]
        dirigeants = ent.get("dirigeants", [])
        dirigeant_nom = dirigeants[0].get("nom", "") if dirigeants else ""
        dirigeant_prenom = dirigeants[0].get("prenom", "") if dirigeants else ""
        site_internet = ent.get("site_internet", "") or ""
        has_autre_site = bool(site_internet) and site_internet.strip("/").replace("https://", "").replace("http://", "").strip("/") != domain.strip("/")
        return {
            "dirigeant_nom": dirigeant_nom,
            "dirigeant_prenom": dirigeant_prenom,
            "has_autre_site": has_autre_site,
        }
    except Exception as e:
        log.debug(f"Annuaire entreprises {nom_recherche}: {e}")
        return {}

# ── ÉTAPE 3E — Common Crawl ───────────────────────────────────────────────────

def common_crawl(domain: str) -> dict:
    try:
        url = f"http://index.commoncrawl.org/CC-MAIN-2024-51-index?url={domain}/*&output=json&limit=5"
        r = requests.get(url, timeout=10)
        lines = [l for l in r.text.strip().split("\n") if l]
        return {"common_crawl_pages": len(lines)}
    except Exception as e:
        log.debug(f"CommonCrawl {domain}: {e}")
        return {"common_crawl_pages": 0}

# ── ÉTAPE 3F — INPI ───────────────────────────────────────────────────────────

def inpi_marque(nom_sans_tld: str) -> dict:
    """Vérifie si le nom est une marque déposée à l'INPI.
    Scrape bases-marques.inpi.fr (recherche identique) — gratuit, sans token.
    Fallback sur l'API data.inpi.fr si un token est configuré.
    """
    # Essai 1 : scraping bases-marques.inpi.fr (gratuit, sans clé)
    try:
        from bs4 import BeautifulSoup
        url = "https://bases-marques.inpi.fr/Typo3_INPI/marques_frII_resultats.php"
        params = {
            "champ1": nom_sans_tld,
            "champ1Label": "Dénomination",
            "critere1": "1",   # recherche identique
            "bouton": "Lancer+la+recherche"
        }
        headers = {"User-Agent": "Mozilla/5.0 (compatible; DomainHunter/1.0)"}
        r = requests.get(url, params=params, headers=headers, timeout=10)
        if r.status_code == 200:
            soup = BeautifulSoup(r.text, "lxml")
            # Cherche les résultats indiquant une marque enregistrée
            texte = soup.get_text().lower()
            if "enregistrée" in texte or "enregistree" in texte or "registered" in texte:
                # Vérifie qu'il y a vraiment un résultat (pas juste la page vide)
                tables = soup.find_all("table")
                if tables and len(texte) > 500:
                    return {"inpi_marque_deposee": True}
        return {"inpi_marque_deposee": False}
    except Exception as e:
        log.debug(f"INPI scraping {nom_sans_tld}: {e}")

    # Fallback : API data.inpi.fr si token configuré
    token = CONFIG.get("inpi_token", "")
    if token and not token.startswith("TON_"):
        try:
            url = f"https://data.inpi.fr/marques?q={nom_sans_tld}"
            r = requests.get(url, headers={"Authorization": f"Bearer {token}"}, timeout=8)
            data = r.json()
            marques = data.get("results", data.get("marques", []))
            for m in marques:
                if m.get("statut", "").lower() in ("enregistrée", "enregistree", "registered"):
                    return {"inpi_marque_deposee": True}
        except Exception as e:
            log.debug(f"INPI API {nom_sans_tld}: {e}")

    return {"inpi_marque_deposee": False}

# ── ÉTAPE 3G — Réputation/Sécurité ───────────────────────────────────────────

SPAM_KEYWORDS = [
    "casino", "poker", "viagra", "cialis", "pharmacy", "pharma",
    "adult", "xxx", "porn", "payday loan", "cheap meds",
    "buy followers", "free iphone"
]

def check_reputation(domain: str, wayback_data: dict) -> dict:
    try:
        url = f"http://web.archive.org/cdx/search/cdx?url={domain}&output=json&limit=5&fl=original,statuscode,mimetype"
        r = requests.get(url, timeout=8)
        rows = r.json()[1:]
        for row in rows:
            content_url = f"https://web.archive.org/web/{row[0]}"
            try:
                page = requests.get(content_url, timeout=5)
                text_lower = page.text.lower()
                if any(kw in text_lower for kw in SPAM_KEYWORDS):
                    return {"domaine_blackliste": True}
            except Exception:
                pass
        return {"domaine_blackliste": False}
    except Exception as e:
        log.debug(f"Réputation {domain}: {e}")
        return {"domaine_blackliste": False}

# ── ÉTAPE 3H — Détection pivot PBN ───────────────────────────────────────────

SPAM_THEMES = ["casino", "poker", "pharma", "pharmacy", "adult", "xxx", "top 10", "best 2024", "best 2025"]
LEGITIMATE_THEMES = ["contact", "accueil", "about", "services", "entreprise", "association"]

def detect_pivot_pbn(domain: str) -> dict:
    try:
        url = f"http://web.archive.org/cdx/search/cdx?url={domain}&output=json&limit=10&from=2019&to=2026&collapse=timestamp:6&fl=timestamp,statuscode"
        r = requests.get(url, timeout=10)
        rows = r.json()[1:]
        if len(rows) < 2:
            return {"pivot_thematique_detecte": False}
        ancien_ts = rows[0][0]
        recent_ts = rows[-1][0]

        def get_keywords(ts):
            try:
                snap_url = f"https://web.archive.org/web/{ts}/{domain}"
                page = requests.get(snap_url, timeout=8)
                soup = BeautifulSoup(page.text, "lxml")
                text = soup.get_text().lower()
                return text
            except Exception:
                return ""

        ancien_text = get_keywords(ancien_ts)
        recent_text = get_keywords(recent_ts)
        ancien_legitime = any(t in ancien_text for t in LEGITIMATE_THEMES)
        recent_spam = any(t in recent_text for t in SPAM_THEMES)
        pivot = ancien_legitime and recent_spam
        return {"pivot_thematique_detecte": pivot}
    except Exception as e:
        log.debug(f"Pivot PBN {domain}: {e}")
        return {"pivot_thematique_detecte": False}

# ── ÉTAPE 4 — Scoring ─────────────────────────────────────────────────────────

THEMATIQUES_BANKABLES = [
    "immobilier", "maison", "habitat", "logement",
    "mode", "femme", "beaute", "fashion",
    "entreprise", "business", "emploi", "formation", "coaching",
    "sante", "medical", "bien-etre", "fitness", "musculation",
    "tourisme", "voyage", "hotel", "vacances",
    "informatique", "tech", "web", "digital", "ia", "intelligence",
    "voiture", "auto", "moto", "vehicule",
    "sport", "football", "tennis",
    "cuisine", "recette", "restaurant", "food",
    "animaux", "chien", "chat", "veterinaire",
    "finance", "bourse", "investissement", "trading", "crypto",
    "credit", "pret", "assurance", "mutuelle", "banque",
    "energie", "solaire", "panneaux", "electricite", "renovation",
    "juridique", "avocat", "droit", "divorce", "succession"
]

def calculate_score(domain_data: dict) -> tuple[int, bool]:
    score = 0
    flag_prudence = False

    sirene_ok = domain_data.get("sirene_actif") and domain_data.get("sirene_nom_correspond")
    if sirene_ok:
        score += 40
        categorie = domain_data.get("sirene_categorie_entreprise", "")
        if categorie == "GE":
            score += 15
        elif categorie == "ETI":
            score += 10
        elif categorie == "PME":
            score += 5

    snapshots = domain_data.get("wayback_snapshots", 0)
    if snapshots >= 50:
        score += 20
    elif snapshots >= 20:
        score += 10

    pr = domain_data.get("page_rank", 0)
    if pr >= 5:
        score += 25
    elif pr >= 3:
        score += 15
    elif pr >= 1:
        score += 5

    if domain_data.get("common_crawl_pages", 0) > 0:
        score += 10

    domain_lower = domain_data.get("domain", "").lower()
    if any(mot in domain_lower for mot in THEMATIQUES_BANKABLES):
        score += 10

    if domain_lower.endswith(".fr"):
        score += 5

    if domain_data.get("inpi_marque_deposee"):
        if sirene_ok:
            flag_prudence = True
        else:
            score -= 20

    if domain_data.get("ref_domains", 0) > 300:
        score -= 30

    if domain_data.get("pivot_thematique_detecte"):
        score -= 40

    if domain_data.get("domaine_blackliste"):
        score -= 50

    domain_data["flag_prudence"] = flag_prudence
    return min(max(score, 0), 100), flag_prudence

# ── ÉTAPE 5 — Estimation prix ─────────────────────────────────────────────────

def estimate_recovery_price(categorie_entreprise: str) -> tuple[int, int]:
    fourchettes = {
        "GE": (1500, 5000),
        "ETI": (800, 2500),
        "PME": (500, 1200),
    }
    return fourchettes.get(categorie_entreprise, (300, 800))

def estimate_sale_price(page_rank: int, ref_domains: int) -> tuple[int, int]:
    if page_rank >= 5:
        price_pr = 200
    elif page_rank >= 3:
        price_pr = 100
    elif page_rank >= 1:
        price_pr = 60
    else:
        price_pr = 34

    if ref_domains >= 200:
        price_rd = 133
    elif ref_domains >= 100:
        price_rd = 60
    else:
        price_rd = 34

    estimated = max(price_pr, price_rd)
    return (estimated, int(estimated * 1.5))

def estimate_final_price(domain_data: dict) -> tuple[int, int]:
    sirene_ok = domain_data.get("sirene_actif") and domain_data.get("sirene_nom_correspond")
    fourchette_seo = estimate_sale_price(
        domain_data.get("page_rank", 0),
        domain_data.get("ref_domains", 0)
    )
    if sirene_ok:
        fourchette_sirene = estimate_recovery_price(domain_data.get("sirene_categorie_entreprise", ""))
        if domain_data.get("has_autre_site"):
            fourchette_sirene = (int(fourchette_sirene[0] * 0.7), int(fourchette_sirene[1] * 0.7))
        return max(fourchette_sirene, fourchette_seo, key=lambda f: f[0])
    return fourchette_seo

# ── ÉTAPE 6 — Alerte Telegram ─────────────────────────────────────────────────

def send_telegram_alert(domain_data: dict, score: int, fourchette_prix: tuple) -> None:
    token = CONFIG.get("telegram_token", "")
    chat_id = CONFIG.get("telegram_chat_id", "")
    if not token or token.startswith("TON_"):
        log.warning("Telegram non configuré, alerte ignorée.")
        return

    pr = domain_data.get("page_rank", 0)
    rd = domain_data.get("ref_domains", 0)
    snapshots = domain_data.get("wayback_snapshots", 0)
    sirene = domain_data.get("sirene_denomination", "Non trouvée")
    sirene_ok = domain_data.get("sirene_actif") and domain_data.get("sirene_nom_correspond")
    sirene_statut = "✅ ACTIVE — correspondance confirmée" if sirene_ok else "❌ Non trouvée / pas de correspondance fiable"
    categorie = domain_data.get("sirene_categorie_entreprise") or "TPE/indépendant"
    flag = domain_data.get("flag_prudence", False)
    inpi = domain_data.get("inpi_marque_deposee", False)

    if flag:
        ligne_marque = "🟠 MARQUE DÉPOSÉE — entreprise active derrière : approche rapide et raisonnable (pas de négociation agressive)"
    elif inpi:
        ligne_marque = "⚠️ MARQUE DÉPOSÉE — pas d'entreprise active identifiée, risque juridique"
    else:
        ligne_marque = "✅ Non déposée — OK légalement"

    prix_min, prix_max = fourchette_prix
    days_left = domain_data.get("days_until_drop", "?")
    dirigeant_prenom = domain_data.get("dirigeant_prenom", "")
    dirigeant_nom = domain_data.get("dirigeant_nom", "")
    dirigeant = f"{dirigeant_prenom} {dirigeant_nom}".strip() or "Madame, Monsieur"
    has_autre_site = domain_data.get("has_autre_site", False)
    site_note = (
        "⚠️ Entreprise semble avoir un autre site actif — urgence réduite, prix ajusté"
        if has_autre_site else
        "✅ Aucun autre site détecté — entreprise sans présence web"
    )

    try:
        days_int = int(days_left)
        if days_int > 0:
            timing_note = f"📆 Pas encore tombé ({days_int}j) — backorder maintenant, contacter dans 48h après le drop"
        else:
            jpp = abs(days_int)
            if jpp <= 30:
                timing_note = f"🔥 DROP RÉCENT ({jpp}j) — FENÊTRE IDÉALE, contacter maintenant"
            elif jpp <= 90:
                timing_note = f"⏳ Drop il y a {jpp}j — encore exploitable"
            else:
                timing_note = f"❄️ Drop il y a {jpp}j — intérêt réduit, entreprise probablement reconstruite ailleurs"
    except (ValueError, TypeError):
        timing_note = "📆 Date de drop inconnue — contacter dès acquisition confirmée"

    domain_name = domain_data.get("domain", "")

    email_template = f"""---
✉️ *TEMPLATE EMAIL — à adapter :*

Objet : Votre nom de domaine {domain_name}

Bonjour {dirigeant},

Je me permets de vous contacter au sujet du nom de domaine {domain_name}, qui correspond à votre entreprise {sirene}.

Ce domaine vient de devenir disponible suite à sa non-reconduction. Je l'ai récemment acquis et souhaite vous proposer en priorité de le récupérer avant qu'il soit utilisé par un tiers.

Je vous propose de vous le céder pour {prix_min}€ \\(virement bancaire ou PayPal\\), transfert immédiat une fois le paiement reçu.

Cordialement,
[Votre nom]
---"""

    message = f"""{"🟠" if flag else "🎯"} *DOMAINE — Revente estimée {prix_min}–{prix_max}€*

🌐 Domaine : `{domain_name}`
📅 Drop dans : {days_left} jours
📊 Score : {score}/100
🏢 SIRENE : {sirene} \\({categorie}\\) — {sirene_statut}
👤 Dirigeant : {dirigeant}
🌍 Présence web : {site_note}
📸 Wayback : {snapshots} snapshots
🔗 Backlinks : {rd} RD, score d'autorité {pr}/10
⚖️ Marque INPI : {ligne_marque}
{timing_note}

📌 *Actions :*
→ Backorder DropCatch \\(.com\\)
→ Backorder Dynadot \\(.fr\\)
→ Backorder WebExpire si .fr \\(30€, AFNIC\\)
→ [Fiche SIRENE](https://annuaire-entreprises.data.gouv.fr/rechercher?terme={sirene})

{email_template}

📎 Max 2 plateformes de backorder par domaine."""

    try:
        url = f"https://api.telegram.org/bot{token}/sendMessage"
        requests.post(url, json={
            "chat_id": chat_id,
            "text": message,
            "parse_mode": "MarkdownV2",
            "disable_web_page_preview": True
        }, timeout=10)
        log.info(f"Alerte Telegram envoyée : {domain_name}")
    except Exception as e:
        log.error(f"Telegram envoi échoué pour {domain_name}: {e}")

# ── Supabase ──────────────────────────────────────────────────────────────────

def supabase_headers() -> dict:
    key = CONFIG.get("supabase_service_key", "")
    return {
        "apikey": key,
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
        "Prefer": "resolution=merge-duplicates"
    }

def upsert_domain(domain_data: dict) -> None:
    base_url = CONFIG.get("supabase_url", "")
    if not base_url or base_url.startswith("TON_"):
        return
    payload = {k: v for k, v in domain_data.items() if not isinstance(v, datetime)}
    try:
        r = requests.post(
            f"{base_url}/rest/v1/domains_scanned",
            headers=supabase_headers(),
            json=payload,
            timeout=10
        )
        if r.status_code not in (200, 201):
            log.warning(f"Supabase upsert {domain_data.get('domain')}: {r.status_code} {r.text[:200]}")
    except Exception as e:
        log.warning(f"Supabase upsert {domain_data.get('domain')}: {e}")

def domaine_deja_alerte(domain: str) -> bool:
    base_url = CONFIG.get("supabase_url", "")
    if not base_url or base_url.startswith("TON_"):
        return False
    key = CONFIG.get("supabase_service_key", "")
    try:
        r = requests.get(
            f"{base_url}/rest/v1/domains_scanned?domain=eq.{domain}&select=alerte_telegram_envoyee",
            headers={"apikey": key, "Authorization": f"Bearer {key}"},
            timeout=10
        )
        data = r.json()
        return data[0]["alerte_telegram_envoyee"] if data else False
    except Exception:
        return False

def marquer_alerte_envoyee(domain: str) -> None:
    base_url = CONFIG.get("supabase_url", "")
    if not base_url or base_url.startswith("TON_"):
        return
    key = CONFIG.get("supabase_service_key", "")
    try:
        requests.patch(
            f"{base_url}/rest/v1/domains_scanned?domain=eq.{domain}",
            headers={
                "apikey": key,
                "Authorization": f"Bearer {key}",
                "Content-Type": "application/json"
            },
            json={"alerte_telegram_envoyee": True},
            timeout=10
        )
    except Exception as e:
        log.warning(f"Supabase patch alerte {domain}: {e}")

# ── Pipeline principal ────────────────────────────────────────────────────────

def enrichir_domaine(domain: str, pre_enriched: dict = None) -> Optional[dict]:
    """Enrichit un domaine avec toutes les APIs et retourne les données complètes."""
    domain_data = {"domain": domain, "date_scan": datetime.now(timezone.utc).isoformat()}
    if pre_enriched:
        domain_data.update(pre_enriched)

    # A — RDAP
    rdap = rdap_lookup(domain)
    if rdap:
        expiry = rdap.get("expiry_date")
        if expiry:
            days = (expiry - datetime.now(timezone.utc)).days
            domain_data["days_until_drop"] = days
            domain_data["jours_avant_drop"] = days if days > 0 else 0
            domain_data["jours_post_drop"] = abs(days) if days <= 0 else 0
        domain_data["registrar"] = rdap.get("registrar", "")
    time.sleep(DELAY)

    # D — SIRENE (sauf si déjà enrichi via source inversée)
    if not pre_enriched or not pre_enriched.get("sirene_actif"):
        sirene_data = insee_sirene(domain)
        domain_data.update(sirene_data)
        time.sleep(DELAY)

    # D2 — Annuaire Entreprises (seulement si correspondance SIRENE confirmée)
    if domain_data.get("sirene_nom_correspond"):
        nom_r = domain.rsplit(".", 1)[0].replace("-", " ")
        annuaire_data = annuaire_entreprises(nom_r, domain)
        domain_data.update(annuaire_data)
        time.sleep(DELAY)

    # C — OpenPageRank (seulement si SIRENE actif ou potentiel SEO)
    pr_data = openpagerank(domain)
    domain_data.update(pr_data)
    time.sleep(DELAY)

    # B — Wayback
    wb_data = wayback_snapshots(domain)
    domain_data.update(wb_data)
    time.sleep(DELAY)

    # E — Common Crawl
    cc_data = common_crawl(domain)
    domain_data.update(cc_data)
    time.sleep(DELAY)

    # F — INPI
    nom_sans_tld = domain.rsplit(".", 1)[0] if "." in domain else domain
    inpi_data = inpi_marque(nom_sans_tld)
    domain_data.update(inpi_data)
    time.sleep(DELAY)

    # G — Réputation
    rep_data = check_reputation(domain, wb_data)
    domain_data.update(rep_data)
    time.sleep(DELAY)

    # H — Pivot PBN (seulement si snapshots suffisants)
    if domain_data.get("wayback_snapshots", 0) >= 5:
        pbn_data = detect_pivot_pbn(domain)
        domain_data.update(pbn_data)
        time.sleep(DELAY)
    else:
        domain_data["pivot_thematique_detecte"] = False

    return domain_data

def run():
    log.info("=== Domain Hunter démarré ===")
    stats = {"collectes": 0, "apres_filtre": 0, "en_base": 0, "alertes": 0}

    domaines_edn, domaines_sirene = collecter_domaines()
    stats["collectes"] = len(domaines_edn) + len(domaines_sirene)

    pipeline = []
    domaines_vus = set()

    # Source 0 : SIRENE inversé — déjà enrichis, priorité maximale
    for d in domaines_sirene:
        pipeline.append((d["domain"], d))
        domaines_vus.add(d["domain"])

    # Source 1 : ExpiredDomains.net — dicts avec ref_domains + wayback_snapshots scrapés
    for d in domaines_edn:
        domain = d.get("domain", "")
        if not domain or domain in domaines_vus:
            continue
        rd = d.get("ref_domains", 0)
        if filtrer(domain, rd):
            pipeline.append((domain, {"ref_domains": rd, "wayback_snapshots": d.get("wayback_snapshots", 0)}))
            domaines_vus.add(domain)

    pipeline = pipeline[:MAX_DOMAINES]
    stats["apres_filtre"] = len(pipeline)
    log.info(f"Filtre : {stats['apres_filtre']} domaines à enrichir")

    prix_seuil = CONFIG.get("prix_minimum_alerte", 500)

    for domain, pre_enriched in pipeline:
        try:
            domain_data = enrichir_domaine(domain, pre_enriched or None)
            if not domain_data:
                continue

            score, flag_prudence = calculate_score(domain_data)
            domain_data["score"] = score
            domain_data["flag_prudence"] = flag_prudence

            fourchette = estimate_final_price(domain_data)
            domain_data["prix_estime_min"] = fourchette[0]
            domain_data["prix_estime_max"] = fourchette[1]

            # Écrire en base tous les domaines retenus (pas seulement les alertes)
            upsert_domain(domain_data)
            stats["en_base"] += 1

            # Alerte Telegram si prix borne basse >= seuil et pas déjà alerté
            if fourchette[0] >= prix_seuil and not domaine_deja_alerte(domain):
                send_telegram_alert(domain_data, score, fourchette)
                marquer_alerte_envoyee(domain)
                stats["alertes"] += 1

        except Exception as e:
            log.error(f"Erreur pipeline {domain}: {e}")

    log.info(
        f"=== Fin : {stats['collectes']} collectés → {stats['apres_filtre']} après filtre "
        f"→ {stats['en_base']} écrits en base → {stats['alertes']} alertes Telegram ==="
    )

if __name__ == "__main__":
    run()
