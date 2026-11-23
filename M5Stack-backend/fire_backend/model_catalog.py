"""Reviewed Standard USD prices shared by the model picker and spending ledger.

Only models compatible with the implemented transport are offered per role.
Updating this catalog does not contact OpenAI or discover account permissions.
"""
from dataclasses import dataclass


PRICING_DATE = "2026-11-23"
SOURCE = "https://developers.openai.com/api/docs/models/"
CODE_MODELS = ("gpt-6-luna", "gpt-5.6-luna", "gpt-6.1-terra", "gpt-6.2-sol", "gpt-6.1-sol", "gpt-6.2-astra")
REALTIME_MODELS = ("gpt-realtime-2.1-mini", "gpt-realtime-2.1")
ROLE_MODELS = {
    "code_model": CODE_MODELS, "review_model": CODE_MODELS,
    "dialog_model": REALTIME_MODELS, "speech_model": REALTIME_MODELS,
    "transcribe_model": ("gpt-transcribe",),
}
ECONOMY_MODELS = {name: models[0] for name, models in ROLE_MODELS.items()}
EXPLICIT_CACHE_MODELS = frozenset(CODE_MODELS)
LONG_CONTEXT_MODELS = frozenset(CODE_MODELS)


@dataclass(frozen=True)
class ModelPrice:
    text_in: float
    text_cache: float
    text_out: float
    audio_in: float | None = None
    audio_cache: float | None = None
    audio_out: float | None = None

    def rates(self):
        return (self.text_in, self.text_cache, self.text_out, self.audio_in, self.audio_cache, self.audio_out)


PRICES = {
    "gpt-6-luna": ModelPrice(.10, .01, .50),
    "gpt-5.6-luna": ModelPrice(.20, .02, 1.20),
    "gpt-6.1-terra": ModelPrice(1, .05, 5),
    "gpt-6.2-sol": ModelPrice(2, .10, 10),
    "gpt-6.1-sol": ModelPrice(2, .10, 10),
    "gpt-6.2-astra": ModelPrice(8, .40, 40),
    "gpt-realtime-2.1-mini": ModelPrice(.60, .06, 2.40, 10, .30, 20),
    "gpt-realtime-2.1": ModelPrice(4, .40, 24, 32, .40, 64),
    # Preserve accounting for older saved profiles, without offering retired
    # transcription models for new selections (shutdown 2027-02-26).
    "gpt-4o-mini-transcribe": ModelPrice(1.25, 1.25, 5, 1.25, 1.25),
}
RATES = {name: price.rates() for name, price in PRICES.items()}
MINUTE_RATES = {"gpt-transcribe": .0045}


def dollars(value):
    amount = f"{value:.4f}".rstrip("0")
    return "$" + amount + "0" * max(0, 2 - len(amount.partition(".")[2]))


def choice_label(role, model):
    if model in MINUTE_RATES:
        return f"{model} · lyd inn {dollars(MINUTE_RATES[model])}/min"
    price = PRICES.get(model)
    if price is None or model not in ROLE_MODELS[role]:
        return f"{model} · lagret modell, utenfor anbefalt liste"
    if role == "speech_model":
        return f"{model} · tekst inn {dollars(price.text_in)} / lyd ut {dollars(price.audio_out)}"
    return f"{model} · inn {dollars(price.text_in)} / ut {dollars(price.text_out)}"


def price_detail(role, model):
    if model not in ROLE_MODELS[role]:
        return "Egendefinert/eldre valg beholdes. Pris og støtte må kontrolleres før bruk."
    if model in MINUTE_RATES:
        return "USD per minutt opptak. Tekstutdata er inkludert; ingen egen outputpris."
    price = PRICES[model]
    text = f"Tekst / 1 mill. tokens: inn {dollars(price.text_in)}, ut {dollars(price.text_out)}, cache lest {dollars(price.text_cache)}."
    if model in EXPLICIT_CACHE_MODELS:
        return text + f" Cache skrevet (30 min): {dollars(price.text_in * 1.25)}."
    if role == "speech_model":
        return text + f" Lyd: inn {dollars(price.audio_in)}, ut {dollars(price.audio_out)}, cache {dollars(price.audio_cache)} / 1 mill. lydtokens."
    return text + " Dialogen bruker tekst; talesvar prises separat."
