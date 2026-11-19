"""Native desktop evaluation launcher. Credentials live only in this process."""

from __future__ import annotations

import os
import queue
import threading
import tkinter as tk
import webbrowser
from datetime import datetime, timezone
from pathlib import Path
from tkinter import messagebox, ttk

from agent_eval.providers import ModelInfo, discover_ollama, discover_openai, redact_error
from agent_eval.schema import CONDITIONS, ExperimentConfig
from agent_eval.storage import atomic_json, read_json

PROJECT = Path(__file__).resolve().parents[2]
PROFILES = {
    "Quick check": ("configs/quick.json", 4),
    "Pilot": ("configs/pilot.json", 54),
    "Main study": ("configs/main.json", 61236),
}
PROFILE_NAMES = {
    "Quick check": "Try it out — 4 tests per model",
    "Pilot": "Small comparison — 54 tests per model",
    "Main study": "Thesis study — large evaluation",
}
PUBLIC_PREFERENCES = {"provider", "ollama_url", "profile", "prices"}


def save_preferences(path, values):
    atomic_json(path, {key: value for key, value in values.items() if key in PUBLIC_PREFERENCES})


class EvaluationApp:
    def __init__(self, root):
        self.root = root
        self.events = queue.Queue()
        self.stop = threading.Event()
        self.busy = False
        self.discovering = False
        self.inventory = []
        self.checked = set()
        self.model_rows = {}
        self.result_directory = None
        self.preference_path = PROJECT / "output/gui-preferences.json"
        try:
            prefs = read_json(self.preference_path)
        except (OSError, ValueError):
            prefs = {}
        if not isinstance(prefs, dict):
            prefs = {}
        if prefs.get("provider") not in {"ollama", "openai"}:
            prefs["provider"] = "ollama"
        if prefs.get("profile") not in PROFILES:
            prefs["profile"] = "Quick check"
        if not isinstance(prefs.get("prices", {}), dict):
            prefs["prices"] = {}
        self.prices = prefs.get("prices", {})
        self.provider = tk.StringVar(value=prefs.get("provider", "ollama"))
        self.endpoint = tk.StringVar(value=prefs.get("ollama_url", "http://127.0.0.1:11434"))
        self.api_key = tk.StringVar(value=os.getenv("OPENAI_API_KEY", ""))
        self.show_key = tk.BooleanVar(value=False)
        self.profile = tk.StringVar(value=prefs.get("profile", "Quick check"))
        self.profile_display = tk.StringVar(value=PROFILE_NAMES[self.profile.get()])
        self.show_unsupported = tk.BooleanVar(value=False)
        self.show_log = tk.BooleanVar(value=False)
        self.show_server = tk.BooleanVar(value=False)
        self.condition_mode = tk.StringVar(value="Preset")
        self.search = tk.StringVar()
        self.model_name = tk.StringVar()
        self.input_price, self.output_price = tk.StringVar(), tk.StringVar()
        self.budget = tk.StringVar(value="5")
        self.advanced = tk.BooleanVar(value=False)
        self.context = tk.StringVar(value="32768")
        self.output_tokens = tk.StringVar(value="1024")
        self.steps = tk.StringVar(value="8")
        self.timeout = tk.StringVar(value="180")
        self.temperature = tk.StringVar(value="0")
        self.model_temperature = tk.BooleanVar(value=True)
        self.think = tk.StringVar(value="Model default")
        self.episode_cap = tk.StringVar()
        self.connection = tk.StringVar(value="Refresh models to connect.")
        self.plan = tk.StringVar()
        self.status = tk.StringVar(value="Ready. Start with a quick local check.")
        self._build()
        self._provider_changed()
        self.search.trace_add("write", lambda *_: self._render_models())
        self.root.protocol("WM_DELETE_WINDOW", self._close)
        self.root.after(150, self._poll)
        self.root.after(300, self.refresh_models)
        self.root.after(200, self._load_latest_results)

    def _build(self):
        root = self.root
        root.title("Agent Evaluation — Research Console")
        root.geometry("1200x860")
        root.minsize(1020, 740)
        root.configure(background="#edf2f7")
        style = ttk.Style(root)
        style.theme_use("clam")
        style.configure("TFrame", background="#edf2f7")
        style.configure("TLabel", background="#edf2f7", foreground="#203348", font=("Segoe UI", 10))
        style.configure("TLabelframe", background="#edf2f7")
        style.configure("TLabelframe.Label", background="#edf2f7", font=("Segoe UI", 11, "bold"))
        style.configure("TButton", font=("Segoe UI", 10), padding=7)
        style.configure("Accent.TButton", background="#2367a0", foreground="white")
        style.configure("Treeview", rowheight=30, font=("Segoe UI", 10))
        style.configure("Treeview.Heading", font=("Segoe UI", 10, "bold"))
        self.notebook = ttk.Notebook(root)
        self.notebook.pack(fill="both", expand=True, padx=6, pady=6)
        shell = ttk.Frame(self.notebook, padding=22)
        self.notebook.add(shell, text="  1  Set up a test  ")
        from agent_eval.results_gui import ResultsPanel

        self.results_panel = ResultsPanel(self.notebook, self.open_results)
        self.notebook.add(self.results_panel, text="  2  Understand the results  ")
        shell.columnconfigure(0, weight=1)
        shell.rowconfigure(3, weight=1)
        ttk.Label(shell, text="Does your agent stay on task?", font=("Segoe UI", 24, "bold")).grid(
            row=0, column=0, sticky="w"
        )
        ttk.Label(
            shell,
            text="Pick a model. We test it with ordinary inputs and with misleading instructions, then show what the protections changed.",
        ).grid(row=1, column=0, sticky="w", pady=(3, 16))
        connection = ttk.LabelFrame(shell, text="1  Where should the model run?", padding=12)
        connection.grid(row=2, column=0, sticky="ew")
        ttk.Label(connection, text="Provider").grid(row=0, column=0, sticky="w")
        selector = ttk.Combobox(
            connection, textvariable=self.provider, values=("ollama", "openai"), state="readonly", width=13
        )
        selector.grid(row=0, column=1, padx=8)
        selector.bind("<<ComboboxSelected>>", lambda _: self._provider_changed())
        self.provider_selector = selector
        self.endpoint_label = ttk.Label(connection, text="Ollama server")
        self.endpoint_label.grid(row=2, column=2, sticky="w", pady=(8, 0))
        self.endpoint_entry = ttk.Entry(connection, textvariable=self.endpoint, width=38)
        self.endpoint_entry.grid(row=2, column=3, padx=8, sticky="ew", pady=(8, 0))
        self.local_note = ttk.Label(connection, text="On your computer. No OpenAI key needed.")
        self.local_note.grid(row=0, column=2, columnspan=2, sticky="w")
        self.server_toggle = ttk.Checkbutton(
            connection, text="Change server", variable=self.show_server, command=self._connection_visibility
        )
        self.server_toggle.grid(row=0, column=4)
        self.key_label = ttk.Label(connection, text="API key (not saved)")
        self.key_label.grid(row=0, column=2, sticky="w")
        self.key_entry = ttk.Entry(connection, textvariable=self.api_key, show="*", width=38)
        self.key_entry.grid(row=0, column=3, padx=8, sticky="ew")
        self.key_toggle = ttk.Checkbutton(
            connection,
            text="Show",
            variable=self.show_key,
            command=lambda: self.key_entry.configure(show="" if self.show_key.get() else "*"),
        )
        self.key_toggle.grid(row=0, column=4)
        self.refresh = ttk.Button(connection, text="Refresh models", command=self.refresh_models)
        self.refresh.grid(row=0, column=5, padx=(12, 0))
        connection.columnconfigure(3, weight=1)
        ttk.Label(connection, textvariable=self.connection).grid(
            row=1, column=0, columnspan=6, sticky="w", pady=(10, 0)
        )
        middle = ttk.Frame(shell)
        middle.grid(row=3, column=0, sticky="nsew", pady=16)
        middle.columnconfigure(0, weight=3)
        middle.columnconfigure(1, weight=2)
        middle.rowconfigure(0, weight=1)
        models = ttk.LabelFrame(middle, text="2  Which models do you want to compare?", padding=12)
        models.grid(row=0, column=0, sticky="nsew", padx=(0, 14))
        models.columnconfigure(0, weight=1)
        models.rowconfigure(1, weight=1)
        tools = ttk.Frame(models)
        tools.grid(row=0, column=0, sticky="ew", pady=(0, 10))
        ttk.Entry(tools, textvariable=self.search, width=22).pack(side="left", fill="x", expand=True)
        ttk.Button(tools, text="Select all usable models", command=self.select_all).pack(side="left", padx=6)
        ttk.Button(tools, text="Clear", command=self.clear_selection).pack(side="left")
        tree_frame = ttk.Frame(models)
        tree_frame.grid(row=1, column=0, sticky="nsew")
        self.tree = ttk.Treeview(
            tree_frame,
            columns=("use", "name", "support", "size", "input", "output"),
            show="headings",
            height=11,
        )
        for column, label, width in [
            ("use", "Use", 40),
            ("name", "Model", 205),
            ("support", "Can run these tests?", 145),
            ("size", "Download size", 90),
            ("input", "Input $/M", 85),
            ("output", "Output $/M", 85),
        ]:
            self.tree.heading(column, text=label)
            self.tree.column(column, width=width, minwidth=35, stretch=column == "name")
        scroll = ttk.Scrollbar(tree_frame, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=scroll.set)
        self.tree.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")
        self.tree.tag_configure("unsupported", foreground="#8291a0")
        self.tree.bind("<ButtonRelease-1>", self._click_model)
        self.tree.bind("<space>", lambda _: self._toggle(self.tree.focus()))
        self.tree.bind("<Double-1>", lambda event: self._toggle(self.tree.identify_row(event.y)))
        ttk.Checkbutton(
            models,
            text="Show models that cannot use the simulated tools",
            variable=self.show_unsupported,
            command=self._render_models,
        ).grid(row=2, column=0, sticky="w", pady=8)
        manual = ttk.Frame(models)
        self.manual_frame = manual
        manual.grid(row=3, column=0, sticky="ew")
        ttk.Entry(manual, textvariable=self.model_name).pack(side="left", fill="x", expand=True)
        ttk.Button(manual, text="Add model ID", command=self.add_model).pack(side="left", padx=(8, 0))
        self.price_frame = ttk.Frame(models)
        self.price_frame.grid(row=4, column=0, sticky="ew", pady=(10, 0))
        ttk.Label(self.price_frame, text="USD / million tokens").grid(
            row=0, column=0, columnspan=3, sticky="w"
        )
        ttk.Entry(self.price_frame, textvariable=self.input_price, width=10).grid(
            row=1, column=0, padx=(0, 6)
        )
        ttk.Entry(self.price_frame, textvariable=self.output_price, width=10).grid(
            row=1, column=1, padx=(0, 6)
        )
        ttk.Button(self.price_frame, text="Apply prices to checked models", command=self.apply_prices).grid(
            row=1, column=2
        )
        ttk.Label(self.price_frame, text="Input price             Output price").grid(
            row=2, column=0, columnspan=3, sticky="w"
        )
        settings = ttk.LabelFrame(middle, text="3  How much testing?", padding=14)
        settings.grid(row=0, column=1, sticky="nsew")

        def combo(label, variable, values):
            ttk.Label(settings, text=label).pack(anchor="w", pady=(6, 3))
            item = ttk.Combobox(settings, textvariable=variable, values=values, state="readonly")
            item.pack(fill="x")
            item.bind("<<ComboboxSelected>>", lambda _: self._update_plan())

        ttk.Label(settings, text="Start small to see how it works.").pack(anchor="w", pady=(4, 6))
        profile_selector = ttk.Combobox(
            settings,
            textvariable=self.profile_display,
            values=tuple(PROFILE_NAMES.values()),
            state="readonly",
        )
        profile_selector.pack(fill="x")
        profile_selector.bind("<<ComboboxSelected>>", lambda _: self._profile_changed())
        ttk.Label(
            settings,
            text="Ordinary input  →  Did it finish your task?\nMisleading input  →  Did the attacker's goal succeed?",
            wraplength=390,
        ).pack(anchor="w", pady=14)
        self.budget_frame = ttk.Frame(settings)
        self.budget_frame.pack(fill="x", pady=8)
        ttk.Label(self.budget_frame, text="Total batch API budget (USD)").pack(side="left")
        ttk.Entry(self.budget_frame, textvariable=self.budget, width=7).pack(side="right")
        ttk.Label(settings, textvariable=self.plan, wraplength=390, font=("Segoe UI", 10, "bold")).pack(
            anchor="w", pady=10
        )
        ttk.Checkbutton(
            settings,
            text="Research and model settings (optional)",
            variable=self.advanced,
            command=self._advanced_changed,
        ).pack(anchor="w")
        self.advanced_window = tk.Toplevel(root)
        self.advanced_window.title("Advanced evaluation settings")
        self.advanced_window.geometry("520x440")
        self.advanced_window.transient(root)
        self.advanced_window.protocol("WM_DELETE_WINDOW", self.advanced_window.withdraw)
        self.advanced_window.withdraw()
        self.advanced_frame = ttk.Frame(self.advanced_window, padding=18)
        self.advanced_frame.pack(fill="both", expand=True)
        for row, (label, variable) in enumerate(
            [
                ("Context / input budget", self.context),
                ("Max output tokens", self.output_tokens),
                ("Max tool-loop steps", self.steps),
                ("Request timeout (seconds)", self.timeout),
                ("Temperature", self.temperature),
                ("Episode cap per model (blank = preset)", self.episode_cap),
            ]
        ):
            ttk.Label(self.advanced_frame, text=label).grid(row=row, column=0, sticky="w", pady=3)
            ttk.Entry(self.advanced_frame, textvariable=variable, width=8).grid(row=row, column=1, padx=8)
        ttk.Checkbutton(
            self.advanced_frame, text="Use model's default temperature", variable=self.model_temperature
        ).grid(row=6, column=0, columnspan=2, sticky="w")
        ttk.Label(self.advanced_frame, text="Ollama thinking").grid(row=7, column=0, sticky="w")
        ttk.Combobox(
            self.advanced_frame,
            textvariable=self.think,
            values=("Model default", "Off", "On"),
            state="readonly",
            width=14,
        ).grid(row=7, column=1)
        ttk.Label(self.advanced_frame, text="Research comparisons").grid(row=8, column=0, sticky="w", pady=8)
        comparisons = ttk.Combobox(
            self.advanced_frame,
            textvariable=self.condition_mode,
            values=("Preset", "Baseline + full safeguards", "All 9 conditions"),
            state="readonly",
            width=26,
        )
        comparisons.grid(row=8, column=1)
        comparisons.bind("<<ComboboxSelected>>", lambda _: self._update_plan())
        ttk.Button(self.advanced_frame, text="Done", command=self.advanced_window.withdraw).grid(
            row=9, column=1, pady=18
        )
        ttk.Label(
            settings,
            text="A tiny check helps you learn the system.\nUse larger comparisons for research.\nAll actions happen in simulated apps.",
            wraplength=380,
        ).pack(anchor="w", pady=10)
        controls = ttk.Frame(shell)
        controls.grid(row=4, column=0, sticky="ew")
        self.start = ttk.Button(
            controls, text="Start comparison →", style="Accent.TButton", command=self.start_run
        )
        self.start.pack(side="left")
        self.stop_button = ttk.Button(
            controls, text="Stop after current request", command=self.cancel, state="disabled"
        )
        self.stop_button.pack(side="left", padx=8)
        ttk.Button(controls, text="Understand my results", command=self.show_results).pack(side="right")
        ttk.Button(controls, text="Try a sample (no model)", command=self.offline_demo).pack(
            side="right", padx=8
        )
        self.progress_bar = ttk.Progressbar(shell, mode="determinate")
        self.progress_bar.grid(row=5, column=0, sticky="ew", pady=(12, 5))
        ttk.Label(shell, textvariable=self.status).grid(row=6, column=0, sticky="w")
        self.log = tk.Text(
            shell,
            height=6,
            wrap="word",
            font=("Consolas", 9),
            background="white",
            foreground="#203348",
            relief="flat",
        )
        self.log.grid(row=7, column=0, sticky="ew", pady=(10, 0))
        self.log.grid_remove()
        self.log.configure(state="disabled")
        ttk.Checkbutton(
            controls,
            text="Technical log",
            variable=self.show_log,
            command=lambda: self.log.grid() if self.show_log.get() else self.log.grid_remove(),
        ).pack(side="left", padx=8)

    def _connection_visibility(self):
        local = self.provider.get() == "ollama"
        for widget in (self.endpoint_label, self.endpoint_entry):
            widget.grid() if local and self.show_server.get() else widget.grid_remove()
        self.local_note.grid() if local else self.local_note.grid_remove()
        self.server_toggle.grid() if local else self.server_toggle.grid_remove()

    def _profile_changed(self):
        self.profile.set(
            next(key for key, value in PROFILE_NAMES.items() if value == self.profile_display.get())
        )
        self._update_plan()

    def _provider_changed(self):
        if self.busy or self.discovering:
            return
        local = self.provider.get() == "ollama"
        self._connection_visibility()
        for widget in (self.key_label, self.key_entry, self.key_toggle):
            widget.grid_remove() if local else widget.grid()
        self.price_frame.grid_remove() if local else self.price_frame.grid()
        self.manual_frame.grid_remove() if local else self.manual_frame.grid()
        self.budget_frame.pack_forget() if local else self.budget_frame.pack(fill="x", pady=8)
        self.tree.configure(
            displaycolumns=("use", "name", "support") if local else ("use", "name", "input", "output")
        )
        self.inventory, self.checked = [], set()
        self.connection.set(
            "Ollama uses your server; no OpenAI key needed."
            if local
            else "Enter your key and refresh, or add a model ID directly."
        )
        self._render_models()

    def refresh_models(self):
        if self.busy or self.discovering:
            return
        provider, endpoint, key = self.provider.get(), self.endpoint.get(), self.api_key.get().strip()
        if provider == "openai" and not key:
            self.connection.set("Enter an API key to list account models, or add a model ID manually.")
            return
        self.discovering = True
        self.provider_selector.configure(state="disabled")
        self.refresh.configure(state="disabled")
        self.connection.set("Connecting and checking model capabilities…")

        def work():
            try:
                items = discover_ollama(endpoint) if provider == "ollama" else discover_openai(key)
                self.events.put(("models", provider, items))
            except Exception as exc:
                self.events.put(("discovery_error", redact_error(exc, key)))

        threading.Thread(target=work, daemon=True).start()

    def _render_models(self):
        self.tree.delete(*self.tree.get_children())
        self.model_rows = {}
        text = self.search.get().casefold()
        ordered = sorted(
            self.inventory,
            key=lambda model: (model.compatible is False, model.size_bytes or float("inf"), model.name),
        )
        for index, model in enumerate(ordered):
            if text not in model.name.casefold():
                continue
            if model.compatible is False and not self.show_unsupported.get():
                continue
            row = str(index)
            self.model_rows[row] = model
            rates = self.prices.get(model.name, {})
            self.tree.insert(
                "",
                "end",
                iid=row,
                values=(
                    "☑" if model.name in self.checked else "☐",
                    model.name,
                    "Yes" if model.compatible else "Try a small check" if model.compatible is None else "No",
                    f"{model.size_bytes / 1e9:.1f} GB" if model.size_bytes else "—",
                    rates.get("input", "—"),
                    rates.get("output", "—"),
                ),
                tags=("unsupported",) if model.compatible is False else (),
            )
        self._update_plan()

    def _click_model(self, event):
        if self.tree.identify_column(event.x) == "#1":
            self._toggle(self.tree.identify_row(event.y))

    def _toggle(self, row):
        if self.busy or row not in self.model_rows:
            return
        model = self.model_rows[row]
        if model.compatible is False:
            self.connection.set(model.reason)
            return
        self.checked.symmetric_difference_update({model.name})
        self._render_models()

    def select_all(self):
        if not self.busy:
            self.checked.update(
                m.name
                for m in self.inventory
                if m.compatible is True or (m.provider == "openai" and m.compatible is None)
            )
            self._render_models()

    def clear_selection(self):
        if not self.busy:
            self.checked.clear()
            self._render_models()

    def add_model(self):
        name = self.model_name.get().strip()
        if self.busy or not name:
            return
        if self.provider.get() == "ollama":
            self.connection.set(
                "Refresh to select an installed Ollama model. No model downloads are performed."
            )
            return
        if name not in {m.name for m in self.inventory}:
            self.inventory.append(ModelInfo(name=name, provider="openai"))
        self.checked.add(name)
        self.model_name.set("")
        self._render_models()

    def apply_prices(self):
        try:
            rates = {"input": float(self.input_price.get()), "output": float(self.output_price.get())}
            if not self.checked or min(rates.values()) <= 0:
                raise ValueError("Select models and enter positive input and output prices.")
            for name in self.checked:
                self.prices[name] = rates.copy()
            self._render_models()
        except ValueError as exc:
            messagebox.showerror("Token prices", str(exc), parent=self.root)

    def _advanced_changed(self):
        self.advanced_window.deiconify() if self.advanced.get() else self.advanced_window.withdraw()

    def _update_plan(self):
        _, per_model = PROFILES.get(self.profile.get(), PROFILES["Quick check"])
        original = 2 if self.profile.get() == "Quick check" else 9
        count = (
            2
            if self.condition_mode.get() == "Baseline + full safeguards"
            else 9
            if self.condition_mode.get() == "All 9 conditions"
            else original
        )
        per_model = per_model // original * count
        names = sorted(self.checked)
        selection = (
            names[0]
            if len(names) == 1
            else f"{len(names)} models selected"
            if names
            else "Choose a model on the left."
        )
        self.plan.set(
            f"{selection}\n\n{per_model:,} test runs per model · {len(names) * per_model:,} runs in total.\n"
            "A test run is one attempt at a task. The results show separately whether the task or attack succeeded."
        )

    def _configs(self):
        data = read_json(PROFILES[self.profile.get()][0])
        if self.condition_mode.get() != "Preset":
            data["conditions"] = (
                ["r0v0a0", "r1v1a1"] if self.condition_mode.get().startswith("Baseline") else list(CONDITIONS)
            )
        provider = self.provider.get()
        data.update(
            provider=provider,
            temperature=None if self.model_temperature.get() else float(self.temperature.get()),
            ollama_url=self.endpoint.get(),
        )
        if self.advanced.get():
            data.update(
                max_output_tokens=int(self.output_tokens.get()),
                max_steps=int(self.steps.get()),
                request_timeout_seconds=float(self.timeout.get()),
                max_episodes=int(self.episode_cap.get()) if self.episode_cap.get().strip() else None,
            )
        if provider == "ollama":
            context = int(self.context.get())
            output = data.get("max_output_tokens", 2048)
            data.update(
                ollama_context_tokens=context,
                max_input_tokens=context - output - 2048,
                ollama_think={"Model default": None, "Off": False, "On": True}[self.think.get()],
                max_cost_usd=None,
                input_usd_per_million=None,
                output_usd_per_million=None,
            )
        else:
            if self.advanced.get():
                data["max_input_tokens"] = int(self.context.get())
            data["max_cost_usd"] = float(self.budget.get())
            if not self.api_key.get().strip():
                raise ValueError("Enter your OpenAI API key first.")
        configs = []
        for name in sorted(self.checked):
            entry = {**data, "model": name}
            if provider == "openai":
                prices = self.prices.get(name, {})
                if not prices:
                    raise ValueError(f"Enter and apply verified token prices for {name}.")
                entry.update(input_usd_per_million=prices["input"], output_usd_per_million=prices["output"])
            configs.append(ExperimentConfig.model_validate(entry))
        return configs

    def _new_directory(self):
        import uuid

        return (
            PROJECT
            / "runs"
            / ("gui-" + datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%SZ-") + uuid.uuid4().hex[:6])
        )

    def _running(self, state):
        self.busy = state
        self.provider_selector.configure(state="disabled" if state else "readonly")
        self.start.configure(state="disabled" if state else "normal")
        self.refresh.configure(state="disabled" if state else "normal")
        self.stop_button.configure(state="normal" if state else "disabled")

    def start_run(self):
        if self.busy or self.discovering:
            return
        try:
            if not self.checked:
                raise ValueError("Choose at least one compatible model.")
            configs = self._configs()
            save_preferences(
                self.preference_path,
                {
                    "provider": self.provider.get(),
                    "ollama_url": self.endpoint.get(),
                    "profile": self.profile.get(),
                    "prices": self.prices,
                },
            )
        except (ValueError, OSError) as exc:
            messagebox.showerror("Check evaluation settings", str(exc), parent=self.root)
            return
        directory, key = (
            self._new_directory(),
            self.api_key.get().strip() if self.provider.get() == "openai" else None,
        )
        self.stop.clear()
        self._running(True)
        self.status.set("Starting evaluation… first local model load may take some time.")

        def work():
            try:
                from agent_eval.batch import run_batch, set_latest

                record = run_batch(
                    configs,
                    directory,
                    api_key=key,
                    stop_event=self.stop,
                    progress=lambda event: self.events.put(("progress", event)),
                )
                set_latest(directory, PROJECT)
                self.events.put(("finished", directory, record))
            except Exception as exc:
                self.events.put(("run_error", redact_error(exc, key)))

        threading.Thread(target=work, daemon=True).start()

    def offline_demo(self):
        if self.busy:
            return
        directory = self._new_directory()
        self.stop.clear()
        self._running(True)
        self.status.set("Running scripted offline integration scenarios…")

        def work():
            try:
                from agent_eval.analysis import analyze
                from agent_eval.demo import run_demo

                run_demo(directory)
                coverage = analyze(directory)
                relative = (directory / "analysis/report.html").relative_to(PROJECT).as_posix()
                atomic_json(
                    PROJECT / "output/latest-results.json",
                    {"report": relative, "run": directory.relative_to(PROJECT).as_posix(), "mode": "Test"},
                )
                self.events.put(("offline_finished", directory / "analysis/report.html", coverage))
            except Exception as exc:
                self.events.put(("run_error", redact_error(exc)))

        threading.Thread(target=work, daemon=True).start()

    def _append_log(self, text):
        self.log.configure(state="normal")
        self.log.insert("end", text + "\n")
        self.log.see("end")
        self.log.configure(state="disabled")

    def _poll(self):
        try:
            while True:
                event = self.events.get_nowait()
                if event[0] == "models":
                    self.discovering = False
                    self.provider_selector.configure(state="readonly")
                    self.refresh.configure(state="normal")
                    if self.provider.get() != event[1]:
                        self._provider_changed()
                        continue
                    self.inventory = event[2]
                    self.checked.intersection_update(m.name for m in self.inventory)
                    eligible = [m for m in self.inventory if m.compatible is True]
                    if not self.checked and eligible and event[1] == "ollama":
                        self.checked.add(min(eligible, key=lambda m: m.size_bytes or float("inf")).name)
                    self.connection.set(
                        f"Connected. {len(self.inventory)} models found; {len(eligible)} advertise tool calling."
                        if event[1] == "ollama"
                        else f"Connected. {len(self.inventory)} candidate model IDs. Tool support must be verified by a quick check."
                    )
                    self._render_models()
                elif event[0] == "discovery_error":
                    self.discovering = False
                    self.provider_selector.configure(state="readonly")
                    self.refresh.configure(state="normal")
                    self.connection.set("Could not connect. Check the server/key and refresh.")
                    self._append_log(event[1])
                elif event[0] == "progress":
                    item = event[1]
                    if item["stage"] == "model_start":
                        self.progress_bar.configure(value=0)
                        self.status.set(
                            f"Model {item['index']}/{item['models']}: {item['model']} — starting…"
                        )
                    elif item["stage"] == "episode":
                        self.progress_bar.configure(maximum=item["total"], value=item["done"])
                        self.status.set(
                            f"{item['model']} · {item['done']} of {item['total']} test runs finished. "
                            "Task and attack outcomes will appear on the results tab."
                        )
                        self._append_log(
                            f"{item['model']} | {item['task']} | {item['condition']} | {item['attack']} | {item['status']}"
                            + (f" | {item['error']}" if item.get("error") else "")
                        )
                    else:
                        self._append_log(
                            f"{item['model']}: {item['status']}"
                            + (f" — {item['error']}" if item.get("error") else "")
                        )
                elif event[0] in {"finished", "offline_finished"}:
                    self._running(False)
                    self.result_directory = event[1]
                    self.status.set(
                        "Stopped. Available results are saved."
                        if event[2].get("stopped")
                        else "Finished. Click Open results to see the report."
                    )
                    self._append_log(f"Results saved: {event[1]}")
                    self.progress_bar.configure(value=self.progress_bar["maximum"])
                    self._load_latest_results(select=True)
                elif event[0] == "run_error":
                    self._running(False)
                    self.status.set("Run stopped with an error. See the log below.")
                    self._append_log(event[1])
        except queue.Empty:
            pass
        self.root.after(150, self._poll)

    def cancel(self):
        self.stop.set()
        self.status.set("Stop requested. Waiting for the current model request (bounded by its timeout)…")

    def open_results(self):
        try:
            latest = read_json(PROJECT / "output/latest-results.json")
            path = (PROJECT / latest["report"]).resolve()
            if not path.is_file():
                raise ValueError("No report found. Complete an evaluation or offline demo first.")
            webbrowser.open(path.as_uri())
        except (OSError, ValueError) as exc:
            messagebox.showinfo("Results", str(exc), parent=self.root)

    def _load_latest_results(self, select=False):
        try:
            from agent_eval.understand import read_dashboard

            latest = read_json(PROJECT / "output/latest-results.json")
            folder = (PROJECT / latest["report"]).parent
            packet = read_dashboard(folder)
            self.results_panel.load(packet)
            if select:
                self.notebook.select(self.results_panel)
        except (OSError, ValueError, KeyError):
            return

    def show_results(self):
        self._load_latest_results(select=True)
        self.notebook.select(self.results_panel)

    def _close(self):
        if self.busy:
            self.cancel()
            self.status.set("Stopping safely. Close again after the current request finishes.")
            return
        self.api_key.set("")
        self.root.destroy()


def main():
    os.chdir(PROJECT)
    root = tk.Tk()
    try:
        EvaluationApp(root)
    except Exception as exc:
        messagebox.showerror(
            "Research console could not start", redact_error(exc, os.getenv("OPENAI_API_KEY")), parent=root
        )
        root.destroy()
        return
    root.mainloop()


if __name__ == "__main__":
    main()
