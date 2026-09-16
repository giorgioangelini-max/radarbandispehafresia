#!/usr/bin/env python3
"""
RADAR BANDI — collettore.

Legge fonti.yaml, passa ogni fonte (RSS, pagina HTML o API del portale UE),
estrae titolo / link / date, calcola la pertinenza per Speha Fresia con
parole_chiave.yaml e aggiorna data/bandi.json, che è il database letto
dal sito. Nessun modello AI, nessuna chiave: solo testo vero dalle fonti.

Uso:
    python raccogli.py              aggiorna tutto
    python raccogli.py --fonte id   aggiorna una fonte sola (per provare)
"""

import argparse
import datetime as dt
import hashlib
import json
import re
import sys
import time
import unicodedata
from pathlib import Path
from urllib.parse import urljoin, urlparse, urlunparse

import feedparser
import requests
import yaml
from bs4 import BeautifulSoup

CARTELLA = Path(__file__).resolve().parent
FILE_FONTI = CARTELLA / "fonti.yaml"
FILE_PAROLE = CARTELLA / "parole_chiave.yaml"
FILE_DATI = CARTELLA / "data" / "bandi.json"

OGGI = dt.date.today()
GIORNI_MEMORIA = 240          # un bando sparisce dal database se non lo vediamo più da tanti giorni
MAX_PER_FONTE = 120           # tetto per non farsi inondare da una fonte sola
TIMEOUT = 30

INTESTAZIONI = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
                  "Chrome/124.0 Safari/537.36 RadarBandi/1.0 (+strumento interno, una lettura al giorno)",
    "Accept-Language": "it-IT,it;q=0.9,en;q=0.7",
}

# Un link è candidato bando se titolo o indirizzo contengono una di queste
PAROLE_LINK = re.compile(
    r"bando|bandi|avvis|call|manifestazione|invito|procedura|voucher|catalogo|"
    r"finanziament|contribut|incentiv|selezione|candidatur|proposte|tender|opportunit",
    re.I,
)

MESI = {
    "gennaio": 1, "gen": 1, "febbraio": 2, "feb": 2, "marzo": 3, "mar": 3, "aprile": 4, "apr": 4,
    "maggio": 5, "mag": 5, "giugno": 6, "giu": 6, "luglio": 7, "lug": 7, "agosto": 8, "ago": 8,
    "settembre": 9, "set": 9, "sett": 9, "ottobre": 10, "ott": 10, "novembre": 11, "nov": 11,
    "dicembre": 12, "dic": 12,
    "january": 1, "february": 2, "march": 3, "april": 4, "may": 5, "june": 6, "july": 7,
    "august": 8, "september": 9, "october": 10, "november": 11, "december": 12,
}
RE_DATA_NUM = re.compile(r"\b(\d{1,2})[/.\-](\d{1,2})[/.\-](\d{4}|\d{2})\b")
RE_DATA_ISO = re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b")
RE_DATA_TESTO = re.compile(
    r"\b(\d{1,2})\s*(?:°|º)?\s+(" + "|".join(sorted(MESI, key=len, reverse=True)) + r")\.?\s+(\d{4})\b", re.I
)
# parole che, vicino a una data, dicono "questa è la scadenza"
RE_CONTESTO_SCADENZA = re.compile(
    r"scad|entro|termine|deadline|chiusura|fino al|non oltre|presentazione|candidatur|closing", re.I
)


# ---------------------------------------------------------------------
# utilità
# ---------------------------------------------------------------------
def normalizza_testo(s: str) -> str:
    """minuscolo, senza accenti, spazi compattati — per confronti."""
    s = unicodedata.normalize("NFKD", s or "")
    s = "".join(c for c in s if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", s).strip().lower()


def pulisci(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "")).strip()


def normalizza_url(u: str) -> str:
    p = urlparse(u.strip())
    percorso = p.path.rstrip("/") or "/"
    return urlunparse((p.scheme.lower(), p.netloc.lower(), percorso, "", p.query, ""))


