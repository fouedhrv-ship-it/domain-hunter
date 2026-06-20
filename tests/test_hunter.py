"""Tests des fonctions pures de hunter.py (pas d'I/O réseau).

Lancer : python3 -m unittest tests.test_hunter -v
(depuis la racine du repo, ou `python3 -m unittest discover -s tests`)
"""
import os
import sys
import unittest
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import hunter


class TestFiltrer(unittest.TestCase):
    def test_domaine_valide(self):
        self.assertTrue(hunter.filtrer("exemple.fr", 50))

    def test_trop_long(self):
        self.assertFalse(hunter.filtrer("un-nom-de-domaine-vraiment-trop-long.fr", 50))

    def test_double_tiret_rejete(self):
        self.assertFalse(hunter.filtrer("ex--emple.fr", 50))

    def test_que_des_chiffres_rejete(self):
        self.assertFalse(hunter.filtrer("123456.com", 50))

    def test_tld_non_autorise(self):
        self.assertFalse(hunter.filtrer("exemple.io", 50))

    def test_rd_trop_eleve(self):
        self.assertFalse(hunter.filtrer("exemple.com", 301))

    def test_faux_nom_catchdoms_paywall(self):
        # Cas réel rencontré en prod : CatchDoms masque certains résultats
        # gratuits derrière "•••.com — Upgrade to Pro..." ; le rsplit('.', 1)
        # tombe sur le ".com" de l'URL de pricing dans le texte, pas le vrai
        # TLD, donc tld devient ".com/pricing" → rejeté par tlds_autorises.
        faux_nom = "••••••••.com — Upgrade to Pro to unlock today's new listings: https://catchdoms.com/pricing"
        self.assertFalse(hunter.filtrer(faux_nom, 50))


class TestJoursAvantFinEnchere(unittest.TestCase):
    def test_webexpire_avec_lien(self):
        self.assertEqual(hunter._jours_avant_fin_enchere({"source": "webexpire", "webexpire_lien": "https://x"}), 0)

    def test_webexpire_sans_lien(self):
        self.assertIsNone(hunter._jours_avant_fin_enchere({"source": "webexpire"}))

    def test_catchdoms_closeout_toujours_zero(self):
        data = {"source": "catchdoms", "catchdoms_type": "closeout"}
        self.assertEqual(hunter._jours_avant_fin_enchere(data), 0)

    def test_catchdoms_sans_date_fin(self):
        data = {"source": "catchdoms", "catchdoms_type": "auction"}
        self.assertIsNone(hunter._jours_avant_fin_enchere(data))

    def test_source_inconnue(self):
        self.assertIsNone(hunter._jours_avant_fin_enchere({"source": "expireddomains"}))


class TestEligibleSeo(unittest.TestCase):
    def _domaine_ok(self, **overrides):
        fin_proche = (datetime.now(timezone.utc) + timedelta(days=4)).isoformat()
        base = {
            "source": "catchdoms",
            "catchdoms_type": "auction",
            "ref_domains": 50,
            "trust_flow": 25,
            "catchdoms_auction_end_date": fin_proche,
        }
        base.update(overrides)
        return base

    def test_cas_nominal_eligible(self):
        ok, _ = hunter.eligible_seo(self._domaine_ok())
        self.assertTrue(ok)

    def test_tf_trop_bas_rejete(self):
        ok, _ = hunter.eligible_seo(self._domaine_ok(trust_flow=15))
        self.assertFalse(ok)

    def test_tf_trop_haut_rejete(self):
        ok, _ = hunter.eligible_seo(self._domaine_ok(trust_flow=35))
        self.assertFalse(ok)

    def test_rd_trop_bas_rejete(self):
        ok, _ = hunter.eligible_seo(self._domaine_ok(ref_domains=1))
        self.assertFalse(ok)

    def test_rd_trop_haut_rejete(self):
        ok, _ = hunter.eligible_seo(self._domaine_ok(ref_domains=400))
        self.assertFalse(ok)

    def test_pas_en_enchere_rejete(self):
        ok, _ = hunter.eligible_seo({"source": "catchdoms", "ref_domains": 50, "trust_flow": 25})
        self.assertFalse(ok)

    def test_blackliste_rejete(self):
        ok, _ = hunter.eligible_seo(self._domaine_ok(domaine_blackliste=True))
        self.assertFalse(ok)

    def test_pivot_pbn_rejete(self):
        ok, _ = hunter.eligible_seo(self._domaine_ok(pivot_thematique_detecte=True))
        self.assertFalse(ok)

    def test_closeout_eligible_sans_date_fin(self):
        ok, jours = hunter.eligible_seo(self._domaine_ok(
            catchdoms_type="closeout", catchdoms_auction_end_date=None
        ))
        self.assertTrue(ok)
        self.assertEqual(jours, 0)

    def test_webexpire_eligible(self):
        ok, jours = hunter.eligible_seo({
            "source": "webexpire", "webexpire_lien": "https://x",
            "ref_domains": 50, "trust_flow": 25,
        })
        self.assertTrue(ok)
        self.assertEqual(jours, 0)

    def test_edn_jamais_eligible(self):
        # EDN n'est jamais "en enchère" au sens propre (voir en_enchere_active).
        ok, _ = hunter.eligible_seo({"source": "expireddomains", "ref_domains": 50, "trust_flow": 25})
        self.assertFalse(ok)


class TestEligibleRevente(unittest.TestCase):
    def test_aucun_critere_non_eligible(self):
        eligible, timing_ok = hunter.eligible_revente({})
        self.assertFalse(eligible)
        self.assertTrue(timing_ok)  # convention : rien à valider si pas concerné

    def test_sirene_ok_timing_inconnu_rejete(self):
        eligible, timing_ok = hunter.eligible_revente({
            "sirene_actif": True, "sirene_nom_correspond": True,
        })
        self.assertTrue(eligible)
        self.assertFalse(timing_ok)

    def test_sirene_ok_deja_repris_toujours_garde(self):
        eligible, timing_ok = hunter.eligible_revente({
            "sirene_actif": True, "sirene_nom_correspond": True,
            "deja_reenregistre_tiers": True,
        })
        self.assertTrue(eligible)
        self.assertTrue(timing_ok)

    def test_sirene_ok_drop_proche_garde(self):
        eligible, timing_ok = hunter.eligible_revente({
            "sirene_actif": True, "sirene_nom_correspond": True,
            "days_until_drop": 10, "jours_post_drop": 0,
        })
        self.assertTrue(eligible)
        self.assertTrue(timing_ok)

    def test_sirene_ok_trop_loin_rejete(self):
        eligible, timing_ok = hunter.eligible_revente({
            "sirene_actif": True, "sirene_nom_correspond": True,
            "days_until_drop": 200, "jours_post_drop": 0,
        })
        self.assertTrue(eligible)
        self.assertFalse(timing_ok)

    def test_catchdoms_sans_sirene_suit_en_enchere_active(self):
        eligible, timing_ok = hunter.eligible_revente({
            "site_etait_actif": True, "source": "catchdoms",
            "catchdoms_auction_end_date": "2099-01-05T12:00:00Z",
        })
        self.assertTrue(eligible)
        self.assertTrue(timing_ok)

    def test_site_etait_actif_tombe_trop_longtemps_rejete(self):
        eligible, timing_ok = hunter.eligible_revente({
            "site_etait_actif": True, "source": "expireddomains",
            "days_until_drop": -200, "jours_post_drop": 200,
        })
        self.assertTrue(eligible)
        self.assertFalse(timing_ok)


if __name__ == "__main__":
    unittest.main()
