# FIRE App SDK: backend, simulator og Studio

SDK-kontrakten og biblioteket er beskrevet i [FIRE_APP_SDK.md](FIRE_APP_SDK.md).
Backend bruker samme kanoniske kontrakt, bitmapfonter, lisensierte ressurser og
`ui.lua` som firmware. Ingen separat font- eller assetkatalog vedlikeholdes.

## Valg av kontrakt

Enheten beholder maskinvarekontrakten `fire-lua-0.2`. SDK-pakker velges bare når
kapabilitetene annonserer `app_sdk.version=fire-app-sdk-1.0` og riktig separat
SDK-kontrakthash. Pakken angir SDK-versjonen og SDK-hashen eksplisitt. Eldre
0.1/0.2-pakker og maskinvarehashen er bevart. SDK kan ikke gi displaytilgang uten
tilsvarende tjeneste og tillatelse. Pakker avvises ved kontraktavvik.

Den uttrykkelig valgte PC-maskinvareprofilen annonserer også SDK. Dens syntetiske
sensorer og I/O er alltid simulering og gir ingen fysisk enhet nye kapabiliteter.

## Bygging og kodekontroll

Vanlig `build_confirm` med gjeldende forslag kreves fortsatt. Genereringen får et
deterministisk utvalg av relevante komponenters faktiske signaturer, tema,
layoutretning, fontmetrikker og maksimalt tolv ressursbeskrivelser. Hele katalogen,
bitmapdataene og UI-modulen sendes ikke i prompten. Ved feil beholdes eksisterende
avgrenset reparasjonsflyt og kildebundet feilhistorikk.

`fire-sdk-generation-v5` erstatter de generelle legacyinstruksene i SDK-kall med
én konsistent versjonsstyrt policy. Valgte komponenter får kanonisk hjelp og
options, ekte temapalett og korte kjørbare Lua-eksempler. Norske sammensatte
appnavn som «bilspill», «værapp» og «måleinstrument» samt engelske aliaser velges
av samme kategorisering som brukes for relevante maskinvaredetaljer. Hele den
faktiske tilgjengelighetslisten beholdes; detaljerte signaturer velges fra mål,
avhengigheter og eksisterende apps manifest. Dette gir ingen nye tillatelser.
En liten gruppert opplysning hentes fra de faktiske fontmaskene: seks UI-fonter
har skrivbar ASCII og ni ekstra tegn, mens legacyreferansen bare har skrivbar
ASCII. Andre tegn blir `?`. Ingen ny font, API eller parallell tegnliste innføres.
Kodekontrollen får eksplisitt aktuell kandidatkontrakt og skal skille konkrete
feil fra valgfri ekstra funksjonalitet og umålt fysisk ytelse.

Nye SDK-livebygg har en deterministisk standardport før AI-review. Faktisk
annonserte tjenester og bekreftet bestilling bestemmer RGB-/lydkravene; en
kandidat kan ikke unngå dem ved å utelate `rgb` eller `speaker`. Lokale tester må
vise ikke-null aktivitet på begge LED-sider og faktiske speaker-jobber når lyd
er avtalt og tilgjengelig. Start med lyd av og permanent brukerunntak behandles
forskjellig. Mangler rettes med den kjernetestede koden som grunnlag.
Tolking av nektede tillegg støtter også norsk/engelsk kommaseparerte og skråstrek-
lister: «ingen ny lyd» er verken et positivt lydønske eller et permanent unntak
fra avtalt spilllyd. Separate positive/nektende klausuler beholdes.
Levering krever kilde-/kontraktbundet standardbevis i tillegg til lokale tester og review.
Se [SDK_STANDARD_GATE_PLAN.md](SDK_STANDARD_GATE_PLAN.md) for kontroll og avgrensning.

Release-testene kjører ekte Lua i den eksisterende isolerte worker-prosessen.
Utvalgte komplette frames fanges uavhengig av den korte diagnostikktracen.
Oppstart, navigasjon, aktiv bruk, lengre kjøring og relevante feilstier kan gi
bilder. Like operasjonssekvenser og like piksler dedupliseres. Maksimalt åtte
PNG-er lagres og seks vedlegges den eksisterende kodekontrollen i samme AI-kall
som kildekode og testresultater. Det opprettes ingen separat designagent.

Bilder bindes til full kildehash, PNG-hash, SDK-kontrakt og et datafingeravtrykk
av UI, fonter, assets og SDK-metadata. Kilde- eller datamismatch avvises før visning
eller AI-bruk. Filnavn er korte for Windows; full hash valideres som identitet.