def id_da_url(u: str) -> str:
    return hashlib.sha1(normalizza_url(u).encode()).hexdigest()[:12]


def scarica(url: str) -> requests.Response:
    ultimo_errore = None
    for tentativo in range(2):
        try:
            r = requests.get(url, headers=INTESTAZIONI, timeout=TIMEOUT, allow_redirects=True)
            r.raise_for_status()
            return r
        except Exception as e:      # noqa: BLE001
            ultimo_errore = e
            time.sleep(2)
    raise ultimo_errore


def a_data(anno, mese, giorno):
    try:
        anno = int(anno)
        if anno < 100:
            anno += 2000
        d = dt.date(anno, int(mese), int(giorno))
        if 2020 <= d.year <= 2035:
            return d
    except ValueError:
        pass
    return None


def trova_date(testo: str):
    """Restituisce [(data, posizione_nel_testo), ...] per tutte le date trovate."""
    trovate = []
    for m in RE_DATA_NUM.finditer(testo):
        d = a_data(m.group(3), m.group(2), m.group(1))
        if d:
            trovate.append((d, m.start()))
    for m in RE_DATA_ISO.finditer(testo):
        d = a_data(m.group(1), m.group(2), m.group(3))
        if d:
            trovate.append((d, m.start()))
    for m in RE_DATA_TESTO.finditer(testo):
        d = a_data(m.group(3), MESI[m.group(2).lower()], m.group(1))
        if d:
            trovate.append((d, m.start()))
    return trovate


def trova_scadenza(testo: str):
    """La data che ha una parola tipo 'scadenza/entro/termine' nei 70 caratteri prima."""
    if not testo:
        return None
    candidate = []
    for d, pos in trova_date(testo):
        contesto = testo[max(0, pos - 70):pos]
        if RE_CONTESTO_SCADENZA.search(contesto):
            candidate.append(d)
    if not candidate:
        return None
    # se ce n'è più d'una, la più lontana nel futuro è quasi sempre il termine ultimo
    future = [d for d in candidate if d >= OGGI - dt.timedelta(days=3)]
    return max(future) if future else max(candidate)


# ---------------------------------------------------------------------
# lettori: ognuno restituisce una lista di dict grezzi
#   {titolo, url, sommario, pubblicato(date|None), scadenza(date|None)}
# ---------------------------------------------------------------------
def leggi_rss(fonte):
    r = scarica(fonte["url"])
    feed = feedparser.parse(r.content)
    if feed.bozo and not feed.entries:
        raise RuntimeError(f"feed non leggibile: {getattr(feed, 'bozo_exception', '')}")
    voci = []
    for e in feed.entries[:MAX_PER_FONTE]:
        titolo = pulisci(e.get("title", ""))
        link = e.get("link", "")
        if not titolo or not link:
            continue
        sommario = BeautifulSoup(e.get("summary", "") or "", "lxml").get_text(" ", strip=True)
        pubblicato = None
        for campo in ("published_parsed", "updated_parsed"):
            if e.get(campo):
                pubblicato = dt.date(*e[campo][:3])
                break
        voci.append({
            "titolo": titolo, "url": link, "sommario": sommario[:600],
            "pubblicato": pubblicato, "scadenza": trova_scadenza(titolo + " " + sommario),
        })
    return voci


