"""One-time local Canada representative configuration, separate from clients."""
import tkinter as tk
from tkinter import ttk, messagebox

from .models import CanadaCase
from .representative_store import default_profile_path, load_profile_into_case, save_profile, PROFILE_FIELDS
from .official_options import REPRESENTATIVE_CATEGORIES


def show_settings(parent):
    case = CanadaCase()
    path = default_profile_path()
    if path.exists():
        try: load_profile_into_case(case,path)
        except (OSError,ValueError) as error:
            messagebox.showerror('Canada representative',str(error),parent=parent)
            return
    win = tk.Toplevel(parent)
    win.title('Canada representative - saved for future cases')
    win.geometry('700x750')
    win.transient(parent)
    ttk.Label(win,text='Enter confirmed representative details once. They will populate new cases.\n'
              'Appointment/cancellation and signatures remain specific to each case.',padding=12).pack(anchor='w')
    frame=ttk.Frame(win)
    frame.pack(fill='both',expand=True)
    canvas=tk.Canvas(frame,highlightthickness=0)
    bar=ttk.Scrollbar(frame,command=canvas.yview)
    canvas.configure(yscrollcommand=bar.set)
    canvas.pack(side='left',fill='both',expand=True)
    bar.pack(side='right',fill='y')
    body=ttk.Frame(canvas,padding=12)
    window=canvas.create_window((0,0),window=body,anchor='nw')
    body.bind('<Configure>',lambda e:canvas.configure(scrollregion=canvas.bbox('all')))
    canvas.bind('<Configure>',lambda e:canvas.itemconfigure(window,width=e.width))
    variables={}
    for key in vars(case.representative):
        if key not in PROFILE_FIELDS: continue
        ttk.Label(body,text=key.replace('_',' ').capitalize()).pack(anchor='w',pady=(8,2))
        var=tk.StringVar(value=getattr(case.representative,key))
        variables[key]=var
        widget=ttk.Combobox(body,textvariable=var,values=('',*REPRESENTATIVE_CATEGORIES),state='readonly') if key=='category' else ttk.Entry(body,textvariable=var)
        widget.pack(fill='x')
    def save():
        for key,var in variables.items(): setattr(case.representative,key,var.get().strip())
        try: save_profile(case.representative,path)
        except (OSError,ValueError) as error:
            messagebox.showerror('Canada representative',str(error),parent=win)
            return
        win.destroy()
    ttk.Button(win,text='Save for future cases',command=save).pack(side='right',padx=12,pady=12)
    ttk.Button(win,text='Cancel',command=win.destroy).pack(side='right',pady=12)
    win.grab_set()
    parent.wait_window(win)
