"""Desktop inspector; dataset checks run off the Tk event loop."""

from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
from threading import Event
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from .core import ScanCancelled, contract_from, report_dict, scan


class Inspector:
    def __init__(self, root):
        self.root = root
        root.title("Contract Sentinel — local data inspector")
        root.geometry("860x560")
        self.executor = ThreadPoolExecutor(max_workers=1)
        self.cancel_event = Event()
        self.running = False
        self.closed = False
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
        self.cancel_button = ttk.Button(
            toolbar, text="Cancel", command=self.cancel, state="disabled"
        )
        self.cancel_button.pack(side="left", padx=8)
        self.export_button = ttk.Button(
            toolbar, text="Export report", command=self.export, state="disabled"
        )
        self.export_button.pack(side="right")
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
        if self.running:
            return
        selected = filedialog.askopenfilename(filetypes=[("JSON contract", "*.json")])
        if selected:
            self.clear_report()
            self.contract = Path(selected)
            self.status.set("Contract selected; choose dataset, then validate.")

    def choose_data(self):
        if self.running:
            return
        selected = filedialog.askopenfilename(
            filetypes=[("NDJSON", "*.ndjson"), ("All", "*")]
        )
        if selected:
            self.clear_report()
            self.dataset = Path(selected)
            self.status.set("Dataset selected. Ready to validate.")

    def run(self):
        if self.running or self.closed:
            return
        if not self.contract or not self.dataset:
            messagebox.showinfo("Select inputs", "Choose a contract and dataset first.")
            return
        contract_path, dataset = self.contract, self.dataset
        self.running = True
        self.cancel_event.clear()
        self.clear_report()
        self.run_button.configure(state="disabled")
        self.cancel_button.configure(state="normal")
        self.status.set("Validating locally…")
        future = self.executor.submit(
            lambda: scan(
                dataset,
                contract_from(contract_path),
                should_cancel=self.cancel_event.is_set,
            )
        )

        def poll():
            if self.closed:
                return
            if not future.done():
                self.root.after(100, poll)
                return
            self.run_button.configure(state="normal")
            self.cancel_button.configure(state="disabled")
            self.running = False
            try:
                report = future.result()
                # A cancel click can race with a worker that just completed.
                if self.cancel_event.is_set():
                    raise ScanCancelled()
            except ScanCancelled:
                self.status.set("Validation cancelled. No report was produced.")
                return
            except (ValueError, OSError):
                self.status.set(
                    "Validation could not run. Check input formats and permissions."
                )
                return
            self.report = report_dict(report)
            self.export_button.configure(state="normal")
            self.table.delete(*self.table.get_children())
            for finding in report.samples:
                self.table.insert(
                    "",
                    "end",
                    values=(finding["line"], finding["field"], finding["code"]),
                )
            self.status.set(
                f"{'PASS' if report.passed else 'FAIL'} · {report.records} records · "
                f"{report.invalid_records} invalid · truncated={report.truncated} · "
                + (
                    "source changed during scan"
                    if report.input_changed
                    else "fingerprint complete"
                    if report.input_complete
                    else "input incomplete"
                )
            )

        self.root.after(100, poll)

    def cancel(self):
        if self.running:
            self.cancel_event.set()
            self.cancel_button.configure(state="disabled")
            self.status.set("Cancelling validation…")

    def clear_report(self):
        self.report = None
        self.export_button.configure(state="disabled")
        self.table.delete(*self.table.get_children())

    def export(self):
        if self.report is None or self.running:
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
        self.closed = True
        self.cancel_event.set()
        self.executor.shutdown(wait=False, cancel_futures=True)
        self.root.destroy()


def main():
    root = tk.Tk()
    Inspector(root)
    root.mainloop()