def leggi_html(fonte, url=None):
    url = url or fonte["url"]
    r = scarica(url)
    soup = BeautifulSoup(r.content, "lxml")
    for tag in soup(["script", "style", "noscript", "nav", "footer", "header"]):
        tag.decompose()

    voci, visti = [], set()

    def aggiungi(a, blocco=None):
        href = a.get("href", "")
        if not href or href.startswith(("#", "mailto:", "tel:", "javascript:")):
            return
        link = urljoin(url, href)
        if normalizza_url(link) == normalizza_url(url):
            return
        titolo = pulisci(a.get_text(" ", strip=True))
        if blocco is not None and len(titolo) < 25:
            # nel blocco il link può dire solo "leggi" — prendo il titolo dal blocco
            h = blocco.find(["h1", "h2", "h3", "h4", "h5"])
            titolo = pulisci(h.get_text(" ", strip=True)) if h else pulisci(blocco.get_text(" ", strip=True))[:160]
        if len(titolo) < 25 or len(titolo) > 300:
            return
        if blocco is None and not (PAROLE_LINK.search(titolo) or PAROLE_LINK.search(href)):
            return
        chiave = normalizza_url(link)
        if chiave in visti:
            return
        visti.add(chiave)
        contesto = blocco if blocco is not None else (a.find_parent(["li", "article", "div", "tr", "p"]) or a)
        testo_contesto = pulisci(contesto.get_text(" ", strip=True))[:700]
        date = trova_date(testo_contesto)
        pubblicato = None
        if date:
            passate = [d for d, _ in date if d <= OGGI]
            pubblicato = max(passate) if passate else None
        voci.append({
            "titolo": titolo, "url": link, "sommario": testo_contesto if testo_contesto != titolo else "",
            "pubblicato": pubblicato, "scadenza": trova_scadenza(testo_contesto),
        })

    if fonte.get("selettore"):
        for blocco in soup.select(fonte["selettore"]):
            a = blocco if blocco.name == "a" else blocco.find("a", href=True)
            if a:
                aggiungi(a, blocco)
    else:
        for a in soup.find_all("a", href=True):
            aggiungi(a)
    return voci[:MAX_PER_FONTE]


def leggi_ft(fonte):
    """Funding & Tenders Portal: API di ricerca pubblica (chiave SEDIA, è la loro, non serve registrarsi)."""
    prefissi = tuple(p.upper() for p in fonte.get("prefissi", []))
    voci = []
    query = {"bool": {"must": [
        {"terms": {"type": ["1"]}},                      # 1 = call for proposals (grant)
        {"terms": {"status": ["31094501", "31094502"]}},  # forthcoming + open
    ]}}
    for pagina in range(1, 12):
        r = requests.post(
            fonte["url"],
            params={"apiKey": "SEDIA", "text": "***", "pageSize": "100", "pageNumber": str(pagina)},
            files={"query": (None, json.dumps(query)), "sort": (None, json.dumps({"field": "sortStatus", "order": "DESC"}))},
            headers={"User-Agent": INTESTAZIONI["User-Agent"]}, timeout=TIMEOUT,
        )
        r.raise_for_status()
        dati = r.json()
        risultati = dati.get("results", [])
        if not risultati:
            break
        for ris in risultati:
            m = ris.get("metadata", {}) or {}
            ident = (primo(m.get("identifier")) or "").strip()
            if prefissi and not ident.upper().startswith(prefissi):
                continue
            titolo = primo(m.get("title")) or primo(m.get("callTitle")) or ident
            scad = None
            for s in (m.get("deadlineDate") or []):
                d = a_data(s[:4], s[5:7], s[8:10]) if len(s) >= 10 else None
                if d and (scad is None or d > scad):
                    scad = d
            apertura = primo(m.get("startDate")) or ""
            pubblicato = a_data(apertura[:4], apertura[5:7], apertura[8:10]) if len(apertura) >= 10 else None
            stato = {"31094501": "forthcoming", "31094502": "open"}.get(primo(m.get("status")) or "", "")
            programma = primo(m.get("frameworkProgramme")) or ""
            voci.append({
                "titolo": pulisci(f"{ident} — {titolo}"),
                "url": f"https://ec.europa.eu/info/funding-tenders/opportunities/portal/screen/opportunities/topic-details/{ident.lower()}",
                "sommario": pulisci(f"{stato}. Call: {primo(m.get('callTitle')) or ''}. {programma}")[:600],
                "pubblicato": pubblicato, "scadenza": scad,
            })
        if len(risultati) < 100:
            break
    return voci


def primo(v):
    if isinstance(v, list):
        return v[0] if v else None
    return v


LETTORI = {"rss": leggi_rss, "html": leggi_html, "ft": leggi_ft}


