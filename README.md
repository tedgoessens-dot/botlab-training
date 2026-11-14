# Botlab Training

*showmethemoney*

Oefen met crypto-tradingbots op **live BTC/EUR-koersen** met **nep-geld**. Botlab Training draait volledig in je browser, op je pc en op je iPhone. Je hebt geen server, geen account en geen API-sleutels nodig.

**Online:** https://tedgoessens-dot.github.io/botlab-training/ (werkt zodra GitHub Pages aan staat, zie hieronder)

## Veilig

- **Alleen papierhandel.** De bots kopen en verkopen met nep-geld. Er gaan nooit echte orders uit.
- **Geen sleutels of wachtwoorden.** De koersen komen van de openbare koersfeed van Kraken (`wss://ws.kraken.com/v2`). Daar is geen account voor nodig.
- **Geen gegevens naar buiten.** Je kleurinstelling en de gekozen modus worden alleen in je eigen browser bewaard.
- Zet nooit API-sleutels, wachtwoorden of `.env`-bestanden in deze repository. De `.gitignore` houdt de meest voorkomende al tegen.

## Twee standen

| Stand | Koers | Snelheid |
| --- | --- | --- |
| **Live** | Echte BTC/EUR-koers van Kraken | Echte tijd. De bots lopen alleen zolang de pagina open is. |
| **Oefenmarkt** | Gesimuleerde koers | Versnelbaar tot 1 uur per seconde, dus veel trades in korte tijd |

## De bots

1. **Steunkoper** koopt net boven een steunlijn en verkoopt net onder de weerstand. De stop ligt net onder de steun.
2. **Weerstandverkoper** shortt net onder een weerstand en sluit net boven de steun.
3. **Uitbraak omhoog / omlaag** handelen pas als een 15m-candle met 1,5× het gemiddelde volume door de lijn sluit.
4. **Toeval** gooit een munt. Dit is de controlegroep: een goede bot moet hem verslaan.

De bots gebruiken de 9- en 20-EMA (1m en 5m) voor het momentum en de 200-EMA (5m) voor de trend. Kosten van 0,25% per trade zijn meegerekend. Standaard start elke bot met €50, met als doel €75 en een noodrem bij €35. Dit pas je aan bij **Instellingen**.

**Signaalknop:** rood = kopen (laagpunt), oranje = houden (stabiel), groen = verkopen (hoogtepunt). Bij Instellingen kun je ook de beurskleuren kiezen. Tik op de knop om te zien waarom de bots dit signaal geven.

Zet **"Vraag mijn akkoord bij elke koop en verkoop"** aan als je elke trade zelf wilt goedkeuren.

## Openen

- **Op je pc:** dubbelklik op `index.html`, of open de online link.
- **Op je iPhone:** open de online link in Safari, tik op het deelicoon en kies **Zet op beginscherm**. Botlab opent dan als een eigen app.

## GitHub Pages aanzetten (eenmalig)

1. Ga in deze repository naar **Settings → Pages**.
2. Kies bij **Source**: *Deploy from a branch*. Selecteer bij **Branch** `main` en de map `/ (root)` en klik op **Save**.
3. Na ongeveer een minuut staat de site op https://tedgoessens-dot.github.io/botlab-training/.

Let op: met een gratis GitHub-account werkt Pages alleen bij een **openbare** repository. Voor Pages op een privérepository heb je GitHub Pro nodig. Openbaar maken is hier veilig, want er staan geen sleutels of persoonlijke gegevens in.

## Botlab2: het volledige programma (map `botlab2/`)

In de map [`botlab2/`](botlab2/) staat het volledige Botlab-programma voor je Windows-pc of een eigen server. Het haalt live koersen op van Kraken of Bitvavo en kan, na jouw akkoord per order, ook met echt geld handelen. De uitleg staat in [`botlab2/LEESMIJ.txt`](botlab2/LEESMIJ.txt), en voor de server in [`botlab2/server/LEESMIJ-SERVER.txt`](botlab2/server/LEESMIJ-SERVER.txt).

- Start met `start_botlab.bat` (Python nodig). Het dashboard opent op http://127.0.0.1:8765.
- Je API-sleutels zet je alleen in `botlab_config.json` op je eigen pc of server. Dat bestand staat in `.gitignore` en komt dus **nooit** in deze repository, net als `botlab_state.json`.
- Het dashboard in deze map werkt alleen samen met `botlab.py`, niet via GitHub Pages.


---

Geen financieel advies. Resultaten op papier zeggen niets over echte winst.
