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
from datetime import datetime, timedelta, timezone
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
        "rd_min_seo": 2,
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
        "catchdoms_token":      "CATCHDOMS_TOKEN",
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

def mots_significatifs(texte: str) -> set[str]:
    """Mots normalisés (≥3 caractères) — utilisé pour comparer des noms mot à mot
    plutôt qu'en sous-chaîne brute, qui matchait des fragments à l'intérieur d'un
    autre mot sans rapport (ex: "go" dans "diego")."""
    texte = unicodedata.normalize("NFKD", texte.lower()).encode("ascii", "ignore").decode()
    return {m for m in re.findall(r"[a-z0-9]+", texte) if len(m) >= 3}

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
            # Colonnes du HTML brut (vérifiées via requests+BeautifulSoup, pas le DOM
            # JS-hydraté qui ajoute une colonne "enchérisseur" en plus) :
            # 0=Nom 1=icône GMB 2=Fin 3=BL 4=RD 5=TF 6=CF 7=VI 8=TR 9=KW 10=NB
            # 11=Prix actuel 12=Action (lien /offres/new)
            def col_int(idx):
                if len(cols) > idx:
                    m = re.search(r"(\d+)", cols[idx].get_text(strip=True))
                    return int(m.group(1)) if m else 0
                return 0
            bl = col_int(3)
            rd = col_int(4)
            tf = col_int(5)
            cf = col_int(6)
            vi = col_int(7)
            tr = col_int(8)
            kw = col_int(9)
            nb = col_int(10)
            # Col 2 = délai (ex: "7 jours", "3 heures")
            delai_txt = cols[2].get_text(strip=True)
            # Col 11 = prix actuel de l'enchère (ex: "80.00 €")
            prix_actuel = 0.0
            if len(cols) > 11:
                m = re.search(r"([\d.,]+)", cols[11].get_text(strip=True))
                if m:
                    prix_actuel = float(m.group(1).replace(",", "."))
            # Col 12 = lien direct vers la page d'enchère de ce domaine précis
            lien_enchere = None
            if len(cols) > 12:
                a = cols[12].find("a", href=re.compile(r"/offres/new"))
                if a and a.get("href"):
                    href = a["href"]
                    lien_enchere = href if href.startswith("http") else f"https://www.webexpire.fr{href}"
            domaines.append({
                "domain": domain_name,
                "ref_domains": rd,
                "wayback_snapshots": bl,  # BL comme proxy wayback (seule métrique dispo sans API)
                "trust_flow": tf,
                "citation_flow": cf,
                "webexpire_visites": vi,
                "webexpire_trafic": tr,
                "webexpire_mots_cles": kw,
                "webexpire_nb": nb,
                "source": "webexpire",
                "delai_enchere": delai_txt,
                "webexpire_prix_actuel": prix_actuel,
                "webexpire_lien": lien_enchere,
            })
        log.info(f"WebExpire: {len(domaines)} domaines .fr collectés")
    except Exception as e:
        log.warning(f"WebExpire scraping: {e}")
    return domaines

# ── Source CatchDoms (API officielle, remplace EDN — comptes bannis 2x) ───────