# ---------------------------------------------------------------------
# pertinenza e territorio
# ---------------------------------------------------------------------
class Valutatore:
    def __init__(self, regole):
        self.categorie = []
        for chiave, cat in regole["categorie"].items():
            self.categorie.append((chiave, cat["etichetta"], int(cat.get("peso", 2)),
                                   [self._re(p) for p in cat["parole"]]))
        pen = regole.get("penalita", {})
        self.penalita = (int(pen.get("peso", -4)), [self._re(p) for p in pen.get("parole", [])])
        self.soglie = regole.get("soglie", {"alta": 7, "media": 3})
        self.territori = {k: [normalizza_testo(p) for p in v] for k, v in regole.get("territori", {}).items()}

    @staticmethod
    def _re(parola):
        p = normalizza_testo(str(parola))
        # sigle corte (GOL, ETS, AI, PA…) le voglio intere, le altre come inizio di parola
        if len(p) <= 4 and p.isalpha():
            return re.compile(r"(?<![a-z0-9])" + re.escape(p) + r"(?![a-z0-9])")
        return re.compile(r"(?<![a-z0-9])" + re.escape(p))

    def valuta(self, titolo, sommario):
        t, s = normalizza_testo(titolo), normalizza_testo(sommario)
        punteggio, etichette = 0, []
        for chiave, etichetta, peso, regex in self.categorie:
            colpi = 0
            for r in regex:
                if r.search(t):
                    colpi += 2
                elif r.search(s):
                    colpi += 1
            if colpi:
                punteggio += min(peso * colpi, peso * 3)     # tetto per categoria
                etichette.append(etichetta)
        peso_pen, regex_pen = self.penalita
        for r in regex_pen:
            if r.search(t):
                punteggio += peso_pen
                break
        if punteggio >= self.soglie["alta"]:
            livello = "alta"
        elif punteggio >= self.soglie["media"]:
            livello = "media"
        else:
            livello = "bassa"
        return punteggio, livello, etichette

    def territorio(self, predefinito, titolo, sommario):
        if predefinito and predefinito != "auto":
            return predefinito
        testo = normalizza_testo(titolo + " " + sommario)
        for terr in ("sicilia", "lazio", "ue"):
            if any(re.search(r"(?<![a-z])" + re.escape(p), testo) for p in self.territori.get(terr, [])):
                return terr
        return "nazionale"


