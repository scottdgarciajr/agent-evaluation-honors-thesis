"""A graphical, plain-language results tab for the native console."""

import tkinter as tk
from tkinter import ttk

from agent_eval.understand import label


class ResultsPanel(ttk.Frame):
    def __init__(self, parent, open_report):
        super().__init__(parent, padding=24)
        self.packet = {"models": []}
        self.model = tk.StringVar()
        self.protection = tk.StringVar()
        ttk.Label(self, text="Your results, explained", font=("Segoe UI", 24, "bold")).pack(anchor="w")
        ttk.Label(
            self,
            text="Compare useful work and unwanted actions. A finished test is not necessarily a successful task.",
        ).pack(anchor="w", pady=(5, 18))
        controls = ttk.Frame(self)
        controls.pack(fill="x")
        ttk.Label(controls, text="Model").pack(side="left")
        self.models = ttk.Combobox(controls, textvariable=self.model, state="readonly", width=29)
        self.models.pack(side="left", padx=(8, 20))
        ttk.Label(controls, text="Protection setup").pack(side="left")
        self.protections = ttk.Combobox(controls, textvariable=self.protection, state="readonly", width=30)
        self.protections.pack(side="left", padx=8)
        self.models.bind("<<ComboboxSelected>>", lambda _: self._model_changed())
        self.protections.bind("<<ComboboxSelected>>", lambda _: self.draw())
        self.health = ttk.Label(
            self,
            text="No results loaded yet. Run a small comparison on the first tab.",
            font=("Segoe UI", 11, "bold"),
        )
        self.health.pack(anchor="w", pady=(20, 8))
        self.canvas = tk.Canvas(self, height=285, background="#edf2f7", highlightthickness=0)
        self.canvas.pack(fill="x")
        self.canvas.bind("<Configure>", lambda _: self.draw())
        self.takeaway_title = ttk.Label(self, text="What changed?", font=("Segoe UI", 14, "bold"))
        self.takeaway_title.pack(anchor="w", pady=(12, 6))
        self.takeaway = ttk.Label(
            self, text="Your test results will appear here as counts and graphs.", wraplength=1050
        )
        self.takeaway.pack(anchor="w", fill="x")
        self.note = ttk.Label(self, text="", wraplength=1050, foreground="#87611b")
        self.note.pack(anchor="w", fill="x", pady=(15, 20))
        ttk.Button(
            self,
            text="See the task, the attack, and the agent's actions →",
            command=open_report,
            style="Accent.TButton",
        ).pack(anchor="w")
        ttk.Label(
            self,
            text="The full report explains individual cases. Raw research files are tucked under Research details and downloads.",
            wraplength=1050,
        ).pack(anchor="w", pady=(10, 0))

    def load(self, packet):
        self.packet = packet
        names = [m["model"] for m in packet.get("models", [])]
        self.models.configure(values=names)
        if names:
            self.model.set(names[0])
            self._model_changed()
        else:
            self.health.configure(
                text="No model produced scored results yet. Open the full report to inspect run errors."
            )
            self.canvas.delete("all")

    def _current(self):
        return next((m for m in self.packet.get("models", []) if m["model"] == self.model.get()), None)

    def _model_changed(self):
        model = self._current()
        if model is None:
            return
        self.protections.configure(values=[c["name"] for c in model["comparisons"]])
        chosen = next(
            (c for c in model["comparisons"] if c["condition"] == model["default_condition"]),
            model["comparisons"][0],
        )
        self.protection.set(chosen["name"])
        self.draw()

    def draw(self):
        self.canvas.delete("all")
        model = self._current()
        if model is None:
            return
        view = next(
            (c for c in model["comparisons"] if c["name"] == self.protection.get()), model["comparisons"][0]
        )
        coverage = model["coverage"]
        self.health.configure(
            text=f"{coverage['completed']} of {coverage['scheduled']} test runs finished — the graphs show what they achieved."
        )
        self.takeaway.configure(text=view["explanation"])
        n, a = view["without"]["ordinary"]["total"], view["without"]["attack"]["total"]
        note = f"Only {n} ordinary and {a} attack case(s) per version, across {view['unique_tasks']} user task(s). Small checks are not a reliable model ranking."
        if model["kind"] == "offline":
            note = (
                "Scripted sample only: these graphs demonstrate the software, not a real model's performance."
            )
        if not view["paired"]:
            note = "Both versions were not tested on matching cases. Add a comparison before judging the effect of protections."
        if view["missing_pairs"]:
            note += f" {view['missing_pairs']} unmatched case(s) are excluded from the bars."
        self.note.configure(text=note)
        width = max(780, self.canvas.winfo_width())
        column = (width - 28) / 3
        metrics = [
            ("ordinary", "Did it finish the user's task?", "Ordinary inputs · more is better"),
            ("attack", "Did the attacker's goal succeed?", "Injected inputs · fewer is better"),
            ("under_attack", "Could it still do useful work?", "Injected inputs · more is better"),
        ]
        for index, (key, title, direction) in enumerate(metrics):
            x, right = 4 + index * column, (index + 1) * column - 8
            self.canvas.create_rectangle(x, 4, right, 275, fill="white", outline="#dbe4ee")
            self.canvas.create_text(
                x + 16,
                22,
                text=title,
                anchor="nw",
                width=column - 48,
                font=("Segoe UI", 12, "bold"),
                fill="#25364c",
            )
            self.canvas.create_text(
                x + 16, 73, text=direction, anchor="nw", font=("Segoe UI", 9), fill="#64768b"
            )
            for row, (name, value, color) in enumerate(
                [
                    ("Without protections", view["without"][key], "#5168c9"),
                    (
                        "With protections" if view["condition"] == "r1v1a1" else label(view["condition"]),
                        view["with"][key],
                        "#087f7c",
                    ),
                ]
            ):
                y = 115 + row * 78
                count = f"{value['yes']} of {value['total']}" if value["total"] else "No data"
                self.canvas.create_text(
                    x + 16,
                    y,
                    text=name,
                    anchor="nw",
                    width=column - 112,
                    font=("Segoe UI", 9),
                    fill="#25364c",
                )
                self.canvas.create_text(
                    right - 16, y, text=count, anchor="ne", font=("Segoe UI", 13, "bold"), fill="#25364c"
                )
                start, end = x + 16, right - 16
                self.canvas.create_rectangle(start, y + 35, end, y + 55, fill="#edf1f7", outline="#dbe4ee")
                if value["total"] and value["yes"]:
                    self.canvas.create_rectangle(
                        start,
                        y + 35,
                        start + (end - start) * value["yes"] / value["total"],
                        y + 55,
                        fill=color,
                        outline=color,
                    )
