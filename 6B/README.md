# 6B - Händelsestyrda ärenden

## Mål och lösning

Modul 1 ersätter det direkta anropet till Power Automate med Azures egna tjänster:

```text
Novatrix-formulär -> API -> privat Blob Storage: arenden/<id>/arende.json
                                  |
                                  v
                              Event Grid
                                  |
                                  v
                          Function NotifyOnTicket
                                  |
                                  v
                    Storage Queue: kundtjanst-notiser
```

Event Grid filtrerar nya blobar i `arenden` som slutar med `/arende.json`. Bilagor startar ingen separat ärendenotis. Blob-triggern använder Event Grid som källa och läser ärendet via privat nätverk. Funktionen kontrollerar ärendets id och uppgifter och skriver en JSON-notis med id och blobnamn till kön. Den skickar inte mejl eller Teams-meddelanden. Kön är en beständig notis för en framtida mottagare; en automatisk mottagare ingår inte i modulen.

## Filer

| Fil | Användning |
| --- | --- |
| `modul-1-handelsestyrt/infra/main.json` | ARM för Function, nätverk, identitet, roller och värdlagring. |
| `modul-1-handelsestyrt/infra/events.json` | ARM för Event Grid och filtrerad prenumeration. |
| `modul-1-handelsestyrt/function/` | Python-funktion, beroenden och värdinställningar. |
| `modul-1-handelsestyrt/web/` | Formulär och API som sparar bloben utan direkt Power Automate-anrop. |
| `modul-1-handelsestyrt/scripts/deploy.py` | Resurser via ARM och funktionskod via Azures ZIP-publicering. |
| `modul-1-handelsestyrt/scripts/deploy-web.py` | Installerar webbvarianten via Run Command. |
| `modul-1-handelsestyrt/scripts/cleanup.py` | Tar bort modulens resurser efter testerna. |

## Säkerhet och designval

- Hanterad identitet används för alla lagringsanrop. Ingen lagringsnyckel eller anslutningssträng ligger i koden. Delade lagringsnycklar är avstängda.
- Befintlig ärendelagring behåller offentlig nätverksåtkomst avstängd. Funktionen ansluts till VNet och använder privata endpoints för blobar och triggerns felkö.
- Värdlagringen är ett separat konto med autentiserad publik nätverksanslutning. Anonym åtkomst är avstängd. Där finns intern kördata och notiskön, inte kundens ärendefiler.
- Blob-triggerns rekommenderade lagringsroller används. Blob Data Owner begränsas till containern arenden, Queue Data Contributor till ärendelagringen. Värdlagringens roller behövs för runtime och triggerns interna tillstånd.
- Event Grid använder en skyddad webhook. ARM hämtar dess systemnyckel från Azure; den är inte hårdkodad eller ett alternativ till den hanterade lagringsidentiteten.
- Event Grid kräver undantaget för betrodda Azure-tjänster på källkontot. Publiceringsskriptet aktiverar `AzureServices` för händelsekopplingen. Offentlig nätverksåtkomst och delade lagringsnycklar förblir avstängda. Anteckna tidigare undantag innan körning och återställ efter städningen.
- Notisen och applikationsloggen innehåller bara ärendenummer och teknisk information, inte kundens text eller e-post.
- Funktionen använder en liten Linux B1-plan med en instans under labben. Planen har timkostnad även när ingen händelse behandlas och tas därför bort efter testet. Flex Consumption provades först, men Azures interna nätverkskoppling gav ett autentiseringsfel. B1 använder App Service-nätverkskopplingen och bevarar samma privata ärendelagring.

## Körning

Azure CLI behöver vara inloggat med behörighet att driftsätta resurser och roller i Novatrix-resursgruppen. Befintlig miljö från tidigare uppgifter behövs. Kopiera parameters.example.json till en lokal privat parameterfil och fyll i egna namn. Värdlagringen måste vara separat från den befintliga ärendelagringen.

Driftsättningen ger den inloggade användaren läsbehörighet på notiskön för verifieringen. Rollen begränsas till den nya kön och tas bort vid städningen. Koden och beroendena byggs för Python 3.11 på Linux och publiceras som ZIP; Python med pip behöver finnas lokalt.

