# Botlab Training

Een trainingsomgeving voor crypto-tradingbots met **live koersen** van Bitvavo en Kraken.
Alles draait in je browser, zonder server. Standaard handel je met nep-geld. Echt geld kan alleen via Bitvavo, met jouw akkoord per order.

**Online openen:** https://tedgoessens-dot.github.io/botlab-training/

## Wat het doet

- Toont realtime koersen via de openbare websocket-feeds van Bitvavo en Kraken
- Live grafiek per **seconde, minuut, 5 en 15 minuten, uur, dag, week, maand en jaar**. Seconden worden live opgebouwd vanaf het openen van de pagina. Week en maand komen van de beurs (bij Kraken wordt de maand uit weekcandles opgebouwd), het jaar uit de maanden
- Laat de bots oefenen op papier: kopen net boven steun, verkopen net onder weerstand of handelen op een uitbraak, met de 9/20/200 EMA
- Signaalkleuren: **rood** = kopen bij een laagpunt, **oranje** = houden, **groen** = verkopen
- Je instellingen en oefenresultaten blijven bewaard in de browser van je eigen apparaat

## Kleuren en aanwijzers

- Signaal en knoppen: **rood = kopen**, **oranje = houden**, **groen = verkopen**. Het beurs-standaardschema kan ook.
- Steunlijn = koopzone (koopkleur), weerstandslijn = verkoopzone (verkoopkleur).
- Bots hebben neutrale kleuren: Steunkoper blauw, Weerstandverkoper geel, Uitbraak omhoog paars, Uitbraak omlaag lila en Toeval grijs.
- In de grafiek staat ▲ voor koop en ▼ voor verkoop, met een rand in de kleur van de bot. **Aanwijzers** tonen wat elke bot deed, waar een open positie staat en waar een wachtende bot in actie komt. Beweeg of tik op een teken voor de details.

## Wanneer kopen of verkopen

- **KOPEN** alleen bij een laagpunt (bij steun of ver onder de 20 EMA), in een stijgende trend op 5m én 1u (200 EMA), en pas als de koers draait (9 EMA weer boven 20 EMA op 1m).
- **VERKOPEN** bij een hoogtepunt (bij weerstand of ver boven de 20 EMA).
- Bij de bots staat wat de Steunkoper doet en waarom.

## Kosten en winstbehoud

- Kosten per beurs: Bitvavo 0,25% en Kraken 0,80% per kant (instelbaar), plus spread en slippage. Een doel moet minstens 2× de kosten opleveren.
- **Risico per trade**: de inzet is zo gekozen dat je bij de stop ongeveer 1% van je kas verliest.
- **Winstkluis**: 50% van elke winst gaat apart en wordt niet opnieuw ingezet.
- **Pauze**: daalt een bot 10% vanaf zijn hoogste stand, dan doet hij 24 uur geen nieuwe trades.

## Wachtrij en pushmeldingen

- Standaard wacht elke trade op **jouw akkoord**. De wachtrij staat bovenaan, met een teller ⏳ in de kopbalk en een afteller per voorstel. Geldigheid: 2, 5, 10 of 15 minuten. Daarna vervalt het voorstel.
- **Pushmelding naar je telefoon** via de gratis app **ntfy**: abonneer je in ntfy (server ntfy.sh) op het onderwerp dat in de app staat en klik **Testmelding**.
- In de melding staan **Akkoord** en **Niet doen**, als knop én als tikbare link. Je antwoord komt terug bij de app op je pc, die het uitvoert. Elk voorstel heeft een eenmalige code: een oud of verkeerd antwoord doet niets.
- **Echte orders** keur je standaard alleen in de app goed. Vanuit de melding kan alleen als je dat apart aanzet. Dan geldt bovendien: is de koers meer dan 0,5% opgelopen sinds het voorstel, dan koopt de app niet.
- Het onderwerp werkt als wachtwoord: deel het niet. Meldingen gaan via ntfy.sh, met alleen bot, coin, koers en bedrag, nooit sleutels of saldi.
- De pagina met de bots moet openstaan (bijvoorbeeld op je pc). Daar worden je antwoorden uitgevoerd.

## Backtest

Test alle bots in een paar seconden op 30, 90 of 180 dagen aan 1-uurscandles (Bitvavo, openbaar). Daarbij gelden dezelfde kosten, slippage, risico en winstkluis. Je ziet trades, winst-%, winstfactor, eindstand en maximale daling, vergeleken met Toeval en met kopen en vasthouden. Het is een benadering, geen garantie.

## Coin-zoeker

Klik bovenin op 🔎 om alle EUR-markten van Kraken of Bitvavo te doorzoeken. Kies een coin en de bots gaan direct op die markt trainen.

Per coin zie je de koers, de verandering over 24 uur, het volume, het dagbereik ("beweging"), de spread en de minimale ordergrootte. De **Trade-index (0–100)** geeft aan hoe geschikt een coin is voor deze bots:

