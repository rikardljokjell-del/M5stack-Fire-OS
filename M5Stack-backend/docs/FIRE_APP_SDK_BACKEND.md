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

`fire-sdk-generation-v3` erstatter de generelle legacyinstruksene i SDK-kall med
én konsistent versjonsstyrt policy. Valgte komponenter får kanonisk hjelp og
options, ekte temapalett og korte kjørbare Lua-eksempler. Norske sammensatte
appnavn som «bilspill», «værapp» og «måleinstrument» samt engelske aliaser velges
av samme kategorisering som brukes for relevante maskinvaredetaljer. Hele den
faktiske tilgjengelighetslisten beholdes; detaljerte signaturer velges fra mål,
avhengigheter og eksisterende apps manifest. Dette gir ingen nye tillatelser.
Kodekontrollen får eksplisitt aktuell kandidatkontrakt og skal skille konkrete
feil fra valgfri ekstra funksjonalitet og umålt fysisk ytelse.

Nye SDK-livebygg har en deterministisk standardport før AI-review. Faktisk
annonserte tjenester og bekreftet bestilling bestemmer RGB-/lydkravene; en
kandidat kan ikke unngå dem ved å utelate `rgb` eller `speaker`. Lokale tester må
vise ikke-null aktivitet på begge LED-sider og faktiske speaker-jobber når lyd
er avtalt og tilgjengelig. Start med lyd av og permanent brukerunntak behandles
forskjellig. Mangler rettes med den kjernetestede koden som grunnlag. Levering
krever kilde-/kontraktbundet standardbevis i tillegg til lokale tester og review.
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
måler ikke ESP32-callbacktid. Native 12 ms-beskyttelse må verifiseres på enheten.
Ingen appminne-, native instruksjons-, I/O- eller tidskvote økes her.

Hver fanget frame er fullstendig, maksimalt 64 tegneoperasjoner og 24000
serialiserte tegn; ingen avkortet frame presenteres som et fullstendig bilde.
PNG-er er maksimalt 240000 bytes. En ny svart framebuffer brukes per frame,
tilsvarende OS-eid clear-before-update. Bitmapfontene og atlasdataene er felles;
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
