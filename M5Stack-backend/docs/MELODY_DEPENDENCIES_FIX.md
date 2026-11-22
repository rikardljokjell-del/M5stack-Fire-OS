# Melodiverksted: Hardware service dependencies invalid

Påvist i faktisk Melodiverksted0.1.1 / build-6a129d11a82a46ae9cf9:
manifestet oppga display/buttons/rgb/speaker/jobs, men manglet sd.
Firmware fire_os.cpp krever speaker + jobs + sd før oppstart av hele adapteren,
også når appkoden bare bruker tone. Backend kontrollerte tidligere bare
avhengighetene til de metodene som ble kalt, og overså dermed native oppstartskrav.

Alle nye bygg får nå full transitiv tjenesteavhengighet fra samme API-register
som handshaken bruker. Manifest og permissions må inkludere hele mengden. Ingen
rettighet utenfor annonserte capabilities gis. Manifestparser og nedlastings-/
installasjonskontroll avviser manglende avhengigheter før levering. Registry-hash
og device-kode er uendret; dette håndhever eksisterende kontrakt.

SD som kun er en avhengighet for tone-adapteren skal ikke tvinge appen til å
finne på filoperasjoner for å bestå I/O-dekning. Tester skiller dette fra faktisk
SD-bruk og beholder kontroll av tone-jobber, feil og opprydding.

Melodiverksted0.1.2 er pakket med samme uendrede Lua-kilde, korrigerte tjenester/
permissions og ny arkivhash. Den består17PC-profiler. Den gamle pakken beholdes,
men sperres for videre levering. Dette retter manifestet; fysisk lydavspilling
er fortsatt separat verifikasjon. Ingen firmware er endret eller flashet.