## Grenser og avgrensninger

SDKs `display.set_background(color)` konfigurerer neste OS-forberedte frame;
startverdien er svart. `ui.set_theme` gjør dette i `init` og ved temavalg før neste
oppdatering. Bare første identiske `clear` på en fortsatt urørt frame kan bruke
OS-fyllingen; alle kall belastes fortsatt. Senere `clear`, annen farge og sletting
etter tegning beholder ekte slettesemantikk. Bakgrunnen følger capture, raster og
bildededuplisering. Gamle 0.1/0.2-pakker beholder svart OS-bakgrunn og gamle porter.

SDK bruker kontraktens 64 totale I/O-kall, 2048 I/O-bytes og 256 tekstbytes per
callback, inkludert måling. Grid har 384 kumulative celler og 32768 piksler.
Appens annonserte minnekvote gjelder også UI-preluden. Hostens private
font-/assetoppslag telles før appens minnebaseline og eksponeres ikke til appen.
Private, varig beholdte trace-/skjermbildetabeller måles separat ved allokeringen;
de bruker ikke appens heapkvote. Identisk galleriapp er kontrollert med
null/ett/åtte captures; for stor reell appallokering avvises fortsatt. UI-kode og
appdata er fullt kvotebelagt. Ingen Python-callback eller appkode kjøres under
den private diagnostikkmålingen.
Ingen Python-callback, generell filtilgang, `require`, OS-funksjon eller loader
gjøres tilgjengelig i appmiljøet.

Den gamle konservative 0.2-policyen med 24 outputoperasjoner, 120000 estimerte
work-enheter og 128 kumulative gridceller er bevart for gamle profiler. Den er
ingen skjult SDK-grense. SDK rapporterer fortsatt estimert tegnearbeid, men PC-en
måler ikke ESP32-callbacktid. Den opprinnelige SDK-updategrensen var 12 ms;
etter fysiske målinger kalibreres bare SDK-update til 24 ms. Knappetrykk beholder
12 ms, init beholder sin eksisterende grense på 250 ms, også for legacy.
Trusted UI-load (250 ms) og kildekompilering (1000 ms) er separate, uendrede
oppstartsgrenser. Appminne-, instruksjons-, I/O-, byte- og gridkvoter er uendret.
V5-policy, forhandlet kontrakt og worker-metadata avleder fasefakta fra samme
kanoniske kontrakt. PC-workerens lokale guard er ingen ESP32-tidsmåling;
`native_timing_measured=false`. Ny fysisk OS-, knapp- og nettverksmåling må
bestås før denne SDK-kalibreringen kan godkjennes som fysisk leveranse.

Hver fanget frame er fullstendig, maksimalt 64 tegneoperasjoner og 24000
serialiserte tegn; ingen avkortet frame presenteres som et fullstendig bilde.
PNG-er er maksimalt 240000 bytes. Framebufferen starter med den fangede
OS-bakgrunnsfargen; eldre frames uten feltet starter svart. Bitmapfontene og
atlasdataene er felles;
eksakt native rasterisering, numerisk paritet og fysisk ytelse er ikke bevist
av en PC-simulering. Dette vises også i metadata og brukergrensesnittet.
`font_data_exact` gjelder bitmapdataidentitet. `font_mode` skiller delte
SDK-fonter fra legacyreferanse; historiske firmwarefontinnstillinger har separat
`legacy_font_settings_verified=false`. Ingen av feltene beviser fysisk rasterparitet.

## Studio

Åpne Appbibliotek og velg **Forhåndsvisning** for den valgte appversjonen.
Simulatoren viser 320 × 240, virtuelle korte A/B/C-trykk, bildene fra forløpet,
ny start og ett sekund videre. Hver forespørsel spiller en avgrenset sekvens på
nytt: maksimalt 32 korttrykk og 12 sekunder. Den installerer eller kjører ingen
app på FIRE. En blokkert pakke kan undersøkes uten at leveringsblokken fjernes.

Samme innlogging, CSRF- og origin-kontroll som resten av Studio gjelder.
Arkivets manifest, kildehash og ZIP-hash kontrolleres før simulering. Bare én
interaktiv forhåndsvisning beregnes om gangen i den eksisterende backendprosessen.

## Verifikasjon og målinger

`test_app_sdk.py` bruker den faktiske UI-modulen og de håndskrevne gallery-,
stopwatch- og racing-eksemplene. Testene dekker blant annet seks distinkte
gallerisider, tekstklipping, bitmapmetrikker, RLE/transparens, tintregler,
gradientavrunding, minne/I/O/tekstkvoter, sandbox og SDK/legacy-porten.
Studio testes også via autentiserte HTTP-kall uten nettverkslytter eller device.

