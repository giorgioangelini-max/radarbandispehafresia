#!/usr/bin/env python3
"""
Prova tutte le fonti (o una sola) SENZA toccare data/bandi.json e stampa
cosa ha trovato: quanti link, i primi titoli, l'errore se c'è.

Serve a capire quali indirizzi in fonti.yaml vanno bene e quali vanno
sistemati. Si lancia da GitHub col workflow "Verifica fonti" oppure in
locale:  python verifica_fonti.py [--fonte id] [--titoli 5]
"""

import argparse
import yaml

import raccogli


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--fonte", help="verifica solo questa fonte (id)")
    ap.add_argument("--titoli", type=int, default=4, help="quanti titoli d'esempio mostrare")
    args = ap.parse_args()

    fonti = yaml.safe_load(raccogli.FILE_FONTI.read_text(encoding="utf-8"))["fonti"]
    fonti = [f for f in fonti if f.get("attiva", True) and (not args.fonte or f["id"] == args.fonte)]
    regole = yaml.safe_load(raccogli.FILE_PAROLE.read_text(encoding="utf-8"))
    val = raccogli.Valutatore(regole)

    ok, ko = [], []
    for f in fonti:
        voci, errore, via = raccogli.raccogli_fonte(f)
        if voci:
            pertinenti = sum(1 for v in voci if val.valuta(v["titolo"], v.get("sommario", ""))[1] != "bassa")
            con_scadenza = sum(1 for v in voci if v.get("scadenza"))
            ok.append(f["id"])
            print(f"\n✔ {f['id']}  ({f['nome']})")
            print(f"   via: {via}")
            print(f"   {len(voci)} link, {pertinenti} pertinenti, {con_scadenza} con scadenza riconosciuta")
            for v in voci[:args.titoli]:
                sc = f"  [scad. {v['scadenza']}]" if v.get("scadenza") else ""
                print(f"   · {v['titolo'][:100]}{sc}")
        else:
            ko.append(f["id"])
            print(f"\n✘ {f['id']}  ({f['nome']})")
            print(f"   {errore}")
            print(f"   → apri {f['url']} nel browser: se la pagina esiste ma non ha link a bandi,")
            print(f"     cerca la pagina 'Bandi' o 'Avvisi' del sito e metti quell'indirizzo in fonti.yaml.")

    print("\n" + "=" * 70)
    print(f"Fonti ok: {len(ok)}   Fonti da sistemare: {len(ko)}")
    if ko:
        print("Da sistemare: " + ", ".join(ko))


if __name__ == "__main__":
    main()