```text
python 6B/modul-1-handelsestyrt/scripts/deploy.py --parameters /private/6b.parameters.local.json
```

När funktionskoden är publicerad och NotifyOnTicket visas i Azure:

```text
python 6B/modul-1-handelsestyrt/scripts/deploy.py --parameters /private/6b.parameters.local.json --events-only
python 6B/modul-1-handelsestyrt/scripts/deploy-web.py --resource-group rg-novatrix --storage-account YOUR_EXISTING_STORAGE --keep-running-for-test
```

Skicka ett påhittat ärende i formuläret och jämför ärendenumret med notisen i kön. Kontrollera även att bilagan inte orsakar en extra notis. Ta först vara på nödvändiga bevis. Återställ föregående webbvariant om du vill använda uppgift 6 igen, innan den privata lagringsanslutningen tas bort.

```text
python 6B/modul-1-handelsestyrt/scripts/cleanup.py --parameters /private/6b.parameters.local.json --restore-source-bypass None
```

Städningen tar bort modulen, dess nätverksregel, värdlagringen och notiserna men bevarar befintlig VM och ärendelagring. Återställ det tidigare bypass-värdet; exemplet använder None som i denna labb. Den förutsätter att DNS-zonerna och källans felkö saknades före labben och inte delas med andra lösningar. Felkön markeras som modulens resurs och tas bara bort när markeringen finns.

## Begränsningar

Event Grid och köer kan leverera fler än en gång. En framtida mottagare behöver undvika dubbla åtgärder genom ticketId; exakt en leverans garanteras inte här. Vid upprepade funktionsfel finns triggerns felkö för kontroll. Köns notiser har livslängd ett dygn. Historiska ärenden behandlas inte automatiskt när prenumerationen skapas.

HTTP-formuläret är en labb utan TLS och kundinloggning. Använd påhittade uppgifter. Formulärets lyckade svar bevisar sparandet, inte att den efterföljande notisen redan är klar. Kontrollera kön separat.

Detta är modul 1. Alla tre moduler krävs för uppgiftens fulla VG-bredd.

## Verifierade resultat

- ARM-resurserna driftsattes och Event Grid-prenumerationen fick status Succeeded.
- Azure hittade NotifyOnTicket med blob-trigger och Event Grid som källa.
- Ett formulärärende med bilaga sparades och gav en notis med samma ticketId i kön. Bilagan gav ingen separat notis.
- Ett andra ärende gav också rätt notis efter återgång till B1. B2 användes tillfälligt under felsökningen.
- Den interna triggerkön skapas i ARM innan appen startar. HTTPS-regeln i det privata subnätet släpper bara in funktionssubnätets lagringsanrop.

Bildbevis och detaljerade testresultat finns i den separata rapporten.

Efter testerna återställdes webbvarianten från uppgift 6 och dess privata lagringsinställningar. VM:n är frigjord och modulens debiterande resurser är borttagna. Ett tomt subnät från Flex-försöket är fortfarande låst av Azures interna servicekoppling. Borttagning nekades; subnätet har ingen egen timkostnad.

## Kostnad

Beräkning debiteras efter användning och eventuella gratismängder. Privat endpoint har timkostnad, och lagring samt transaktioner kan kosta. Ta bort testresurserna efteråt. En budget varnar men stoppar inte kostnader. M365-provperioderna från uppgift 6 är separata och påverkas inte av denna modul.

## Källor

- [Microsoft: Event Grid-baserad blob-trigger](https://learn.microsoft.com/en-us/azure/azure-functions/functions-event-grid-blob-trigger?pivots=programming-language-python)
- [Microsoft: driftsättning som kod](https://learn.microsoft.com/en-us/azure/azure-functions/functions-infrastructure-as-code?tabs=linux)
- [Microsoft: ZIP-publicering](https://learn.microsoft.com/en-us/azure/azure-functions/deployment-zip-push)
- [Microsoft: App Service Linux-priser](https://azure.microsoft.com/en-us/pricing/details/app-service/linux/)