- **Liquiditeit 40%**: volume per dag (€10.000 = 0, €100 mln = vol)
- **Spread 25%**: verschil tussen bied- en laatprijs (hoe kleiner, hoe goedkoper)
- **Beweging 35%**: dagbereik van 2–8% is ideaal voor steun en weerstand

70 of hoger is geschikt, 45–69 is matig en onder 45 is riskant. De drempels van de bots schalen mee met de beweeglijkheid van de gekozen coin. Elke coin heeft zijn eigen bewaarde trainingsstand.

## Uitvoering van trades

Elke trade (papier en echt) staat in **Uitvoering van trades** als stappenplan:

1. **Signaal**: welke bot, waarom, en de koers op dat moment
2. **Controles**: trendfilter, winst/risico, stop-afstand, inzet, kosten en akkoord
3. **Order**: papier of echt, market-order, bedrag en hoeveelheid
4. **Uitvoering**: gevulde prijs, kosten en slippage ten opzichte van het signaal
5. **Beheer**: doel, stop en het ongerealiseerde resultaat zolang de positie loopt
6. **Afsluiting**: reden, prijs en resultaat

Klik je een trade aan, dan zie je instap, doel en stop als lijnen in de grafiek.

## Echt geld via Bitvavo

Standaard is alles papier. Wil je echt handelen:

1. Maak op bitvavo.com via **Instellingen → API** een sleutel met alleen **Bekijken** en **Handelen**. Zet **Opnemen nooit aan**.
2. Plak sleutel en geheim in de app en klik **Verbinden**. Het geheim verlaat je apparaat niet: de app ondertekent het inloggen zelf (HMAC-SHA256).
3. Kies de echte bot (alleen long), het bedrag per order en je dag-limieten. Zet dan **Echt geld AAN**.

Veiligheid:

- Een bot mag pas met echt geld als hij op papier **bewezen** is: minstens 30 trades, winstfactor boven 1,2 na kosten, en beter dan Toeval.
- Elke echte koop en verkoop vraagt **jouw akkoord**. Een koopvoorstel vervalt na 2 minuten.
- Na elke koop zet de app een **stop-loss bij Bitvavo zelf**. Die werkt ook als je telefoon slaapt of de pagina dicht is. Verkoopt de bot eerder, dan annuleert de app eerst die stop.
- Ordertype: market (direct) of limiet als maker (goedkoper, maar wordt binnen 60 seconden gevuld of geannuleerd). Bij een verkoop gaat wat niet gevuld is alsnog via market.
- Zolang echt geld aanstaat, blijft het scherm aan (als de browser dat toestaat).
- Limieten: bedrag per order, maximum aantal orders per dag en maximum verlies per dag. Bij het dagverlies gaat echt geld automatisch uit.
- **Noodstop** zet echt geld uit en annuleert alle voorstellen. Met **Verkoop echte positie nu** verkoop je zelf.
- Na herladen of bij een verbroken verbinding staat echt geld altijd **UIT**.
- Echte orders zijn alleen long. Bitvavo heeft short selling wel in de app, maar nog niet via de API, dus short-bots blijven papier.
- De sleutel wordt alleen bewaard als je dat zelf aanvinkt. Doe dat alleen op je eigen apparaat.

Echt geld is echt risico. Begin klein en controleer je eerste orders in de Bitvavo-app. Dit is geen financieel advies.

## Op je telefoon

**iPhone (Safari):** open de link hierboven, tik op het deelicoon en kies **Zet op beginscherm**.
**Android (Chrome):** open de link, tik op ⋮ en kies **App installeren** of **Toevoegen aan startscherm**.

Botlab staat dan als app-icoon op je telefoon en opent zonder adresbalk.

Pushmeldingen: installeer de gratis app **ntfy**, abonneer je op het onderwerp dat in Botlab staat en klik in Botlab op **Testmelding**.

## Veiligheid

- Er staan **geen API-sleutels** of wachtwoorden in deze code en die horen er ook nooit in.
- Zonder API-sleutel gebruikt de pagina alleen openbare koersdata en plaatst hij geen orders.
- **Sleutel onthouden** gebeurt alleen versleuteld met een pincode van minstens 6 cijfers (PBKDF2 + AES-256-GCM), alleen op je eigen apparaat. Na 5 keer een verkeerde pincode wordt de bewaarde sleutel gewist.
- De pagina mag alleen verbinding maken met Bitvavo, Kraken en ntfy.sh (Content-Security-Policy). Andere adressen blokkeert de browser.
- Maak bij Bitvavo een sleutel met alleen **Bekijken** en **Handelen**, nooit **Opnemen**.
- Beveilig je GitHub-account met **tweestapsverificatie**: wie dit account overneemt, kan de app aanpassen.
- De app-pagina op GitHub Pages is altijd openbaar. Zet hier dus nooit sleutels, saldo's of persoonlijke gegevens neer.

## Bijwerken

Vervang `index.html` door een nieuwe versie. GitHub Pages zet de wijziging binnen een paar minuten online. Op je telefoon zie je de nieuwe versie na het opnieuw openen van de app.
