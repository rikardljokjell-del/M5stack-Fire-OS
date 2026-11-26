"""Small controls inside the existing Windows app library."""
import copy
import json
import tkinter as tk
from tkinter import ttk,messagebox


def open_window(app):
    selected=app.selected_app()
    if not selected:return
    project=selected['project_id'];prefix='/desktop/apps/'+project+'/evolution'
    window=tk.Toplevel(app.root);window.title('Evolution – '+selected['name']);window.geometry('740x680')
    body=ttk.Frame(window,padding=16);body.pack(fill='both',expand=True)
    state={};proposal={};enabled=tk.BooleanVar();consent=tk.BooleanVar()
    flags={key:tk.BooleanVar() for key in ('generate','repair','optimize','expand','evolve')}
    autonomy=tk.StringVar(value='manual');operation=tk.StringVar(value='repair');goal=tk.StringVar();budget=tk.StringVar(value='.50')
    metric=tk.StringVar(value='max_callback_display_work');note=tk.StringVar();status=tk.StringVar(value='Henter faktisk status …')
    ttk.Label(body,textvariable=status,wraplength=690).pack(anchor='w',pady=6)
    ttk.Checkbutton(body,text='Evolution aktiv for appen',variable=enabled).pack(anchor='w')
    ttk.Checkbutton(body,text='Tillat kildebundet måletelemetri',variable=consent).pack(anchor='w')
    row=ttk.Frame(body);row.pack(fill='x',pady=5)
    for key,label in (('generate','Lag'),('repair','Rett'),('optimize','Optimaliser'),('expand','Utvid'),('evolve','Arbeidsmåte')):
        ttk.Checkbutton(row,text=label,variable=flags[key]).pack(side='left')
    for label,var,choices in (('Selvstendighet',autonomy,('manual','suggest','auto_build','assisted')),
                              ('Oppgave',operation,tuple(flags)),('Målemetode',metric,('max_callback_display_work','app_memory_peak','max_io_calls','max_io_bytes'))):
        ttk.Label(body,text=label).pack(anchor='w');ttk.Combobox(body,textvariable=var,values=choices,state='readonly').pack(fill='x')
    ttk.Label(body,text='Mål for den valgte versjonen').pack(anchor='w');ttk.Entry(body,textvariable=goal).pack(fill='x')
    ttk.Label(body,text='Nominelt mandatbudsjett USD (effektiv håndheving vises over)').pack(anchor='w');ttk.Entry(body,textvariable=budget).pack(fill='x')
    ttk.Label(body,text='Ny eksplisitt brukerpreferanse (valgfritt)').pack(anchor='w');ttk.Entry(body,textvariable=note).pack(fill='x')
    detail=tk.Text(body,height=8,wrap='word');detail.pack(fill='both',expand=True,pady=8)

    def show(value):
        state.update(value);c=value['config'];enabled.set(c['enabled']);consent.set(c['telemetry_consent']);autonomy.set(c['autonomy']);budget.set(str(c['limits']['budget_usd']))
        for key,var in flags.items():var.set(c['flags'][key])
        job=value.get('job') or {};price=job.get('cost',{})
        status.set((job.get('display_text') or 'Ingen aktiv Evolution-jobb')+' · Kostgrenser '+('på' if value['cost_enforcement'] else 'av'))
        detail.delete('1.0','end');detail.insert('1.0',json.dumps({'jobb':job,'historikk':value.get('items',[]),'analyse':value.get('analysis')},ensure_ascii=False,indent=2))

    def refresh():app.work(lambda:app.runtime.request('GET',prefix),done=show,message='Henter Evolution …')
    def accept(value):
        proposal.clear();proposal.update(value)
        if messagebox.askyesno('Bekreft Evolution',json.dumps(value,ensure_ascii=False,indent=2),parent=window):
            app.work(lambda:app.runtime.request('POST',prefix+'/confirm',json={'proposal_id':value['id'],'expected_revision':value['expected_revision']}),done=lambda _:refresh(),message='Lagrer bekreftet valg …')
    def prepare(configure=False):
        if not state:return
        c=copy.deepcopy(state['config']);c.update(enabled=enabled.get(),telemetry_consent=consent.get(),autonomy=autonomy.get(),flags={k:v.get() for k,v in flags.items()})
        c['limits']['budget_usd']=float(budget.get());c['user_preferences']=[note.get()] if note.get().strip() else []
        value=c if configure else {'goal':goal.get(),'base_package_id':selected['package_id'],'autonomy':autonomy.get(),
            **({'metric':metric.get()} if operation.get() in {'optimize','evolve'} else {})}
        app.work(lambda:app.runtime.request('POST',prefix+'/prepare',json={'operation':'configure' if configure else operation.get(),'expected_revision':state['revision'],'value':value}),done=accept,message='Forbereder avgrenset forslag …')
    def control(action):
        app.work(lambda:app.runtime.request('POST',prefix+'/control',json={'action':action,'expected_revision':state['revision'],'job_id':(state.get('job') or {}).get('id')}),done=lambda _:refresh(),message='Oppdaterer eksisterende jobb …')
    row=ttk.Frame(body);row.pack(fill='x')
    ttk.Button(row,text='Bekreft innstillinger',command=lambda:prepare(True)).pack(side='left')
    ttk.Button(row,text='Forbered oppgave',command=prepare).pack(side='left',padx=4)
    ttk.Button(row,text='Hent vanlig byggforslag',command=lambda:app.work(lambda:app.runtime.request('GET',prefix+'/proposal'),done=app.choose_pc_session,message='Åpner gjeldende byggforslag …')).pack(side='left')
    def permissions():
        request=state.get('permission_request')
        if not request:return
        app.work(lambda:app.runtime.request('POST',prefix+'/prepare',json={'operation':request['operation'],
            'expected_revision':state['revision'],'value':request['prepare']}),done=accept,message='Forbereder tillatelsene …')
    ttk.Button(body,text='Vurder foreslåtte tillatelser',command=permissions).pack(anchor='w',pady=4)
    ttk.Button(body,text='Vis sammenligning',command=lambda:app.work(lambda:app.runtime.request('GET',prefix+'?view=compare'),done=show,message='Henter sammenligning …')).pack(anchor='w')
    row=ttk.Frame(body);row.pack(fill='x',pady=6)
    for action,label in (('pause','Pause'),('resume','Fortsett'),('stop','Stopp'),('revoke','Trekk mandat')):ttk.Button(row,text=label,command=lambda a=action:control(a)).pack(side='left',padx=2)
    ttk.Button(row,text='Oppdater status',command=refresh).pack(side='right');refresh()