def fetch_catchdoms(tld: str = ".fr,.com", type_: str = "auction", rd_min: int = 2,
                     per_page: int = 100, max_pages: int = 15) -> list[dict]:
    """
    Collecte les domaines en enchère via l'API CatchDoms (catchdoms.com/api/domains).
    Pas de paramètre "source" → agrège nativement les 20 plateformes prises en
    charge (Dynadot, GoDaddy, DropCatch, NameShift, WebExpire, BloomUp,
    SEO.Domains, etc.), pas seulement une plateforme par défaut.
    type="auction" : ne garde que les domaines réellement aux enchères (pas les
    closeouts/backorders, hors-sujet pour ce filtre).
    rd_min=2 : seuil minimum du cahier des charges (Filtre 1 SEO, "2-3 RD").
    """
    token = CONFIG.get("catchdoms_token", "")
    if not token or token.startswith("TON_"):
        log.warning("CatchDoms : token non configuré, source désactivée.")
        return []

    headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
    domaines = []
    for page in range(1, max_pages + 1):
        try:
            r = requests.get(
                "https://catchdoms.com/api/domains",
                headers=headers,
                params={
                    "tld": tld,
                    "type": type_,
                    "rd_min": rd_min,
                    "per_page": per_page,
                    "page": page,
                },
                timeout=15,
            )
            if r.status_code == 429:
                log.warning("CatchDoms : rate limit atteint, on s'arrête pour ce run.")
                break
            r.raise_for_status()
            data = r.json()
            items = data.get("data", [])
            if not items:
                break
            for item in items:
                nom = (item.get("name") or "").lower()
                if not nom:
                    continue
                domaines.append({
                    "domain": nom,
                    "ref_domains": item.get("referring_domains") or 0,
                    "wayback_snapshots": item.get("wayback_snapshots") or 0,
                    "trust_flow": item.get("trust_flow") or 0,
                    "citation_flow": item.get("citation_flow") or 0,
                    "domain_authority": item.get("domain_authority") or 0,
                    "catchdoms_score": item.get("score") or 0,
                    "catchdoms_type": item.get("type"),
                    "catchdoms_max_bid": item.get("max_bid"),
                    "catchdoms_bids_count": item.get("bids_count"),
                    "catchdoms_auction_end_date": item.get("auction_end_date"),
                    "catchdoms_purchase_url": item.get("purchase_url"),
                    # "source" dans la réponse API = la plateforme réelle (NameShift,
                    # GoDaddy, WebExpire...) ; "purchase_platform" n'est pas un champ
                    # documenté mais on le garde en repli si jamais présent.
                    "catchdoms_purchase_platform": item.get("source") or item.get("purchase_platform"),
                    "has_gmb": item.get("has_gmb", False),
                    "language": item.get("language"),
                    "whois_expires_at": item.get("whois_expires_at"),
                    "source": "catchdoms",
                })
            log.info(f"CatchDoms {tld} ({type_}) page {page} : {len(items)} domaines")

            meta = data.get("meta", {})
            last_page = meta.get("last_page", page)
            if page >= last_page:
                break
            time.sleep(0.5)
        except Exception as e:
            log.warning(f"CatchDoms {tld} page {page}: {e}")
            break

    log.info(f"CatchDoms : {len(domaines)} domaines {tld} ({type_}) collectés, toutes plateformes")
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
    # Stratégie 1 : cookies Chrome (dev local uniquement, jamais sur GitHub Actions)
    import platform, os as _os
    chrome_db_paths = {
        "Darwin": _os.path.expanduser("~/Library/Application Support/Google/Chrome/Default/Cookies"),
        "Linux":  _os.path.expanduser("~/.config/google-chrome/Default/Cookies"),
    }
    chrome_db = chrome_db_paths.get(platform.system(), "")
    if chrome_db and _os.path.exists(chrome_db):
        try:
            import browser_cookie3
            chrome_cookies = list(browser_cookie3.chrome(domain_name=".expireddomains.net"))
            if chrome_cookies:
                session = _make_edn_session()
                for c in chrome_cookies:
                    session.cookies.set(c.name, c.value, domain=c.domain)
                if _edn_session_valide(session):
                    log.info("EDN : session via cookies Chrome (dev local)")
                    return session
        except ImportError:
            pass
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
                # Col 5 = DP (drop date, ex: "2026-06-22" ou "22 Jun 2026")
                drop_date_str = cols[5].get_text(strip=True) if len(cols) > 5 else ""
                drop_date_edn = None
                if drop_date_str:
                    try:
                        drop_date_edn = dateutil_parser.parse(drop_date_str, dayfirst=True).replace(tzinfo=timezone.utc)
                    except Exception:
                        pass
                # Col 8 = ACR (archive count ≈ wayback snapshots)
                wayback = extraire_entier(cols[8].get_text(strip=True)) if len(cols) > 8 else 0

                domaines.append({
                    "domain": domain_name,
                    "ref_domains": ref_domains,
                    "wayback_snapshots": wayback,
                    "drop_date_edn": drop_date_edn,
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

def collecter_domaines() -> list[dict]:
    """Retourne la liste des domaines bruts collectés depuis les sources réelles
    d'enchères/expirations (jamais générés/devinés à partir d'un nom d'entreprise).
    Deux sources sans risque de bannissement, sans abonnement payant requis :
      1. CatchDoms (API officielle, essai gratuit) — agrège déjà 20 plateformes
         (Dynadot, GoDaddy, DropCatch, NameShift, WebExpire, BloomUp, etc.), mais
         l'essai masque une partie des annonces du jour derrière un mur "upgrade
         to Pro" — on récupère ce qu'il laisse passer.
      2. WebExpire.fr (scraping direct, public, gratuit) — comble une partie du
         manque : CatchDoms ne reflète qu'~1/3 des annonces WebExpire réelles
         (vérifié en direct), donc le scraper direct est plus complet et gratuit.
    La correspondance SIRENE (si le nom du domaine ressemble explicitement à une
    entreprise active) est vérifiée plus tard, en lecture seule, sur ces domaines
    réels — jamais l'inverse.
    """
    catchdoms = fetch_catchdoms(tld=".fr,.com", type_="auction", rd_min=2)
    webexpire = scraper_webexpire()
    log.info(f"Collecte : {len(catchdoms)} CatchDoms + {len(webexpire)} WebExpire = {len(catchdoms) + len(webexpire)} total")
    return catchdoms + webexpire

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

EMAIL_REGEX = re.compile(r"[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+")
EMAIL_DOMAINES_IGNORES = (
    "sentry.io", "wordpress.org", "wordpress.com", "wix.com", "godaddy.com",
    "example.com", "domain.com", "schema.org", "w3.org", "googleapis.com",
    "gstatic.com", "cloudflare.com", "sentry-cdn.com",
)

def extraire_email_wayback(url: str) -> Optional[str]:
    """Cherche un email de contact dans la dernière archive Wayback Machine d'un site
    (best-effort, gratuit — Pappers/PagesJaunes ne donnent pas d'email sans abonnement)."""
    url_propre = url.strip().replace("https://", "").replace("http://", "").strip("/")
    if not url_propre:
        return None
    try:
        cdx = f"http://web.archive.org/cdx/search/cdx?url={url_propre}&output=json&limit=1&fl=timestamp&fastLatest=true"
        r = requests.get(cdx, timeout=8)
        data = r.json()
        if len(data) < 2:
            return None
        timestamp = data[1][0]
        snap_url = f"https://web.archive.org/web/{timestamp}/{url_propre}"
        page = requests.get(snap_url, timeout=10)
        emails = EMAIL_REGEX.findall(page.text)
        emails = [
            e for e in emails
            if not any(ignore in e.lower() for ignore in EMAIL_DOMAINES_IGNORES)
            and not e.lower().endswith((".png", ".jpg", ".gif", ".svg"))
        ]
        if not emails:
            return None
        # Préférer un email du même nom de domaine que le site (plus probable d'être le bon contact)
        domaine_racine = url_propre.split("/")[0].replace("www.", "")
        for e in emails:
            if domaine_racine.lower() in e.lower():
                return e.lower()
        return emails[0].lower()
    except Exception as e:
        log.debug(f"Email wayback {url}: {e}")
        return None

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
            mots_domaine = mots_significatifs(nom_recherche)
            mots_denom = mots_significatifs(denomination)
            # Tous les mots du domaine doivent se retrouver tels quels (mot entier,
            # pas un fragment) dans la dénomination, ou inversement pour les noms
            # composés courts (ex: domaine "poopy" == dénomination "POOPY").
            # Fallback en égalité stricte (sans espaces) pour les sigles courts
            # (ex: "J C A" → mots de 1 caractère filtrés, mais "jca" == "jca").
            match = (
                bool(mots_domaine) and (mots_domaine.issubset(mots_denom) or mots_denom.issubset(mots_domaine))
            ) or normalise(nom_recherche) == normalise(denomination)
            if match:
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
            "site_internet": site_internet,
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
    elif domain_data.get("site_etait_actif"):
        # Pas de société identifiée nommément, mais le site avait un vrai
        # contenu actif avant de tomber : opportunité de revente plausible,
        # juste moins actionnable immédiatement (pas de contact direct).
        score += 15

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

# Logique A (Filtre 2 — revente à l'ancien propriétaire) : Namebio/Majestic/INPI →
# fourchette basée sur la taille de l'entreprise, ajustée par le Trust Flow réel.
def estimate_recovery_price(categorie_entreprise: str, trust_flow: int = 0) -> tuple[int, int]:
    fourchettes = {
        "GE": (1500, 5000),
        "ETI": (800, 2500),
        "PME": (500, 1200),
    }
    prix_min, prix_max = fourchettes.get(categorie_entreprise, (300, 800))
    if trust_flow >= 30:
        return (int(prix_min * 1.3), int(prix_max * 1.3))
    if trust_flow >= 20:
        return (int(prix_min * 1.15), int(prix_max * 1.15))
    return (prix_min, prix_max)

# Logique B (Filtre 1 — SEO/vente de liens) : grille de tarification complète du guide
# Mathieu (Trafic SEMrush x TF x DR/DA, étude sur 14 098 sites .fr). WebExpire fournit
# directement le trafic (colonne TR) ; sans cette donnée (ex: CatchDoms), on retombe
# sur les seuils différenciants TF/DA/RD.
def estimate_sale_price_seo(domain_data: dict) -> tuple[int, int]:
    tf = domain_data.get("trust_flow") or 0
    da = domain_data.get("domain_authority") or 0
    rd = domain_data.get("ref_domains") or 0
    trafic = domain_data.get("webexpire_trafic")

    if trafic is not None:
        if trafic >= 50000 and tf >= 35:
            base = (150, 300)
        elif trafic >= 10000 and tf >= 30:
            base = (120, 200)
        elif trafic >= 2000 and tf >= 25:
            base = (80, 120)
        elif trafic >= 500 and tf >= 15:
            base = (50, 79)
        else:
            base = (29, 49)
        if da >= 40:
            base = (max(base[0], 150), max(base[1], 300))
        elif da >= 30:
            base = (max(base[0], 80), max(base[1], 120))
        return base

    fourchettes = []
    if tf >= 30:
        fourchettes.append((100, 200))
    elif tf >= 20:
        fourchettes.append((50, 90))

    if da >= 30:
        fourchettes.append((100, 150))
    elif da >= 20:
        fourchettes.append((50, 90))

    if rd >= 200:
        fourchettes.append((100, 133))
    elif rd >= 50:
        fourchettes.append((60, 100))
    elif rd >= 3:
        fourchettes.append((34, 60))

    if not fourchettes:
        return (29, 49)
    return max(fourchettes, key=lambda f: f[0])

def estimate_final_price(domain_data: dict) -> tuple[int, int]:
    sirene_ok = domain_data.get("sirene_actif") and domain_data.get("sirene_nom_correspond")
    if sirene_ok:
        fourchette = estimate_recovery_price(
            domain_data.get("sirene_categorie_entreprise", ""),
            domain_data.get("trust_flow") or 0
        )
        if domain_data.get("has_autre_site"):
            fourchette = (int(fourchette[0] * 0.7), int(fourchette[1] * 0.7))

        # Le prix de l'enchère réelle (un tiers se bat déjà pour ce domaine) est un
        # signal de valeur bien plus fort que la fourchette théorique par taille
        # d'entreprise — sans ça on pouvait afficher "300–800€" sur un domaine déjà
        # enchéri à 15 000€ par un repreneur, ce qui n'a aucun sens.
        prix_marche = domain_data.get("catchdoms_max_bid") or domain_data.get("webexpire_prix_actuel")
        if prix_marche and prix_marche > fourchette[1]:
            fourchette = (int(prix_marche), int(prix_marche * 1.5))

        return fourchette

    fourchette_seo = estimate_sale_price_seo(domain_data)
    prix_actuel = domain_data.get("webexpire_prix_actuel")
    domain_data["badge_surpaye"] = bool(prix_actuel and prix_actuel > fourchette_seo[1])
    return fourchette_seo

# ── ÉTAPE 6 — Alerte Telegram ─────────────────────────────────────────────────

def _timing_note(days_left) -> str:
    try:
        days_int = int(days_left)
        if days_int > 0:
            return f"📆 Pas encore tombé ({days_int}j) — backorder maintenant, contacter dans 48h après le drop"
        jpp = abs(days_int)
        if jpp <= 30:
            return f"🔥 DROP RÉCENT ({jpp}j) — FENÊTRE IDÉALE, contacter maintenant"
        elif jpp <= 90:
            return f"⏳ Drop il y a {jpp}j — encore exploitable"
        return f"❄️ Drop il y a {jpp}j — intérêt réduit"
    except (ValueError, TypeError):
        return "📆 Date de drop inconnue — contacter dès acquisition confirmée"

def _envoyer_message_telegram(message: str, domain_name: str) -> None:
    token = CONFIG.get("telegram_token", "")
    chat_id = CONFIG.get("telegram_chat_id", "")
    if not token or token.startswith("TON_"):
        log.warning("Telegram non configuré, alerte ignorée.")
        return
    try:
        url = f"https://api.telegram.org/bot{token}/sendMessage"
        r = requests.post(url, json={
            "chat_id": chat_id,
            "text": message,
            "parse_mode": "Markdown",
            "disable_web_page_preview": True
        }, timeout=10)
        resp = r.json()
        if resp.get("ok"):
            log.info(f"Alerte Telegram envoyée : {domain_name}")
        else:
            log.error(f"Telegram rejeté pour {domain_name}: {resp.get('description')}")
            raise RuntimeError(resp.get("description", "Telegram error"))
    except Exception as e:
        log.error(f"Telegram envoi échoué pour {domain_name}: {e}")
        raise  # remonte pour que marquer_alerte_envoyee ne soit pas appelé

def send_telegram_alert_revente(domain_data: dict, score: int, fourchette_prix: tuple) -> None:
    """Filtre 2 — domaine correspondant à une entreprise active : revente à l'ancien
    propriétaire. Met en avant SIRENE, dirigeant, INPI — rien de tout ça n'a de sens
    côté SEO pur (voir send_telegram_alert_seo)."""
    domain_name = domain_data.get("domain", "")
    prix_min, prix_max = fourchette_prix
    days_left = domain_data.get("days_until_drop", "?")
    sirene = domain_data.get("sirene_denomination", "Non trouvée")
    categorie = domain_data.get("sirene_categorie_entreprise") or "TPE/indépendant"
    dirigeant_prenom = domain_data.get("dirigeant_prenom", "")
    dirigeant_nom = domain_data.get("dirigeant_nom", "")
    dirigeant = f"{dirigeant_prenom} {dirigeant_nom}".strip() or "Madame, Monsieur"
    snapshots = domain_data.get("wayback_snapshots", 0)
    presence_web = (
        "✅ Contenu détecté \\(Common Crawl\\)"
        if domain_data.get("common_crawl_pages", 0) > 0 else
        "❌ Aucun contenu indexé détecté"
    )
    email = domain_data.get("email_contact") or "non trouvé"

    sirene_ok = domain_data.get("sirene_actif") and domain_data.get("sirene_nom_correspond")
    if sirene_ok:
        ligne_sirene = f"🏢 SIRENE : {sirene} \\({categorie}\\) — ✅ ACTIVE"
    else:
        ligne_sirene = "🏢 SIRENE : ⚠️ société non identifiée — site actif détecté avant le drop, ancien propriétaire à retrouver manuellement"

    flag = domain_data.get("flag_prudence", False)
    inpi = domain_data.get("inpi_marque_deposee", False)
    if flag:
        ligne_marque = "🟠 MARQUE DÉPOSÉE — entreprise active derrière : approche rapide et raisonnable (pas de négociation agressive)"
    elif inpi:
        ligne_marque = "⚠️ MARQUE DÉPOSÉE — pas d'entreprise active identifiée, risque juridique"
    else:
        ligne_marque = "✅ Non déposée — OK légalement"

    en_enchere = domain_data.get("source") == "webexpire" and domain_data.get("webexpire_lien")
    prix_actuel = domain_data.get("webexpire_prix_actuel") or 0
    lien_webexpire = domain_data.get("webexpire_lien")

    if en_enchere:
        titre = "🔥 *DOMAINE EN ENCHÈRE SUR WEBEXPIRE — Opportunité de revente*"
        ligne_enchere = "📈 Enchère sur WebExpire : ✅ Oui"
        ligne_prix = f"💰 Prix actuel WebExpire : {prix_actuel:.2f}€"
        action = f"→ [Voir l'enchère sur WebExpire]({lien_webexpire})"
    else:
        titre = "🎯 *DOMAINE DISPONIBLE — Opportunité de revente*"
        ligne_enchere = "📈 Enchère sur WebExpire : ❌ Non \\(autre source\\)"
        ligne_prix = "💰 Prix actuel WebExpire : non disponible"
        action = "→ [Voir sur WebExpire](https://www.webexpire.fr/encheres)"

    bonus = ""
    if domain_data.get("deja_reenregistre_tiers"):
        registrar = domain_data.get("registrar", "") or "inconnu"
        bonus = f"""

⚠️ Ce domaine n'est plus disponible en backorder — il a déjà été ré-enregistré par un tiers \\(registrar : {registrar}\\).
📌 *Recours légal :* procédure PARL EXPERT \\(AFNIC, ~250€\\) si atteinte aux droits de l'entreprise — voir afnic\\.fr"""

    message = f"""{titre}

🌐 Domaine : `{domain_name}`
⚖️ Marque INPI : {ligne_marque}
📅 Date avant drop : {days_left} jours
{ligne_sirene}
👤 Dirigeant : {dirigeant}
{ligne_enchere}
{ligne_prix}
🌍 Présence web : {presence_web}
📸 Wayback : {snapshots} snapshots
{_timing_note(days_left)}

📌 *Action :*
{action}

💵 *Estimation à la revente : {prix_min}–{prix_max}€*{bonus}

📧 Mail de l'ancien propriétaire : {email}"""

    _envoyer_message_telegram(message, domain_name)

def send_telegram_alert_seo(domain_data: dict, score: int, fourchette_prix: tuple) -> None:
    """Filtre 1 — domaine à potentiel SEO/vente de liens, sans entreprise active
    identifiée. Rien à voir avec SIRENE/dirigeant/INPI qui ne s'appliquent pas ici."""
    domain_name = domain_data.get("domain", "")
    prix_min, prix_max = fourchette_prix
    days_left = domain_data.get("days_until_drop", "?")
    rd = domain_data.get("ref_domains", 0)
    snapshots = domain_data.get("wayback_snapshots", 0)
    presence_web = (
        "✅ Contenu détecté \\(Common Crawl\\)"
        if domain_data.get("common_crawl_pages", 0) > 0 else
        "❌ Aucun contenu indexé détecté"
    )

    en_enchere = domain_data.get("source") == "webexpire" and domain_data.get("webexpire_lien")
    prix_actuel = domain_data.get("webexpire_prix_actuel") or 0
    lien_webexpire = domain_data.get("webexpire_lien")

    if en_enchere:
        titre = "🔥 *DOMAINE SEO EN ENCHÈRE SUR WEBEXPIRE*"
        ligne_enchere = "📈 Enchère sur WebExpire : ✅ Oui"
        ligne_prix = f"💰 Prix actuel WebExpire : {prix_actuel:.2f}€"
        if domain_data.get("badge_surpaye"):
            ligne_prix += f"\n🚩 *SURPAYÉ* — valeur réelle estimée à {prix_max}€ max"
        action = f"→ [Voir l'enchère sur WebExpire]({lien_webexpire})"
    else:
        titre = "🎯 *DOMAINE SEO DISPONIBLE*"
        ligne_enchere = "📈 Enchère sur WebExpire : ❌ Non \\(autre source\\)"
        ligne_prix = "💰 Prix actuel WebExpire : non disponible"
        action = "→ [Voir sur WebExpire](https://www.webexpire.fr/encheres)"

    trafic = domain_data.get("webexpire_trafic")
    kw = domain_data.get("webexpire_mots_cles")
    ligne_trafic = f"\n📈 Trafic WebExpire : {trafic} visites/mois \\· {kw} mots\\-clés" if trafic is not None else ""

    message = f"""{titre}

🌐 Domaine : `{domain_name}`
📅 Date avant drop : {days_left} jours
{ligne_enchere}
{ligne_prix}
📊 Score : {score}/100
🌍 Présence web : {presence_web}
📸 Wayback : {snapshots} snapshots
🔗 Backlinks : {rd} RD{ligne_trafic}
{_timing_note(days_left)}

📌 *Action :*
{action}

💵 *Estimation à la revente : {prix_min}–{prix_max}€*"""

    _envoyer_message_telegram(message, domain_name)

def send_telegram_alert(domain_data: dict, score: int, fourchette_prix: tuple) -> None:
    """Dispatcher : route vers l'alerte Filtre 2 (revente à l'ancien propriétaire) ou
    Filtre 1 (SEO/vente de liens). Cahier des charges : Filtre 2 = société active OU
    site qui était actif — pas seulement les correspondances SIRENE nommées."""
    sirene_ok = domain_data.get("sirene_actif") and domain_data.get("sirene_nom_correspond")
    if sirene_ok or domain_data.get("site_etait_actif"):
        send_telegram_alert_revente(domain_data, score, fourchette_prix)
    else:
        send_telegram_alert_seo(domain_data, score, fourchette_prix)

# ── Supabase ──────────────────────────────────────────────────────────────────

def supabase_headers() -> dict:
    key = CONFIG.get("supabase_service_key", "")
    return {
        "apikey": key,
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
        "Prefer": "resolution=merge-duplicates"
    }

# Champs internes au pipeline, jamais persistés (pas de colonne Supabase
# correspondante — PostgREST rejette tout l'insert si une clé inconnue est
# présente, même si sa valeur est null).
_CHAMPS_INTERNES = {"drop_date_edn"}

def upsert_domain(domain_data: dict) -> None:
    base_url = CONFIG.get("supabase_url", "")
    if not base_url or base_url.startswith("TON_"):
        return
    payload = {
        k: v for k, v in domain_data.items()
        if not isinstance(v, datetime) and k not in _CHAMPS_INTERNES
    }
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

def domaines_existants_recents(jours: int = 1) -> set[str]:
    """Liste les domaines déjà en base (scannés par CatchDoms/WebExpire) sur les N derniers jours.
    Sert à éviter de réenrichir un domaine déjà couvert par les sources temps réel."""
    base_url = CONFIG.get("supabase_url", "")
    if not base_url or base_url.startswith("TON_"):
        return set()
    key = CONFIG.get("supabase_service_key", "")
    try:
        depuis = (datetime.now(timezone.utc) - timedelta(days=jours)).isoformat()
        r = requests.get(
            f"{base_url}/rest/v1/domains_scanned",
            params={"date_scan": f"gte.{depuis}", "select": "domain"},
            headers={"apikey": key, "Authorization": f"Bearer {key}"},
            timeout=15,
        )
        r.raise_for_status()
        return {row["domain"] for row in r.json() if row.get("domain")}
    except Exception as e:
        log.warning(f"Supabase lecture domaines récents: {e}")
        return set()

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

    # A — RDAP (ignoré pour WebExpire/CatchDoms : le dropcatcher a déjà re-enregistré → 364j faux)
    if domain_data.get("source") == "catchdoms" and domain_data.get("whois_expires_at"):
        # CatchDoms fournit déjà le WHOIS à jour, pas besoin de relookup RDAP
        try:
            expiry = dateutil_parser.parse(domain_data["whois_expires_at"]).replace(tzinfo=timezone.utc)
            days = (expiry - datetime.now(timezone.utc)).days
            domain_data["days_until_drop"] = days
            domain_data["jours_avant_drop"] = days if days > 0 else 0
            domain_data["jours_post_drop"] = abs(days) if days <= 0 else 0
            if days > 60:
                # Whois encore loin : quelqu'un a déjà (re)enregistré ce domaine,
                # même logique que la branche RDAP générique plus bas.
                domain_data["deja_reenregistre_tiers"] = True
        except Exception:
            domain_data["days_until_drop"] = 0
            domain_data["jours_avant_drop"] = 0
            domain_data["jours_post_drop"] = 0
    elif domain_data.get("source") == "webexpire":
        # WebExpire ne liste que des enchères déjà en cours : le drop a forcément
        # déjà eu lieu, J+0 est donc une donnée réelle ("vient de tomber").
        domain_data["days_until_drop"] = 0
        domain_data["jours_avant_drop"] = 0
        domain_data["jours_post_drop"] = 0
    elif domain_data.get("source") == "catchdoms":
        # CatchDoms sans whois exploitable : le timing est réellement inconnu.
        # On ne fake pas un J+0 qui afficherait "vient de tomber" à tort sur le
        # dashboard/Telegram pour un domaine dont on ne connaît pas l'état.
        domain_data["days_until_drop"] = None
        domain_data["jours_avant_drop"] = None
        domain_data["jours_post_drop"] = None
    else:
        rdap = rdap_lookup(domain)
        if rdap:
            rdap_statuses = [s.lower() for s in (rdap.get("status") or [])]
            expiry = rdap.get("expiry_date")

            if rdap.get("status") == "available":
                domain_data["days_until_drop"] = 0
                domain_data["jours_avant_drop"] = 0
                domain_data["jours_post_drop"] = 0
            elif expiry:
                days = (expiry - datetime.now(timezone.utc)).days
                domain_data["days_until_drop"] = days
                domain_data["jours_avant_drop"] = days if days > 0 else 0
                domain_data["jours_post_drop"] = abs(days) if days <= 0 else 0
                if days > 60:
                    # Renouvellement récent, loin de toute expiration : quelqu'un d'autre
                    # a déjà ré-enregistré ce domaine — plus possible en backorder.
                    domain_data["deja_reenregistre_tiers"] = True
            elif any(s in rdap_statuses for s in ["pendingdelete", "pending delete", "redemptionperiod"]):
                domain_data["days_until_drop"] = 3
                domain_data["jours_avant_drop"] = 3
                domain_data["jours_post_drop"] = 0

            domain_data["registrar"] = rdap.get("registrar", "")

        # Fallback : date de drop scrapée depuis EDN si RDAP n'a rien donné
        if domain_data.get("jours_avant_drop") is None and domain_data.get("jours_post_drop") is None:
            drop_date_edn = domain_data.get("drop_date_edn")
            if drop_date_edn:
                days_edn = (drop_date_edn - datetime.now(timezone.utc)).days
                domain_data["days_until_drop"] = days_edn
                domain_data["jours_avant_drop"] = days_edn if days_edn > 0 else 0
                domain_data["jours_post_drop"] = abs(days_edn) if days_edn <= 0 else 0

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

    # E2 — Site qui était actif avant l'expiration ? (cahier des charges, Filtre 2 :
    # "société active OU site qui était actif" — deuxième critère indépendant de la
    # correspondance SIRENE, pour ne pas rater un ancien propriétaire qu'on n'a pas
    # pu identifier nommément).
    # common_crawl() est plafonné à 5 résultats (limit=5 dans la requête) — un seul
    # hit n'est pas un signal fiable (peut être une page parking/erreur résiduelle).
    # CatchDoms sélectionne déjà des domaines à profil SEO/backlinks réel, donc la
    # quasi-totalité avait au moins 1 page indexée : le seuil ">0" rendait Filtre 1
    # (SEO) vide en pratique. Seuil relevé à "≥3 sur 5" pour un vrai signal de
    # contenu actif, pas juste une coïncidence d'indexation.
    seuil_wayback = CONFIG.get("wayback_snapshots_min", 10)
    domain_data["site_etait_actif"] = (
        domain_data.get("common_crawl_pages", 0) >= 3
        or domain_data.get("wayback_snapshots", 0) >= seuil_wayback
    )

    # D2b — Email de contact (best-effort via Wayback) : dès qu'il y a une piste de
    # revente (société identifiée OU site qui était actif), pas seulement en cas de
    # correspondance SIRENE nommée — sinon on ne cherchait jamais de contact pour les
    # domaines "site actif, société non identifiée".
    if domain_data.get("sirene_nom_correspond") or domain_data.get("site_etait_actif"):
        email = extraire_email_wayback(domain)
        if not email and domain_data.get("site_internet"):
            email = extraire_email_wayback(domain_data["site_internet"])
        domain_data["email_contact"] = email
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

def en_enchere_active(domain_data: dict) -> bool:
    """Vrai uniquement si le domaine est réellement en enchère/backorder actif —
    pas juste listé avec une date whois encore lointaine (ex: CatchDoms 365j)."""
    source = domain_data.get("source")
    if source == "webexpire":
        return bool(domain_data.get("webexpire_lien"))
    if source == "catchdoms":
        a_une_enchere = bool(
            domain_data.get("catchdoms_auction_end_date")
            or domain_data.get("catchdoms_max_bid")
            or domain_data.get("catchdoms_bids_count")
        )
        deja_expire_ou_imminent = (domain_data.get("days_until_drop") or 0) <= 0
        return a_une_enchere and deja_expire_ou_imminent
    return False

def respecte_seuil_seo(domain_data: dict) -> bool:
    """Cahier des charges, Filtre 1 : 'RD minimum 2-3 RD thématisés' — ne s'applique
    qu'aux domaines purement SEO (pas de société active, pas de site qui était actif :
    la revente n'a pas besoin d'un profil de liens pour être pertinente)."""
    sirene_ok = domain_data.get("sirene_actif") and domain_data.get("sirene_nom_correspond")
    if sirene_ok or domain_data.get("site_etait_actif"):
        return True
    rd_min = CONFIG.get("rd_min_seo", 2)
    return (domain_data.get("ref_domains") or 0) >= rd_min

def run():
    log.info("=== Domain Hunter démarré ===")
    stats = {"collectes": 0, "apres_filtre": 0, "en_base": 0, "alertes": 0}

    domaines_edn = collecter_domaines()
    stats["collectes"] = len(domaines_edn)

    domaines_vus = set()

    # WebExpire + CatchDoms — on garde tous les champs déjà collectés (score,
    # TF/CF/DA, prix d'enchère, WHOIS...) au lieu d'un sous-ensemble figé. La
    # correspondance SIRENE est vérifiée plus tard dans enrichir_domaine(), en
    # lecture seule sur ces domaines réels — jamais générée à l'avance.
    par_source: dict[str, list] = {}
    for d in domaines_edn:
        domain = d.get("domain", "")
        if not domain or domain in domaines_vus:
            continue
        rd = d.get("ref_domains", 0)
        if filtrer(domain, rd):
            pre_enriched = {k: v for k, v in d.items() if k != "domain"}
            par_source.setdefault(d.get("source", "?"), []).append((domain, pre_enriched))
            domaines_vus.add(domain)

    # Intercalage round-robin entre sources : sans ça, WebExpire (qui ne liste
    # que du .fr) remplit tout le quota MAX_DOMAINES avant que CatchDoms (qui a
    # des .com) ait la moindre chance — c'est ce qui faisait disparaître le .com
    # du dashboard malgré une vraie collecte en amont.
    pipeline = []
    listes = list(par_source.values())
    idx = 0
    while any(listes) and len(pipeline) < MAX_DOMAINES:
        lst = listes[idx % len(listes)]
        if lst:
            pipeline.append(lst.pop(0))
        idx += 1
    stats["apres_filtre"] = len(pipeline)
    log.info(f"Filtre : {stats['apres_filtre']} domaines à enrichir")

    prix_seuil = CONFIG.get("prix_minimum_alerte", 500)

    for domain, pre_enriched in pipeline:
        try:
            domain_data = enrichir_domaine(domain, pre_enriched or None)
            if not domain_data:
                continue

            # Filtre temporel post-RDAP :
            # - WebExpire/CatchDoms (sans SIRENE) → uniquement si réellement en enchère
            #   active (sinon un domaine CatchDoms avec un whois encore valide 365j
            #   passait quand même, ce qui n'a rien à voir avec une enchère).
            # - Filtre 2 (entreprise active) déjà repris par un tiers → toujours garder,
            #   c'est une opportunité de négociation/recours légal (pastille orange).
            # - Filtre 2 sans timing connu ou trop loin/vieux et pas "déjà repris" → drop
            #   (sinon un simple listing CatchDoms type "buy" sans rapport avec un drop
            #   s'affichait avec un "659j" ou un J+0 trompeur dans la revente).
            # - Sinon (générique) : drop dans ≤ 60j OU tombé depuis ≤ 90j
            source = domain_data.get("source", "")
            days_until = domain_data.get("days_until_drop")
            jours_post = domain_data.get("jours_post_drop", 0) or 0
            sirene_ok = domain_data.get("sirene_actif") and domain_data.get("sirene_nom_correspond")
            deja_repris = domain_data.get("deja_reenregistre_tiers")
            if sirene_ok:
                if not deja_repris:
                    if days_until is None:
                        log.debug(f"Ignoré {domain}: SIRENE matché mais timing inconnu, pas un cas de recours")
                        continue
                    if days_until > 60 and jours_post == 0:
                        continue
                    if jours_post > 90:
                        continue
            elif source in ("webexpire", "catchdoms"):
                if not en_enchere_active(domain_data):
                    log.debug(f"Ignoré {domain}: pas d'enchère active ({source})")
                    continue
            elif days_until is not None:
                if days_until > 60 and jours_post == 0:
                    log.debug(f"Ignoré {domain}: re-enregistré ou trop loin ({days_until}j)")
                    continue
                if jours_post > 90:
                    log.debug(f"Ignoré {domain}: tombé il y a {jours_post}j > 90j")
                    continue

            if not respecte_seuil_seo(domain_data):
                log.debug(f"Ignoré {domain}: RD insuffisant pour le SEO ({domain_data.get('ref_domains')})")
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
                try:
                    send_telegram_alert(domain_data, score, fourchette)
                    marquer_alerte_envoyee(domain)
                    stats["alertes"] += 1
                except Exception:
                    pass  # log déjà fait dans send_telegram_alert

        except Exception as e:
            log.error(f"Erreur pipeline {domain}: {e}")

    log.info(
        f"=== Fin : {stats['collectes']} collectés → {stats['apres_filtre']} après filtre "
        f"→ {stats['en_base']} écrits en base → {stats['alertes']} alertes Telegram ==="
    )

def run_edn():
    """Job séparé, déclenché 2x/jour seulement (pas toutes les 15 min comme le scan
    principal) — pour rester sous le radar d'EDN après 2 bannissements de compte.
    Scrape EDN, ignore tout domaine déjà connu via CatchDoms/WebExpire dans les
    dernières 24h, et n'enrichit que les nouveaux."""
    log.info("=== Domain Hunter — EDN (2x/jour) démarré ===")
    stats = {"collectes": 0, "deja_connus": 0, "nouveaux": 0, "en_base": 0, "alertes": 0}

    edn = scraper_expireddomains_net()
    stats["collectes"] = len(edn)

    existants = domaines_existants_recents(jours=1)
    prix_seuil = CONFIG.get("prix_minimum_alerte", 500)

    vus = set()
    traites = 0
    for d in edn:
        domain = d.get("domain", "")
        if not domain or domain in vus:
            continue
        vus.add(domain)

        if domain in existants:
            stats["deja_connus"] += 1
            continue

        rd = d.get("ref_domains", 0)
        if not filtrer(domain, rd):
            continue
        stats["nouveaux"] += 1

        if traites >= MAX_DOMAINES:
            continue

        try:
            pre_enriched = {
                "ref_domains": rd,
                "wayback_snapshots": d.get("wayback_snapshots", 0),
                "source": d.get("source") or "expireddomains",
                "drop_date_edn": d.get("drop_date_edn"),
            }
            domain_data = enrichir_domaine(domain, pre_enriched)
            if not domain_data:
                continue

            # EDN liste des domaines tombés depuis des mois — sans ce filtre, une
            # correspondance SIRENE sur un drop très ancien (J+300...) atterrissait
            # quand même dans la revente. On garde uniquement les cas récents/imminents,
            # sauf si le domaine a été repris par un tiers (recours PARL EXPERT, garder
            # quel que soit l'âge — c'est justement l'opportunité de négociation).
            deja_repris = domain_data.get("deja_reenregistre_tiers")
            jours_post = domain_data.get("jours_post_drop", 0) or 0
            days_until = domain_data.get("days_until_drop")
            if not deja_repris and days_until is not None:
                if days_until > 60 and jours_post == 0:
                    log.debug(f"Ignoré EDN {domain}: re-enregistré ou trop loin ({days_until}j)")
                    continue
                if jours_post > 90:
                    log.debug(f"Ignoré EDN {domain}: tombé il y a {jours_post}j > 90j")
                    continue

            if not respecte_seuil_seo(domain_data):
                log.debug(f"Ignoré EDN {domain}: RD insuffisant pour le SEO ({domain_data.get('ref_domains')})")
                continue

            score, flag_prudence = calculate_score(domain_data)
            domain_data["score"] = score
            domain_data["flag_prudence"] = flag_prudence

            fourchette = estimate_final_price(domain_data)
            domain_data["prix_estime_min"], domain_data["prix_estime_max"] = fourchette

            upsert_domain(domain_data)
            stats["en_base"] += 1
            traites += 1

            if fourchette[0] >= prix_seuil and not domaine_deja_alerte(domain):
                try:
                    send_telegram_alert(domain_data, score, fourchette)
                    marquer_alerte_envoyee(domain)
                    stats["alertes"] += 1
                except Exception:
                    pass
        except Exception as e:
            log.error(f"Erreur pipeline EDN {domain}: {e}")

    log.info(
        f"=== Fin EDN : {stats['collectes']} collectés → {stats['deja_connus']} déjà connus "
        f"(CatchDoms/WebExpire) → {stats['nouveaux']} nouveaux candidats → {stats['en_base']} "
        f"écrits en base → {stats['alertes']} alertes Telegram ==="
    )

# ── Monitoring temps réel des favoris (toutes les 30 min) ─────────────────────

def domaines_favoris() -> list[dict]:
    """Récupère les domaines marqués favoris en base (cochés depuis le dashboard)."""
    base_url = CONFIG.get("supabase_url", "")
    if not base_url or base_url.startswith("TON_"):
        return []
    try:
        r = requests.get(
            f"{base_url}/rest/v1/domains_scanned",
            headers=supabase_headers(),
            params={"favori": "eq.true", "select": "*"},
            timeout=15,
        )
        r.raise_for_status()
        return r.json()
    except Exception as e:
        log.warning(f"Supabase lecture favoris: {e}")
        return []

def _envoyer_alerte_favori(domain: str, corps: str) -> None:
    message = f"⭐ *SUIVI FAVORI*\n\n🌐 Domaine : `{domain}`\n\n{corps}"
    try:
        _envoyer_message_telegram(message, domain)
    except Exception:
        pass

def surveiller_favoris() -> None:
    """Job dédié (30 min) : pour chaque domaine favori, vérifie si le prix WebExpire
    a augmenté ou si le domaine vient de passer de backorder à enchère, et met à jour
    le temps avant drop via RDAP (peu importe le registrar)."""
    log.info("=== Domain Hunter — Surveillance favoris démarrée ===")
    favoris = domaines_favoris()
    if not favoris:
        log.info("Aucun favori à surveiller.")
        return

    webexpire_actuel = {d["domain"]: d for d in scraper_webexpire()}
    alertes = 0

    for fav in favoris:
        domain = fav.get("domain", "")
        if not domain:
            continue

        maj: dict = {}
        ancien_prix = fav.get("webexpire_prix_actuel") or 0
        etait_en_enchere = bool(fav.get("webexpire_lien"))
        actuel = webexpire_actuel.get(domain)

        if actuel:
            nouveau_prix = actuel.get("webexpire_prix_actuel") or 0
            est_en_enchere = bool(actuel.get("webexpire_lien"))
            maj["webexpire_prix_actuel"] = nouveau_prix
            maj["webexpire_lien"] = actuel.get("webexpire_lien")
            maj["delai_enchere"] = actuel.get("delai_enchere")

            if not etait_en_enchere and est_en_enchere:
                _envoyer_alerte_favori(
                    domain,
                    f"🎯 *Passage de backorder à enchère sur WebExpire*\n"
                    f"💰 Prix actuel : {nouveau_prix:.2f}€\n"
                    f"→ [Voir l'enchère]({actuel.get('webexpire_lien')})"
                )
                alertes += 1
            elif est_en_enchere and nouveau_prix > ancien_prix:
                _envoyer_alerte_favori(
                    domain,
                    f"📈 *Le prix de l'enchère a augmenté*\n"
                    f"💰 {ancien_prix:.2f}€ → {nouveau_prix:.2f}€\n"
                    f"→ [Voir l'enchère]({actuel.get('webexpire_lien')})"
                )
                alertes += 1

        # Temps avant drop à jour, peu importe le registrar (RDAP interroge le bon
        # serveur selon le TLD : nic.fr, Verisign .com/.net, etc.)
        rdap = rdap_lookup(domain)
        if rdap and rdap.get("expiry_date"):
            jours = (rdap["expiry_date"] - datetime.now(timezone.utc)).days
            if jours != fav.get("jours_avant_drop"):
                maj["jours_avant_drop"] = jours
            if rdap.get("registrar"):
                maj["registrar"] = rdap["registrar"]

        if maj:
            maj["domain"] = domain
            upsert_domain(maj)

    log.info(f"=== Fin surveillance favoris : {len(favoris)} suivis, {alertes} alertes envoyées ===")

if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "edn":
        run_edn()
    elif len(sys.argv) > 1 and sys.argv[1] == "monitor":
        surveiller_favoris()
    else:
        run()