Håndskrevne fixtures og skjermbilder er ikke bevis på AI-førsteforsøk. Det separate
`scripts/benchmark_app_sdk.py` viser som standard bare en renset kjøreplan.
`--execute` gjør betalte kode-/reviewkall og skal bare brukes ved koordinert
testbeslutning. Testen bruker elleve korte bestillinger og tre matchede
legacykontroller, normal eksplisitt byggebekreftelse og samme test-/reviewkjede.
Den starter ingen server, installerer ingenting og endrer ingen lagret profil.
Isolerte resultater inkluderer tid, faktiske API-kall, providerbruk, anslått
listepriskostnad, forsøk, kildebytes, minne og skjermbilder. Evalueringen har egne
grenser: to genereringsforsøk og åtte faktiske API-forespørsler per testcase;
vanlig ledger håndhever USD 0.25 per testcase. Før neste testcase reserveres
plass til hele USD 0.25 innen samlet USD 1, ellers stoppes bare evalueringen. Dette er
evalueringsrammer og gjelder ikke vanlige brukerjobber. Tre enkeltkontroller
gir ingen statistisk garanti for generell ytelse eller feilfri appgenerering.

Senere kohorter registrerer egen policyversjon og SDK-datahash. Samlet testbudsjett
inkluderer tidligere kohorters registrerte kostnad. Tre første SDK-sentineller
prøver verktøy, sensordashboard og spill; ved minst to feil stoppes videre betalte
cases for analyse. Første negative kohort beholdes uendret som måleresultat.

## Kostnadsgrunnlag og Runtime AI

Jobbpris omfatter kun egen build-ID, inkludert fortsettelse av samme jobb.
Samtalejobber viser bare dialog, transkripsjon og talesvar fra egen session-ID;
manglende prisgrunnlag vises som ukjent.
Apppris summerer utvikling på stabilt prosjekt gjennom alle versjoner og
feilrettinger, inkludert tilordnet dialog, transkripsjon og talesvar. Runtime AI
har egne kall/tokens/pris/latens og inngår ikke som kodingskostnad.

Målt pris, ukjent bruk, historiske anslag og empiriske anslag skilles.
Empirisk anslag krever minst tre målte kall med samme operasjon/modell og bruker
medianen av de siste 20. Det vises som `Ukjent (≈$...)`; blandede summer viser en
målt og en ukjent/anslått del. Uten grunnlag står `Ukjent`. Konservativ reserve
inngår kun i intern budsjettadgang, aldri i vist pris eller målte tokens.
Visningsnullstilling og nye anslag endrer ikke gammel ledgerhistorikk.

Runtime AI gjenbruker OpenAI-klient, transport og credentials. Global bryter,
AI Developer AUTO/OFF, per-app autorisasjon og egen modell finnes i Windows og
Studio. Standard gpt-6-luna er kontrollert mot
[OpenAIs modellside](https://developers.openai.com/api/docs/models/gpt-6-luna):
USD 0.10 inn / 0.01 cache / 0.50 ut per million teksttokens. Luna bruker reasoning
none, andre støttede GPT-modeller low. Teknisk outputramme er 1024 tokens
(konfigurerbar 16..4096); monetære grenser er valgfrie og av som standard.
Ingen blind API-retry, ekstra server eller ekstra AI-oppsummering brukes.

Feilretting beholder kandidaten som har bestått flest faktiske trinn: syntaks,
lokal kjøring, standardkrav, deretter review. Færre review-feil kan ikke velge
en eldre kandidat som fortsatt feiler standardkrav. Resume gjenbruker kilde,
aldri gammel reviewgodkjenning. Reparasjonstekst normaliseres kun i
modellvisningen; gamle logger og forespørsler beholdes.

Eksplisitte startfeil `not_installed`, `archive_mismatch`, `expired_command`,
`metadata_error`, `command_busy` og `invalid_command`
fra enhetens run-kvittering er deploymentfeil før Lua-kjøring. Feilkvittering,
feilhistorikk og mislykket run beholdes, men de sperrer ikke testet Lua-kilde.
Vanlig installasjons-, arkiv- og startbekreftelse kreves fortsatt. Runtime-,
init-, load- og sandboxfeil beholder kildesperren. En senere deploymentfeil
fjerner aldri en uavhengig kilderelatert sperre.
