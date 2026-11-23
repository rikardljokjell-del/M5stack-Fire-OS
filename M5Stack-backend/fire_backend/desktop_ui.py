"""Local Windows control panel. Tk widgets and callbacks stay on the UI thread."""
import ctypes
from datetime import datetime
import os
from pathlib import Path
import queue
import secrets
import threading
import time
import tkinter as tk
from tkinter import filedialog, messagebox, ttk, scrolledtext

from .desktop_config import DesktopConfig, DesktopStore, ECONOMY_MODELS, COST_PROFILE_VERSION
from .desktop_runtime import DesktopRuntime, check_api_key, configure_firewall, firewall_ready, lan_addresses, network_info
from .token_qr import token_matrix
from .model_catalog import ROLE_MODELS, PRICING_DATE, choice_label, price_detail
from .status_text import error_text


BG, INK, MUTED, ORANGE, NAV = "#f2f4f8", "#182231", "#637083", "#e95725", "#172231"


def usage_task_name(operation):
    return {"generate":"Kodebygging", "review":"Kodekontroll", "dialog":"Samtale",
            "transcribe":"Taletolkning", "speech":"Talesvar"}.get(operation,operation or "Ukjent")


def usage_status_name(record):
    status={"pending":"Pågår", "completed":"Fullført", "failed":"Feilet", "cancelled":"Avbrutt",
            "unknown":"Ukjent", "interrupted":"Avbrutt", "rejected":"Stoppet av grense"}.get(record.get('status'),record.get('status','–'))
    return status+(' · anslag' if record.get('usage_source')!='provider' else '')


def app_cost_text(app):
    prefix='≈' if app.get('cost_detail',{}).get('historical_estimate') else ''
    return f"{prefix}${app.get('cost',0):.4f}"


def app_cost_detail(app):
    detail=app.get('cost_detail',{})
    history=detail.get('historical_estimate')
    text=f"Total Cost: {app_cost_text(app)} · alle versjoner og feilrettinger · {detail.get('requests',0)} registrerte API-kall\n"
    if history:
        text+=(f"Registrert: ${detail.get('recorded_usd',0):.4f} · historisk anslag: ${history['estimated_usd']:.2f} "
            f"(scenario ${history['low_usd']:.2f}–${history['high_usd']:.2f})\n"
            f"Eldre bygg/kodekontroll: {', '.join(history['models'])}. Eldre tale/dialog uten måling er ikke med.\n")
    return text


