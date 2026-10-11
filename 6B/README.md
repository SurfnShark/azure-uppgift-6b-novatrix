# 6B: elastiskt, övervakat och händelsestyrt

## Lösningen

Alla tre modulerna finns i separata mappar. Azure-resurserna beskrivs i ARM och programmen finns som kopierbar kod.

```text
Besökare -> publik lastbalanserare -> scale set med 1 eller 2 webbinstanser
                                       |
                                       v
                               privat Blob Storage
                                       |
                                    Event Grid
                                       |
                               Function NotifyOnTicket
                               /        |           \
                            journal    könotis       mejl

CPU-metrik -> autoskalning och CPU-larm -> action group -> mejl
Azure Monitor Agent -> Log Analytics -> KQL
Azure Policy -> kräver labbtagg på scale set
```

## Modul 1: ärendekedjan

Event Grid reagerar bara på nya `arende.json` i containern `arenden`. Bilagor startar ingen egen ärendenotis. Funktionen läser och validerar ärendet med hanterad identitet, skriver en journal i `notification-audit`, lägger en notis i `kundtjanst-notiser` och skickar ett mejl via Azure Communication Services.

Event Grid gör att kedjan reagerar på en sparad fil utan att ett program behöver kontrollera lagringen hela tiden. Funktionen samlar valideringen och de tre åtgärderna i kod. Blob Storage sparar teknisk status, kön gör det möjligt att behandla notisen senare och Communication Services sköter mejlet utan en Microsoft 365-anslutning.

En domän som Azure hanterar används som avsändare. Ingen egen domän eller lagringsnyckel behövs. Mottagaren anges i en privat parameterfil. Testärenden ska innehålla påhittade uppgifter. Journal, könotis, logg och mejl innehåller ärendenummer och teknisk status, inte kundens namn, adress eller ärendetext.

Journalen sparar vilka åtgärder som bekräftats. En tillfällig bloblease begränsar samtidiga försök för samma ärende. Exakt en leverans garanteras ändå inte: om ett anrop lyckas men svaret eller journaluppdateringen försvinner kan en åtgärd upprepas. En framtida mottagare av kön behöver känna igen ticketId. Notiserna i kön sparas i högst ett dygn.

## Modul 2: skalbar webb

Webbinstanserna använder samma grundupplägg med cloud-init som tidigare Novatrix-VM: Nginx, Python-API och hanterad identitet. Webbvarianten sparar ärendet utan att anropa Power Automate. En Standard Load Balancer fördelar HTTP-trafiken. Proben använder `/api/health`, och en utgående regel ger instanserna tillgång till paket och Azure-tjänster.

Hälsokontrollen har en egen Nginx-regel utan formulärets begränsning av antalet anrop. Det gör att lastbalanserarens återkommande kontroller inte blockeras av HTTP 429. Formulärets övriga API-anrop behåller trafikbegränsningen.

Autoskalningen styrs av genomsnittlig CPU under fem minuter:

| Regel | Åtgärd |
| --- | --- |
| Över 70 procent | Lägg till en instans. |
| Under 30 procent | Ta bort en instans. |
| Minsta och största antal | 1 respektive 2. |
| Väntetid efter en skalning | Fem minuter. |

Gränserna skiljer sig åt för att undvika upprepad skalning upp och ner vid samma belastning. Högst två instanser begränsar kostnaden. B-storleken hade kapacitets- eller kvotbegränsningar i testmiljön; parameterexemplet använder därför D2s v6. Välj en mindre tillgänglig storlek om prenumerationen tillåter det. Tillgänglighet över flera zoner är inte verifierad i denna labb.

Belastningstestet använder två CPU-processer i en tillfällig systemd-tjänst med tidsgräns. Det följer kapaciteten och kontrollerar svar från båda instanserna via lastbalanseraren. Svarshuvudet `X-Novatrix-Instance` visar vilken instans som svarade.

## Modul 3: övervakning och regler

CPU-larmet reagerar när genomsnittlig CPU är över 80 procent under fem minuter. En action group skickar mejl till labbägaren. Adressen behöver verifieras hos Azure. När belastningen sjunker kan larmet återgå till normalt tillstånd.

Azure Monitor Agent skickar livstecken och ett begränsat urval av allvarliga systemloggar till Log Analytics. KQL-frågan i `modul-3-overvakat/heartbeat.kql` visar antal livstecken och senaste kontakt per webbinstans. Insamlingen begränsas till en liten mängd loggar, och arbetsytan har en daglig datagräns.

Azure Policy tillämpar den inbyggda regeln som kräver taggen `lab=novatrix-vg`. Tilldelningen begränsas till labbens scale set. En ändring utan taggen ska nekas. Regeln påverkar inte hela prenumerationens övriga resurser.

En separat budget för Novatrix-resursgruppen varnar vid 25 och 50 kronor när kontots faktureringsvaluta är SEK. Budgeten stoppar inte resurser, och kostnadsdata kan visas med fördröjning. Den kan behållas efter labben eftersom den inte kör någon beräkning.

## Säkerhet

