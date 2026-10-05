from __future__ import annotations
import os
import re
import subprocess
import sys
from datetime import date
from pathlib import Path
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from models import ApplicantData, RecipientData
from settings import load_settings, save_settings, settings_path
from source_readers import infer_title
from workflows import get_workflow


class ScrollableFrame(ttk.Frame):
    """Vertically scrollable ttk container with mouse-wheel / trackpad support."""
    def __init__(self, parent, *args, **kwargs):
        super().__init__(parent, *args, **kwargs)

        self.canvas = tk.Canvas(self, highlightthickness=0, borderwidth=0)
        self.scrollbar = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview)
        self.content = ttk.Frame(self.canvas)

        self._window_id = self.canvas.create_window((0, 0), window=self.content, anchor="nw")
        self.canvas.configure(yscrollcommand=self.scrollbar.set)

        self.canvas.pack(side="left", fill="both", expand=True)
        self.scrollbar.pack(side="right", fill="y")

        self.content.bind("<Configure>", self._on_content_configure)
        self.canvas.bind("<Configure>", self._on_canvas_configure)

        # Scroll only while the pointer is over this area. Works with macOS
        # trackpads, Windows mouse wheels and common Linux/X11 wheel events.
        self.canvas.bind("<Enter>", self._bind_wheel)
        self.canvas.bind("<Leave>", self._unbind_wheel)
        self.content.bind("<Enter>", self._bind_wheel)
        self.content.bind("<Leave>", self._unbind_wheel)

    def _on_content_configure(self, _event=None):
        self.canvas.configure(scrollregion=self.canvas.bbox("all"))

    def _on_canvas_configure(self, event):
        self.canvas.itemconfigure(self._window_id, width=event.width)

    def _bind_wheel(self, _event=None):
        self.bind_all("<MouseWheel>", self._on_mousewheel)
        self.bind_all("<Button-4>", self._on_linux_up)
        self.bind_all("<Button-5>", self._on_linux_down)

    def _unbind_wheel(self, _event=None):
        self.unbind_all("<MouseWheel>")
        self.unbind_all("<Button-4>")
        self.unbind_all("<Button-5>")

    def _on_mousewheel(self, event):
        # macOS sends small smooth delta values; Windows typically uses ±120.
        if sys.platform == "darwin":
            step = -int(event.delta)
            if step == 0 and event.delta:
                step = -1 if event.delta > 0 else 1
        else:
            step = -int(event.delta / 120) if event.delta else 0
        if step:
            self.canvas.yview_scroll(step, "units")

    def _on_linux_up(self, _event):
        self.canvas.yview_scroll(-1, "units")

    def _on_linux_down(self, _event):
        self.canvas.yview_scroll(1, "units")


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Visa Automatic")
        self.geometry("820x720")
        self.minsize(680, 480)
        self.settings_data = load_settings()
        self.destination = tk.StringVar(value="Australia")
        self.workflow = get_workflow("australia")
        self.applicant = ApplicantData(country=self.settings_data.get("default_client_country", "BRAZIL"))
        self.canada_case = None
        self.source_path = tk.StringVar()
        self.output_dir = tk.StringVar(value=str(Path.home() / "Documents"))
        self.vars = {}
        self._build_ui()
        self._load_applicant_to_ui()

    def _build_ui(self):
        scroll = ScrollableFrame(self)
        scroll.pack(fill="both", expand=True)
        root = ttk.Frame(scroll.content, padding=14)
        root.pack(fill="both", expand=True)

        destination = ttk.LabelFrame(root, text="1. Visa destination", padding=10)
        destination.pack(fill="x")

        destination_box = ttk.Combobox(
            destination,
            textvariable=self.destination,
            state="readonly",
            values=["Australia", "Canada"],
            width=20,
        )
        destination_box.pack(anchor="w")
        destination_box.bind("<<ComboboxSelected>>", self.on_destination_changed)

        src = ttk.LabelFrame(root, text="2. Source", padding=10)
        src.pack(fill="x")
        ttk.Entry(src, textvariable=self.source_path).grid(row=0, column=0, sticky="ew", padx=(0, 8))
        ttk.Button(src, text="Browse...", command=self.choose_source).grid(row=0, column=1)
        ttk.Button(src, text="Read client data", command=self.read_source).grid(row=0, column=2, padx=(8, 0))
        src.columnconfigure(0, weight=1)
        self.source_hint = tk.StringVar(value="Australia: Google Forms/Sheets CSV preferred; completed PDF exports also supported.")
        ttk.Label(src, textvariable=self.source_hint, wraplength=740).grid(row=1, column=0, columnspan=3, sticky="w", pady=(7,0))

        self.australia_panel = ttk.Frame(root)
        self.australia_panel.pack(fill="x")
        self.canada_panel = ttk.LabelFrame(root, text="3. Canada intake", padding=10)
        ttk.Label(self.canada_panel, text="Load a Canada CSV or saved case. Review answers, add staff follow-ups and representative details, then save. PDF drafts require completion and validation in desktop Adobe Acrobat.", wraplength=740).pack(anchor="w")
        ttk.Button(self.canada_panel, text="Review loaded Canada intake", command=self.review_canada).pack(anchor="w", pady=(10, 0))
        ttk.Button(self.canada_panel, text="Save Canada case", command=self.save_canada_case).pack(anchor="w", pady=(5, 0))
        ttk.Button(self.canada_panel, text="Create Canada PDF drafts", command=self.generate).pack(anchor="w", pady=(5, 0))
        ttk.Button(self.canada_panel, text="Load Canada representative profile", command=self.load_canada_representative).pack(anchor="w", pady=(5, 0))
        ttk.Button(self.canada_panel, text="Save Canada representative profile", command=self.save_canada_representative).pack(anchor="w", pady=(5, 0))
        ttk.Button(self.canada_panel, text="Canada representative settings (remember)", command=self.canada_representative_settings).pack(anchor="w", pady=(5, 0))

        info = ttk.LabelFrame(self.australia_panel, text="3. Applicant data - extracted values can be corrected", padding=10)
        info.pack(fill="x", pady=(12,0))
        fields = [
            ("Family name", "family_name"), ("Given names", "given_names"),
            ("Date of birth (DD/MM/YYYY)", "date_of_birth"), ("Residential address", "residential_address"),
            ("City", "city"), ("State", "state"), ("Postcode / CEP", "postcode"),
            ("Country", "country"), ("Mobile", "mobile"), ("Marital status", "marital_status"),
        ]
        for r, (label, key) in enumerate(fields):
            ttk.Label(info, text=label).grid(row=r, column=0, sticky="w", pady=3)
            var = tk.StringVar()
            self.vars[key] = var
            ttk.Entry(info, textvariable=var, width=70).grid(row=r, column=1, sticky="ew", pady=3)
        info.columnconfigure(1, weight=1)

        unresolved = ttk.LabelFrame(self.australia_panel, text="4. Australia 956A-specific data", padding=10)
        unresolved.pack(fill="x", pady=(12,0))
        ttk.Label(unresolved, text="Title").grid(row=0, column=0, sticky="w", pady=3)
        self.vars["title"] = tk.StringVar()
        ttk.Combobox(unresolved, textvariable=self.vars["title"], state="readonly", values=["Mr", "Mrs", "Miss", "Ms", "Other"], width=12).grid(row=0, column=1, sticky="w")
        ttk.Label(unresolved, text="Other title").grid(row=0, column=2, sticky="w", padx=(20,4))
        self.vars["title_other"] = tk.StringVar()
        ttk.Entry(unresolved, textvariable=self.vars["title_other"], width=18).grid(row=0, column=3, sticky="w")

        for r, (label, key) in enumerate([
            ("Home Affairs Client ID (CID), if any", "cid"),
            ("Date lodged (DD/MM/YYYY)", "date_lodged"),
            ("HA Request ID (RID), if known", "rid"),
            ("Transaction Reference Number (TRN), if known", "trn"),
        ], start=1):
            ttk.Label(unresolved, text=label).grid(row=r, column=0, sticky="w", pady=3)
            var = tk.StringVar()
            self.vars[key] = var
            ttk.Entry(unresolved, textvariable=var, width=35).grid(row=r, column=1, columnspan=3, sticky="ew", pady=3)
        unresolved.columnconfigure(3, weight=1)

        rules = ttk.LabelFrame(self.australia_panel, text="Automatic business rules", padding=10)
        rules.pack(fill="x", pady=(12,0))
        ttk.Label(rules, text=(
            "Q1 Appointing | Q2 Visa applicant | Q8 AS ABOVE | Q10 blank | Q11 No | "
            "Q12 Application process / Visitor Visa - Subclass 600 | Q28/Q29 Appointment ticked; signatures remain blank."
        ), wraplength=740).pack(anchor="w")

        out = ttk.LabelFrame(self.australia_panel, text="5. Generate", padding=10)
        out.pack(fill="x", pady=(12,0))
        ttk.Entry(out, textvariable=self.output_dir).grid(row=0, column=0, sticky="ew", padx=(0,8))
        ttk.Button(out, text="Output folder...", command=self.choose_output).grid(row=0, column=1)
        ttk.Button(out, text="Recipient settings...", command=self.open_recipient_settings).grid(row=1, column=0, sticky="w", pady=(10,0))
        ttk.Button(out, text="Generate 956A", command=self.generate).grid(row=1, column=1, sticky="e", pady=(10,0))
        out.columnconfigure(0, weight=1)

        self.status = tk.StringVar(value=f"Settings: {settings_path()} | Enter or review authorised recipient settings.")
        self.status_label = ttk.Label(root, textvariable=self.status, wraplength=760)
        self.status_label.pack(fill="x", pady=(12,0))

    def on_destination_changed(self, _event=None):
        key = self.destination.get().strip().lower()
        self.workflow = get_workflow(key)

        if key == "australia":
            self.canada_panel.pack_forget()
            self.australia_panel.pack(fill="x", before=self.status_label)
            self.source_hint.set("Australia: Google Forms/Sheets CSV preferred; completed PDF exports also supported.")
            self.status.set(
                f"Australia workflow selected. Settings: {settings_path()}"
            )
        else:
            self.australia_panel.pack_forget()
            self.canada_panel.pack(fill="x", pady=(12, 0), before=self.status_label)
            self.source_hint.set("Canada: Google Forms/Sheets CSV or saved .canada-case.json file.")
            self.status.set(
                "Canada workflow selected. Load a Google Forms CSV "
                "to review the Canada intake."
            )

    def choose_source(self):
        filetypes = [("Canada intake / saved case", "*.csv *.canada-case.json"), ("CSV", "*.csv"), ("Canada case", "*.canada-case.json")] if self.workflow.key == "canada" else [("Supported", "*.csv *.pdf"), ("CSV", "*.csv"), ("PDF", "*.pdf")]
        p = filedialog.askopenfilename(filetypes=filetypes)
        if p:
            self.source_path.set(p)

    def choose_output(self):
        p = filedialog.askdirectory(initialdir=self.output_dir.get() or str(Path.home()))
        if p:
            self.output_dir.set(p)

    def read_source(self):
        path = Path(self.source_path.get())
        if not path.exists():
            messagebox.showerror("Source", "Select a valid CSV or PDF first.")
            return

        try:
            default_country = self.settings_data.get(
                "default_client_country",
                "BRAZIL",
            )

            records = self.workflow.read_source(path, default_country)

            if not records:
                raise ValueError("No response rows found.")

            selected = (
                self.select_csv_row(records)
                if len(records) > 1
                else records[0]
            )

            if selected is None:
                return

            if self.workflow.key == "canada":
                self.canada_case = selected
                from canada.representative_store import apply_default_profile
                apply_default_profile(selected)
                self.show_canada_review(selected)

                issues = selected.validation_issues()
                from canada.review_tasks import review_tasks
                tasks = review_tasks(selected)

                if issues:
                    self.status.set(
                        f"Canada intake loaded: {path.name}. "
                        f"{len(tasks)} review task(s), covering {len(issues)} validation issue(s)."
                    )
                else:
                    self.status.set(
                        f"Canada intake loaded: {path.name}. "
                        "No validation issues found."
                    )

                return

            # Australia
            self.applicant = selected
            self.applicant.date_lodged = date.today().strftime("%d/%m/%Y")

            if not self.applicant.title:
                self.applicant.title = infer_title(
                    self.applicant.sex,
                    self.applicant.marital_status,
                )

            self._load_applicant_to_ui()

            issues = self.workflow.validation_issues(self.applicant)

            if issues:
                self.status.set(
                    f"Loaded: {path.name}. "
                    f"{len(issues)} field(s) need review."
                )

                messagebox.showwarning(
                    "Australia intake needs review",
                    "Please review these fields before generating:\n\n"
                    + "\n".join(f"• {issue}" for issue in issues),
                )
            else:
                self.status.set(
                    f"Loaded: {path.name}. "
                    "Review extracted values before generating."
                )

            if not any(
                (
                    self.applicant.family_name,
                    self.applicant.given_names,
                    self.applicant.date_of_birth,
                    self.applicant.residential_address,
                )
            ):
                messagebox.showwarning(
                    "No client answers found",
                    "This appears to be a blank form or an unsupported "
                    "response export. Use a completed CSV/PDF response "
                    "or enter the client data manually.",
                )

        except Exception as e:
            messagebox.showerror("Read failed", str(e))

    def select_csv_row(self, records):
        win = tk.Toplevel(self)
        win.title("Select client")
        win.geometry("600x420")

        ttk.Label(
            win,
            text="The CSV contains multiple responses. Select one:",
            padding=10,
        ).pack(anchor="w")

        lb = tk.Listbox(win)
        lb.pack(fill="both", expand=True, padx=10)

        for i, record in enumerate(records):
            if self.workflow.key == "canada":
                name = record.display_name()
                dob = record.identity.date_of_birth or "-"
                email = record.contact.email or record.source_email or "-"
                label = f"{i + 1}. {name} | DOB {dob} | {email}"
            else:
                label = (
                    f"{i + 1}. "
                    f"{record.family_name}, {record.given_names} | "
                    f"DOB {record.date_of_birth} | "
                    f"{record.source_email}"
                )

            lb.insert("end", label)

        result = {"value": None}

        def choose():
            sel = lb.curselection()
            if sel:
                result["value"] = records[sel[0]]
                win.destroy()

        ttk.Button(
            win,
            text="Select",
            command=choose,
        ).pack(pady=10)

        win.transient(self)
        win.grab_set()
        self.wait_window(win)

        return result["value"]

    def review_canada(self):
        if self.canada_case is None:
            messagebox.showinfo("Canada", "Load a Canada CSV response first.")
            return
        self.show_canada_review(self.canada_case)

    def show_canada_review(self, case):
        from canada.review_ui import show_review
        show_review(self, case)
        from canada.review_tasks import review_tasks
        self.status.set(
            f"Canada review: {len(review_tasks(case))} task(s), covering {len(case.validation_issues())} validation issue(s). "
            "Use Save Canada case to keep corrections."
        )

    def save_canada_case(self):
        if self.canada_case is None:
            messagebox.showinfo("Canada", "Load a Canada case first.")
            return
        path = filedialog.asksaveasfilename(
            title="Save Canada case", defaultextension=".canada-case.json",
            initialfile="case.canada-case.json", filetypes=[("Canada case", "*.canada-case.json")],
        )
        if not path:
            return
        from canada.case_store import save_case
        try:
            save_case(self.canada_case, path)
        except (OSError, ValueError) as error:
            messagebox.showerror("Canada case", str(error))
            return
        self.status.set(f"Canada case saved: {Path(path).name}")

    def load_canada_representative(self):
        if self.canada_case is None:
            messagebox.showinfo('Canada', 'Load a Canada case first.')
            return
        path = filedialog.askopenfilename(title='Load Canada representative profile',
                    filetypes=[('Canada representative profile', '*.canada-representative.json')])
        if not path:
            return
        from canada.representative_store import load_profile_into_case
        try:
            load_profile_into_case(self.canada_case,path)
        except (OSError,ValueError) as error:
            messagebox.showerror('Canada representative',str(error))
            return
        self.status.set('Canada representative profile loaded. Review the case-specific action and save the case.')
        self.show_canada_review(self.canada_case)

    def canada_representative_settings(self):
        from canada.representative_ui import show_settings
        from canada.representative_store import apply_default_profile
        show_settings(self)
        if self.canada_case is not None:
            apply_default_profile(self.canada_case)
        self.status.set('Canada representative settings are remembered for new cases. Review the action for each case.')

    def save_canada_representative(self):
        if self.canada_case is None:
            messagebox.showinfo('Canada', 'Load a Canada case first.')
            return
        path = filedialog.asksaveasfilename(title='Save reusable Canada representative details',
                    defaultextension='.canada-representative.json',
                    initialfile='representative.canada-representative.json',
                    filetypes=[('Canada representative profile','*.canada-representative.json')])
        if not path:
            return
        from canada.representative_store import save_profile
        try:
            save_profile(self.canada_case.representative,path)
        except (OSError,ValueError) as error:
            messagebox.showerror('Canada representative',str(error))
            return
        self.status.set('Representative profile saved. Case-specific actions and cancelled representatives are excluded.')

    def _load_applicant_to_ui(self):
        for key in ["family_name","given_names","date_of_birth","residential_address","city","state","postcode","country","mobile","marital_status","title","title_other","cid","date_lodged","rid","trn"]:
            if key in self.vars:
                self.vars[key].set(getattr(self.applicant, key, ""))

    def _ui_to_applicant(self):
        for key, var in self.vars.items():
            if hasattr(self.applicant, key):
                setattr(self.applicant, key, var.get().strip())

    def open_recipient_settings(self):
        SettingsDialog(self, self.settings_data, self._settings_saved)

    def _settings_saved(self, data):
        self.settings_data = data
        self.status.set(f"Recipient settings saved: {settings_path()}")

    def generate(self):
        if self.workflow.key == "canada":
            case = getattr(self, "canada_case", None)

            if case is None:
                messagebox.showinfo(
                    "Canada",
                    "Load a Canada CSV response first.",
                )
                return

            parent = filedialog.askdirectory(title="Choose a folder for a NEW Canada draft bundle")
            if not parent:
                return
            from datetime import datetime
            folder = Path(parent) / ("canada-drafts-" + datetime.now().strftime('%Y%m%d-%H%M%S-%f'))
            try:
                report = self.workflow.generate(case, folder)
            except (OSError, ValueError, RuntimeError) as error:
                messagebox.showerror("Canada drafts", str(error))
                return
            self.status.set(f"Canada drafts created: {folder}")
            messagebox.showinfo("Canada drafts — review required",
                f"Created IMM5257, IMM5707 and IMM5476 drafts in:\n{folder}\n\n"
                f"{len(report['populated_fields_not_exported'])} populated fields require separate review. "
                "See review-report.json. Open the PDFs in desktop Adobe Acrobat; "
                "complete remaining fields, validate and sign manually. These drafts are not ready for submission.")
            return

        # Australia
        self._ui_to_applicant()

        rec = RecipientData(
            **self.settings_data.get("recipient", {})
        )

        folder = Path(self.output_dir.get())
        out = folder / "956A.pdf"

        try:
            self.workflow.generate(
                self.applicant,
                rec,
                out,
            )
        except Exception as e:
            messagebox.showerror(
                "Cannot generate",
                str(e),
            )
            return

        self.status.set(f"Created: {out}")

        if messagebox.askyesno(
            "956A created",
            f"Created:\n{out}\n\nOpen it now?",
        ):
            open_file(out)