# ---------------------------------------------------------------------
# ciclo principale
# ---------------------------------------------------------------------
def carica_dati():
    if FILE_DATI.exists():
        try:
            return json.loads(FILE_DATI.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            pass
    return {"aggiornato": None, "bandi": [], "fonti": []}


def raccogli_fonte(fonte):
    """Prova la fonte, poi il fallback. Restituisce (voci, errore, via_usata)."""
    tentativi = [(fonte["tipo"], fonte["url"])]
    if fonte.get("fallback"):
        tentativi.append((fonte["fallback"]["tipo"], fonte["fallback"]["url"]))
    errore = None
    for tipo, url in tentativi:
        try:
            f = dict(fonte, tipo=tipo, url=url)
            voci = LETTORI[tipo](f)
            if voci:
                return voci, None, f"{tipo} {url}"
            errore = f"{tipo}: pagina letta ma nessun bando riconosciuto"
        except Exception as e:  # noqa: BLE001
            errore = f"{tipo}: {type(e).__name__}: {str(e)[:160]}"
    return [], errore, None


def esegui(solo_fonte=None):
    regole = yaml.safe_load(FILE_PAROLE.read_text(encoding="utf-8"))
    valutatore = Valutatore(regole)
    fonti = [f for f in yaml.safe_load(FILE_FONTI.read_text(encoding="utf-8"))["fonti"] if f.get("attiva", True)]
    if solo_fonte:
        fonti = [f for f in fonti if f["id"] == solo_fonte]
        if not fonti:
            sys.exit(f"Fonte '{solo_fonte}' non trovata in fonti.yaml")

    dati = carica_dati()
    archivio = {b["id"]: b for b in dati["bandi"] if not b.get("esempio")}
    stato_fonti = {s["id"]: s for s in dati.get("fonti", [])}
    oggi = OGGI.isoformat()
    nuovi_totali = 0

    for fonte in fonti:
        t0 = time.time()
        voci, errore, via = raccogli_fonte(fonte)
        nuovi = 0
        for v in voci:
            bid = id_da_url(v["url"])
            punteggio, livello, etichette = valutatore.valuta(v["titolo"], v.get("sommario", ""))
            record = {
                "id": bid,
                "titolo": v["titolo"],
                "url": v["url"],
                "sommario": v.get("sommario", ""),
                "fonte_id": fonte["id"],
                "fonte": fonte["nome"],
                "ente": fonte.get("ente", fonte["nome"]),
                "blocco": fonte["blocco"],
                "territorio": valutatore.territorio(fonte.get("territorio", "auto"), v["titolo"], v.get("sommario", "")),
                "pubblicato": v["pubblicato"].isoformat() if v.get("pubblicato") else None,
                "scadenza": v["scadenza"].isoformat() if v.get("scadenza") else None,
                "sportello": bool(re.search(r"sportello|fino ad esaurimento|sempre aperto|rolling", normalizza_testo(v["titolo"] + " " + v.get("sommario", "")))),
                "punteggio": punteggio,
                "pertinenza": livello,
                "categorie": etichette,
                "ultima_visto": oggi,
            }
            if bid in archivio:
                vecchio = archivio[bid]
                record["prima_visto"] = vecchio.get("prima_visto", oggi)
                # una scadenza vista in passato non la perdo se oggi il testo non la riporta
                record["scadenza"] = record["scadenza"] or vecchio.get("scadenza")
                record["pubblicato"] = record["pubblicato"] or vecchio.get("pubblicato")
                record["note"] = vecchio.get("note", "")
                # stesso link già visto da una fonte primaria: l'aggregatore non la scalza
                if fonte["blocco"] == "aggregatori" and vecchio.get("blocco") != "aggregatori":
                    for campo in ("fonte_id", "fonte", "ente", "blocco", "territorio"):
                        record[campo] = vecchio.get(campo, record[campo])
            else:
                record["prima_visto"] = oggi
                record["note"] = ""
                nuovi += 1
            archivio[bid] = record
        nuovi_totali += nuovi
        stato_fonti[fonte["id"]] = {
            "id": fonte["id"], "nome": fonte["nome"], "blocco": fonte["blocco"],
            "stato": "ok" if voci else "errore", "trovati": len(voci), "nuovi": nuovi,
            "via": via, "errore": errore, "controllato": oggi, "secondi": round(time.time() - t0, 1),
            "ultimo_ok": oggi if voci else stato_fonti.get(fonte["id"], {}).get("ultimo_ok"),
        }
        print(f"[{'ok ' if voci else 'ERR'}] {fonte['id']:<28} {len(voci):>4} trovati  {nuovi:>3} nuovi  {errore or ''}")

    # pulizia: via i bandi che non vediamo più da troppo
    limite = (OGGI - dt.timedelta(days=GIORNI_MEMORIA)).isoformat()
    bandi = [b for b in archivio.values() if b.get("ultima_visto", oggi) >= limite]
    bandi.sort(key=lambda b: (b.get("prima_visto", ""), b.get("punteggio", 0)), reverse=True)

    dati = {
        "aggiornato": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "totale": len(bandi),
        "nuovi_oggi": nuovi_totali,
        "fonti": sorted(stato_fonti.values(), key=lambda s: (s["blocco"], s["nome"])),
        "bandi": bandi,
    }
    FILE_DATI.parent.mkdir(parents=True, exist_ok=True)
    FILE_DATI.write_text(json.dumps(dati, ensure_ascii=False, indent=1), encoding="utf-8")
    ok = sum(1 for s in stato_fonti.values() if s["stato"] == "ok")
    print(f"\n{len(bandi)} bandi in archivio, {nuovi_totali} nuovi oggi, {ok}/{len(stato_fonti)} fonti ok.")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--fonte", help="aggiorna solo questa fonte (id)")
    esegui(ap.parse_args().fonte)
