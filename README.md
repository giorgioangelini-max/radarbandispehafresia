# Radar bandi · Speha Fresia

Motore di ricerca interno per bandi e avvisi. Ogni mattina un automatismo
passa una cinquantina di fonti (Regione Siciliana e Lazio, ministeri, fondi
interprofessionali, portale UE, aggregatori del Terzo settore), salva i bandi
in un database e li etichetta per pertinenza rispetto a quello che Speha
Fresia può fare: formazione, politiche attive, orientamento, Terzo settore,
sviluppo locale, digitalizzazione e consulenza.

Niente modelli AI, niente chiavi, niente server: solo titoli e link veri presi
dalle fonti. Costo: zero, per sempre, sul piano gratuito di GitHub.

## Come è fatto

| File | A cosa serve |
|---|---|
| `index.html` | il sito: ricerca, filtri, scadenze, note, esporta CSV |
| `data/bandi.json` | il database, riscritto ogni mattina dall'automatismo |
| `fonti.yaml` | **la lista delle fonti** — questo lo modifichi tu |
| `parole_chiave.yaml` | **parole e pesi della pertinenza** — anche questo lo modifichi tu |
| `raccogli.py` | il collettore: legge le fonti e aggiorna il database |
| `verifica_fonti.py` | prova le fonti e ti dice quali funzionano |
| `.github/workflows/aggiorna.yml` | fa girare il collettore ogni mattina alle 6:30 |
| `.github/workflows/verifica.yml` | lancia la verifica fonti quando lo chiedi tu |

## Metterlo online (una volta sola, 10 minuti)

1. **Account GitHub.** Se non lo hai: github.com → Sign up. Il piano gratuito basta.

2. **Crea il repository.** In alto a destra `+` → *New repository*.
   Nome: `radar-bandi`. Lascia **Public** (GitHub Pages gratis funziona solo
   sui repository pubblici; dentro ci sono solo link a bandi già pubblici,
   niente di riservato). Non spuntare nulla, premi *Create repository*.

3. **Carica i file.** Nella pagina del repository vuoto clicca
   *uploading an existing file*. Trascina dentro **tutto il contenuto** di
   questa cartella, compresa la cartella nascosta `.github` (su Windows/Mac
   se non la vedi: attiva i file nascosti, oppure carica prima tutto il resto
   e poi crea a mano `.github/workflows/aggiorna.yml` con *Add file → Create
   new file*, incollando il contenuto). In basso premi *Commit changes*.

4. **Dai il permesso di scrittura all'automatismo.**
   *Settings → Actions → General → Workflow permissions* →
   seleziona **Read and write permissions** → *Save*.

5. **Attiva il sito.** *Settings → Pages → Build and deployment →
   Source: Deploy from a branch → Branch: main, cartella / (root)* → *Save*.
   Dopo un minuto in alto compare l'indirizzo, del tipo
   `https://TUONOME.github.io/radar-bandi/`. Salvalo nei preferiti.

6. **Primo aggiornamento.** Scheda *Actions* → a sinistra *Aggiorna bandi* →
   *Run workflow* → *Run workflow*. Dopo 3-5 minuti il sito si riempie
   (ricarica la pagina). Da qui in poi gira da solo ogni mattina.

## Sistemare le fonti (la prima settimana)

Gli indirizzi in `fonti.yaml` sono la mia migliore stima: alcuni siti
cambiano struttura, altri non hanno un feed, alcuni bloccano i robot.
Aspettati che **un terzo delle fonti dia errore al primo giro**: è normale
e si sistema in pochi minuti l'una.

1. Nel sito premi **Stato fonti**: vedi chi ha risposto e chi no, con
   l'errore.
2. Per una fonte in errore apri il suo sito nel browser e cerca la pagina
   "Bandi", "Avvisi", "Opportunità" o simili. Copia l'indirizzo.
3. Su GitHub apri `fonti.yaml`, premi la matita, sostituisci l'`url` di
   quella fonte, *Commit changes*.
4. Prova subito: *Actions → Verifica fonti → Run workflow*, nel campo scrivi
   l'`id` della fonte. Dopo un minuto, apri il risultato e leggi cosa trova.
   Se vedi i titoli giusti, fatto: al prossimo giro entra nel database.

Trucchi:
- Se una fonte è WordPress (quasi tutti i siti di fondazioni e aggregatori),
  `https://sito.it/feed/` funziona quasi sempre ed è la via più affidabile.
  Mettilo come `tipo: rss`.
- Se una pagina HTML prende troppi link inutili (menu, notizie), aggiungi
  `selettore:` con il selettore CSS del blocco che contiene un singolo bando
  (es. `article`, `.card`, `li.bando`). Con il tasto destro → *Ispeziona*
  sul titolo di un bando lo trovi in un attimo.
- Per aggiungere una fonte nuova: copia una voce esistente, cambia `id`,
  `nome`, `ente`, `blocco`, `territorio`, `url`. Fine.
- Per spegnere una fonte senza cancellarla: aggiungi `attiva: false`.

## Regolare la pertinenza

`parole_chiave.yaml` decide il punteggio. Ogni parola trovata nel sommario
vale il peso della sua categoria, nel titolo il doppio. Sotto 3 → bassa,
da 3 a 6 → media, da 7 → alta. Le parole in `penalita` (forniture, buoni
pasto, concorsi, graduatorie…) tolgono 4 punti.

Se noti che il radar segna "alta" cose che non ti interessano, o "bassa"
cose che ti interessano: aggiungi o togli parole, oppure alza/abbassa le
soglie in fondo al file. Le modifiche valgono dal giro successivo e
ricalcolano tutto l'archivio.

## Cose da sapere

- **Le scadenze le legge dal testo**: cerca una data vicina a parole come
  "scadenza", "entro", "termine". Quando non la trova scrive "Scadenza
  n.d." e tu apri il link. Meglio un n.d. onesto che una data inventata.
- **Le note e le stelle** che metti nel sito restano nel browser che stai
  usando (non vanno su GitHub). Se cambi computer non le ritrovi; l'esporta
  CSV le include, se vuoi tenerle.
- Un bando resta in archivio finché una fonte lo mostra; sparisce dopo 240
  giorni che non lo si vede più. I bandi scaduti restano consultabili col
  filtro "Anche scaduti": utili per capire cosa esce ogni anno.
- Il portale UE viene letto con la sua API pubblica (chiave `SEDIA`, che è
  la loro, non tua). Tiene solo le call CERV, Erasmus+, ESF+, EaSI, AMIF,
  JUST, Digital, Creative Europe: i prefissi sono in `fonti.yaml`.
- L'orario è 6:30 ora italiana in estate, 5:30 in inverno (GitHub usa UTC).
  Per cambiarlo modifica la riga `cron` in `aggiorna.yml`.
- GitHub sospende gli automatismi programmati sui repository fermi da 60
  giorni. Basta che tu apra il sito o faccia una modifica ogni tanto; se
  vedi l'avviso "ultimo aggiornamento di N giorni fa", vai su Actions e
  premi *Run workflow*.
