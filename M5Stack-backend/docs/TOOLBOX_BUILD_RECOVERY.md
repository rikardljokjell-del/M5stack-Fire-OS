# Toolbox-bygg stoppet før levering

Undersøkt faktisk bygg `build-dff288a23982495e8e0c`, electronics toolbox med
I²C/GPIO/PWM/UART. Bygget feilet med TimeoutError etter to kandidater og to
avviste kildegjennomganger. Den globale180-sekundersgrensen var for kort for
generering, runtimeprofiler, uavhengig gjennomgang og den lovede rettingsløkken.
Ingen utestet pakke ble sendt til FIRE.

Kontrollene fant reelle feil: delvis UART-sending kunne duplisere data ved nytt
forsøk; pending data kunne følge feil portforbindelse; mottaks-/sendebuffer og
PWM-feilstatus var utilstrekkelig håndtert; I²C-etiketter ble bygd hver ramme.
Andre gjennomgang avdekket dessuten at testene ikke hadde startet I²C/UART-jobber
eller PWM, til tross for vellykkede meny-/knappetester. En kodeendring alene kan
ikke reparere at testriggen mangler en vei til instrumentene.

## Permanente backendendringer

- Standard totalbudsjett900s, fortsatt maksimalt fire genereringer (tre rettinger),
  uendrede API-/worker-/minnegrenser og eksplisitt avbryt. Eksplisitt konfigurert
  tidsgrense beholdes. Tidsavbrudd forklares med fase; forrige kontrollfunn og
  fasetid lagres. Det er ikke en ubegrenset løkke eller en lempet kvalitetsport.
- Generert app kan levere inntil seks test_sequences: bare A/B/C, maks32trykk,
  100..1000ms avstand. Planen er data, ikke kjørbar testkode. Den lagres pr forsøk.
- Hver sekvens kjøres i fersk VM med normal I/O, feil, timeout og frakobling.
  Det skal være tid til å poll/result/close, og planen må starte funksjonene.
- Simulatoren rapporterer faktiske metodekall og opprettede jobber. Nye livebygg
  av maskinvareverktøy avvises hvis deklarert instrument ikke blir øvd. Manglende
  dekning gir konkret melding til neste genereringsforsøk, før betalt review.
- GPIO/PWM/UI må skille valgt og fysisk bekreftet verdi. Busy betyr avvist lease,
  ikke ledig pinne. UART RX/TX serialiseres uten å forkaste ubehandlet leseresultat.
  Bekreftet delvis skriving beholder bare usendt suffix; ukjent resultat skal ikke
  automatisk prøves igjen. Pending data og utkast må avklares ved portbytte.
- Faste input-/gameplay-/OS-/langtidsprofiler beholdes. Ingen tidligere kontroll
  fjernes for å få et bygg gjennom. PC-resultater beviser fortsatt ikke fysisk I/O.

Dette reduserer de påviste feilkildene. Nett-/modellfeil, nye appfeil og fysisk
hardware krever fortsatt presis feilhåndtering; ingen garanti om at alle
fremtidige bygg kan fullføres. En kandidat uten godkjent kontroll sendes ikke.

## Verifikasjon

372 automatiske tester besto. Isolert ekte OpenAI fortsatte fra den lagrede
andre kandidatens kilde og kontrollfunn. Elektronikkbenk ble godkjent etter fire
interne forsøk med41profiler: I²C scan8jobber, UART read509/write2, GPIO mode/read/
write/release og PWM configure/write/stop ble faktisk utøvd. Ingen native
kommando ble sendt. Dette er PC-/kildeverifikasjon, ikke fysisk loopback.
