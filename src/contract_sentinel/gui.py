"""Desktop inspector; dataset checks run off the Tk event loop."""

from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from .core import contract_from, report_dict, scan


class Inspector:
    def __init__(self, root):
        self.root = root
        root.title("Contract Sentinel — local data inspector")
        root.geometry("860x560")
        self.executor = ThreadPoolExecutor(max_workers=1)
        self.contract = None
        self.dataset = None
        self.report = None
        self.status = tk.StringVar(
            value="Select a contract and an NDJSON dataset. Data stays local."
        )
        toolbar = ttk.Frame(root, padding=12)
        toolbar.pack(fill="x")
        ttk.Button(toolbar, text="Choose contract", command=self.choose_contract).pack(
            side="left"
        )
        ttk.Button(toolbar, text="Choose dataset", command=self.choose_data).pack(
            side="left", padx=8
        )
        self.run_button = ttk.Button(toolbar, text="Validate", command=self.run)
        self.run_button.pack(side="left")
        ttk.Button(toolbar, text="Export report", command=self.export).pack(
            side="right"
        )
        ttk.Label(root, textvariable=self.status, padding=12, wraplength=800).pack(
            fill="x"
        )
        self.table = ttk.Treeview(
            root, columns=("line", "field", "code"), show="headings"
        )
        for column in ("line", "field", "code"):
            self.table.heading(column, text=column.title())
        self.table.pack(fill="both", expand=True, padx=12, pady=12)
        root.protocol("WM_DELETE_WINDOW", self.close)

    def choose_contract(self):
        selected = filedialog.askopenfilename(filetypes=[("JSON contract", "*.json")])
        if selected:
            self.contract = Path(selected)
            self.status.set("Contract selected; choose dataset, then validate.")

    def choose_data(self):
        selected = filedialog.askopenfilename(
            filetypes=[("NDJSON", "*.ndjson"), ("All", "*")]
        )
        if selected:
            self.dataset = Path(selected)
            self.status.set("Dataset selected. Ready to validate.")

    def run(self):
        if not self.contract or not self.dataset:
            messagebox.showinfo("Select inputs", "Choose a contract and dataset first.")
            return
        contract_path, dataset = self.contract, self.dataset
        self.run_button.configure(state="disabled")
        self.status.set("Validating locally…")
        future = self.executor.submit(
            lambda: scan(dataset, contract_from(contract_path))
        )

        def poll():
            if not future.done():
                self.root.after(100, poll)
                return
            self.run_button.configure(state="normal")
            try:
                report = future.result()
            except (ValueError, OSError):
                self.status.set(
                    "Validation could not run. Check input formats and permissions."
                )
                return
            self.report = report_dict(report)
            self.table.delete(*self.table.get_children())
            for finding in report.samples:
                self.table.insert(
                    "",
                    "end",
                    values=(finding["line"], finding["field"], finding["code"]),
                )
            self.status.set(
                f"{'PASS' if report.passed else 'FAIL'} · {report.records} records · "
                f"{report.invalid_records} invalid · truncated={report.truncated}"
            )

        self.root.after(100, poll)

    def export(self):
        if self.report is None:
            return
        selected = filedialog.asksaveasfilename(defaultextension=".json")
        if selected:
            try:
                Path(selected).write_text(
                    json.dumps(self.report, indent=2), encoding="utf-8"
                )
            except OSError:
                messagebox.showerror(
                    "Export failed", "Cannot write to the selected location."
                )

    def close(self):
        self.executor.shutdown(wait=False, cancel_futures=True)
        self.root.destroy()


def main():
    root = tk.Tk()
    Inspector(root)
    root.mainloop()