- Ärendelagringen behåller publik nätverksåtkomst avstängd. Privata endpoints och avgränsade HTTPS-regler används.
- Funktionsappen och webbinstanserna använder hanterade identiteter. Lagringsnycklar är avstängda och anonym åtkomst tillåts inte.
- Funktionens lagringsroller följer blobtriggerns krav. Ärendeblobarnas roll begränsas till containern `arenden`.
- Contributor tilldelas endast på labbens Communication Services för mejlsändning. Rollen kan även administrera just den resursen och är därför bredare än enbart mejlsändning.
- Event Grid använder en skyddad webhook. ARM hämtar systemnyckeln från Azure; ingen nyckel ligger i koden.
- Undantaget `AzureServices` behövs på ärendelagringen för Event Grid. Återställ det tidigare värdet efter labben.
- Ingen publik SSH-port öppnas. Administration och belastningstest använder Azure Run Command.
- HTTP-formuläret saknar TLS och kundinloggning och används bara med påhittade uppgifter.

## Körning

Azure CLI och Python med pip behövs. CLI ska vara inloggat i rätt Azure-prenumeration. Den befintliga Novatrix-miljön, nätverket, containern `arenden` och identiteten `id-novatrix-app` behövs. Kopiera parameterexemplen till privata filer och fyll i egna namn, offentlig SSH-nyckel och mottagaradress. Värdlagringen måste vara separat från ärendelagringen. DNS-zoner och modulens felkö ska inte delas med en annan lösning.

```text
python 6B/modul-1-handelsestyrt/scripts/deploy.py --parameters /private/module1.local.json
python 6B/modul-1-handelsestyrt/scripts/deploy.py --parameters /private/module1.local.json --events-only
python 6B/modul-2-elastiskt/scripts/deploy.py --parameters /private/module2.local.json
python 6B/modul-3-overvakat/scripts/deploy.py --parameters /private/module3.local.json
az deployment group create --resource-group rg-novatrix --template-file 6B/modul-3-overvakat/infra/budget.json --parameters @/private/budget.local.json
python 6B/modul-2-elastiskt/scripts/load-test.py --output /private/scale-test.local.json
```

Kopiera `modul-3-overvakat/budget.parameters.example.json` till den privata budgetfilen och fyll i mottagare och månadens första dag som startDate. Lägg budgeten innan belastningstestet. Om en tjänst nyss registrerats kan Azure behöva tid innan dess API fungerar; kontrollera registreringen och försök igen. Skicka därefter ett påhittat formulärärende genom lastbalanseraren och jämför samma ticketId i journalen, kön och mejlet.

Samla bevis innan städningen. Återställ eventuell tillfälligt ändrad webbvariant på den tidigare VM:n innan dess privata lagringsanslutning tas bort.

```text
python 6B/cleanup-vg.py --parameters /private/module1.local.json
```

Städningen tar bort labbens scale set, lastbalanserare, autoskalning, larm, policytilldelning, arbetsyta, privata anslutningar, funktionsapp, mejltjänster, värdlagring och tillfälliga roller. Befintlig VM och ärendelagring bevaras. VM:n frigörs. Källans bypass återställs till None, som gällde i denna miljö. Budgeten behålls.

## Verifiering

Alla tre modulerna är driftsatta och kontrollerade i Azure:

| Kontroll | Resultat |
| --- | --- |
| Händelsekedja | Samma ärendenummer i formulärsvaret, journalen, könotisen och det mottagna mejlet. |
| Autoskalning | CPU-belastning gav automatisk skalning från en till två instanser och tillbaka till en. |
| Lastbalanserare | HTTP 200 från båda instansernas hälsokontroll. |
| CPU-larm | Larmet utlöste vid cirka 99,58 procent och återställdes när belastningen sjönk. |
| Larmets mejlkoppling | Verifierad mottagaradress och kopplad action group. Ett separat test för metriklarm skickades genom Azure Monitor och mottagaren bekräftade att testmejlet kom fram. CPU-larmet och mejlleveransen verifierades i två separata tester. |
| KQL | Livstecken från båda webbinstanserna i Log Analytics. |
| Azure Policy | Ändring utan labbtaggen nekades med RequestDisallowedByPolicy; befintliga taggar bevarades. |
| Städning | Inga debiterande 6B-testresurser kvar. Ursprunglig VM frigjord, ärendelagring privat och bypass återställd till None. |

Ett tomt subnät från ett tidigare Flex-försök är fortfarande låst av en Azure-koppling. Det kör ingen beräkning och har ingen egen timkostnad. Budgeten behålls.

Bildbevisen redovisas i den separata PDF-rapporten. PDF, privata parameterfiler, råa bevis och arbetsanteckningar ingår inte i GitHub-underlaget.

## Källor

- [Microsoft: Event Grid och blobtrigger](https://learn.microsoft.com/en-us/azure/azure-functions/functions-event-grid-blob-trigger?pivots=programming-language-python)
- [Microsoft: skicka mejl via Azure Communication Services](https://learn.microsoft.com/en-us/azure/communication-services/quickstarts/email/send-email)
- [Microsoft: autoskalningens regler](https://learn.microsoft.com/en-us/azure/azure-monitor/autoscale/autoscale-understanding-settings)
- [Microsoft: Azure Monitor Agent](https://learn.microsoft.com/en-us/azure/azure-monitor/agents/azure-monitor-agent-manage)
- [Microsoft: Azure Policy](https://learn.microsoft.com/en-us/azure/governance/policy/overview)
