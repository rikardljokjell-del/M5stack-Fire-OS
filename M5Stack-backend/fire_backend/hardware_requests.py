"""Retain real hardware app requirements when installed firmware lacks adapters."""
import re

from .api_registry import BASE_SERVICES

TERMS={
    "i2c":r"\bi(?:2|²)c\b", "gpio":r"\bgpio\b", "pwm":r"\bpwm\b",
    "uart":r"\buart\b|\bserial\b|\bgps\b", "spi":r"\bspi\b",
    "adc":r"\badc\b|analog(?:inngang| input)", "dac":r"\bdac\b|analog(?:utgang| output)",
    "wifi":r"wi[ -]?fi|\bwlan\b|\bhttps?\b", "bluetooth":r"bluetooth|\bble\b|\bbt\b",
    "rgb":r"\brgb\b", "mic":r"\bmic\b|mikrofon|microphone|lydopptak",
    "speaker":r"høyttaler|hoyttaler|speaker|\blyd\b|\bsound\b", "sd":r"\bsd\b|sd[ -]?kort|loggfil|lagre fil",
    "rtc":r"\brtc\b", "power":r"batteri|battery|strømforbruk|stromforbruk",
}
LABELS={"i2c":"I²C","gpio":"GPIO","pwm":"PWM","uart":"UART","spi":"SPI","adc":"ADC","dac":"DAC",
        "wifi":"Wi‑Fi","bluetooth":"Bluetooth","mic":"mikrofon","speaker":"høyttaler","sd":"SD","rtc":"klokke","power":"strømstyring","jobs":"bakgrunnsjobber","rgb":"RGB"}


def hardware_goal(text,previous=None):
    detected={service for service,pattern in TERMS.items() if re.search(pattern,text,re.I)}
    build=bool(re.search(r"\b(lag|lage|bygg|bygge|create|make|build|fiks|reparer)\b|toolbox|tester|scanner|skanner",text,re.I))
    if not detected:
        return previous if previous and re.search(r"lag appen|bygg (?:den|appen)|fortsett|continue",text,re.I) else None
    if not build:return None
    if detected&{"i2c","uart","spi","wifi","bluetooth","mic","speaker","sd"}:detected.add("jobs")
    if "mic" in detected and re.search(r"opptak|record",text,re.I):detected.add("sd")
    if not detected-BASE_SERVICES:return None
    if previous and re.search(r"^\s*(og|legg til|ta med|inkluder|også)",text,re.I):
        detected.update(previous["required_services"]);text=previous["request"]+"\n"+text
    return {"request":text[-4000:],"required_services":sorted(detected)}


def missing_hardware(goal,capabilities):
    return sorted(set(goal["required_services"])-set((capabilities or {}).get("services",BASE_SERVICES)))


def capability_message(missing):
    names=", ".join(LABELS.get(s,s) for s in missing if s!="jobs")
    return "Appønsket er lagret med "+(names or "maskinvarefunksjonene")+". Denne firmwaren mangler app-adapterne. Device-agenten må legge dem til før en fungerende app kan leveres."
