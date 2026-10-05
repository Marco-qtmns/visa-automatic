"""Modal Canada review editor. Edits are applied only on explicit confirmation."""
import tkinter as tk
from tkinter import ttk, messagebox, simpledialog

from .review import ReviewSession, PARENT_ROLES, editable_fields
from .official_options import choices_for
from .compact_review import QUESTIONS, review_findings
from .preparation import prepare_case, is_confirmed


def show_review(parent, case):
    session = ReviewSession(case)
    prepare_case(session.draft)
    session.values = editable_fields(session.draft)
    win = tk.Toplevel(parent)
    win.title('Canada — review and correct')
    win.geometry('1050x750')
    win.transient(parent)
    win.protocol('WM_DELETE_WINDOW', win.destroy)
    frame = ttk.Frame(win, padding=10)
    frame.pack(fill='both', expand=True)
    ttk.Label(frame, text='Edit fields or add details received by WhatsApp. Apply updates the loaded case.\n'
              'Use Save Canada case in the main window to keep it after closing the app. Cancel discards this draft.').pack(anchor='w')
    tabs = ttk.Notebook(frame)
    tabs.pack(fill='both', expand=True, pady=8)
    compact = ttk.Frame(tabs)
    tabs.add(compact, text='Official questions')
    edit = ttk.Frame(tabs)
    tabs.add(edit, text='Corrections')
    tree_frame = ttk.Frame(edit)
    tree_frame.pack(fill='both', expand=True)
    tree = ttk.Treeview(tree_frame, columns=('value',), selectmode='browse', height=14)
    tree.heading('#0', text='Field / source block')
    tree.heading('value', text='Current draft value')
    tree.column('#0', width=340)
    tree.column('value', width=600)
    scroll = ttk.Scrollbar(tree_frame, orient='vertical', command=tree.yview)
    tree.configure(yscrollcommand=scroll.set)
    tree.pack(side='left', fill='both', expand=True)
    scroll.pack(side='right', fill='y')
    def populate():
        groups = {}
        for path, value in session.values.items():
            group, _, field_label = path.rpartition('.')
            group = group or 'Case'
            if group not in groups:
                title = group.replace('_', ' ').title()
                if group.startswith('family.parents[') or group.startswith('family.children['):
                    name, index = group.split('.')[1].rstrip(']').split('[')
                    member = getattr(session.draft.family, name)[int(index)]
                    title = f'{name.title()} — block {member.source_block_index} ({member.confirmed_role or member.source_role})'
                elif group.startswith('documents['):
                    index = int(group[len('documents['):-1])
                    document = session.draft.documents[index]
                    title = f'{document.source_role.title()} document — {document.category}'
                groups[group] = tree.insert('', 'end', text=title, open=False)
            tree.insert(groups[group], 'end', iid=path, text=field_label.replace('_', ' ').title(), values=(value,))
    populate()
    label = ttk.Label(edit, text='Select a field above')
    label.pack(anchor='w', pady=(8, 0))
    editor = tk.Text(edit, height=4, wrap='word', state='disabled')
    editor.pack(fill='x')
    role = ttk.Combobox(edit, values=PARENT_ROLES, state='readonly')
    active = [None]
    question_vars = {}

    canvas = tk.Canvas(compact, highlightthickness=0)
    qscroll = ttk.Scrollbar(compact, orient='vertical', command=canvas.yview)
    canvas.configure(yscrollcommand=qscroll.set)
    canvas.pack(side='left', fill='both', expand=True)
    qscroll.pack(side='right', fill='y')
    questions = ttk.Frame(canvas, padding=8)
    canvas_window = canvas.create_window((0,0), window=questions, anchor='nw')
    questions.bind('<Configure>', lambda e: canvas.configure(scrollregion=canvas.bbox('all')))
    canvas.bind('<Configure>', lambda e: canvas.itemconfigure(canvas_window, width=e.width))
    ttk.Label(questions, text='Confirm the complete question. Blank means unresolved. Original CSV answers are available in the Original answers tab.', wraplength=850).pack(anchor='w', pady=8)
    for path, prompt in QUESTIONS.items():
        ttk.Label(questions, text=prompt, wraplength=850).pack(anchor='w', pady=(7,2))
        var = tk.StringVar(value=session.values[path])
        question_vars[path] = var
        options = choices_for(path)
        widget = ttk.Combobox(questions, textvariable=var, values=options, state='readonly') if options else ttk.Entry(questions, textvariable=var)
        widget.pack(fill='x')
        def changed(*_, p=path, v=var):
            session.set_value(p,v.get())
            tree.item(p,values=(v.get(),))
            if active[0] == p:
                if choices_for(p) is not None:
                    role.set(v.get())
                elif editor.get('1.0','end-1c') != v.get():
                    editor.delete('1.0','end')
                    editor.insert('1.0',v.get())
        var.trace_add('write', changed)

    def flush():
        path = active[0]
        if path:
            value = role.get() if choices_for(path) is not None else editor.get('1.0', 'end-1c')
            session.set_value(path, value)
            tree.item(path, values=(value,))
            if path in question_vars and question_vars[path].get() != value:
                question_vars[path].set(value)

    def select(_event=None):
        flush()
        selected = tree.selection()
        path = selected[0] if selected and selected[0] in session.values else None
        active[0] = path
        role.pack_forget()
        editor.pack_forget()
        label.configure(text=path or 'Select a field above')
        if path and choices_for(path) is not None:
            role.configure(values=choices_for(path))
            role.set(session.values[path])
            role.pack(fill='x')
        else:
            editor.pack(fill='x')
            editor.configure(state='normal')
            editor.delete('1.0', 'end')
            if path:
                editor.insert('1.0', session.values[path])
            editor.configure(state='normal' if path else 'disabled')

    tree.bind('<<TreeviewSelect>>', select)

    history = ttk.Frame(tabs, padding=8)
    tabs.add(history, text='Residence / travel proposals')
    ttk.Label(history, text='Select a proposal, edit its fields under Corrections, then confirm it here.\n'
              'Only reviewed residence records enter IMM5257; complete structured trips are validated automatically. Editing a confirmed record requires a new confirmation.').pack(anchor='w')
    records_tree = ttk.Treeview(history, columns=('country','period','status'), selectmode='browse', height=10)
    for column, title in (('#0','Record'),('country','Country'),('period','Period'),('status','Review')):
        records_tree.heading(column,text=title)
    records_tree.pack(fill='both',expand=True,pady=8)
    original = tk.Text(history, height=7, wrap='word', state='disabled')
    original.pack(fill='x')

    def refresh_records():
        selected = records_tree.selection()
        for item in records_tree.get_children(): records_tree.delete(item)
        draft = session.preview()
        for kind in ('residence','travel'):
            for i,r in enumerate(getattr(draft,kind+'_records')):
                records_tree.insert('', 'end', iid=f'{kind}:{i}', text=f'{kind.title()} {i+1}',
                    values=(r.country, f'{r.start_date} - {r.end_date}', 'Validated / confirmed' if is_confirmed(r) else 'Needs review'))
        if selected and records_tree.exists(selected[0]): records_tree.selection_set(selected[0])

    def history_selection(_=None):
        selection = records_tree.selection()
        if not selection: return
        kind,index = selection[0].split(':')
        r = getattr(session.preview(),kind+'_records')[int(index)]
        original.configure(state='normal')
        original.delete('1.0','end')
        original.insert('1.0', 'Original source (unchanged):\n'+r.source_text+'\n\nStatus / purpose: '+r.status_or_purpose)
        original.configure(state='disabled')

    def history_action(action):
        selection = records_tree.selection()
        if not selection: return
        kind,index = selection[0].split(':')
        try:
            flush()
            if action == 'confirm': session.confirm_record(kind,int(index))
            elif action == 'edit':
                path=f'{kind}_records[{index}].country'
                tree.selection_set(path)
                tree.see(path)
                tabs.select(edit)
                select()
            else:
                session.remove_record(kind,int(index))
                active[0] = None
                for item in tree.get_children(): tree.delete(item)
                populate()
            refresh_records()
        except ValueError as error:
            messagebox.showerror('History review',str(error),parent=win)
    records_tree.bind('<<TreeviewSelect>>',history_selection)
    row = ttk.Frame(history)
    row.pack(fill='x',pady=8)
    for action,title in (('edit','Edit selected'),('confirm','Confirm selected'),('remove','Remove proposal')):
        ttk.Button(row,text=title,command=lambda a=action:history_action(a)).pack(side='left',padx=4)
    refresh_records()
    def tab_changed(_=None):
        flush()
        refresh_records()
    tabs.bind('<<NotebookTabChanged>>',tab_changed)

    def text_tab(title, content):
        pane = ttk.Frame(tabs)
        tabs.add(pane, text=title)
        text = tk.Text(pane, wrap='word', padx=8, pady=8)
        bar = ttk.Scrollbar(pane, command=text.yview)
        text.configure(yscrollcommand=bar.set)
        text.pack(side='left', fill='both', expand=True)
        bar.pack(side='right', fill='y')
        text.insert('1.0', content)
        text.configure(state='disabled')
        return text

    actions = ttk.Frame(tabs, padding=8)
    tabs.insert(0, actions, text='Required review')
    tabs.select(actions)
    issue_tree = ttk.Treeview(actions, columns=('code','field'), selectmode='browse')
    issue_tree.heading('#0', text='Review / error')
    issue_tree.heading('code', text='Status')
    issue_tree.heading('field', text='Checks')
    issue_tree.pack(fill='both',expand=True)
    issue_details = tk.Text(actions,height=7,wrap='word',state='disabled')
    issue_details.pack(fill='x')
    task_summary=ttk.Label(actions,text='')
    task_summary.pack(anchor='w')
    current_issues = []
    current_tasks = []
    def refresh_actions():
        from .review_tasks import review_tasks
        from .compact_review import QUESTIONS
        from .validation import issue_text
        current_tasks[:] = review_tasks(session.preview())
        from .review_tasks import automated_answers
        task_summary.configure(text=f'{len(current_tasks)} tasks remain. {len(automated_answers(session.preview()))} official answers are supported automatically by the verified intake.')
        current_issues.clear()
        for item in issue_tree.get_children(): issue_tree.delete(item)
        for number,task in enumerate(current_tasks):
            parent_id='task:'+str(number)
            issue_tree.insert('', 'end', iid=parent_id, text=task.title, values=(task.status,len(task.issues)),open=False)
            for issue in task.issues:
                i=len(current_issues);current_issues.append(issue)
                issue_tree.insert(parent_id,'end',iid=str(i),text=QUESTIONS.get(issue.field,issue_text(issue)),values=(issue.status,''))
    def show_issue(_=None):
        selected=issue_tree.selection()
        if not selected: return
        if selected[0].startswith('task:'):
            from .review_tasks import task_text
            task=current_tasks[int(selected[0].split(':')[1])]
            issue_details.configure(state='normal')
            issue_details.delete('1.0','end')
            issue_details.insert('1.0',task_text(task))
            issue_details.configure(state='disabled')
            return
        issue=current_issues[int(selected[0])]
        issue_details.configure(state='normal')
        issue_details.delete('1.0','end')
        issue_details.insert('1.0',f'Status: {issue.status} / {issue.severity}\nSuggestion: {issue.suggested_value or "none"}\n'+
            '\n'.join(f'{k}: {v}' for k,v in issue.source_values.items()))
        issue_details.configure(state='disabled')
    issue_tree.bind('<<TreeviewSelect>>',show_issue)
    def open_task():
        from .review_tasks import task_fields,field_label,task_text
        selected=issue_tree.selection()
        if not selected: return
        flush()
        if selected[0].startswith('task:'):
            task_id=current_tasks[int(selected[0].split(':')[1])].id
        else:
            issue=current_issues[int(selected[0])]
            task_id=next(t.id for t in current_tasks if issue in t.issues)
        task=next((t for t in session.tasks() if t.id==task_id),None)
        if task is None:
            refresh_issues();return
        fields=task_fields(task,session.preview())
        if not fields:
            tabs.select(edit)
            messagebox.showinfo('Review task','Reconcile the source or add the missing records under Corrections. Existing errors remain open.',parent=win)
            return
        dialog=tk.Toplevel(win);dialog.title(task.title);dialog.geometry('850x650');dialog.transient(win)
        outer=ttk.Frame(dialog,padding=10);outer.pack(fill='both',expand=True)
        cv=tk.Canvas(outer,highlightthickness=0);bar=ttk.Scrollbar(outer,orient='vertical',command=cv.yview)
        cv.configure(yscrollcommand=bar.set);cv.pack(side='left',fill='both',expand=True);bar.pack(side='right',fill='y')
        body=ttk.Frame(cv,padding=8);window=cv.create_window((0,0),window=body,anchor='nw')
        body.bind('<Configure>',lambda e:cv.configure(scrollregion=cv.bbox('all')))
        cv.bind('<Configure>',lambda e:cv.itemconfigure(window,width=e.width))
        ttk.Label(body,text=task_text(task),wraplength=730,justify='left').pack(anchor='w',pady=8)
        ttk.Label(body,text='Save updates this review draft. Missing answers remain open. No answer defaults to No.',wraplength=730).pack(anchor='w')
        inputs={}
        confirmed_countries=set()
        for path in fields:
            ttk.Label(body,text=field_label(path),wraplength=730).pack(anchor='w',pady=(8,2))
            options=choices_for(path)
            if options is not None:
                v=tk.StringVar(value=session.values[path]);inputs[path]=v
                ttk.Combobox(body,textvariable=v,values=options,state='readonly').pack(fill='x')
            else:
                v=tk.Text(body,height=3 if path.endswith(('details','explanation','address')) else 1,wrap='word')
                v.insert('1.0',session.values[path]);v.pack(fill='x');inputs[path]=v
        missing_countries=[p for p in fields if p.startswith('activities[') and p.endswith('.country') and not session.values[p].strip()]
        if missing_countries:
            def confirm_brazil():
                for path in missing_countries:
                    inputs[path].delete('1.0','end');inputs[path].insert('1.0','Brazil')
                    confirmed_countries.add(path)
            ttk.Button(body,text='Confirm Brazil for all listed missing activity countries',command=confirm_brazil).pack(anchor='w',pady=8)
        def close_dialog():
            dialog.destroy();win.grab_set()
        def save_task():
            values={p:(v.get() if choices_for(p) is not None else v.get('1.0','end-1c')) for p,v in inputs.items()}
            try: session.resolve_task(task,values,confirmed_paths={p for p in confirmed_countries if values[p]=='Brazil'})
            except ValueError as error:
                messagebox.showerror('Review task',str(error),parent=dialog);return
            active[0]=None
            for item in tree.get_children(): tree.delete(item)
            populate()
            for path,var in question_vars.items(): var.set(session.values[path])
            close_dialog();refresh_issues()
        footer=ttk.Frame(dialog,padding=8);footer.pack(fill='x')
        ttk.Button(footer,text='Save to review draft',command=save_task).pack(side='right')
        ttk.Button(footer,text='Cancel',command=close_dialog).pack(side='right')
        dialog.protocol('WM_DELETE_WINDOW',close_dialog);dialog.grab_set()

    def resolve_selected(confirm):
        selected=issue_tree.selection()
        if not selected: return
        if selected[0].startswith('task:'): return open_task()
        issue=current_issues[int(selected[0])]
        try:
            flush()
            if confirm:
                if issue.code=='HISTORY_CONFIRMATION':
                    kind,index=issue.field.rstrip(']').split('[')
                    session.confirm_record(kind.replace('_records',''),int(index))
                    refresh_issues();return
                if issue.resolution_type=='batch_confirm_or_edit' and not messagebox.askyesno(
                    'Activity countries','Did ALL listed activities take place in Brazil?\nChoose No to enter individual countries.',parent=win):
                    return resolve_selected(False)
                session.resolve_issue(issue,confirm=True)
            else:
                paths=list(issue.source_values) if issue.resolution_type=='batch_confirm_or_edit' else [issue.field]
                if issue.code=='EDUCATION_LOCATION_INCOMPLETE': paths=['education.city','education.state']
                if any(path not in session.values for path in paths):
                    tabs.select(edit)
                    messagebox.showinfo('Review','Edit the indicated record under Corrections, then check the draft again.',parent=win)
                    return
                values={}
                for path in paths:
                    value=simpledialog.askstring('Staff review',path,initialvalue=session.values[path] or issue.suggested_value,parent=win)
                    if value is None: return
                    values[path]=value
                session.resolve_issue(issue,values)
            active[0]=None
            for item in tree.get_children(): tree.delete(item)
            populate()
            for path,var in question_vars.items(): var.set(session.values[path])
            refresh_issues()
        except ValueError as error:
            messagebox.showerror('Review',str(error),parent=win)
    action_buttons=ttk.Frame(actions)
    action_buttons.pack(fill='x')
    ttk.Button(action_buttons,text='Open review task',command=open_task).pack(side='left')
    ttk.Button(action_buttons,text='Confirm suggestion',command=lambda:resolve_selected(True)).pack(side='left')
    ttk.Button(action_buttons,text='Enter / edit values',command=lambda:resolve_selected(False)).pack(side='left')

    issues = text_tab('Technical details', '')
    text_tab('Original answers', '\n\n'.join(
        f'{header} [occurrence {i}]\n{value}'
        for header, answers in case.raw_response.items() for i, value in enumerate(answers, 1)))
    text_tab('Applied corrections', '\n\n'.join(
        f'{c.reviewed_at} — {c.path}\nBefore: {c.previous_value}\nAfter: {c.corrected_value}'
        for c in case.review_changes) or 'No corrections applied yet.')

    def refresh_issues():
        flush()
        draft = session.preview()
        findings = draft.validation_issues()
        refresh_actions()
        refresh_records()
        issues.configure(state='normal')
        issues.delete('1.0', 'end')
        issues.insert('1.0', '\n'.join(findings) or 'No current intake issues. PDF drafts still require a complete review and validation in Acrobat.')
        issues.configure(state='disabled')

    def apply():
        try:
            flush()
            session.apply()
        except ValueError as error:
            messagebox.showerror('Canada review', str(error), parent=win)
            return
        win.destroy()

    def add_record(kind):
        try:
            flush()
            session.add_record(kind)
        except ValueError as error:
            messagebox.showerror('Canada review', str(error), parent=win)
            return
        active[0] = None
        for item in tree.get_children():
            tree.delete(item)
        populate()
        select()
        refresh_records()

    additions = ttk.Frame(frame)
    additions.pack(fill='x', pady=5)
    for kind, title in (('child', 'Add child'), ('activity', 'Add activity'),
                        ('mother', 'Add mother'), ('father', 'Add father'),
                        ('residence', 'Add residence'), ('travel', 'Add trip')):
        ttk.Button(additions, text=title, command=lambda k=kind: add_record(k)).pack(side='left', padx=3)

    buttons = ttk.Frame(frame)
    buttons.pack(fill='x')
    ttk.Button(buttons, text='Check draft', command=lambda: (refresh_issues(), tabs.select(issues.master))).pack(side='left')
    ttk.Button(buttons, text='Cancel', command=win.destroy).pack(side='right')
    ttk.Button(buttons, text='Apply corrections (session)', command=apply).pack(side='right', padx=8)
    refresh_issues()
    win.grab_set()
    parent.wait_window(win)
