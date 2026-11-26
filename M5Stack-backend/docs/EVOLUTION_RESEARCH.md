# Evolution: research og gjenbruksvalg

Kontrollert 26. november 2026 mot prosjektkilder, pakkemetadata og faktisk
GEPA-wheel. Dette er en integrasjonsvurdering, ikke en garanti for resultatene
til noen av forskningssystemene.

| Kilde | Lisens og vurdering | Bruk i FIRE |
| --- | --- | --- |
| [Apeiron](https://github.com/microsoft/apeiron) | MIT; research preview, uttrykkelig ikke produksjonsprodukt. CUA med separate miljøer og Azure-tilknytning. | Lokaliserte endringer, sporbar interaksjon og evaluering tilpasses eksisterende reparasjonsgrunnlag og kilde-diff. Ingen kode/runtimeavhengighet importeres. |
| [Möbius](https://github.com/mobius-os/mobius) | MIT; selvhostet, aktiv plattform med bred agent-/appfunksjonalitet. | Eieravgrenset hukommelse, varige tilbakemeldinger og synlig historikk. Ingen Codex/Claude-, Docker- eller separat backendavhengighet. |
| [LangGraph](https://github.com/langchain-ai/langgraph) | MIT; etablert checkpoint-/interrupt-rammeverk. Nåværende metadata oppgir Python >=3.10 og flere LangChain-/checkpoint-avhengigheter. | Checkpoint og eksplisitt gjenopptakelse tilpasses dagens atomiske Store, Jobs og Builder. Ingen ekstra scheduler eller lagringssystem. |
| [OpenHands SDK](https://github.com/OpenHands/software-agent-sdk) | MIT; kontrollert kildeversjon 1.64.1 krever Python >=3.12, Pillow >=13 og en bred verktøy-/modellstack. | Arkitekturprinsipper for kodearbeid; ingen import. Dette unngår konflikt med FIREs Python 3.11+, Pillow <13 og direkte OpenAI-integrasjon. |
| [GEPA](https://github.com/gepa-ai/gepa) | MIT; distribuert 0.1.4 krever Python >=3.10,<3.15. Kjernepakken har ingen obligatoriske tredjepartsavhengigheter. | Direkte valgfri avhengighet `gepa==0.1.4`, injisert FIRE-evaluator og forslag via eksisterende provider/ledger. Ingen LiteLLM/DSPy/full-ekstraer, cloudlogging eller pickle-resume. |
| [DSPy](https://github.com/stanfordnlp/dspy) | MIT; kontrollert kildeversjon 3.5.0 har bredere avhengighetsflate og inkluderer GEPA. | Strukturerte oppgaver og målbar evaluering gjenbrukes gjennom dagens Pydantic/provider. Biblioteket importeres ikke i tillegg til GEPA. |
| [Darwin Gödel Machine](https://arxiv.org/abs/2505.22954) | Forskningspublikasjon; ikke importert programvare. | Kandidatarkiv, foreldre og empirisk utvalg. Ingen autonom modifikasjon av backend, firmware, sikkerhet eller evaluator. |
| [Self-Evolving Software](https://github.com/douglas-grishen/self-evolving-software) | MIT; prosjektet betegner seg selv som early-stage/experimental. Har separat evolution-plane, Docker/PostgreSQL og selvmodifikasjon. | MAPE-K-inndelingen brukes. Eksisterende FIRE-jobber og filrecords erstatter plattformen; selvmodifikasjon importeres ikke. |
| [Hypothesis](https://github.com/HypothesisWorks/hypothesis) | MPL-2.0; faktisk pakke 6.170.17 krever Python >=3.11 og sortedcontainers. | Direkte testavhengighet for tilstandsmaskiner, avbrudd, gjentakelser og autorisasjonsgrenser. Ingen firmware- eller produksjonsruntimeavhengighet. |

## Kontroll av den valgte GEPA-distribusjonen

`gepa-0.1.4-py3-none-any.whl`, 290 167 byte, SHA256:
`12b971039599625c156d2231f6d72a29c31a22e9c237689459b5f1a3c353f532`.
Adaptergrensesnitt og `optimize()` er kontrollert i denne distribusjonen,
ikke bare mot et bevegelig hovedbranch-eksempel.

FIRE tilbyr `evaluate` og `make_reflective_dataset` og bruker en avgrenset
`custom_candidate_proposer`. Evaluering og modellarbeid delegeres til
eksisterende eierloop. GEPA får ingen backendnøkler, shell-/filverktøy eller
rett til å endre akseptansekrav. Eksterne trackere og bibliotekets picklebaserte
`run_dir`/resume er av; varige handlinger journalføres av FIRE som JSON.

Feil i provider, kostnadsadmisjon eller avbrudd stanser forsøket. De skal ikke
slukes av optimalisereren og føre til flere betalte forsøk. Testene bruker
selve GEPA-pakken med injiserte, lokale funksjoner og nettverk blokkert.

Treningsgrunnlag og holdout er adskilt. Et bedre lokalt utfall er ikke bevis
for generell forbedring på fremtidige apper. Eierstandard krever en separat
godkjenning og uavhengige evalueringer på flere apper.

## Egen implementering som fortsatt er nødvendig

FIREs eier-/kilde-/versjonsbinding, mandater, kobling til eksisterende
BuildConfirm/RunConfirm, OS-kontroll, begrenset telemetri og filbaserte
referanser er produktspesifikke. De bygges som små adaptere rundt eksisterende
funksjoner. Det opprettes ingen ny backend, database, generell agentplattform
eller separat appbygger.

Ingen tredjepartsprosjektkode er kopiert inn i FIRE-kilden. GEPA og Hypothesis
brukes som uendrede pakker; deres lisensfiler skal følge med dersom de
distribueres i et programarkiv. Hypothesis hører bare til testmiljøet.