class DesktopUI:
    def __init__(self, root, store):
        self.root, self.store = root, store
        self.runtime = DesktopRuntime()
        self.queue = queue.Queue()
        self.busy, self.closing = False, False
        self.snapshot = {"sessions": [], "devices": [], "builds": []}
        self.usage_snapshot = {}
        self.job_snapshot = {}
        self.job_rows = {}
        self.job_drafts = {}
        self.activity_drafts = {}
        self.job_editor_target = None
        self.current_page = "Oversikt"
        self.network, self.firewall = "Kontrollerer nettverk …", False
        self.addresses = lan_addresses()
        self.events = []
        self.token_qr_window = None
        self.api_result = "API-nøkkelen er ikke kontrollert."
        self.root.title("FIRE Backend")
        self.root.geometry("1120x810")
        self.root.minsize(970, 730)
        self.root.configure(bg=BG)
        self.root.protocol("WM_DELETE_WINDOW", self.close)
        self.style()
        self.variables()
        self.layout()
        self.root.after(100, self.drain)
        self.root.after(200, self.start)
        threading.Thread(target=self.poll, daemon=True).start()
        threading.Thread(target=self.inspect_network, daemon=True).start()

    def style(self):
        style = ttk.Style(self.root)
        style.theme_use("clam")
        style.configure("TFrame", background=BG)
        style.configure("Card.TFrame", background="white")
        style.configure("TLabel", background=BG, foreground=INK, font=("Segoe UI", 10))
        style.configure("Card.TLabel", background="white")
        style.configure("Muted.TLabel", foreground=MUTED)
        style.configure("Title.TLabel", font=("Segoe UI Semibold", 24))
        style.configure("Heading.TLabel", font=("Segoe UI Semibold", 13))
        style.configure("CardHeading.TLabel", background="white", font=("Segoe UI Semibold", 12))
        style.configure("TButton", font=("Segoe UI", 10), padding=(14, 8), background="white", foreground=INK)
        style.configure("Accent.TButton", background=ORANGE, foreground="white", borderwidth=0)
        style.map("Accent.TButton", background=[("active", "#d84c1c"), ("disabled", "#e4ad98")])
        style.configure("TEntry", padding=7, font=("Segoe UI", 10))
        style.configure("TCombobox", padding=7, font=("Segoe UI", 10))
        style.configure("TCheckbutton", background=BG, font=("Segoe UI", 10))
        style.configure("Treeview", rowheight=29, font=("Segoe UI", 10), borderwidth=0)
        style.configure("Treeview.Heading", font=("Segoe UI Semibold", 10))

    def variables(self):
        c = self.store.config
        self.mode = tk.StringVar(value="Test uten API" if c.mode == "mock" else "OpenAI")
        self.lan = tk.BooleanVar(value=c.allow_lan)
        self.transport = tk.StringVar(value=c.transport)
        self.reverse_host = tk.StringVar(value=c.reverse_host)
        self.reverse_port = tk.StringVar(value=str(c.reverse_port))
        self.port = tk.StringVar(value=str(c.port))
        self.host = tk.StringVar(value=self.addresses[0] if self.addresses else "127.0.0.1")
        self.device_id = tk.StringVar(value=c.device_ids[0])
        self.device_token = tk.StringVar(value=self.store.secret("device/" + c.device_ids[0]))
        self.api_key = tk.StringVar()
        self.key_saved = bool(self.store.secret("openai"))
        self.key_status = tk.StringVar(value="Nøkkel er lagret i Windows." if self.key_saved else "Ingen API-nøkkel er lagret ennå.")
        self.audio = tk.BooleanVar(value=c.audio_enabled)
        self.speech_enabled=tk.BooleanVar(value=c.speech_enabled)
        self.cost_limits_enabled=tk.BooleanVar(value=c.cost_limits_enabled)
        self.output_limits_enabled=tk.BooleanVar(value=c.output_limits_enabled)
        self.models = {name: tk.StringVar(value=getattr(c, name)) for name in
                       ("dialog_model", "code_model", "review_model", "transcribe_model", "speech_model", "speech_voice")}
        self.cost_limits = {name: tk.StringVar(value=str(getattr(c, name))) for name in
                            ("daily_budget_usd", "build_budget_usd", "request_budget_usd", "max_corrections")}
        self.workspace = tk.StringVar(value=c.workspace)
        self.disk = tk.StringVar(value=str(c.max_workspace_mb))
        self.selected_session = tk.StringVar()
        self.selected_version = tk.StringVar()
        self.version_choices = {}
        self.version_selection = {}
        self.firmware_version = tk.StringVar()
        self.firmware_rows = {}
        self.notice = tk.StringVar(value="Starter lokal backend …")

    def label(self, parent, text="", style=None, **kwargs):
        return ttk.Label(parent, text=text, style=style or "TLabel", **kwargs)

    def layout(self):
        nav = tk.Frame(self.root, bg=NAV, width=185)
        nav.pack(side="left", fill="y")
        nav.pack_propagate(False)
        tk.Label(nav, text="FIRE", bg=NAV, fg="#ff8456", font=("Segoe UI Black", 28)).pack(anchor="w", padx=25, pady=(27, 0))
        tk.Label(nav, text="BACKEND", bg=NAV, fg="white", font=("Segoe UI", 12)).pack(anchor="w", padx=27, pady=(0, 32))
        self.nav_buttons = {}
        for name in ("Oversikt", "M5Stack", "Tilkobling", "OpenAI", "Bruk og kostnad", "Jobber", "Aktivitet", "Apper", "Firmware", "Innstillinger"):
            button = tk.Button(nav, text=name, command=lambda n=name: self.show(n), anchor="w", relief="flat",
                               bg=NAV, fg="#c1ccd9", activebackground="#293b51", activeforeground="white",
                               font=("Segoe UI", 12), padx=25, pady=10, bd=0, cursor="hand2")
            button.pack(fill="x", padx=10, pady=2)
            self.nav_buttons[name] = button
        tk.Label(nav, text="Lokal Windows-app\nProtokoll 0.2", justify="left", bg=NAV, fg="#91a2b6",
                 font=("Segoe UI", 9)).pack(side="bottom", anchor="w", padx=26, pady=22)
        content = ttk.Frame(self.root, padding=(28, 22))
        content.pack(side="left", fill="both", expand=True)
        bar = ttk.Frame(content)
        bar.pack(fill="x")
        self.title = self.label(bar, "Oversikt", "Title.TLabel")
        self.title.pack(side="left")
        self.stop_button = ttk.Button(bar, text="Stopp", command=self.stop)
        self.stop_button.pack(side="right", padx=(8, 0))
        self.start_button = ttk.Button(bar, text="Start backend", command=self.start, style="Accent.TButton")
        self.start_button.pack(side="right")
        self.label(content, "Din forbindelse mellom FIRE OS og OpenAI.", "Muted.TLabel").pack(anchor="w", pady=(5, 15))
        self.pages = {}
        holder = ttk.Frame(content)
        holder.pack(fill="both", expand=True)
        for name in self.nav_buttons:
            page = ttk.Frame(holder)
            self.pages[name] = page
        self.overview(self.pages["Oversikt"])
        self.connection_page(self.pages["M5Stack"])
        self.transport_page(self.pages["Tilkobling"])
        self.openai_page(self.scroll_content(self.pages["OpenAI"]))
        self.usage_page(self.scroll_content(self.pages["Bruk og kostnad"]))
        self.jobs_page(self.scroll_content(self.pages["Jobber"]))
        self.activity_page(self.pages["Aktivitet"])
        self.apps_page(self.pages["Apper"])
        self.firmware_page(self.pages["Firmware"])
        self.settings_page(self.scroll_content(self.pages["Innstillinger"]))
        self.label(content, textvariable=self.notice, foreground=MUTED, wraplength=830).pack(anchor="w", pady=(14, 0))
        self.show("Oversikt")

    def show(self, name):
        for page in self.pages.values():
            page.pack_forget()
        self.pages[name].pack(fill="both", expand=True)
        self.current_page = name
        self.title.configure(text=name)
        for key, button in self.nav_buttons.items():
            button.configure(bg="#2a3a4e" if key == name else NAV, fg="white" if key == name else "#c1ccd9")

    @staticmethod
    def scroll_content(page):
        canvas=tk.Canvas(page,bg=BG,highlightthickness=0)
        bar=ttk.Scrollbar(page,orient="vertical",command=canvas.yview)
        canvas.configure(yscrollcommand=bar.set)
        canvas.pack(side="left",fill="both",expand=True);bar.pack(side="right",fill="y")
        inner=ttk.Frame(canvas)
        window=canvas.create_window((0,0),window=inner,anchor="nw")
        inner.bind("<Configure>",lambda _:canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.bind("<Configure>",lambda event:canvas.itemconfigure(window,width=event.width))
        return inner

    def card(self, parent, title):
        card = ttk.Frame(parent, style="Card.TFrame", padding=18)
        self.label(card, title, "CardHeading.TLabel").pack(anchor="w", pady=(0, 9))
        return card

    def overview(self, page):
        row = ttk.Frame(page)
        row.pack(fill="x")
        self.summary_labels = {}
        for i, (name, title) in enumerate((("server", "Backend"), ("api", "OpenAI"), ("device", "M5Stack"))):
            row.columnconfigure(i, weight=1, uniform="cards")
            card = self.card(row, title)
            card.grid(row=0, column=i, sticky="nsew", padx=(0 if i == 0 else 9, 0))
            value = self.label(card, "Venter …", "Card.TLabel", font=("Segoe UI Semibold", 12), wraplength=210)
            value.pack(anchor="w")
            self.summary_labels[name] = value
        card = self.card(page, "Kom i gang")
        card.pack(fill="x", pady=15)
        for text in ("1   Legg inn API-nøkkelen under OpenAI, og velg OpenAI-modus.",
                     "2   Velg direkte nett eller mobilnett under Tilkobling.",
                     "3   Legg PC-adresse, port, enhets-ID og enhetstoken inn på FIRE.",
                     "4   Åpne AI Developer på FIRE. Tilkoblingen vises her automatisk."):
            self.label(card, text, "Card.TLabel", wraplength=760).pack(anchor="w", pady=5)
        self.readiness = self.label(page, "", wraplength=810, foreground=MUTED)
        self.readiness.pack(anchor="w", pady=(4, 12))
        ttk.Button(page, text="Konfigurer M5Stack →", command=lambda: self.show("M5Stack"), style="Accent.TButton").pack(anchor="w")
        self.label(page, "Lyd styres av funksjonene enheten annonserer. Tekst fra PC finnes under Aktivitet.\n"
                   "Installert / kjører vises først etter kvittering fra enheten. Fysisk test er ikke bekreftet.",
                   "Muted.TLabel", wraplength=810).pack(anchor="w", pady=18)

    def field(self, parent, row, title, variable, secret=False, width=46):
        self.label(parent, title).grid(row=row, column=0, sticky="w", pady=7, padx=(0, 18))
        entry = ttk.Entry(parent, textvariable=variable, width=width, show="•" if secret else "")
        entry.grid(row=row, column=1, sticky="ew", pady=7)
        parent.columnconfigure(1, weight=1)
        return entry

    def connection_page(self, page):
        self.label(page, "Disse fire verdiene brukes i backend-oppsettet på FIRE.", wraplength=800).pack(anchor="w", pady=(0, 14))
        grid = ttk.Frame(page)
        grid.pack(fill="x")
        self.label(grid, "PC-adresse").grid(row=0, column=0, sticky="w", padx=(0, 18))
        self.host_box = ttk.Combobox(grid, textvariable=self.host, values=self.addresses or ["127.0.0.1"], width=43)
        self.host_box.grid(row=0, column=1, sticky="ew", pady=7)
        self.field(grid, 1, "Port", self.port)
        self.field(grid, 2, "Enhets-ID", self.device_id)
        self.token_entry = self.field(grid, 3, "Enhetstoken", self.device_token, secret=True)
        row = ttk.Frame(page)
        row.pack(fill="x", pady=8)
        ttk.Button(row, text="Kopier tilkobling", command=self.copy_connection).pack(side="left")
        ttk.Button(row, text="Kopier token", command=self.copy_token).pack(side="left", padx=8)
        ttk.Button(row, text="QR for token", command=self.show_token_qr).pack(side="left")
        ttk.Button(row, text="Vis / skjul token", command=self.toggle_token).pack(side="left")
        ttk.Button(row, text="Nytt token", command=lambda: self.device_token.set(secrets.token_urlsafe(32))).pack(side="left", padx=8)
        ttk.Checkbutton(page, text="Tillat M5Stack på lokalt nettverk", variable=self.lan).pack(anchor="w", pady=(10, 5))
        self.label(page, "Lagre etter at du har endret port, ID eller token. Backend starter på nytt.", "Muted.TLabel").pack(anchor="w")
        ttk.Button(page, text="Lagre tilkobling", command=self.save, style="Accent.TButton").pack(anchor="w", pady=13)
        ttk.Button(page, text="Direkte nett / mobilnett →", command=lambda: self.show("Tilkobling")).pack(anchor="w", pady=(0, 6))
        network_card = self.card(page, "Windows og nettverk")
        network_card.pack(fill="x", pady=(4, 8))
        self.network_label = self.label(network_card, "Kontrollerer …", "Card.TLabel", wraplength=760)
        self.network_label.pack(anchor="w")
        ttk.Button(network_card, text="Tillat FIRE gjennom brannmuren …", command=self.firewall_action).pack(anchor="w", pady=(10, 0))
        self.label(page, "Brannmurknappen ber Windows om administratorgodkjenning. Regelen gjelder\n"
                   "bare dette programmet, valgt port og maskiner på lokalt subnett.\n"
                   "OpenAI-nøkkelen skal aldri legges inn på M5Stack.", "Muted.TLabel", wraplength=800).pack(anchor="w", pady=5)

    def transport_page(self, page):
        self.label(page, "Velg hvordan PC og FIRE når hverandre", "Heading.TLabel").pack(anchor="w", pady=(0, 15))
        ttk.Radiobutton(page, text="Direkte nett — FIRE kobler til PC-en", value="direct", variable=self.transport).pack(anchor="w", pady=6)
        self.label(page, "Brukes når PC og FIRE kan nå hverandre direkte på samme nettverk.", "Muted.TLabel").pack(anchor="w", padx=24, pady=(0, 13))
        ttk.Radiobutton(page, text="Mobilnett / omvendt TCP — PC-en kobler til FIRE", value="reverse_tcp", variable=self.transport).pack(anchor="w", pady=6)
        self.label(page, "For USB-nettdeling og andre nett der FIRE ikke når PC-en tilbake.\n"
                   "Krever ny FIRE-firmware med reverse TCP-mottaker. Ingen telefoninnstillinger.", "Muted.TLabel").pack(anchor="w", padx=24, pady=(0, 16))
        grid = ttk.Frame(page)
        grid.pack(fill="x")
        self.field(grid, 0, "FIREs Wi-Fi-adresse", self.reverse_host)
        self.field(grid, 1, "Port på FIRE", self.reverse_port)
        self.label(page, "Dette er enhetens egen adresse fra Wi-Fi-status/UniFi, ikke PC-adressen.\n"
                   "Enhets-ID og lagret token på M5Stack-siden brukes også for denne forbindelsen.", "Muted.TLabel", wraplength=800).pack(anchor="w", pady=10)
        ttk.Button(page, text="Lagre og bruk tilkobling", command=self.save, style="Accent.TButton").pack(anchor="w", pady=12)
        card = self.card(page, "Forbindelsesstatus")
        card.pack(fill="x", pady=12)
        self.transport_status = self.label(card, "Backend starter …", "Card.TLabel", wraplength=760)
        self.transport_status.pack(anchor="w")
        self.label(page, "Bro klar betyr at transporten er autentisert. FIRE vises som tilkoblet først\n"
                   "når vanlig session_start er godkjent. Bygging og kjøring krever fortsatt bekreftelse.", "Muted.TLabel", wraplength=800).pack(anchor="w", pady=10)

    def openai_page(self, page):
        grid = ttk.Frame(page)
        grid.pack(fill="x")
        self.label(grid, "Driftsmodus").grid(row=0, column=0, sticky="w", padx=(0, 18))
        ttk.Combobox(grid, textvariable=self.mode, state="readonly", values=["Test uten API", "OpenAI"]).grid(row=0, column=1, sticky="ew", pady=7)
        self.key_entry = self.field(grid, 1, "Ny API-nøkkel", self.api_key, secret=True)
        self.label(page, textvariable=self.key_status, foreground=MUTED).pack(anchor="w", pady=6)
        self.label(page, "Tomt nøkkelfelt beholder lagret nøkkel. Nøkkelen lagres i Windows\n"
                   "legitimasjonsbehandling for brukeren din, og sendes bare til OpenAI.", "Muted.TLabel").pack(anchor="w")
        row = ttk.Frame(page)
        row.pack(fill="x", pady=14)
        ttk.Button(row, text="Lagre og bruk", style="Accent.TButton", command=self.save).pack(side="left")
        ttk.Button(row, text="Test API-nøkkel", command=self.test_key).pack(side="left", padx=9)
        ttk.Button(row, text="Fjern lagret nøkkel", command=self.remove_key).pack(side="left")
        self.api_label = self.label(page, self.api_result, wraplength=800)
        self.api_label.pack(anchor="w", pady=(0, 15))
        ttk.Checkbutton(page,text='Les AI-svar høyt på FIRE',variable=self.speech_enabled).pack(anchor='w',pady=(0,4))
        self.label(page,'Slå av for å unngå AI-lydkostnad. Mikrofon, transkripsjon, tekstsvar og bygging virker fortsatt.\n'
                   'Lydprisen i modellvalget gjelder per million lydtokens, ikke per svar.',
                   'Muted.TLabel',wraplength=780).pack(anchor='w',pady=(0,8))
        self.label(page, "Modeller", "Heading.TLabel").pack(anchor="w", pady=(5, 8))
        grid = ttk.Frame(page)
        grid.pack(fill="x")
        grid.columnconfigure(1, weight=1)
        self.model_pickers = {}
        self.model_labels = {}
        self.model_price_labels = {}
        for row, (name, title) in enumerate((("dialog_model", "Dialog"), ("code_model", "Kodegenerering"),
                                           ("review_model", "Kodekontroll"),
                                           ("transcribe_model", "Transkripsjon"), ("speech_model", "Talesvar"), ("speech_voice", "Stemme"))):
            if name == "speech_voice":
                self.field(grid, row * 2, title, self.models[name])
            else:
                self.model_field(grid, row * 2, title, name)
        self.label(page, f"Standardpriser i USD, kontrollert {PRICING_DATE}. Inn / ut gjelder 1 million tokens.\n"
                   "Transkripsjon prises per minutt. Lange kodeforespørsler (>272 000 inn-tokens)\n"
                   "har 2× input-/cachepris og 1,5× outputpris. Kontotilgang kan variere.\n"
                   "Listene viser modeller som passer den aktuelle oppgaven og lydtransporten.",
                   "Muted.TLabel", wraplength=780).pack(anchor="w", pady=(12, 0))
        ttk.Button(page, text="Anbefalt rimelig oppsett", command=self.economy_profile).pack(anchor="w", pady=(10, 0))
        self.label(page, "Nøkkeltesten henter modellisten. Den genererer ikke innhold og bekrefter\n"
                   "ikke at hele tale-/byggeflyten virker. Bruk av OpenAI kan koste penger.", "Muted.TLabel").pack(anchor="w", pady=12)

    def model_field(self, grid, row, title, name):
        self.label(grid, title).grid(row=row, column=0, sticky="nw", padx=(0, 16), pady=(6, 0))
        display = tk.StringVar()
        picker = ttk.Combobox(grid, textvariable=display, state="readonly", width=58)
        picker.grid(row=row, column=1, sticky="ew", pady=(6, 0))
        detail = self.label(grid, "", "Muted.TLabel", wraplength=610)
        detail.grid(row=row + 1, column=1, sticky="w", pady=(2, 8))
        self.model_pickers[name] = picker
        self.model_labels[name] = display
        self.model_price_labels[name] = detail
        mapping = {}

        def sync(*_):
            current = self.models[name].get()
            models = list(ROLE_MODELS[name])
            if current not in models:
                models.append(current)
            mapping.clear()
            mapping.update({choice_label(name, model): model for model in models})
            picker.configure(values=tuple(mapping))
            display.set(choice_label(name, current))
            detail.configure(text=price_detail(name, current))

        def select(_):
            model = mapping.get(display.get())
            if model is not None:
                self.models[name].set(model)

        picker.bind("<<ComboboxSelected>>", select)
        self.models[name].trace_add("write", sync)
        sync()

    def economy_profile(self):
        for name, value in ECONOMY_MODELS.items():
            self.models[name].set(value)
        for name, value in {"daily_budget_usd":0, "build_budget_usd":0,
                            "request_budget_usd":0, "max_corrections":0}.items():
            self.cost_limits[name].set(str(value))
        self.cost_limits_enabled.set(False);self.output_limits_enabled.set(False)
        self.sync_cost_controls()
        self.notice.set("Rimelige modeller er valgt, uten beløps- og svartak. Trykk Lagre og bruk.")

    def usage_page(self, page):
        row = ttk.Frame(page);row.pack(fill="x")
        self.usage_totals = {}
        for i, (name, title) in enumerate((("since_reset", "Siden nullstilling"), ("today", "I dag"), ("lifetime", "Siden målingen startet"))):
            row.columnconfigure(i, weight=1, uniform="usage")
            card = ttk.Frame(row, style="Card.TFrame", padding=12)
            card.grid(row=0, column=i, sticky="nsew", padx=(0 if i==0 else 8,0))
            self.label(card,title,"Card.TLabel").pack(anchor="w")
            label = self.label(card,"$0.0000","Card.TLabel",font=("Segoe UI Semibold",18))
            label.pack(anchor="w",pady=(5,0));self.usage_totals[name]=label
        self.usage_info = self.label(page,"Kostnadsoversikten hentes når backend kjører.","Muted.TLabel",wraplength=800)
        self.usage_info.pack(anchor="w",pady=(9,5))
        controls = ttk.Frame(page);controls.pack(fill="x",pady=(0,8))
        ttk.Button(controls,text="Oppdater",command=self.refresh_usage).pack(side="left")
        self.usage_reset_button = ttk.Button(controls,text="Nullstill visningstellerne",command=self.reset_usage)
        self.usage_reset_button.pack(side="left",padx=8)
        ttk.Button(controls,text="Endre kostnadsgrenser",command=lambda:self.show("Innstillinger")).pack(side="right")
        self.label(page,"Hva driver kostnaden?", "Heading.TLabel").pack(anchor="w",pady=(2,7))
        notebook = ttk.Notebook(page);notebook.pack(fill="both",expand=True)
        self.usage_groups = {}
        for key, title in (("by_operation","Oppgaver"),("by_model","Modeller"),("by_build","Appjobber")):
            tab=ttk.Frame(notebook);notebook.add(tab,text=title)
            tree=ttk.Treeview(tab,columns=("name","calls","input","output","cost"),show="headings",height=4)
            for name,label,width in (("name",title,280),("calls","Kall",55),("input","Inputtokens",100),("output","Outputtokens",100),("cost","Anslått USD",105)):
                tree.heading(name,text=label);tree.column(name,width=width,minwidth=45)
            bar=ttk.Scrollbar(tab,orient="vertical",command=tree.yview);tree.configure(yscrollcommand=bar.set)
            tree.pack(side="left",fill="both",expand=True);bar.pack(side="right",fill="y")
            self.usage_groups[key]=tree
        self.label(page,"Siste API-kall", "Heading.TLabel").pack(anchor="w",pady=(10,6))
        recent_frame=ttk.Frame(page);recent_frame.pack(fill="both",expand=True)
        self.usage_recent=ttk.Treeview(recent_frame,columns=("time","task","model","tokens","cost","status"),show="headings",height=5)
        for name,label,width in (("time","Tid",62),("task","Oppgave",110),("model","Modell",195),("tokens","Inn / ut / cache",140),("cost","Anslått USD",90),("status","Måling / status",130)):
            self.usage_recent.heading(name,text=label);self.usage_recent.column(name,width=width,minwidth=45)
        bar=ttk.Scrollbar(recent_frame,orient="vertical",command=self.usage_recent.yview);self.usage_recent.configure(yscrollcommand=bar.set)
        self.usage_recent.pack(side="left",fill="both",expand=True);bar.pack(side="right",fill="y")
        self.usage_recent.bind("<<TreeviewSelect>>",lambda _:self.render_usage_detail())
        self.usage_detail=self.label(page,"Velg et kall for å se cache, lyd og jobbtilknytning.","Muted.TLabel",wraplength=800)
        self.usage_detail.pack(anchor="w",pady=(7,0))
        self.usage_records={}

    def refresh_usage(self):
        self.work(self.runtime.usage, done=lambda value:setattr(self,"usage_snapshot",value), message="Henter lokal kostnadsoversikt …")

    def reset_usage(self):
        def done(value):
            self.usage_snapshot=value
            self.notice.set("Visningstellerne er nullstilt. Historikk og dagens kostnadsgrense beholdes.")
        self.work(self.runtime.reset_usage, done=done, message="Nullstiller visningstellerne …")

    def render_usage(self):
        data=self.usage_snapshot
        for key,label in self.usage_totals.items():
            total=data.get(key,{})
            label.configure(text=f"${float(total.get('estimated_usd',0)):.4f} · {total.get('requests',0)} kall")
        limits=data.get('limits',{});period=data.get('since_reset',{})
        budget=(f"Dagsgrense ${float(limits.get('daily_usd',self.store.config.daily_budget_usd)):.2f}; "
                f"ledig ${float(limits.get('daily_remaining_usd') or 0):.2f}. " if limits.get('enabled',False) and limits.get('daily_usd',0)>0 else
                "Ingen dagsgrense. Øvrige valgte beløpstak gjelder. " if limits.get('enabled',False) else
                "Kostnadsgrenser er av. Forbruk måles fortsatt. ")
        text=(f"Anslått kostnad · USD · Prisgrunnlag {data.get('pricing_date','–')}. "
              +budget+f"({limits.get('budget_day','–')}, {limits.get('timezone','lokal tid')}).\n"
              f"Cache lest/skrevet: {period.get('cached_tokens',0):,}/{period.get('cache_write_tokens',0):,} tokens · {period.get('audio_seconds',0):.1f} s lyd · "
              f"{period.get('unknown_usage_requests',0)} kall uten full tokenmåling. "
              "Tokens inkluderer reserver når måling mangler. "
              "Eldre forbruk inngår ikke. OpenAI-fakturaen er fasit.")
        if not data:text="Start backend for å vise lokal kostnadsoversikt. Ingen API-kall gjøres for å hente oversikten."
        self.usage_info.configure(text=text)
        self.usage_reset_button.configure(state="normal" if self.runtime.ready and not self.busy else "disabled")
        for group,tree in self.usage_groups.items():
            rows=[]
            for item in data.get(group,[]):
                name=usage_task_name(item.get('operation','')) if group=='by_operation' else item.get('model','–') if group=='by_model' else self.usage_job_name(item)
                rows.append((name,item.get('requests',0),f"{item.get('input_tokens',0):,}",f"{item.get('output_tokens',0):,}",f"${float(item.get('estimated_usd',0)):.4f}"))
            self.replace_rows(tree,rows)
        records=data.get('recent',[]);self.usage_records={str(item['id']):item for item in records}
        rows=[]
        for item in records:
            stamp=item.get('finished_at') or item.get('started_at')
            label=datetime.fromtimestamp(stamp).strftime('%H:%M:%S') if stamp else '–'
            tokens=f"{item.get('input_tokens',0):,} / {item.get('output_tokens',0):,} / {item.get('cached_tokens',0):,}"
            status=usage_status_name(item)
            rows.append((str(item['id']),(label,usage_task_name(item.get('operation','')),item.get('model','–'),tokens,f"${float(item.get('estimated_usd',0)):.4f}",status)))
        if rows!=getattr(self,'usage_recent_rows',None):
            selected=self.usage_recent.selection();self.usage_recent_rows=rows
            self.usage_recent.delete(*self.usage_recent.get_children())
            for item_id,values in rows:self.usage_recent.insert('', 'end', iid=item_id, values=values)
            if selected and selected[0] in self.usage_records:self.usage_recent.selection_set(selected[0])

    @staticmethod
    def replace_rows(tree, rows):
        if rows==getattr(tree,'_usage_rows',None):return
        tree._usage_rows=rows;tree.delete(*tree.get_children())
        for values in rows:tree.insert('', 'end', values=values)

    def usage_job_name(self,item):
        project=item.get('project_id')
        app=next((a for a in self.snapshot.get('apps',[]) if a.get('project_id')==project),None)
        name=app.get('name') if app else 'Appjobb'
        return name+' · '+str(item.get('build_id') or 'uten bygg')[-12:]

    def render_usage_detail(self):
        selected=self.usage_recent.selection();item=self.usage_records.get(selected[0]) if selected else None
        if not item:return
        audio_in=item.get('input_audio_tokens',0);audio_out=item.get('output_audio_tokens',0)
        self.usage_detail.configure(text=f"{self.usage_job_name(item)} · {item.get('audio_seconds',0):.1f} s lyd · lydtokens inn/ut {audio_in}/{audio_out}. "
            +f"Cache lest/skrevet: {item.get('cached_tokens',0)}/{item.get('cache_write_tokens',0)} tokens. "
            +f"Intern resonnering: {item.get('reasoning_tokens',0)} av {item.get('output_tokens',0)} outputtokens. "
            +(f"Svargrense: {item['max_output_tokens']} tokens ({item.get('reasoning_effort','')}). " if item.get('max_output_tokens') else '')
            +('Ingen ekstra svartak fra backend. ' if 'max_output_tokens' in item and item['max_output_tokens'] is None else '')
            +(error_text('',item['failure_code'])+'. ' if item.get('failure_code') else '')
            +("Tokens rapportert av OpenAI; USD beregnet lokalt." if item.get('usage_source')=='provider' else
              "Anslag fra lydlengde." if item.get('usage_source')=='duration' else "Ufullstendig måling: konservativ kostnadsreserve beholdes."))

    def jobs_page(self,page):
        self.job_heading=self.label(page,"Henter jobber …","Heading.TLabel")
        self.job_heading.pack(anchor="w",pady=(0,7))
        table_frame=ttk.Frame(page);table_frame.pack(fill='x')
        self.job_table=ttk.Treeview(table_frame,columns=('name','status','phase','progress'),show='headings',height=5,selectmode='browse')
        for key,title,width in [('name','App / jobb',230),('status','Status',150),('phase','Arbeider med',260),('progress','Fremdrift',100)]:
            self.job_table.heading(key,text=title);self.job_table.column(key,width=width,minwidth=70)
        self.job_table.pack(side='left',fill='both',expand=True)
        table_scroll=ttk.Scrollbar(table_frame,command=self.job_table.yview)
        self.job_table.configure(yscrollcommand=table_scroll.set);table_scroll.pack(side='right',fill='y')
        self.job_table.bind('<<TreeviewSelect>>',lambda _:self.render_job_detail())
        self.job_progress=ttk.Progressbar(page,maximum=100);self.job_progress.pack(fill='x',pady=8)
        detail_frame=ttk.Frame(page);detail_frame.pack(fill='x')
        self.job_detail=tk.Text(detail_frame,height=11,wrap='word',font=('Segoe UI',10),bg='white',fg=INK,bd=0,padx=10,pady=8,state='disabled')
        self.job_detail.pack(side='left',fill='both',expand=True)
        detail_scroll=ttk.Scrollbar(detail_frame,command=self.job_detail.yview)
        self.job_detail.configure(yscrollcommand=detail_scroll.set);detail_scroll.pack(side='right',fill='y')
        self.label(page,"Tillegg til utviklingen", "Heading.TLabel").pack(anchor='w',pady=(10,5))
        self.job_prompt=tk.Text(page,height=3,wrap='word',font=('Segoe UI',11));self.job_prompt.pack(fill='x')
        self.label(page,"Gjelder neste generering, ikke et modellkall som allerede pågår. Kan bruke ett av jobbens tillatte forsøk.\n"
            "Ved feil: velg Resume. Plan og dialog beholdes; bekreft Bygg for et nytt forsøk.",
            "Muted.TLabel",wraplength=800).pack(anchor='w',pady=6)
        actions=ttk.Frame(page);actions.pack(fill='x')
        self.job_send=ttk.Button(actions,text='Legg til kontekst i valgt jobb',command=self.send_job_context,style='Accent.TButton')
        self.job_send.pack(side='left')
        self.job_resume=ttk.Button(actions,text='Resume valgt jobb',command=self.resume_selected_job)
        self.job_resume.pack(side='left',padx=10)
        ttk.Button(page,text='Åpne Aktivitet',command=lambda:self.show('Aktivitet')).pack(anchor='w',pady=7)

    def send_job_context(self):
        chosen=self.job_table.selection();row=self.job_rows.get(chosen[0]) if chosen else None
        if not row or not row.get('can_add_context'):return
        text=self.job_prompt.get('1.0','end').strip()
        if not text:return
        def done(value):
            self.job_drafts[row['id']]=''
            if self.job_editor_target==row['id']:self.job_prompt.delete('1.0','end')
            self.notice.set(value['message'])
        self.work(lambda:self.runtime.add_job_context(row['build_id'],text),done=done,message='Lagrer kontekst til jobben …')

    def resume_selected_job(self):
        selected=self.job_table.selection();row=self.job_rows.get(selected[0]) if selected else None
        if row and row.get('can_resume'):
            self.work(lambda:self.runtime.resume_job(row['build_id']),done=self.choose_pc_session,
                      message='Henter tilbake plan og dialog …')

    def render_jobs(self):
        rows=self.job_snapshot.get('jobs',[]);self.job_rows={r['id']:r for r in rows}
        self.job_heading.configure(text=f"{self.job_snapshot.get('active_count',0)} aktive jobber · velg en jobb for detaljer")
        labels={'queued':'I kø','building':'Arbeider','ready':'Ferdig','failed':'Stoppet / feilet','awaiting_confirmation':'Venter på bekreftelse',
            'awaiting_build_confirmation':'Venter på bygg','processing':'Behandler','listening':'Tar opp tale'}
        values=[(r['id'],(r['name'],labels.get(r['status'],r['status']),r['message'],str(r['progress'])+'%')) for r in rows]
        if values!=getattr(self,'job_table_values',None):
            selected=self.job_table.selection();self.job_table_values=values
            self.job_table.delete(*self.job_table.get_children())
            for key,value in values:self.job_table.insert('','end',iid=key,values=value)
            if selected and selected[0] in self.job_rows:self.job_table.selection_set(selected[0])
            elif values:self.job_table.selection_set(values[0][0])
        self.render_job_detail()

    def render_job_detail(self):
        selected=self.job_table.selection();r=self.job_rows.get(selected[0]) if selected else None
        target=r['id'] if r else None
        if target!=self.job_editor_target:
            if self.job_editor_target is not None:
                self.job_drafts[self.job_editor_target]=self.job_prompt.get('1.0','end').strip()
                self.job_prompt.delete('1.0','end')
                self.job_prompt.insert('1.0',self.job_drafts.get(target,''))
            self.job_editor_target=target
        self.job_send.configure(text='Legg til kontekst: '+r['name'] if r else 'Legg til kontekst i valgt jobb')
        self.job_send.configure(state='normal' if r and r.get('can_add_context') and not self.busy else 'disabled')
        self.job_resume.configure(state='normal' if r and r.get('can_resume') and not self.busy else 'disabled')
        self.job_progress['value']=r.get('progress',0) if r else 0
        text='Ingen bygg eller feilrettinger registrert.'
        if r:
            pending='VENTER på neste generering' if r.get('context_pending') else 'Tatt med i generering'
            notes=r.get('context',{}).get('notes',[])
            attempts=f"{r.get('attempt',0)}/{r['max_attempts']} forsøk" if r.get('max_attempts') else f"Forsøk {r.get('attempt',0)} · automatisk retting"
            lines=[r['name']+' · '+r['id'],r['message']+f" · {attempts} · anslått ${r.get('estimated_usd',0):.4f}"]
            if r.get('reused_candidate_from'):lines.append('Gjenbruker appkode fra '+r['reused_candidate_from']+'; tester og kontrollerer på nytt.')
            if r.get('retry_at'):lines.append('Neste AI-forsøk tidligst '+time.strftime('%H:%M:%S',time.localtime(r['retry_at'])))
            if r.get('error'):lines+=['STOPPÅRSAK: '+r.get('error_status',''),r['error']]
            if r.get('last_validation_error'):lines+=['Siste kontrollfunn:',r['last_validation_error']]
            lines+=['Plan:',r.get('summary','')]
            if notes:lines+=['Manuell kontekst: '+pending]+[n['text'] for n in notes]
            text='\n'.join(lines)
        if text!=getattr(self,'job_detail_text',None):
            self.job_detail_text=text;self.job_detail.configure(state='normal');self.job_detail.delete('1.0','end');self.job_detail.insert('1.0',text);self.job_detail.configure(state='disabled')

    def activity_page(self, page):
        self.label(page, "Snakk med AI eller beskriv en app. B på FIRE starter et nytt opptak og avbryter forrige svar.", "Muted.TLabel").pack(anchor="w")
        row = ttk.Frame(page)
        row.pack(fill="x", pady=9)
        self.session_box = ttk.Combobox(row, textvariable=self.selected_session, state="readonly", width=48)
        self.session_box.pack(side="left", fill="x", expand=True)
        ttk.Button(row, text="Oppdater", command=self.refresh_now).pack(side="left", padx=(8, 0))
        self.new_app_button = ttk.Button(row, text="Ny app", command=self.new_app)
        self.new_app_button.pack(side="left", padx=(8, 0))
        self.pc_app_button=ttk.Button(row,text="Ny app på PC",command=self.new_pc_app)
        self.pc_app_button.pack(side="left",padx=(8,0))
        ttk.Button(page,text="Avslutt PC-samtalen",command=self.stop_pc_conversation).pack(anchor="e",pady=(0,4))
        row = ttk.Frame(page)
        row.pack(fill="x", pady=(0, 7))
        ttk.Button(row, text="Kun samtale", command=lambda: self.set_conversation("chat")).pack(side="left")
        ttk.Button(row, text="Lag/endre app", command=lambda: self.set_conversation("develop")).pack(side="left", padx=8)
        ttk.Button(row, text="Avbryt AI-svar", command=self.cancel_conversation).pack(side="left")
        self.replay_voice_button=ttk.Button(row,text="Spill svar igjen",command=lambda:self.replay_voice(False))
        self.replay_voice_button.pack(side="left",padx=8)
        self.test_voice_button=ttk.Button(row,text="Test lyd",command=lambda:self.replay_voice(True))
        self.test_voice_button.pack(side="left")
        self.session_detail = self.label(page, "Ingen FIRE tilkoblet ennå.", wraplength=810)
        self.session_detail.pack(anchor="w", pady=(0, 7))
        self.pipeline_detail = self.label(page, "", wraplength=810, foreground=MUTED)
        self.pipeline_detail.pack(anchor="w", pady=(0, 7))
        self.history = tk.Text(page, height=9, wrap="word", font=("Segoe UI", 10), bd=0, padx=12, pady=9,
                               bg="white", fg=INK, state="disabled")
        self.history.pack(fill="both", expand=True)
        self.prompt = tk.Text(page, height=3, wrap="word", font=("Segoe UI", 11), bd=1, relief="solid", padx=9, pady=6)
        self.prompt.pack(fill="x", pady=9)
        self.prompt.insert("1.0", "Lag en animasjon med en sirkel som beveger seg.")
        row = ttk.Frame(page)
        row.pack(fill="x")
        self.send_button = ttk.Button(row, text="Send tekst", command=self.send_text, style="Accent.TButton")
        self.send_button.pack(side="left")
        self.build_button = ttk.Button(row, text="Bekreft bygging", command=lambda: self.confirm("build"))
        self.build_button.pack(side="left", padx=8)
        self.run_button = ttk.Button(row, text="Bekreft kjøring", command=lambda: self.confirm("run"))
        self.run_button.pack(side="left")
        self.progress = ttk.Progressbar(page, maximum=100)
        self.progress.pack(fill="x", pady=(13, 5))
        self.label(page, "Bygging og kjøring krever hver sin bekreftelse. De starter aldri fra teksten alene.", "Muted.TLabel").pack(anchor="w")
        self.logs = tk.Text(page, height=5, wrap="word", font=("Consolas", 9), bd=0, bg="#e8edf4", fg=MUTED, state="disabled")
        self.logs.pack(fill="x", pady=(12, 0))

    def apps_page(self, page):
        top=ttk.Frame(page);top.pack(fill="x",pady=(0,8))
        self.label(top, "Apper og versjoner", "Heading.TLabel").pack(side="left")
        ttk.Button(top,text="Lag ny app med AI",command=self.new_pc_app,style="Accent.TButton").pack(side="right")
        ttk.Button(top,text="Maskinvareutkast på PC",command=lambda:self.new_pc_app(True)).pack(side="right",padx=8)
        self.label(page, "FIRE lagrer appen på SD-kortet i /apps/<app-ID>/.\n"
                   "Cost summerer registrert API-bruk for alle versjoner, feilrettinger og tale, uavhengig av nullstilling.\n"
                   "≈ inkluderer historiske anslag fra lagrede bygg. Eldre tale uten måling er ikke med.",
                   "Muted.TLabel", wraplength=800).pack(anchor="w", pady=(0, 12))
        frame = ttk.Frame(page)
        frame.pack(fill="both", expand=True)
        self.apps_table = ttk.Treeview(frame, columns=("name", "version", "device", "cost", "status"), show="headings", height=7,selectmode="browse")
        for name, title, width in (("name", "App", 165), ("version", "Versjoner", 75), ("device", "Enhet", 135), ('cost','Cost (USD)',100), ("status", "Nyeste versjon", 210)):
            self.apps_table.heading(name, text=title)
            self.apps_table.column(name, width=width, minwidth=60)
        scrollbar = ttk.Scrollbar(frame, orient="vertical", command=self.apps_table.yview)
        self.apps_table.configure(yscrollcommand=scrollbar.set)
        self.apps_table.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")
        self.apps_table.bind("<<TreeviewSelect>>", lambda _: self.render_app_detail())
        version_row=ttk.Frame(page);version_row.pack(fill="x",pady=(10,0))
        self.label(version_row,"Velg versjon").pack(side="left",padx=(0,12))
        self.version_box=ttk.Combobox(version_row,textvariable=self.selected_version,state="readonly",width=42)
        self.version_box.pack(side="left",fill="x",expand=True)
        self.version_box.bind("<<ComboboxSelected>>",lambda _: self.choose_version())
        self.apps_detail = self.label(page, "Ingen app-pakker ennå. Beskriv appen under Aktivitet eller på FIRE.", wraplength=800)
        self.apps_detail.pack(anchor="w", pady=10)
        actions = ttk.Frame(page)
        actions.pack(anchor="w", pady=(0, 10))
        self.install_button = ttk.Button(actions, text="Installer på FIRE", command=self.install_saved, style="Accent.TButton")
        self.install_button.pack(side="left")
        self.edit_app_button = ttk.Button(actions, text="Endre valgt versjon", command=self.edit_saved)
        self.edit_app_button.pack(side="left", padx=8)
        ttk.Button(actions, text="Reparer valgt app", command=self.repair_saved).pack(side="left", padx=(0,8))
        ttk.Button(actions,text="Feil og rettinger",command=self.show_app_quality).pack(side="left")
        deletion=ttk.Frame(page);deletion.pack(anchor="w",pady=(0,8))
        self.delete_app_button=ttk.Button(deletion,text="Slett alle versjoner …",command=self.delete_saved)
        self.delete_app_button.pack(side="left")
        self.delete_version_button=ttk.Button(deletion,text="Slett valgt versjon …",command=lambda:self.delete_saved(True))
        self.delete_version_button.pack(side="left",padx=8)
        self.label(page, "Bruker lagret, testet pakke uten ny AI-generering. Appstart krever fortsatt A RUN / Bekreft kjøring.",
                   "Muted.TLabel", wraplength=800).pack(anchor="w")
        self.label(page, "PC-sletting tillates først når tilkoblet FIRE bekrefter at appen er borte.\n"
                   "Velg Ny app / en annen app først hvis denne appen er aktiv i samtalen.", "Muted.TLabel", wraplength=800).pack(anchor="w", pady=5)
        self.apps_rows = {}

    def render_app_detail(self):
        selected = self.apps_table.selection()
        versions=sorted((a for a in self.apps_rows.values() if selected and a["project_id"]==selected[0]),key=lambda a:int(a["version"].split(".")[-1]),reverse=True)
        self.version_choices={f"{a['version']} · {a['mode']}":a["package_id"] for a in versions}
        self.version_box.configure(values=list(self.version_choices))
        saved=self.version_selection.get(selected[0]) if selected else None
        self.selected_version.set(next((label for label,pkg in self.version_choices.items() if pkg==saved),next(iter(self.version_choices),"")))
        app=self.selected_app()
        if app:
            quality_hint = ("Sperret etter feil – bruk Reparer valgt app.\n" if app.get("quality",{}).get("blocked") else
                            "Trenger utvidet test – bruk Reparer valgt app eller bygg ny versjon.\n" if app.get("validation_suite") != "release-v4" else "")
            self.apps_detail.configure(text=f"{app['name']} · {app['version']} · {app['mode']}\n"
                +app_cost_detail(app)
                +f"SD-mappe: {app['sd_path']}\nPakke: {app['package_id']}\n"
                + quality_hint
                + (app.get("delete_block_reason") or "FIRE har bekreftet at appen er borte; PC-historikken kan slettes."))
        else:self.apps_detail.configure(text="Ingen app valgt.")

    def selected_app(self):
        return self.apps_rows.get(self.version_choices.get(self.selected_version.get()))

    def show_app_quality(self):
        app=self.selected_app()
        if not app:return
        def show(records):
            window=tk.Toplevel(self.root);window.title("Feil og rettinger – "+app['name']);window.geometry("800x560")
            view=scrolledtext.ScrolledText(window,wrap="word",font=("Segoe UI",10),padx=16,pady=16)
            view.pack(fill="both",expand=True)
            lines=[app['name']+" – siste registrerte feil og rettinger",""]
            if not records:lines.append("Ingen feil er registrert for denne appen.")
            for case in records:
                lines.extend(["Feil / observasjon ("+str(case.get('count',1))+" ganger):",case.get('message',''),""])
                fix=case.get('fix') or {}
                if fix:
                    lines.append("Retting: "+fix.get('summary','Ny kandidat er registrert.'))
                    if fix.get('reviewer_summary'):lines.append("AI-rapport: "+fix['reviewer_summary'])
                    lines.append("Endrede linjer: +"+str(fix.get('lines_added','?'))+" / -"+str(fix.get('lines_removed','?')))
                    if fix.get('status')=='failed_on_device':lines.append("Enheten rapporterte en ny feil med kandidaten.")
                    lines.append("En første vellykket start bekrefter ikke at feilen er endelig løst.")
                else:lines.append("Ingen rettet kandidat er registrert ennå.")
                check=fix.get('required_regression_check') or case.get('regression',{}).get('required_check')
                if check:lines.append("Tilbakefallstest: "+check)
                lines.extend(["","—"*40,""])
            view.insert("1.0","\n".join(lines));view.configure(state="disabled")
        self.work(lambda:self.runtime.app_quality(app['project_id']),done=show,message="Henter feil og rettinger …")

    def choose_version(self):
        app=self.selected_app()
        if app:self.version_selection[app["project_id"]]=app["package_id"]
        self.render_app_detail()

    def new_pc_app(self,hardware_preview=False):
        self.work(lambda:self.runtime.desktop_conversation(self.device_id.get(),hardware_preview=hardware_preview),done=self.choose_pc_session,
                  message="Starter maskinvareutkast med simulerte målinger …" if hardware_preview else "Starter AI-dialog på PC …")

    def choose_pc_session(self,result):
        prior=self.session()
        if prior:self.activity_drafts[prior['session_id']]=self.prompt.get('1.0','end').strip()
        draft=self.activity_drafts.get(result['session_id'],'')
        source=result.get('resumed_from_build_id')
        if source:
            pending=self.job_prompt.get('1.0','end').strip() if self.job_editor_target==source else self.job_drafts.get(source,'')
            draft=pending or draft
        self.prompt.delete('1.0','end');self.prompt.insert('1.0',draft)
        self.snapshot["sessions"]=[s for s in self.snapshot["sessions"] if s["session_id"]!=result["session_id"]]+[{**result,"online":False,"history":[]}]
        self.selected_session.set(self.session_name(result))
        self.show("Aktivitet")
        self.refresh_now()

    def stop_pc_conversation(self):
        session=self.session()
        if session and session.get("desktop_device_id"):
            self.work(lambda:self.runtime.stop_conversation(session["session_id"]),message="Avslutter PC-samtalen …")

    def new_app(self):
        session = self.session()
        if session and session.get("desktop_device_id"):return self.new_pc_app()
        if session:
            self.work(lambda: self.runtime.select_app(session["session_id"], "new"),
                      done=lambda _: self.show("Aktivitet"), message="Velger ny app …")

    def set_conversation(self, mode):
        session = self.session()
        if session:
            self.work(lambda: self.runtime.conversation(session["session_id"], conversation_mode=mode),
                      message="Bytter samtalemodus …")

    def cancel_conversation(self):
        session = self.session()
        if session:
            self.work(lambda: self.runtime.conversation(session["session_id"], action="cancel"),
                      message="Avbryter AI-svaret …")

    def replay_voice(self,test=False):
        session=self.session()
        if session:self.work(lambda:self.runtime.voice(session["session_id"],test),message="Tester talesvar …" if test else "Spiller svaret på nytt …")

    def edit_saved(self):
        app=self.selected_app()
        if app and app.get("device_id"):
            self.work(lambda:self.runtime.desktop_conversation(app["device_id"],project_id=app["project_id"],base_package_id=app["package_id"],hardware_preview=app.get("api_version")=="fire-lua-0.2"),
                      done=self.choose_pc_session,message="Åpner valgt versjon i AI-dialog på PC …")

    def delete_saved(self,only_version=False):
        app=self.selected_app()
        if not app or not app.get("can_delete_backend") or self.busy:
            return
        count = sum(a["project_id"] == app["project_id"] for a in self.apps_rows.values())
        subject=f"versjon {app['version']} av «{app['name']}»" if only_version else f"«{app['name']}» og alle {count} lagrede versjoner"
        if messagebox.askyesno("Slett fra PC", f"Slette {subject} fra PC?\n\n"
                              "FIRE har bekreftet at appen er borte. PC-slettingen kan ikke angres.", parent=self.root):
            self.work(lambda:self.runtime.delete_version(app["project_id"],app["package_id"]) if only_version else self.runtime.delete_app(app["project_id"]),message="Sletter fra PC …")

    def repair_saved(self):
        app=self.selected_app()
        if app and app.get("device_id"):
            def repair():
                result=self.runtime.desktop_conversation(app["device_id"],project_id=app["project_id"],base_package_id=app["package_id"],hardware_preview=app.get("api_version")=="fire-lua-0.2")
                self.runtime.send_text(result["session_id"],"Undersøk appen og reparer feilen. Behold funksjonene.")
                return result
            self.work(repair,done=self.choose_pc_session,message="Undersøker valgt app automatisk …")

    def install_saved(self):
        app=self.selected_app()
        session=next((s for s in self.snapshot["sessions"] if app and s["target"]=="device" and s.get("online") and s["device_id"]==app["device_id"]),None)
        if app and session:
            self.work(lambda: self.runtime.install_saved(session["session_id"], app["package_id"]),
                      message="Sender valgt app til FIRE for installasjon …")

    def firmware_page(self,page):
        self.label(page,"Firmware på FIRE", "Heading.TLabel").pack(anchor="w",pady=(0,10))
        self.firmware_status=self.label(page,"Venter på enhetsstatus …",wraplength=800)
        self.firmware_status.pack(anchor="w",pady=(0,14))
        self.label(page,"Firmwarefiler på PC", "Heading.TLabel").pack(anchor="w",pady=(0,8))
        self.firmware_table=ttk.Treeview(page,columns=("name","version","size","status"),show="headings",height=7,selectmode="browse")
        for name,title,width in (("name","Fil",220),("version","Versjon",140),("size","Størrelse",90),("status","SD-overføring",240)):
            self.firmware_table.heading(name,text=title);self.firmware_table.column(name,width=width,minwidth=60)
        self.firmware_table.pack(fill="both",expand=True)
        grid=ttk.Frame(page);grid.pack(fill="x",pady=10)
        self.field(grid,0,"Versjon / byggnavn",self.firmware_version)
        row=ttk.Frame(page);row.pack(fill="x",pady=8)
        ttk.Button(row,text="Legg til firmware.bin …",command=self.upload_firmware,style="Accent.TButton").pack(side="left")
        self.firmware_send_button=ttk.Button(row,text="Send valgt fil til /firmware",command=self.send_firmware)
        self.firmware_send_button.pack(side="left",padx=8)
        self.label(page,"Filer lagres på SD-kortet i /firmware. En lagret fil er ikke installert firmware.\n"
                   "Installert versjon over vises fra FIREs egen tilkoblingsmelding. Overføring starter ingen flashing.","Muted.TLabel",wraplength=800).pack(anchor="w",pady=10)

    def upload_firmware(self):
        path=filedialog.askopenfilename(parent=self.root,title="Velg ESP32 firmware.bin",filetypes=[("ESP32 firmware","*.bin")])
        if not path:return
        version=self.firmware_version.get().strip() or Path(path).stem
        self.work(lambda:self.runtime.upload_firmware(path,version),message="Legger firmwarefilen til på PC …")

    def send_firmware(self):
        selected=self.firmware_table.selection()
        if selected:self.work(lambda:self.runtime.send_firmware(selected[0],self.device_id.get()),message="Sender firmwarefil til SD-kortet …")

    def settings_page(self, page):
        grid = ttk.Frame(page)
        grid.pack(fill="x")
        self.field(grid, 0, "Datamappe", self.workspace)
        self.field(grid, 1, "Lagringsgrense (MB)", self.disk)
        ttk.Button(page, text="Velg datamappe …", command=self.choose_workspace).pack(anchor="w", pady=10)
        ttk.Checkbutton(page, text="Aktiver backendens lydtransport", variable=self.audio).pack(anchor="w", pady=8)
        self.label(page, "Enheten må annonsere mikrofon/avspilling. Tekst virker også uten lydtransport.", "Muted.TLabel").pack(anchor="w")
        self.label(page, "Kostnadsgrenser", "Heading.TLabel").pack(anchor="w",pady=(16,6))
        ttk.Checkbutton(page,text='Bruk kostnadsgrenser (av som standard)',variable=self.cost_limits_enabled,
                        command=self.sync_cost_controls).pack(anchor='w',pady=(0,7))
        grid=ttk.Frame(page);grid.pack(fill="x")
        self.budget_fields=[]
        for row,(name,title) in enumerate((("daily_budget_usd","Maks per dag (USD)"),("build_budget_usd","Maks per appjobb (USD)"),
                                          ("request_budget_usd","Maks per API-kall (USD)"))):
            self.budget_fields.append(self.field(grid,row,title,self.cost_limits[name]))
        ttk.Checkbutton(page,text='Bruk ekstra svartak for AI (av som standard)',variable=self.output_limits_enabled).pack(anchor='w',pady=(10,4))
        row=ttk.Frame(page);row.pack(fill='x')
        self.field(row,0,'Automatiske rettinger (0 = automatisk)',self.cost_limits['max_corrections'])
        self.label(page,"0 = ingen fast grense i hvert av feltene over. Alle fire har 0 som standard.\n"
                   "Med svartaket av fullfører modellen innen sin egen kapasitet. Modellvalg og lav resonnering styrer forbruket.\n"
                   "Automatisk retting fortsetter ved framgang og stopper gjentatte, uløste feil. Kvalitetskontroll beholdes.\n"
                   "Når beløpstak slås på, gjelder de lagrede grensene også for tidligere forbruk i dag.\n"
                   "Nullstilling endrer bare visningen. Tekniske enhets- og driftsgrenser gjelder fortsatt.","Muted.TLabel",wraplength=790).pack(anchor="w",pady=(6,0))
        self.sync_cost_controls()
        ttk.Button(page, text="Lagre innstillinger", style="Accent.TButton", command=self.save).pack(anchor="w", pady=18)
        ttk.Button(page, text="Åpne datamappen", command=self.open_workspace).pack(anchor="w", pady=6)
        self.label(page, "Lagring og drift", "Heading.TLabel").pack(anchor="w", pady=(15, 8))
        self.label(page, "Prosjekter, testede Lua-pakker og logger lagres lokalt. Endring av datamappe\n"
                   "flytter ikke tidligere prosjekter. Innstillinger og nøkler huskes ved neste start.\n\n"
                   "Programmet starter backend når du åpner det. Lukk vinduet for å stoppe den.\n"
                   "La PC-en være på og våken mens M5Stack bruker forbindelsen.", wraplength=800).pack(anchor="w")

    def sync_cost_controls(self):
        for field in getattr(self,'budget_fields',[]):field.configure(state='normal' if self.cost_limits_enabled.get() else 'disabled')

    def collect(self):
        values = self.store.config.model_dump()
        ids = list(values["device_ids"])
        device_id = self.device_id.get().strip()
        if device_id not in ids:
            ids.append(device_id)
        values.update(mode="mock" if self.mode.get() == "Test uten API" else "openai", allow_lan=self.lan.get(),
                      transport=self.transport.get(), reverse_host=self.reverse_host.get().strip(),
                      reverse_port=self.reverse_port.get(), reverse_device_id=device_id if self.transport.get() == "reverse_tcp" else "",
                      port=self.port.get(), workspace=self.workspace.get(), device_ids=ids,
                      audio_enabled=self.audio.get(), max_workspace_mb=self.disk.get(),
                      cost_limits_enabled=self.cost_limits_enabled.get(),output_limits_enabled=self.output_limits_enabled.get(),
                      speech_enabled=self.speech_enabled.get(),
                      cost_profile_version=COST_PROFILE_VERSION,
                      **{name:var.get().strip() for name,var in self.cost_limits.items()},
                      **{name: var.get().strip() for name, var in self.models.items()})
        return DesktopConfig.model_validate(values)

    def work(self, function, done=None, message="Arbeider …"):
        if self.busy:
            return
        self.busy = True
        self.notice.set(message)
        def worker():
            try:
                result = function()
                self.queue.put(("done", (done, result)))
            except Exception as error:
                # Pydantic errors include input values; do not show their repr.
                from pydantic import ValidationError
                if isinstance(error, ValidationError):
                    fields = ", ".join(".".join(map(str, item["loc"])) or "tilkobling" for item in error.errors())
                    message = "Kontroller innstillingene: " + fields
                else:
                    message = str(error)[:400]
                self.queue.put(("error", message))
        threading.Thread(target=worker, daemon=True).start()

    def start(self):
        self.work(lambda: self.runtime.start(self.store.settings()), message="Starter backend …")

    def stop(self):
        self.hide_token_qr()
        self.work(self.runtime.stop, message="Stopper backend …")

    def save(self):
        if self.busy:
            return
        self.hide_token_qr()
        try:
            config = self.collect()
            key = self.api_key.get().strip() or None
            tokens = {self.device_id.get().strip(): self.device_token.get().strip()}
        except Exception:
            messagebox.showerror("Kontroller innstillingene", "Kontroller port, enhets-ID, FIRE-adresse, datamappe og modellnavn.", parent=self.root)
            return
        def apply():
            self.runtime.stop()
            self.store.save(config, api_key=key, device_tokens=tokens)
            self.runtime.start(self.store.settings())
        def saved(_):
            self.api_key.set("")
            self.key_saved = bool(self.store.secret("openai"))
            self.key_status.set("Nøkkel er lagret i Windows." if self.key_saved else "Ingen API-nøkkel er lagret ennå.")
            self.notice.set("Innstillingene er lagret. Backend starter med den nye konfigurasjonen.")
            self.api_label.configure(text="Nøkkel/modeller er ikke kontrollert etter siste lagring.")
        self.work(apply, saved, "Lagrer og starter backend på nytt …")

    def test_key(self):
        try:
            config = self.collect()
            key = self.api_key.get().strip() or self.store.secret("openai")
        except Exception:
            self.notice.set("Kontroller innstillingene før nøkkeltesten.")
            return
        self.work(lambda: check_api_key(config, key), lambda result: self.api_label.configure(text=result), "Kontrollerer nøkkelen hos OpenAI …")

    def remove_key(self):
        if self.busy:
            return
        if not messagebox.askyesno("Fjern API-nøkkel", "Fjerne den lagrede API-nøkkelen fra Windows og gå til testmodus?", parent=self.root):
            return
        config = self.store.config.model_copy(update={"mode": "mock"})
        def remove():
            self.runtime.stop()
            self.store.save(config, api_key="")
            self.runtime.start(self.store.settings())
        def done(_):
            self.mode.set("Test uten API")
            self.api_key.set("")
            self.key_saved = False
            self.key_status.set("Ingen API-nøkkel er lagret ennå.")
            self.api_label.configure(text="API-nøkkelen er fjernet.")
        self.work(remove, done, "Fjerner nøkkelen …")

    def toggle_token(self):
        self.token_entry.configure(show="" if self.token_entry.cget("show") else "•")

    def clipboard(self, value):
        self.root.clipboard_clear()
        self.root.clipboard_append(value)
        def clear():
            try:
                if self.root.clipboard_get() == value:
                    self.root.clipboard_clear()
            except tk.TclError:
                pass
        self.root.after(60000, clear)
        self.notice.set("Kopiert. Utklippstavlen tømmes etter ett minutt hvis innholdet er uendret.")

    def copy_connection(self):
        self.clipboard(f"PC-adresse: {self.host.get()}\nPort: {self.port.get()}\nEnhets-ID: {self.device_id.get()}\nWebSocket: ws://{self.host.get()}:{self.port.get()}/ws/device")

    def copy_token(self):
        self.clipboard(self.device_token.get())

    def hide_token_qr(self):
        if self.token_qr_window is not None:
            self.token_qr_window.destroy()
            self.token_qr_window = None

    def show_token_qr(self):
        try:
            settings = self.runtime.settings if self.runtime.ready else self.store.settings()
            device_id = self.device_id.get().strip()
            saved_token = settings.device_tokens().get(device_id)
            if self.device_token.get() != saved_token:
                raise ValueError("Lagre tilkoblingen først, slik at QR viser tokenet backend bruker.")
            matrix = token_matrix(settings, device_id)
        except ValueError as error:
            self.notice.set(str(error))
            return
        self.hide_token_qr()
        window = tk.Toplevel(self.root)
        self.token_qr_window = window
        window.title("Kopier enhetstoken med mobilen")
        window.resizable(False, False)
        window.configure(bg="white")
        window.transient(self.root)
        tk.Label(window, text="Skann og kopier token", bg="white", fg=INK,
                 font=("Segoe UI Semibold", 15)).pack(padx=25, pady=(18, 5))
        tk.Label(window, text=device_id, bg="white", fg=MUTED, font=("Segoe UI", 10)).pack()
        scale = max(1, 330 // len(matrix))
        size = len(matrix) * scale
        canvas = tk.Canvas(window, width=size, height=size, bg="white", highlightthickness=0)
        canvas.pack(padx=25, pady=12)
        for y, row in enumerate(matrix):
            for x, dark in enumerate(row):
                if dark:
                    canvas.create_rectangle(x*scale, y*scale, (x+1)*scale, (y+1)*scale, fill="black", outline="")
        tk.Label(window, text="Kun enhetstoken – ingen API-nøkkel eller lenke.\n"
                 "Kopier teksten på mobilen og lim den inn på FIRE.", bg="white", fg=INK,
                 font=("Segoe UI", 10)).pack(padx=20, pady=5)
        countdown = tk.Label(window, bg="white", fg=MUTED, font=("Segoe UI", 9))
        countdown.pack(pady=5)
        ttk.Button(window, text="Lukk", command=self.hide_token_qr).pack(pady=(4, 16))
        window.protocol("WM_DELETE_WINDOW", self.hide_token_qr)
        deadline = time.monotonic() + 120
        def tick():
            if self.token_qr_window is not window:
                return
            remaining = int(deadline - time.monotonic())
            if remaining <= 0 or self.device_token.get() != saved_token or self.device_id.get().strip() != device_id:
                self.hide_token_qr()
                return
            countdown.configure(text=f"QR skjules om {remaining} sekunder. Tokenet endres ikke.")
            window.after(1000, tick)
        tick()

    def inspect_network(self):
        profile, known = network_info()
        allowed = firewall_ready(self.store.config.port)
        self.queue.put(("network", (profile if known else "Ukjent", allowed)))

    def firewall_action(self):
        try:
            port = self.collect().port
        except Exception:
            self.notice.set("Kontroller og lagre porten først.")
            return
        if port != self.store.config.port:
            self.notice.set("Lagre ny port før du klargjør Windows-brannmuren.")
            return
        self.work(lambda: configure_firewall(port), lambda _: self.root.after(8000, lambda: threading.Thread(target=self.inspect_network, daemon=True).start()),
                  "Windows ber om administratorgodkjenning for lokal M5Stack-trafikk.")

    def choose_workspace(self):
        chosen = filedialog.askdirectory(parent=self.root, title="Velg datamappe for FIRE Backend")
        if chosen:
            self.workspace.set(chosen)

    def open_workspace(self):
        path = Path(self.store.config.workspace)
        path.mkdir(parents=True, exist_ok=True)
        os.startfile(str(path))

    def session(self):
        chosen = self.selected_session.get()
        return next((s for s in self.snapshot["sessions"] if self.session_name(s) == chosen), None)

    @staticmethod
    def session_name(session):
        return f"{'PC maskinvareutkast' if session.get('hardware_preview') else 'PC-dialog'} · {session['desktop_device_id']} · {session['session_id'][-6:]}" if session.get("desktop_device_id") else f"FIRE · {session['device_id']}"

    def send_text(self):
        session = self.session()
        text = self.prompt.get("1.0", "end").strip()
        if not session or not text or len(text) > 4000:
            self.notice.set("Velg en PC-dialog eller tilkoblet FIRE og skriv 1–4000 tegn.")
            return
        self.work(lambda: self.runtime.send_text(session["session_id"], text), message="Sender tekst til FIRE-samtalen …")

    def confirm(self, kind):
        session = self.session()
        if not session:
            return
        item = session.get("proposal_id" if kind == "build" else "package_id")
        if item:
            self.work(lambda: self.runtime.confirm(session["session_id"], kind, item), message="Bekrefter " + ("bygging …" if kind == "build" else "kjøring …"))

    def refresh_now(self):
        self.work(self.runtime.snapshot, lambda data: setattr(self, "snapshot", data), "Henter status …")

    def poll(self):
        next_usage=0
        next_jobs=0
        while not self.closing:
            if self.runtime.ready:
                try:
                    self.queue.put(("snapshot", self.runtime.snapshot()))
                    if time.monotonic()>=next_jobs:
                        self.queue.put(("jobs",self.runtime.jobs()))
                        next_jobs=time.monotonic()+2
                    if time.monotonic()>=next_usage:
                        self.queue.put(("usage",self.runtime.usage()))
                        next_usage=time.monotonic()+6
                except Exception:
                    pass
            time.sleep(2)

    def drain(self):
        while True:
            try:
                kind, value = self.queue.get_nowait()
            except queue.Empty:
                break
            if kind == "snapshot":
                self.snapshot = value
            elif kind == "jobs":
                self.job_snapshot=value
            elif kind == "usage":
                self.usage_snapshot=value
            elif kind == "network":
                self.network, self.firewall = value
            elif kind == "done":
                self.busy = False
                callback, result = value
                self.notice.set("Ferdig.")
                if callback:
                    callback(result)
            elif kind == "error":
                self.busy = False
                self.notice.set(value)
                messagebox.showerror("FIRE Backend", value, parent=self.root)
            elif kind == "closed":
                self.root.destroy()
                return
        self.render_status()
        if not self.closing:
            self.root.after(300, self.drain)

    @staticmethod
    def set_text(widget, text):
        if widget.get("1.0", "end-1c") != text:
            widget.configure(state="normal")
            widget.delete("1.0", "end")
            widget.insert("1.0", text)
            widget.configure(state="disabled")
            widget.see("end")

    def render_status(self):
        ready = self.runtime.ready
        self.start_button.configure(state="disabled" if self.busy or self.runtime.alive else "normal")
        self.stop_button.configure(state="normal" if not self.busy and self.runtime.alive else "disabled")
        mode = "Testmodus" if self.store.config.mode == "mock" else "OpenAI-modus"
        self.summary_labels["server"].configure(text=("● Kjører" if ready else "● Starter …" if self.runtime.alive else "● Stoppet"),
                                                  foreground="#16825b" if ready else MUTED)
        self.summary_labels["api"].configure(text=mode + ("\nNøkkel lagret" if self.key_saved else "\nNøkkel mangler"))
        self.render_usage()
        self.render_jobs()
        sessions = [s for s in self.snapshot["sessions"] if s["target"] == "device" and s.get("online") and ready]
        self.summary_labels["device"].configure(text=f"{len(sessions)} tilkoblet" if sessions else "Venter på FIRE")
        choices = [self.session_name(s) for s in self.snapshot["sessions"] if ready and (s.get("desktop_device_id") or s["target"]=="device" and s.get("online"))]
        self.session_box.configure(values=choices)
        if self.selected_session.get() not in choices:
            self.selected_session.set(choices[0] if choices else "")
        self.network_label.configure(text=f"Nettverksprofil: {self.network or 'Ukjent'}.  " +
            ("FIRE-regel er aktivert." if self.firewall else "Ingen bekreftet FIRE-regel i brannmuren. Bruk knappen ved behov."))
        bridge = self.snapshot.get("transport", {}) if ready else {}
        if bridge.get("mode") == "reverse_tcp":
            count = bridge.get("authenticated_channels", 0)
            state = bridge.get("state")
            explanation = ("Bro klar. Venter på FIREs sesjon eller data." if state == "ready" else
                           "FIRE avviste ID/token eller svarte med feil transportversjon." if state == "authentication_failed" else
                           "Venter på reverse TCP-mottaker på FIRE. Sjekk adresse og ny firmware.")
            self.transport_status.configure(text=f"PC → {bridge.get('fire_host')}:{bridge.get('fire_port')}\n"
                f"{count}/{bridge.get('pool_size', 4)} autentiserte kanaler, {bridge.get('active_channels', 0)} i bruk.\n{explanation}")
        else:
            self.transport_status.configure(text="Direkte nett: FIRE kobler til PC-ens backendadresse." if ready else "Backend er stoppet.")
        lan = self.host.get()
        connection_hint = (f"PC → FIRE {bridge.get('fire_host')}:{bridge.get('fire_port')}. Se status under Tilkobling."
                           if bridge.get("mode") == "reverse_tcp" else
                           f"M5Stack bruker PC-adressen {lan}." if self.store.config.allow_lan else
                           "Kun denne PC-en er tillatt; aktiver lokalt nettverk under M5Stack.")
        self.readiness.configure(text=(f"Backend lytter på port {self.store.config.port}. " + connection_hint
             if ready else self.runtime.failure or "Backend er stoppet. Innstillinger kan fortsatt redigeres."))
        session = self.session() if ready else None
        apps = self.snapshot.get("apps", [])
        rows = {app["package_id"]: app for app in apps}
        if rows != self.apps_rows:
            selected = self.apps_table.selection()
            self.apps_table.delete(*self.apps_table.get_children())
            self.apps_rows = rows
            groups={}
            for app in apps:groups.setdefault(app["project_id"],[]).append(app)
            for project_id,versions in sorted(groups.items(),key=lambda item:item[1][0]["name"].casefold()):
                app=max(versions,key=lambda a:int(a["version"].split(".")[-1]))
                status = ("Slettet/borte fra FIRE" if app.get("device_presence") in {"deleted", "missing"} else
                          "Sperret etter feil" if app.get("quality",{}).get("blocked") else
                          "Kjører (kvittert)" if app["running"] else "Tidligere kjøring bekreftet" if app["current_healthy"] else
                          "Installert (kvittert)" if app["installed_receipt"] else
                          "Tidligere installert; SD ukjent" if app.get("had_install_receipt") else "Testet på PC; ikke installert")
                self.apps_table.insert("", "end", iid=project_id, values=(app["name"], len(versions), app.get("device_id") or "PC-simulering",app_cost_text(app), app["version"]+" · "+status))
            if selected and selected[0] in groups:
                self.apps_table.selection_set(selected[0])
            elif groups:
                self.apps_table.selection_set(next(iter(groups)))
            self.render_app_detail()
        idle_for_text = session and session["state"] not in {"building", "testing", "running", "starting", "stopping", "rollback_pending"}
        app=self.selected_app()
        choice_idle = idle_for_text and session["state"] != "processing" and session.get("activity", "idle") == "idle"
        physical=next((s for s in sessions if app and s["device_id"]==app.get("device_id")),None)
        can_install=physical and physical["state"] not in {"building","testing","processing","running","starting","stopping","rollback_pending"} and physical.get("activity","idle")=="idle"
        deliverable = app and not app.get("quality",{}).get("blocked") and app.get("validation_suite") == "release-v4"
        self.install_button.configure(state="normal" if can_install and deliverable and not self.busy else "disabled")
        self.edit_app_button.configure(state="normal" if ready and app and app.get("device_id") and not self.busy else "disabled")
        self.pc_app_button.configure(state="normal" if ready and not self.busy else "disabled")
        for button in (self.replay_voice_button,self.test_voice_button):
            button.configure(state="normal" if self.store.config.speech_enabled and session and session["target"]=="device" and session.get("online") and not self.busy else "disabled")
        self.new_app_button.configure(state="normal" if choice_idle and not self.busy else "disabled")
        self.delete_app_button.configure(state="normal" if ready and app and app.get("can_delete_backend") and not self.busy else "disabled")
        self.delete_version_button.configure(state="normal" if ready and app and app.get("can_delete_backend") and not self.busy else "disabled")
        self.send_button.configure(state="normal" if choice_idle and session.get("install_permitted", True) and not self.busy else "disabled")
        self.build_button.configure(state="normal" if session and session.get("install_permitted", True) and session["state"] == "awaiting_build_confirmation" and session.get("proposal_id") and not self.busy else "disabled")
        self.run_button.configure(text="Testkjøring på PC" if session and session.get("desktop_device_id") else "Bekreft kjøring",state="normal" if session and session["state"] in ({"ready_to_run"} if session.get("desktop_device_id") else {"installed"}) and session.get("package_id") and not self.busy else "disabled")
        self.render_firmware(ready)
        if session:
            workflow = {"idle": "Klar for tale eller tekst", "listening": "Tar opp tale på FIRE …", "processing": "Tolker bestillingen …",
                        "clarification_needed": "Svar på spørsmålet med et nytt opptak eller tekst",
                        "awaiting_build_confirmation": "Forslag klart – trykk A BUILD på FIRE eller Bekreft bygging",
                        "awaiting_install": "FIRE laster ned og installerer appen på SD-kortet …",
                        "installed": "Installert – trykk A RUN på FIRE eller Bekreft kjøring",
                        "starting": "Venter på appstart fra FIRE …", "running": "Appen kjører på FIRE (kvittert)",
                        "failed": "Handlingen feilet; se feilen under"}.get(session["state"], session["state"])
            detail = session.get("last_error") or session.get("progress", {}).get("message", "")
            base = self.apps_rows.get(session.get("base_package_id"), {})
            choice = (f"Endrer {base.get('name', 'valgt app')} fra versjon {base.get('version', 'valgt basis')}" if session.get("app_mode") == "update"
                      else "Ny app")
            if session.get("conversation_mode") == "chat":
                choice = "Kun samtale · ingen app bygges"
            audio = session.get("audio_status", {})
            audio_hint = {"recording": "Tar opp tale …", "awaiting_upload": "Venter på lyd fra FIRE …",
                "transcribing": "Gjenkjenner tale …", "dialog": "AI tolker bestillingen …",
                "generating_reply": "Lager AI-lydsvar …", "reply_ready": "Lydsvaret er klart for FIRE",
                "playing": "FIRE spiller av lydsvaret", "played": "FIRE har kvittert for avspilling",
                "upload_missing": "Lydfilen kom ikke frem", "input_failed": "Opptaket kunne ikke tolkes",
                "reply_failed": "Lydsvaret feilet; tekstsvaret er beholdt",
                "playback_failed": "Avspilling mangler/feilet på FIRE; tekst og forslag er beholdt"}.get(audio.get("phase"), "")
            if audio.get("phase") == "retry":
                audio_hint = "Klar for nytt opptak · trykk B"
            if audio_hint and audio.get("duration_seconds"):
                audio_hint += f" · Lyd {audio['duration_seconds']:.1f} s"
                if audio.get("recording_wall_seconds"):
                    audio_hint += f" / opptakstid {audio['recording_wall_seconds']:.1f} s"
                if audio.get("capture_rate_suspected") or audio.get("capture_gap_suspected"):
                    audio_hint += " · Kontroller mikrofonens tidsforhold"
            self.pipeline_detail.configure(text=choice + " · " + workflow + ("\n" + detail if detail else "")
                                           + ("\n" + audio_hint if audio_hint else "")
                                           + ("\nJeg hørte: " + audio["transcript"][:200] if audio.get("transcript") else ""))
            device = next((d for d in self.snapshot["devices"] if d["id"] == session["device_id"]), {})
            self.session_detail.configure(text=f"Status: {session['state']}  ·  Installert: {device.get('installed_package_id') or '–'}\n"
                                                f"Kjører: {device.get('running_package_id') or '–'}  ·  Fysisk test: ikke bekreftet")
            if session.get("desktop_device_id"):
                self.session_detail.configure(text=("MASKINVAREUTKAST: Alle målinger er simulert. Krever samsvarende firmware før installasjon." if session.get("hardware_preview") else "PC-dialog for "+session["desktop_device_id"]+" · Enheten kan være frakoblet. Installer den ferdige versjonen under Apper."))
            history = "\n\n".join(("Du: " if h.get("role") == "user" else "FIRE: ") + str(h.get("content", "")) for h in session.get("history", []))
            progress = session.get("progress", {})
            self.progress["value"] = progress.get("progress", 0)
            self.set_text(self.history, history or "Skriv hva appen skal gjøre. Backend gir et forslag før bygging.")
        else:
            self.pipeline_detail.configure(text="")
            self.session_detail.configure(text="Start Ny app på PC for AI-dialog, eller åpne AI Developer på FIRE.")
            self.set_text(self.history, "Velg Ny app på PC for å lage apper, også uten en tilkoblet FIRE.")
            self.progress["value"] = 0
        self.set_text(self.logs, self.runtime.logs.text() if self.runtime.logs else "Backend-loggen vises her etter oppstart.")

    def render_firmware(self,ready):
        device=next((d for d in self.snapshot["devices"] if d["id"]==self.device_id.get()),{})
        caps=device.get("capabilities") or {}
        online=ready and device.get("online")
        version=caps.get("firmware_version","Ukjent")
        support=online and caps.get("firmware_storage",False)
        self.firmware_status.configure(text="Installert versjon ("+("rapportert av tilkoblet FIRE" if online else "sist rapportert; FIRE er frakoblet")+"): "+version+"\n"+
            ("Mottak til /firmware er tilgjengelig." if support else "Denne enhetsversjonen kan ikke motta firmwarefiler ennå. Device-agenten må legge til SD-mottak; se GitHub-instruksen."))
        firmware=self.snapshot.get("firmware",{})
        jobs=firmware.get("transfers",[])
        view=[]
        for item in firmware.get("files",[]):
            job=next((j for j in jobs if j["firmware_id"]==item["id"] and j["device_id"]==self.device_id.get()),{})
            status={"stored":"Lagret i /firmware (kvittert)","pending":"Overfører …","failed":"Overføring feilet","expired":"Tidsavbrudd","unknown":"Ukjent etter omstart"}.get(job.get("status"),"Kun lagret på PC")
            view.append((item["id"],item["filename"],item["version"],f"{item['size_bytes']/1024:.0f} KB",status))
        if view!=getattr(self,"firmware_view",None):
            selected=self.firmware_table.selection();self.firmware_view=view
            self.firmware_table.delete(*self.firmware_table.get_children())
            for item_id,*values in view:self.firmware_table.insert("","end",iid=item_id,values=values)
            if selected and selected[0] in {v[0] for v in view}:self.firmware_table.selection_set(selected[0])
            elif view:self.firmware_table.selection_set(view[0][0])
        self.firmware_send_button.configure(state="normal" if support and view and not self.busy else "disabled")

    def close(self):
        if self.closing:
            return
        self.hide_token_qr()
        self.closing = True
        self.notice.set("Avslutter backend og lagrer status …")
        def close_worker():
            try:
                self.runtime.stop()
                self.queue.put(("closed", None))
            except Exception as error:
                self.closing = False
                self.queue.put(("error", str(error)))
        threading.Thread(target=close_worker, daemon=True).start()
        # Continue draining while shutdown runs, without blocking the window.
        self.root.after(300, self.drain_closing)

    def drain_closing(self):
        self.drain()
        try:
            if self.closing and self.root.winfo_exists():
                self.root.after(300, self.drain_closing)
        except tk.TclError:
            pass


def main():
    if os.name == "nt":
        with __import__("contextlib").suppress(Exception):
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
    root = tk.Tk()
    try:
        store = DesktopStore()
        # One desktop per profile; advisory locking also protects its server data.
        from .desktop_runtime import WorkspaceLock
        lock = WorkspaceLock(store.root / "desktop-instance")
        store.migrate_cost_profile()
        DesktopUI(root, store)
        root.mainloop()
        lock.close()
    except Exception:
        messagebox.showerror("FIRE Backend", "Programmet kunne ikke åpnes. Det kan allerede kjøre, eller Windows-profilen kan være utilgjengelig.", parent=root)
        root.destroy()


if __name__ == "__main__":
    main()