def open_file(path: Path):
    if sys.platform.startswith("win"):
        os.startfile(str(path))
    elif sys.platform == "darwin":
        subprocess.Popen(["open", str(path)])
    else:
        subprocess.Popen(["xdg-open", str(path)])


class SettingsDialog(tk.Toplevel):
    def __init__(self, parent, data, on_saved):
        super().__init__(parent)
        self.title("Authorised recipient settings")
        self.geometry("650x640")
        self.transient(parent)
        self.data = data
        self.on_saved = on_saved
        self.vars = {}
        scroll = ScrollableFrame(self)
        scroll.pack(fill="both", expand=True)
        frame = ttk.Frame(scroll.content, padding=14); frame.pack(fill="both", expand=True)
        ttk.Label(frame, text="These Q14-Q19 values are stored once on this computer and inserted into every generated 956A.", wraplength=610).pack(anchor="w", pady=(0,10))
        form = ttk.Frame(frame); form.pack(fill="x")
        fields = [
            ("Title (Mr/Mrs/Miss/Ms/Other)", "title"), ("Other title", "title_other"),
            ("Family name", "family_name"), ("Given names", "given_names"),
            ("Date of birth (DD/MM/YYYY)", "date_of_birth"), ("Address line 1", "address_line1"),
            ("Address line 2", "address_line2"), ("Address line 3", "address_line3"), ("Postcode", "postcode"),
            ("Office country code", "office_country_code"), ("Office area code", "office_area_code"),
            ("Office number", "office_number"), ("Mobile", "mobile"), ("Email", "email"),
        ]
        rec = dict(data.get("recipient", {}))
        if not str(rec.get("address_line3", "")).strip() and str(rec.get("country", "")).strip():
            rec["address_line3"] = rec.get("country", "")
        for r,(label,key) in enumerate(fields):
            ttk.Label(form,text=label).grid(row=r,column=0,sticky="w",pady=3)
            v=tk.StringVar(value=str(rec.get(key,""))); self.vars[key]=v
            if key == "title":
                ttk.Combobox(form,textvariable=v,state="readonly",values=["Mr","Mrs","Miss","Ms","Other"],width=28).grid(row=r,column=1,sticky="ew",pady=3)
            else:
                ttk.Entry(form,textvariable=v,width=42).grid(row=r,column=1,sticky="ew",pady=3)
        form.columnconfigure(1,weight=1)
        ttk.Label(frame,text="Default client country (used by PDF-export input when country is not machine-readable):").pack(anchor="w",pady=(12,3))
        self.default_country=tk.StringVar(value=data.get("default_client_country","BRAZIL"))
        ttk.Entry(frame,textvariable=self.default_country).pack(fill="x")
        ttk.Button(frame,text="Save",command=self.save).pack(anchor="e",pady=(16,0))
        self.grab_set()

    def save(self):
        self.data["recipient"]={k:v.get().strip() for k,v in self.vars.items()}
        self.data["default_client_country"]=self.default_country.get().strip() or "BRAZIL"
        save_settings(self.data)
        self.on_saved(self.data)
        self.destroy()


if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] == "--self-test":
        from release_self_test import run
        raise SystemExit(run(sys.argv[2], App))
    App().mainloop()
