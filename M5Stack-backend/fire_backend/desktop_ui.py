"""Local Windows control panel. Tk widgets and callbacks stay on the UI thread."""
import ctypes
import os
from pathlib import Path
import queue
import secrets
import threading
import time
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from .desktop_config import DesktopConfig, DesktopStore
from .desktop_runtime import DesktopRuntime, check_api_key, configure_firewall, firewall_ready, lan_addresses, network_info
from .token_qr import token_matrix


BG, INK, MUTED, ORANGE, NAV = "#f2f4f8", "#182231", "#637083", "#e95725", "#172231"


class DesktopUI:
    def __init__(self, root, store):
        self.root, self.store = root, store
        self.runtime = DesktopRuntime()
        self.queue = queue.Queue()
        self.busy, self.closing = False, False
        self.snapshot = {"sessions": [], "devices": [], "builds": []}
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
        self.models = {name: tk.StringVar(value=getattr(c, name)) for name in
                       ("dialog_model", "code_model", "transcribe_model", "speech_model", "speech_voice")}
        self.workspace = tk.StringVar(value=c.workspace)
        self.disk = tk.StringVar(value=str(c.max_workspace_mb))
        self.selected_session = tk.StringVar()
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
        for name in ("Oversikt", "M5Stack", "Tilkobling", "OpenAI", "Aktivitet", "Apper", "Innstillinger"):
            button = tk.Button(nav, text=name, command=lambda n=name: self.show(n), anchor="w", relief="flat",
                               bg=NAV, fg="#c1ccd9", activebackground="#293b51", activeforeground="white",
                               font=("Segoe UI", 12), padx=25, pady=12, bd=0, cursor="hand2")
            button.pack(fill="x", padx=10, pady=3)
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
        self.openai_page(self.pages["OpenAI"])
        self.activity_page(self.pages["Aktivitet"])
        self.apps_page(self.pages["Apper"])
        self.settings_page(self.pages["Innstillinger"])
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
        self.label(page, "Modeller", "Heading.TLabel").pack(anchor="w", pady=(5, 8))
        grid = ttk.Frame(page)
        grid.pack(fill="x")
        for row, (name, title) in enumerate((("dialog_model", "Dialog"), ("code_model", "Kodegenerering"),
                                           ("transcribe_model", "Transkripsjon"), ("speech_model", "Talesvar"), ("speech_voice", "Stemme"))):
            self.field(grid, row, title, self.models[name])
        self.label(page, "Nøkkeltesten henter modellisten. Den genererer ikke innhold og bekrefter\n"
                   "ikke at hele tale-/byggeflyten virker. Bruk av OpenAI kan koste penger.", "Muted.TLabel").pack(anchor="w", pady=12)

    def activity_page(self, page):
        self.label(page, "Snakk med AI eller beskriv en app. B på FIRE starter et nytt opptak og avbryter forrige svar.", "Muted.TLabel").pack(anchor="w")
        row = ttk.Frame(page)
        row.pack(fill="x", pady=9)
        self.session_box = ttk.Combobox(row, textvariable=self.selected_session, state="readonly", width=48)
        self.session_box.pack(side="left", fill="x", expand=True)
        ttk.Button(row, text="Oppdater", command=self.refresh_now).pack(side="left", padx=(8, 0))
        self.new_app_button = ttk.Button(row, text="Ny app", command=self.new_app)
        self.new_app_button.pack(side="left", padx=(8, 0))
        row = ttk.Frame(page)
        row.pack(fill="x", pady=(0, 7))
        ttk.Button(row, text="Kun samtale", command=lambda: self.set_conversation("chat")).pack(side="left")
        ttk.Button(row, text="Lag/endre app", command=lambda: self.set_conversation("develop")).pack(side="left", padx=8)
        ttk.Button(row, text="Avbryt AI-svar", command=self.cancel_conversation).pack(side="left")
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
        self.label(page, "App-pakker og mottatte installasjonskvitteringer", "Heading.TLabel").pack(anchor="w", pady=(0, 12))
        self.label(page, "FIRE lagrer appen på SD-kortet i /apps/<app-ID>/.\n"
                   "Tabellen viser backendens pakker og enhetens siste kvitteringer, ikke en direktelesing av SD-kortet.",
                   "Muted.TLabel", wraplength=800).pack(anchor="w", pady=(0, 12))
        frame = ttk.Frame(page)
        frame.pack(fill="both", expand=True)
        self.apps_table = ttk.Treeview(frame, columns=("name", "version", "device", "status"), show="headings", height=10)
        for name, title, width in (("name", "App", 180), ("version", "Versjon", 75), ("device", "Enhet", 145), ("status", "Siste status", 210)):
            self.apps_table.heading(name, text=title)
            self.apps_table.column(name, width=width, minwidth=60)
        scrollbar = ttk.Scrollbar(frame, orient="vertical", command=self.apps_table.yview)
        self.apps_table.configure(yscrollcommand=scrollbar.set)
        self.apps_table.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")
        self.apps_table.bind("<<TreeviewSelect>>", lambda _: self.render_app_detail())
        self.apps_detail = self.label(page, "Ingen app-pakker ennå. Beskriv appen under Aktivitet eller på FIRE.", wraplength=800)
        self.apps_detail.pack(anchor="w", pady=16)
        actions = ttk.Frame(page)
        actions.pack(anchor="w", pady=(0, 10))
        self.install_button = ttk.Button(actions, text="Installer på FIRE", command=self.install_saved, style="Accent.TButton")
        self.install_button.pack(side="left")
        self.edit_app_button = ttk.Button(actions, text="Endre valgt versjon", command=self.edit_saved)
        self.edit_app_button.pack(side="left", padx=8)
        ttk.Button(actions, text="Reparer valgt app", command=self.repair_saved).pack(side="left", padx=(0,8))
        self.delete_app_button = ttk.Button(actions, text="Slett fra backend …", command=self.delete_saved)
        self.delete_app_button.pack(side="left")
        self.label(page, "Bruker lagret, testet pakke uten ny AI-generering. Appstart krever fortsatt A RUN / Bekreft kjøring.",
                   "Muted.TLabel", wraplength=800).pack(anchor="w")
        self.label(page, "PC-sletting tillates først når tilkoblet FIRE bekrefter at appen er borte.\n"
                   "Velg Ny app / en annen app først hvis denne appen er aktiv i samtalen.", "Muted.TLabel", wraplength=800).pack(anchor="w", pady=5)
        self.apps_rows = {}

    def render_app_detail(self):
        selected = self.apps_table.selection()
        app = self.apps_rows.get(selected[0]) if selected else None
        if app:
            quality_hint = ("Sperret etter feil – bruk Reparer valgt app.\n" if app.get("quality",{}).get("blocked") else
                            "Trenger utvidet test – bruk Reparer valgt app eller bygg ny versjon.\n" if app.get("validation_suite") != "release-v1" else "")
            self.apps_detail.configure(text=f"{app['name']} · {app['version']} · {app['mode']}\n"
                f"SD-mappe: {app['sd_path']}\nPakke: {app['package_id']}\n"
                + quality_hint
                + (app.get("delete_block_reason") or "FIRE har bekreftet at appen er borte; PC-historikken kan slettes."))

    def new_app(self):
        session = self.session()
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

    def edit_saved(self):
        selected = self.apps_table.selection()
        session = self.session()
        app = self.apps_rows.get(selected[0]) if selected else None
        if app and session:
            self.work(lambda: self.runtime.select_app(session["session_id"], "update", project_id=app["project_id"],
                                                      base_package_id=app["package_id"]),
                      done=lambda _: self.show("Aktivitet"), message="Velger app og basisversjon …")

    def delete_saved(self):
        selected = self.apps_table.selection()
        app = self.apps_rows.get(selected[0]) if selected else None
        if not app or not app.get("can_delete_backend") or self.busy:
            return
        count = sum(a["project_id"] == app["project_id"] for a in self.apps_rows.values())
        if messagebox.askyesno("Slett apphistorikk fra PC", f"Slette «{app['name']}» og alle {count} lagrede versjoner fra PC?\n\n"
                              "FIRE har bekreftet at appen er borte. PC-slettingen kan ikke angres.", parent=self.root):
            self.work(lambda: self.runtime.delete_app(app["project_id"]), message="Sletter apphistorikken fra PC …")

    def repair_saved(self):
        selected = self.apps_table.selection()
        session = self.session()
        app = self.apps_rows.get(selected[0]) if selected else None
        if app and session:
            def repair():
                self.runtime.select_app(session["session_id"], "update", project_id=app["project_id"], base_package_id=app["package_id"])
                return self.runtime.send_text(session["session_id"], "Undersøk appen og reparer feilen. Behold funksjonene.")
            self.work(repair, done=lambda _: self.show("Aktivitet"), message="Undersøker valgt app automatisk …")

    def install_saved(self):
        selected = self.apps_table.selection()
        session = self.session()
        if selected and session:
            self.work(lambda: self.runtime.install_saved(session["session_id"], selected[0]),
                      message="Sender valgt app til FIRE for installasjon …")

    def settings_page(self, page):
        grid = ttk.Frame(page)
        grid.pack(fill="x")
        self.field(grid, 0, "Datamappe", self.workspace)
        self.field(grid, 1, "Lagringsgrense (MB)", self.disk)
        ttk.Button(page, text="Velg datamappe …", command=self.choose_workspace).pack(anchor="w", pady=10)
        ttk.Checkbutton(page, text="Aktiver backendens lydtransport", variable=self.audio).pack(anchor="w", pady=8)
        self.label(page, "Enheten må i tillegg annonsere hver lydretning. Nyeste kilde annonserer\n"
                   "mikrofon, men ingen avspilling. Fysisk lydtest gjenstår; tekst virker også.", "Muted.TLabel").pack(anchor="w")
        ttk.Button(page, text="Lagre innstillinger", style="Accent.TButton", command=self.save).pack(anchor="w", pady=18)
        ttk.Button(page, text="Åpne datamappen", command=self.open_workspace).pack(anchor="w", pady=6)
        self.label(page, "Lagring og drift", "Heading.TLabel").pack(anchor="w", pady=(25, 8))
        self.label(page, "Prosjekter, testede Lua-pakker og logger lagres lokalt. Endring av datamappe\n"
                   "flytter ikke tidligere prosjekter. Innstillinger og nøkler huskes ved neste start.\n\n"
                   "Programmet starter backend når du åpner det. Lukk vinduet for å stoppe den.\n"
                   "La PC-en være på og våken mens M5Stack bruker forbindelsen.", wraplength=800).pack(anchor="w")

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
        return f"{session['device_id']}  ·  {session['session_id']}"

    def send_text(self):
        session = self.session()
        text = self.prompt.get("1.0", "end").strip()
        if not session or not text or len(text) > 4000:
            self.notice.set("Velg en tilkoblet FIRE og skriv 1–4000 tegn.")
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
        while not self.closing:
            if self.runtime.ready:
                try:
                    self.queue.put(("snapshot", self.runtime.snapshot()))
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
        sessions = [s for s in self.snapshot["sessions"] if s["target"] == "device" and s.get("online") and ready]
        self.summary_labels["device"].configure(text=f"{len(sessions)} tilkoblet" if sessions else "Venter på FIRE")
        choices = [self.session_name(s) for s in sessions]
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
            for app in apps:
                status = ("Slettet/borte fra FIRE" if app.get("device_presence") in {"deleted", "missing"} else
                          "Sperret etter feil" if app.get("quality",{}).get("blocked") else
                          "Kjører (kvittert)" if app["running"] else "Tidligere kjøring bekreftet" if app["current_healthy"] else
                          "Installert (kvittert)" if app["installed_receipt"] else
                          "Tidligere installert; SD ukjent" if app.get("had_install_receipt") else "Testet på PC; ikke installert")
                self.apps_table.insert("", "end", iid=app["package_id"], values=(app["name"], app["version"], app.get("device_id") or "PC-simulering", status))
            if selected and selected[0] in rows:
                self.apps_table.selection_set(selected[0])
            elif apps:
                self.apps_table.selection_set(apps[-1]["package_id"])
            self.render_app_detail()
        idle_for_text = session and session["state"] not in {"building", "testing", "running", "starting", "stopping", "rollback_pending"}
        selected = self.apps_table.selection()
        app = self.apps_rows.get(selected[0]) if selected else None
        choice_idle = idle_for_text and session["state"] != "processing" and session.get("activity", "idle") == "idle"
        can_install = choice_idle and app and app.get("device_id") == session["device_id"]
        deliverable = app and not app.get("quality",{}).get("blocked") and app.get("validation_suite") == "release-v1"
        self.install_button.configure(state="normal" if can_install and deliverable and not self.busy else "disabled")
        self.edit_app_button.configure(state="normal" if can_install and not self.busy else "disabled")
        self.new_app_button.configure(state="normal" if choice_idle and not self.busy else "disabled")
        self.delete_app_button.configure(state="normal" if ready and app and app.get("can_delete_backend") and not self.busy else "disabled")
        self.send_button.configure(state="normal" if choice_idle and session.get("install_permitted", True) and not self.busy else "disabled")
        self.build_button.configure(state="normal" if session and session.get("install_permitted", True) and session["state"] == "awaiting_build_confirmation" and session.get("proposal_id") and not self.busy else "disabled")
        self.run_button.configure(state="normal" if session and session["state"] == "installed" and session.get("package_id") and not self.busy else "disabled")
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
                "reply_failed": "Lydsvaret feilet; tekstsvaret er beholdt"}.get(audio.get("phase"), "")
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
            history = "\n\n".join(("Du: " if h.get("role") == "user" else "FIRE: ") + str(h.get("content", "")) for h in session.get("history", []))
            progress = session.get("progress", {})
            self.progress["value"] = progress.get("progress", 0)
            self.set_text(self.history, history or "Skriv hva appen skal gjøre. Backend gir et forslag før bygging.")
        else:
            self.pipeline_detail.configure(text="")
            self.session_detail.configure(text="Ingen FIRE tilkoblet ennå. Åpne AI Developer på enheten etter konfigurering.")
            self.set_text(self.history, "Venter på enheten. Tilkoblingsverdiene finner du under M5Stack.")
            self.progress["value"] = 0
        self.set_text(self.logs, self.runtime.logs.text() if self.runtime.logs else "Backend-loggen vises her etter oppstart.")

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
        DesktopUI(root, store)
        root.mainloop()
        lock.close()
    except Exception:
        messagebox.showerror("FIRE Backend", "Programmet kunne ikke åpnes. Det kan allerede kjøre, eller Windows-profilen kan være utilgjengelig.", parent=root)
        root.destroy()


if __name__ == "__main__":
    main()
