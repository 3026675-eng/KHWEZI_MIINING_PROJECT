from pathlib import Path
from io import BytesIO
from datetime import date, datetime
from functools import wraps
import os
import pandas as pd
from flask import Flask, render_template, request, redirect, url_for, session, flash, Response
from markupsafe import Markup, escape
from werkzeug.security import generate_password_hash, check_password_hash

ROOT = Path(__file__).resolve().parent
DATA = ROOT / 'data'
DATA.mkdir(exist_ok=True)
FLASK_FOLDER = ROOT.parent / 'flask'
app = Flask(__name__, template_folder=str(FLASK_FOLDER / 'templates'), static_folder=str(FLASK_FOLDER / 'static'))
app.secret_key = os.environ.get('FLASK_SECRET_KEY') or os.urandom(24).hex()

ROLES = ['Administrator', 'Safety Officer', 'Mining Engineer', 'Maintenance Engineer', 'Manager']
PERMISSIONS = {
    'dashboard': ROLES,
    'workers': ['Administrator', 'Safety Officer', 'Mining Engineer', 'Manager'],
    'incidents': ['Administrator', 'Safety Officer', 'Mining Engineer', 'Manager'],
    'equipment': ['Administrator', 'Mining Engineer', 'Maintenance Engineer', 'Manager'],
    'maintenance': ['Administrator', 'Mining Engineer', 'Maintenance Engineer', 'Manager'],
    'risk': ['Administrator', 'Safety Officer', 'Mining Engineer', 'Manager'],
    'alerts': ROLES,
    'analysis': ROLES,
    'reports': ROLES,
    'users': ['Administrator']
}

REQUIRED_COLUMNS = {
    'workers': ['worker_id', 'department', 'job_role', 'shift', 'ppe_compliant',
                'training_status', 'fatigue_level', 'safety_observations',
                'near_misses', 'previous_incidents', 'likelihood', 'consequence'],
    'incidents': ['incident_id', 'date', 'time', 'shift', 'location', 'department',
                  'incident_type', 'severity', 'injury_status', 'lost_time_injury',
                  'cause', 'corrective_action', 'status'],
    'equipment': ['equipment_id', 'equipment_type', 'manufacturer', 'department',
                  'operating_hours', 'temperature', 'vibration', 'fuel_consumption',
                  'brake_status', 'tyre_status', 'engine_status', 'maintenance_status',
                  'uptime_hours', 'downtime_hours', 'last_service_date',
                  'next_service_due', 'alerts_30d'],
    'users': ['username', 'full_name', 'role', 'password_hash', 'active']
}

def read_data(name):
    if name not in REQUIRED_COLUMNS:
        raise ValueError('Unknown data file.')
    file = DATA / (name + '.csv')
    if not file.exists():
        raise ValueError(name + '.csv was not found.')
    try:
        table = pd.read_csv(file, dtype=str, keep_default_na=False)
    except pd.errors.EmptyDataError:
        raise ValueError(name + '.csv needs a header row.')
    missing = []
    for col in REQUIRED_COLUMNS[name]:
        if col not in table.columns:
            missing.append(col)
    if missing:
        raise ValueError(name + '.csv is missing: ' + ', '.join(missing))
    return table

def save_data(name, table):
    table.to_csv(DATA / (name + '.csv'), index=False)

def setup_users():
    file = DATA / 'users.csv'
    if not file.exists():
        rows = []
        for username, role, password in [
            ('admin', 'Administrator', 'Admin@123'),
            ('safety', 'Safety Officer', 'Safety@123'),
            ('engineer', 'Mining Engineer', 'Mining@123'),
            ('maint', 'Maintenance Engineer', 'Maint@123'),
            ('manager', 'Manager', 'Manager@123')
        ]:
            rows.append({'username': username, 'full_name': role, 'role': role,
                         'password_hash': generate_password_hash(password), 'active': 'Yes'})
        save_data('users', pd.DataFrame(rows))
setup_users()

def allowed(section):
    return session.get('role') in PERMISSIONS[section]

def login_required(section):
    def decorator(function):
        @wraps(function)
        def check(*args, **kwargs):
            if 'username' not in session:
                return redirect(url_for('login'))
            if not allowed(section):
                flash('You do not have permission to open this page.')
                return redirect(url_for('dashboard'))
            return function(*args, **kwargs)
        return check
    return decorator

def graph(data, kind='bar'):
    if not data:
        return Markup('<p class="muted">No data for this selection.</p>')
    entries = list(data.items())[:15]
    if kind == 'list':
        return Markup('<ol>' + ''.join('<li>' + str(escape(k)) + '</li>' for k, _ in entries) + '</ol>')
    if kind == 'donut':
        colours = ['#f9a02b', '#3777b8', '#43a990', '#a374cb', '#d56c73', '#b6ca51']
        total = sum(max(float(value), 0) for _, value in entries) or 1
        slices = []
        legend = []
        current = 0
        for n, (label, value) in enumerate(entries):
            end = current + max(float(value), 0) / total * 100
            colour = colours[n % len(colours)]
            slices.append(f'{colour} {current:.2f}% {end:.2f}%')
            legend.append(f'<div class="donut-item"><span class="dot" style="background:{colour}"></span>{escape(str(label))}: {float(value):g}</div>')
            current = end
        return Markup('<div class="donut-wrap"><div class="donut" role="img" aria-label="Distribution chart" style="background:conic-gradient(' + ','.join(slices) + ')"></div><div class="donut-list">' + ''.join(legend) + '</div></div>')
    if kind == 'line':
        values = [float(v) for _, v in entries]
        highest = max(values + [1])
        width, height = 550, 200
        points = [(35 + n * 480 / max(len(values)-1, 1), 175 - v / highest * 145) for n, v in enumerate(values)]
        coords = ' '.join(f'{x:.1f},{y:.1f}' for x, y in points)
        dots = ''.join(f'<circle class="point" cx="{x:.1f}" cy="{y:.1f}" r="4"><title>{escape(str(entries[n][0]))}: {values[n]:g}</title></circle>' for n,(x,y) in enumerate(points))
        labels = ''.join(f'<text class="axis" x="{x:.1f}" y="193" text-anchor="middle">{escape(str(entries[n][0]))}</text>' for n,(x,y) in enumerate(points) if n % max(1,len(points)//6) == 0)
        return Markup(f'<svg class="chart-line" viewBox="0 0 {width} {height}" role="img" aria-label="Monthly trend"><polyline class="trend" points="{coords}"/>{dots}{labels}</svg>')
    peak = max([float(v) for _, v in entries] + [1])
    bars = []
    for label, value in entries:
        amount = max(float(value), 0)
        bars.append(f'<div class="chart-row"><span>{escape(str(label))}</span><div class="bar-track"><div class="bar-fill" style="width:{amount / peak * 100:.1f}%"></div></div><b>{amount:g}</b></div>')
    return Markup(''.join(bars))

@app.context_processor
def menu_settings():
    return {'permissions': PERMISSIONS, 'allowed': allowed, 'choices': CHOICES, 'number_fields': NUMBER_FIELDS, 'date_fields': DATE_FIELDS, 'graph': graph}

@app.errorhandler(ValueError)
def data_error(error):
    return render_template('error.html', message=str(error)), 400

@app.route('/', methods=['GET', 'POST'])
def login():
    if request.method == 'GET':
        session.clear()
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')
        users = read_data('users')
        matching = users[users['username'] == username]
        if not matching.empty:
            user = matching.iloc[0]
            if str(user['active']) == 'Yes' and check_password_hash(user['password_hash'], password):
                session.clear()
                session['username'] = username
                session['name'] = user['full_name']
                session['role'] = user['role']
                return redirect(url_for('dashboard'))
        flash('Incorrect username or password.')
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

def worker_data():
    workers = read_data('workers')
    for column in ['likelihood', 'consequence', 'fatigue_level', 'near_misses', 'previous_incidents']:
        try:
            workers[column] = pd.to_numeric(workers[column], errors='raise')
        except ValueError:
            raise ValueError('Invalid value in workers.csv: ' + column)
    workers['risk_score'] = workers['likelihood'] * workers['consequence']
    workers['risk_level'] = workers['risk_score'].apply(risk_level)
    return workers

def risk_level(score):
    if score <= 4:
        return 'Low'
    if score <= 9:
        return 'Medium'
    if score <= 16:
        return 'High'
    return 'Critical'

def equipment_data():
    equipment = read_data('equipment')
    for column in ['temperature', 'vibration', 'uptime_hours', 'downtime_hours', 'alerts_30d']:
        try:
            equipment[column] = pd.to_numeric(equipment[column], errors='raise')
        except ValueError:
            raise ValueError('Invalid value in equipment.csv: ' + column)
    total = equipment['uptime_hours'] + equipment['downtime_hours']
    equipment['availability'] = (equipment['uptime_hours'] / total.where(total != 0, 1) * 100).round(1)
    equipment['temperature_status'] = 'NORMAL'
    equipment['vibration_status'] = 'NORMAL'
    equipment.loc[equipment['temperature'] >= 80, 'temperature_status'] = 'WARNING'
    equipment.loc[equipment['temperature'] > 100, 'temperature_status'] = 'CRITICAL'
    equipment.loc[equipment['vibration'] >= 5, 'vibration_status'] = 'WARNING'
    equipment.loc[equipment['vibration'] > 8, 'vibration_status'] = 'CRITICAL'
    equipment['condition'] = 'NORMAL'
    messages = []
    for index, row in equipment.iterrows():
        findings = []
        statuses = [row['temperature_status'], row['vibration_status']]
        if row['temperature_status'] != 'NORMAL':
            findings.append('Temperature: ' + row['temperature_status'])
        if row['vibration_status'] != 'NORMAL':
            findings.append('Vibration: ' + row['vibration_status'])
        for part in ['brake_status', 'tyre_status', 'engine_status']:
            if row[part] == 'Fault':
                statuses.append('CRITICAL')
                findings.append(part.replace('_status','').title() + ': Fault')
            elif row[part] == 'Worn':
                statuses.append('WARNING')
                findings.append(part.replace('_status','').title() + ': Worn')
        equipment.at[index, 'condition'] = ('CRITICAL' if 'CRITICAL' in statuses else
                                            'WARNING' if 'WARNING' in statuses else 'NORMAL')
        cond = equipment.at[index, 'condition']
        if cond == 'NORMAL':
            messages.append('NORMAL: Equipment operating within defined monitoring limits.')
        elif cond == 'WARNING':
            messages.append('WARNING: ' + '; '.join(findings) + ' approaching predefined threshold.')
        else:
            messages.append('CRITICAL: ' + '; '.join(findings) + ' exceeds predefined threshold. Inspection required')
    equipment['condition_message'] = messages
    today = pd.Timestamp.today().normalize()
    due = pd.to_datetime(equipment['next_service_due'], errors='coerce')
    equipment['maintenance_check'] = 'OK'
    equipment.loc[due.isna(), 'maintenance_check'] = 'Date Missing'
    equipment.loc[due < today, 'maintenance_check'] = 'Overdue'
    equipment.loc[(due >= today) & (due <= today + pd.Timedelta(days=14)), 'maintenance_check'] = 'Due Soon'
    equipment.loc[equipment['maintenance_status'] == 'Under Maintenance', 'maintenance_check'] = 'Under Maintenance'
    return equipment

def make_alerts(workers, incidents, equipment):
    alerts = []
    if len(workers):
        ppe_rate = (workers['ppe_compliant'] == 'Yes').mean() * 100
        if ppe_rate < 90:
            alerts.append(['WARNING', 'Worker Safety', 'All workers', 'PPE compliance', f'{ppe_rate:.1f}%',
                           'Low PPE compliance (below 90%)', 'Run PPE checks before each shift.'])
    for _, w in workers.iterrows():
        if w['ppe_compliant'] != 'Yes':
            alerts.append(['WARNING', 'Worker Safety', w['worker_id'], 'PPE', 'No', 'PPE not compliant', 'Provide required PPE before work.'])
        if w['training_status'] == 'Expired':
            alerts.append(['WARNING', 'Worker Safety', w['worker_id'], 'Training', 'Expired', 'Safety training expired', 'Arrange refresher training.'])
        if w['fatigue_level'] >= 7:
            level = 'CRITICAL' if w['fatigue_level'] >= 9 else 'WARNING'
            alerts.append([level, 'Worker Safety', w['worker_id'], 'Fatigue', str(w['fatigue_level']), 'High fatigue', 'Review fitness for duty and rest periods.'])
        if w['risk_level'] in ['High', 'Critical']:
            alerts.append(['CRITICAL' if w['risk_level'] == 'Critical' else 'WARNING', 'Risk', w['worker_id'], 'Risk score', str(w['risk_score']), 'High-risk safety observation', 'Review risk controls.'])
    for _, i in incidents.iterrows():
        if i['severity'] == 'Critical' and i['status'] != 'Closed':
            alerts.append(['CRITICAL', 'Incident', i['incident_id'], 'Severity', 'Critical', 'Open critical incident', 'Investigate and implement corrective action.'])
    for _, e in equipment.iterrows():
        for parameter, reading, status, unit in [('Vibration', e['vibration'], e['vibration_status'], 'mm/s'), ('Temperature', e['temperature'], e['temperature_status'], '°C')]:
            if status in ['WARNING', 'CRITICAL']:
                alerts.append([status, 'Equipment', e['equipment_id'], parameter,
                               f'{reading:.1f} {unit}', 'Monitoring threshold exceeded',
                               'Inspect equipment and follow the applicable manufacturer procedures.'])
        for part in ['brake_status', 'tyre_status', 'engine_status']:
            if e[part] in ['Worn', 'Fault']:
                level = 'CRITICAL' if e[part] == 'Fault' else 'WARNING'
                alerts.append([level, 'Equipment', e['equipment_id'], part.replace('_status', '').title(),
                               e[part], 'Fault detected' if level == 'CRITICAL' else 'Wear detected',
                               'Inspect equipment and plan appropriate maintenance.'])
        if e['maintenance_check'] == 'Overdue':
            alerts.append(['WARNING', 'Maintenance', e['equipment_id'], 'Service',
                           str(e['next_service_due']), 'Overdue maintenance', 'Schedule maintenance.'])
        if e['downtime_hours'] > 100:
            alerts.append(['WARNING', 'Maintenance', e['equipment_id'], 'Downtime',
                           str(e['downtime_hours']) + ' hours', 'Excessive downtime', 'Investigate equipment downtime.'])
        if e['availability'] < 80:
            alerts.append(['WARNING', 'Maintenance', e['equipment_id'], 'Availability',
                           str(e['availability']) + '%', 'Low availability', 'Review maintenance performance.'])
        if e['alerts_30d'] >= 3:
            alerts.append(['WARNING', 'Maintenance', e['equipment_id'], 'Previous alerts',
                           str(e['alerts_30d']), 'Repeated alerts', 'Inspect equipment history.'])
    table = pd.DataFrame(alerts, columns=['Severity', 'Category', 'ID', 'Parameter', 'Value', 'Status', 'Recommended Action'])
    return table

CHOICES = {
    'shift': ['Day', 'Night'],
    'ppe_compliant': ['Yes', 'No'],
    'training_status': ['Valid', 'Expired', 'Pending'],
    'severity': ['Minor', 'Moderate', 'Major', 'Critical'],
    'status': ['Open', 'Under Investigation', 'Closed'],
    'maintenance_status': ['Operational', 'Under Maintenance', 'Out of Service'],
    'brake_status': ['OK', 'Worn', 'Fault', 'N/A'],
    'tyre_status': ['OK', 'Worn', 'Fault', 'N/A'],
    'engine_status': ['OK', 'Worn', 'Fault', 'N/A'],
    'lost_time_injury': ['Yes', 'No']
}

NUMBER_FIELDS = {'fatigue_level', 'near_misses', 'previous_incidents', 'likelihood', 'consequence',
                 'operating_hours', 'temperature', 'vibration', 'fuel_consumption', 'uptime_hours',
                 'downtime_hours', 'alerts_30d'}
DATE_FIELDS = {'date', 'last_service_date', 'next_service_due'}

def visible_alerts(table):
    sections = {'Worker Safety': 'workers', 'Risk': 'risk', 'Incident': 'incidents',
                'Equipment': 'equipment', 'Maintenance': 'maintenance'}
    permitted = table['Category'].map(lambda category: category in sections and allowed(sections[category]))
    return table[permitted].copy()

def form_values(columns):
    values = {key: request.form.get(key, '').strip() for key in columns}
    if any(not value for value in values.values()):
        raise ValueError('Fill in all fields.')
    for key, value in values.items():
        if key in NUMBER_FIELDS and value:
            number = float(value)
            if not (0 <= number <= 10000000):
                raise ValueError('Enter valid positive numbers.')
            if key in {'likelihood', 'consequence'} and (not number.is_integer() or not 1 <= number <= 5):
                raise ValueError('Likelihood and consequence must be from 1 to 5.')
            if key in {'near_misses', 'previous_incidents', 'alerts_30d', 'operating_hours'} and not number.is_integer():
                raise ValueError('Counts must be whole numbers.')
            if key == 'fatigue_level' and (not number.is_integer() or number > 10):
                raise ValueError('Fatigue must be from 0 to 10.')
        if key in DATE_FIELDS:
            datetime.strptime(value, '%Y-%m-%d')
        if key in CHOICES and value not in CHOICES[key]:
            raise ValueError('Choose a valid option.')
    return values

def dashboard_charts(workers, incidents, equipment):
    charts = []
    if allowed('incidents'):
        charts.append(('Incidents by severity', incidents['severity'].value_counts().to_dict(), 'donut'))
    if allowed('workers'):
        charts.append(('Worker risk levels', workers['risk_level'].value_counts().to_dict(), 'bar'))
    if allowed('equipment'):
        charts.append(('Equipment condition', equipment['condition'].value_counts().to_dict(), 'donut'))
    if allowed('maintenance'):
        charts.append(('Maintenance status', equipment['maintenance_check'].value_counts().to_dict(), 'bar'))
    return charts

@app.route('/dashboard')
@login_required('dashboard')
def dashboard():
    workers, incidents, equipment = worker_data(), read_data('incidents'), equipment_data()
    alerts = visible_alerts(make_alerts(workers, incidents, equipment))
    numbers = [('Workers', len(workers) if allowed('workers') else '-'),
               ('Incidents', len(incidents) if allowed('incidents') else '-'),
               ('Equipment', len(equipment) if allowed('equipment') else '-'),
               ('Active alerts', len(alerts)), ('Critical alerts', int((alerts['Severity'] == 'CRITICAL').sum()))]
    if allowed('workers'):
        numbers.append(('PPE compliance', f"{(workers['ppe_compliant'] == 'Yes').mean() * 100 if len(workers) else 0:.1f}%"))
        numbers.append(('High-risk observations', int(workers['risk_level'].isin(['High', 'Critical']).sum())))
        numbers.append(('Near misses', int(workers['near_misses'].sum())))
    if allowed('equipment'):
        numbers.append(('Average availability', f"{equipment['availability'].mean() if len(equipment) else 0:.1f}%"))
        numbers.append(('Equipment available', int((equipment['maintenance_status'] == 'Operational').sum())))
        numbers.append(('Equipment alerts', int((alerts['Category'] == 'Equipment').sum())))
        numbers.append(('Critical equipment alerts', int(((alerts['Category'] == 'Equipment') & (alerts['Severity'] == 'CRITICAL')).sum())))
    if allowed('maintenance'):
        numbers.append(('Under maintenance', int((equipment['maintenance_check'] == 'Under Maintenance').sum())))
    return render_template('page.html', title='Dashboard', section='dashboard',
                           numbers=numbers, table=alerts.head(12), dashboard_charts=dashboard_charts(workers, incidents, equipment), note=None)

def worker_warnings(w):
    found = []
    if w['ppe_compliant'] != 'Yes':
        found.append('PPE not compliant')
    if w['training_status'] == 'Expired':
        found.append('Training expired')
    if w['fatigue_level'] >= 7:
        found.append('High fatigue')
    if w['risk_level'] in ['High', 'Critical']:
        found.append('High risk')
    return '; '.join(found)

@app.route('/workers', methods=['GET', 'POST'])
@login_required('workers')
def workers():
    if request.method == 'POST':
        table = read_data('workers')
        try:
            values = form_values([key for key in table.columns if key != 'worker_id'])
        except (ValueError, TypeError):
            flash('Check the information entered. Dates must be YYYY-MM-DD and numbers must be valid.')
            return redirect(url_for('workers'))
        values['worker_id'] = 'W' + str(max([int(x[1:]) for x in table['worker_id']] + [0]) + 1).zfill(3)
        save_data('workers', pd.concat([table, pd.DataFrame([values])], ignore_index=True))
        flash('Worker saved.')
        return redirect(url_for('workers'))
    table = worker_data()
    search = request.args.get('search', '').lower().strip()
    if search:
        table = table[table.astype(str).apply(lambda row: search in ' '.join(row).lower(), axis=1)]
    department = request.args.get('department', '')
    if department:
        table = table[table['department'] == department]
    filters = {'department': sorted(read_data('workers')['department'].dropna().unique())}
    table = table.copy()
    table['warnings'] = [worker_warnings(w) for _, w in table.iterrows()]
    return render_template('page.html', title='Worker Health and Safety Monitoring', section='workers',
                           filter_options=filters, table=table, fields=[c for c in read_data('workers').columns if c != 'worker_id'],
                           note=None)

@app.route('/incidents', methods=['GET', 'POST'])
@login_required('incidents')
def incidents():
    if request.method == 'POST':
        table = read_data('incidents')
        try:
            values = form_values([key for key in table.columns if key != 'incident_id'])
        except (ValueError, TypeError):
            flash('Check the information entered. Dates must be YYYY-MM-DD and numbers must be valid.')
            return redirect(url_for('incidents'))
        prefix = 'INC-' + date.today().strftime('%Y') + '-'
        existing = [int(x.rsplit('-', 1)[-1]) for x in table['incident_id'].astype(str) if x.startswith(prefix) and x.rsplit('-', 1)[-1].isdigit()]
        values['incident_id'] = prefix + str(max(existing, default=0) + 1).zfill(4)
        save_data('incidents', pd.concat([table, pd.DataFrame([values])], ignore_index=True))
        flash('Incident saved.')
        return redirect(url_for('incidents'))
    table = read_data('incidents')
    search = request.args.get('search', '').lower()
    if search:
        table = table[table.astype(str).apply(lambda row: search in ' '.join(row).lower(), axis=1)]
    start = request.args.get('start_date', '')
    end = request.args.get('end_date', '')
    try:
        if start and end and start > end:
            raise ValueError()
        if start:
            table = table[pd.to_datetime(table['date'], errors='coerce') >= pd.Timestamp(datetime.strptime(start, '%Y-%m-%d'))]
        if end:
            table = table[pd.to_datetime(table['date'], errors='coerce') <= pd.Timestamp(datetime.strptime(end, '%Y-%m-%d'))]
    except ValueError:
        flash('Choose valid dates, with From before To.')
        return redirect(url_for('incidents'))
    for key in ['department', 'shift', 'severity', 'status', 'incident_type']:
        wanted = request.args.get(key, '')
        if wanted:
            table = table[table[key] == wanted]
    counts = table['severity'].value_counts().to_dict()
    original = read_data('incidents')
    filter_options = {key: sorted(original[key].dropna().astype(str).unique()) for key in ['department', 'shift', 'severity', 'status', 'incident_type']}
    return render_template('page.html', title='Safety Incident Database', section='incidents',
                           table=table, fields=[c for c in read_data('incidents').columns if c != 'incident_id'],
                           filter_options=filter_options, numbers=[('Filtered incidents', len(table)), ('Major', counts.get('Major', 0)),
                                    ('Critical', counts.get('Critical', 0))],
                           dashboard_charts=[('Incident severity', table['severity'].value_counts().to_dict(), 'donut'),
                                             ('Incident types', table['incident_type'].value_counts().head(8).to_dict(), 'bar'),
                                             ('Monthly trend', pd.to_datetime(table['date'], errors='coerce').dt.to_period('M').astype(str).value_counts().sort_index().to_dict(), 'line')], note=None)

@app.route('/equipment', methods=['GET', 'POST'])
@login_required('equipment')
def equipment():
    if request.method == 'POST':
        table = read_data('equipment')
        try:
            values = form_values([key for key in table.columns if key != 'equipment_id'])
        except (ValueError, TypeError):
            flash('Check the information entered. Dates must be YYYY-MM-DD and numbers must be valid.')
            return redirect(url_for('equipment'))
        existing = [int(x.split('-')[-1]) for x in table['equipment_id'].astype(str) if x.split('-')[-1].isdigit()]
        values['equipment_id'] = 'EQ-' + str(max(existing, default=0) + 1).zfill(3)
        save_data('equipment', pd.concat([table, pd.DataFrame([values])], ignore_index=True))
        flash('Equipment saved.')
        return redirect(url_for('equipment'))
    table = equipment_data()
    search = request.args.get('search', '').lower().strip()
    if search:
        table = table[table.astype(str).apply(lambda row: search in ' '.join(row).lower(), axis=1)]
    condition = request.args.get('condition', '')
    if condition:
        table = table[table['condition'] == condition]
    filters = {'condition': ['NORMAL', 'WARNING', 'CRITICAL']}
    return render_template('page.html', title='Equipment Database and Condition Monitoring',
                           section='equipment', table=table, filter_options=filters,
                           fields=[c for c in read_data('equipment').columns if c != 'equipment_id'],
                           dashboard_charts=[('Equipment condition', table['condition'].value_counts().to_dict(), 'donut'),
                                             ('Equipment type', table['equipment_type'].value_counts().to_dict(), 'bar')])

@app.route('/maintenance')
@login_required('maintenance')
def maintenance():
    table = equipment_data()
    table['maintenance_reason'] = table.apply(lambda e: '; '.join(
        ([e['maintenance_check']] if e['maintenance_check'] != 'OK' else []) +
        (['Low availability'] if e['availability'] < 80 else []) +
        (['Excessive downtime'] if e['downtime_hours'] > 100 else []) +
        (['Repeated alerts'] if e['alerts_30d'] >= 3 else []) +
        (['Critical condition'] if e['condition'] == 'CRITICAL' else [])), axis=1)
    table = table[table['maintenance_reason'] != '']
    return render_template('page.html', title='Equipment Maintenance Monitoring', section='maintenance',
                           table=table)

@app.route('/risk', methods=['GET', 'POST'])
@login_required('risk')
def risk():
    result = None
    if request.method == 'POST':
        try:
            likelihood = int(request.form['likelihood'])
            consequence = int(request.form['consequence'])
            if not (1 <= likelihood <= 5 and 1 <= consequence <= 5):
                raise ValueError()
            score = likelihood * consequence
            level = risk_level(score)
            result = f'Risk score: {score} | {level}'
            if level == 'High':
                result += ' | Review safety controls.'
            if level == 'Critical':
                result += ' | Stop work and report the risk.'
        except ValueError:
            flash('Enter numbers from 1 to 5.')
    return render_template('page.html', title='Risk Assessment', section='risk', result=result,
                           note=None)

@app.route('/alerts')
@login_required('alerts')
def alerts():
    table = visible_alerts(make_alerts(worker_data(), read_data('incidents'), equipment_data()))
    return render_template('page.html', title='Alerts and Notifications', section='alerts',
                           table=table, note=None)

QUESTIONS = [
('Health and Safety','How many safety incidents occurred during the selected period?','incidents'),
('Health and Safety','Which department has the highest number of incidents?','incidents'),
('Health and Safety','Which shift records the most incidents?','incidents'),
('Health and Safety','What percentage of workers comply with PPE requirements?','workers'),
('Health and Safety','How many near misses have been recorded?','workers'),
('Health and Safety','Which incident types occur most frequently?','incidents'),
('Health and Safety','How many incidents are classified as high or critical?','incidents'),
('Health and Safety','Which departments have the highest safety risk?','workers'),
('Health and Safety','Is there an observable difference in incidents between day and night shifts?','incidents'),
('Health and Safety','Which safety conditions require immediate attention?','workers'),
('Equipment','Which equipment has the highest downtime?','equipment'),
('Equipment','Which equipment has the lowest availability?','equipment'),
('Equipment','Which equipment has the highest vibration?','equipment'),
('Equipment','Which equipment has the highest operating temperature?','equipment'),
('Equipment','Which equipment has generated the most alerts?','equipment'),
('Equipment','Which equipment requires maintenance?','maintenance'),
('Equipment','Which equipment is overdue for maintenance?','maintenance'),
('Equipment','What is the average equipment availability?','equipment'),
('Equipment','Which equipment type has the highest downtime?','equipment'),
('Equipment','Which equipment requires immediate inspection?','equipment'),
('Integrated Safety and Equipment Analysis','Are safety incidents associated with particular shifts?','incidents'),
('Integrated Safety and Equipment Analysis','Which departments have both high safety risk and high equipment downtime?','workers,equipment'),
('Integrated Safety and Equipment Analysis','Which equipment contributes to the greatest number of alerts?','equipment'),
('Integrated Safety and Equipment Analysis','Which equipment should receive maintenance priority?','maintenance'),
('Integrated Safety and Equipment Analysis','What are the most common causes of safety incidents?','incidents'),
('Integrated Safety and Equipment Analysis','Which safety indicators require management intervention?','workers,incidents'),
('Integrated Safety and Equipment Analysis','What percentage of monitored equipment is operating normally?','equipment'),
('Integrated Safety and Equipment Analysis','How many critical alerts are currently active?','alerts'),
('Integrated Safety and Equipment Analysis','Which areas of the operation require the greatest attention?','workers,incidents,equipment'),
('Integrated Safety and Equipment Analysis','What recommendations can be generated from the monitoring results?','workers,incidents,equipment')]

def answer_question(index, w, i, e, alerts):
    count = len(i)
    serious = i[i['severity'].isin(['Major','Critical'])]
    risk = w[w['risk_level'].isin(['High','Critical'])]
    overdue = e[e['maintenance_check'] == 'Overdue']
    attention = e[(e['condition']=='CRITICAL') | (e['maintenance_check'].isin(['Overdue','Due Soon'])) | (e['availability']<80)]
    aid = alerts[alerts['Category']=='Equipment']
    def rank(table, key, n=10):
        return table.set_index(key).iloc[:,0].head(n).to_dict()
    def top(items):
        return next(iter(items), 'None')
    def result(text, data=None, kind='bar', table=None):
        return {'text': text, 'data': data or {}, 'kind': kind, 'table': table}
    def frequency(column):
        return i[column].value_counts().to_dict()
    if index == 0:
        trend = i.groupby(pd.to_datetime(i['date']).dt.to_period('M')).size()
        return result(f'{count} safety incidents occurred during the selected period.', {str(x):int(y) for x,y in trend.items()}, 'line')
    if index == 1:
        d=frequency('department'); return result(f'{top(d)} has the highest number of incidents ({next(iter(d.values()),0)}).',d)
    if index == 2:
        d=frequency('shift'); return result(f'{top(d)} shift records the most incidents ({next(iter(d.values()),0)}).',d)
    if index == 3:
        rate=round((w['ppe_compliant']=='Yes').mean()*100,1) if len(w) else 0
        d=w.groupby('department')['ppe_compliant'].apply(lambda x:round((x=='Yes').mean()*100,1)).to_dict()
        return result(f'{rate}% of workers comply with PPE requirements.',d)
    if index == 4:
        d=w.groupby('department')['near_misses'].sum().to_dict();return result(f'{int(w["near_misses"].sum())} near misses have been recorded.',d)
    if index == 5:
        d=frequency('incident_type');return result(f'{top(d)} is the most frequent incident type.',d)
    if index == 6:
        d=serious['severity'].value_counts().to_dict();return result(f'{len(serious)} incidents are classified as Major or Critical.',d,'donut')
    if index == 7:
        if w.empty: return result('No worker records.')
        d=w.groupby('department')['risk_score'].mean().round(1).sort_values(ascending=False).to_dict();return result(f'{top(d)} has the highest average safety risk score.',d)
    if index in (8,20):
        d=frequency('shift');return result('Incident counts by shift; differences do not prove causation.',d)
    if index == 9:
        danger=w[(w['ppe_compliant']!='Yes') | (w['training_status']=='Expired') | (w['fatigue_level']>=7) | (w['risk_level'].isin(['High','Critical']))]
        return result(f'{len(danger)} workers have safety conditions requiring attention.', danger['department'].value_counts().to_dict(), table=danger[['worker_id','department','risk_level','fatigue_level','ppe_compliant']].head(30))
    if index in (10,11,12,13,14):
        cols=['downtime_hours','availability','vibration','temperature','alerts_30d']; c=cols[index-10]
        ranked=e.sort_values(c,ascending=(index==11))[['equipment_id','equipment_type',c]].head(10)
        if ranked.empty:return result('No equipment records.')
        first=ranked.iloc[0];note='' 
        return result(f'{first["equipment_id"]} has the {"lowest" if index==11 else "highest"} {c.replace("_"," ")}: {first[c]}{note}.',rank(ranked[['equipment_id',c]],'equipment_id'),table=ranked)
    if index == 15:
        return result(f'{len(attention)} equipment units require maintenance or inspection.', attention['maintenance_check'].value_counts().to_dict(),table=attention[['equipment_id','condition','maintenance_check','availability']])
    if index == 16:
        return result(f'{len(overdue)} equipment units are overdue for maintenance.',overdue['equipment_type'].value_counts().to_dict(),table=overdue[['equipment_id','next_service_due','maintenance_status']])
    if index == 17:
        d=e.groupby('equipment_type')['availability'].mean().round(1).to_dict()
        return result(f'Average equipment availability is {e["availability"].mean() if len(e) else 0:.1f}%.',d)
    if index == 18:
        d=e.groupby('equipment_type')['downtime_hours'].sum().sort_values(ascending=False).round(1).to_dict();return result(f'{top(d)} has the highest total downtime.',d)
    if index == 19:
        critical=e[e['condition']=='CRITICAL'];return result(f'{len(critical)} units have recorded critical condition findings.',critical['equipment_type'].value_counts().to_dict(),table=critical[['equipment_id','condition_message']])
    if index == 21:
        x=w.groupby('department')['risk_score'].mean();y=e.groupby('department')['downtime_hours'].sum()
        common=x.index.intersection(y.index);both=pd.DataFrame({'risk':x.reindex(common),'downtime':y.reindex(common)})
        selected=both[(both['risk']>=both['risk'].median()) & (both['downtime']>=both['downtime'].median())] if len(both) else both
        return result('Departments at or above the median for both average risk and downtime: '+(', '.join(selected.index) or 'none')+'.', selected['downtime'].round(1).to_dict(),table=both.reset_index())
    if index in (22,):
        d=aid['ID'].value_counts().head(10).to_dict();return result(f'{top(d)} contributes the most currently generated equipment alerts.',d)
    if index == 23:
        x=e.copy();x['priority']= (x['condition']=='CRITICAL').astype(int)*3+(x['maintenance_check']=='Overdue').astype(int)*3+(x['availability']<80).astype(int)*2+(x['downtime_hours']>100).astype(int)+(x['alerts_30d']>=3).astype(int)
        x=x.sort_values('priority',ascending=False)
        return result(f'{x.iloc[0]["equipment_id"]} has highest maintenance priority score.' if len(x) else 'No equipment.',x.set_index('equipment_id')['priority'].head(10).to_dict(),table=x[['equipment_id','priority','condition','maintenance_check']].head(10))
    if index == 24:
        d=frequency('cause');return result(f'{top(d)} is the most frequently recorded incident cause.',d)
    if index == 25:
        d={'PPE non-compliant':int((w['ppe_compliant']!='Yes').sum()),'High fatigue':int((w['fatigue_level']>=7).sum()),'Training expired':int((w['training_status']=='Expired').sum()),'High risk':len(risk),'Open critical incidents':int(((i['severity']=='Critical') & (i['status']!='Closed')).sum())}
        return result('Safety indicators requiring attention are shown below.',d)
    if index == 26:
        percent=round((e['condition']=='NORMAL').mean()*100,1) if len(e) else 0
        return result(f'{percent}% of equipment is operating normally within monitoring limits.',e['condition'].value_counts().to_dict(),'donut')
    if index == 27:
        c=alerts[alerts['Severity']=='CRITICAL'];return result(f'{len(c)} critical alerts are currently active.',c['Category'].value_counts().to_dict())
    if index == 28:
        departments=sorted(set(w['department'])|set(i['department'])|set(e['department']))
        data={}
        for dep in departments:
            data[dep]=int(((w['department']==dep)&w['risk_level'].isin(['High','Critical'])).sum()+ (i['department']==dep).sum()+ ((e['department']==dep)&(e['condition']=='CRITICAL')).sum()+((e['department']==dep)&(e['maintenance_check']=='Overdue')).sum())
        data=dict(sorted(data.items(),key=lambda x:-x[1]))
        return result(f'{top(data)} has the highest combined attention count (indicative only).',data)
    if index == 29:
        rec=[]
        if (w['ppe_compliant']!='Yes').any():rec.append('Check PPE compliance before shifts.')
        if (w['fatigue_level']>=7).any():rec.append('Review fatigue and work schedules.')
        if (w['training_status']=='Expired').any():rec.append('Schedule expired safety training.')
        if len(overdue):rec.append('Service overdue equipment.')
        if (e['condition']=='CRITICAL').any():rec.append('Inspect critical equipment conditions.')
        if len(serious):rec.append('Review major and critical incidents.')
        if not rec:rec.append('Continue routine monitoring.')
        return result('Recommendations based on current monitoring records.',{str(n+1)+'. '+v:1 for n,v in enumerate(rec)},'list')
    return result('No result available.')

@app.route('/analysis')
@login_required('analysis')
def analysis():
    available=[(n,group,label) for n,(group,label,required) in enumerate(QUESTIONS) if all(allowed(part) for part in required.split(','))]
    groups={name: [(n,label) for n,group,label in available if group==name] for name in ['Health and Safety','Equipment','Integrated Safety and Equipment Analysis']}
    selected=request.args.get('question',type=int)
    if selected is None or selected not in [n for n,_,_ in available]:
        selected=available[0][0] if available else None
    w,i,e=worker_data(),read_data('incidents'),equipment_data()
    start,end=request.args.get('start_date',''),request.args.get('end_date','')
    try:
        if start:i=i[pd.to_datetime(i['date'], errors='coerce')>=pd.Timestamp(datetime.strptime(start, '%Y-%m-%d'))]
        if end:i=i[pd.to_datetime(i['date'], errors='coerce')<=pd.Timestamp(datetime.strptime(end, '%Y-%m-%d'))]
        if start and end and start>end:raise ValueError()
    except ValueError:
        flash('Choose valid dates, with From before To.')
        return redirect(url_for('analysis'))
    alerts=visible_alerts(make_alerts(w,read_data('incidents'),e))
    answer=answer_question(selected,w,i,e,alerts) if selected is not None else None
    return render_template('page.html',title='Interactive Data Analysis',section='analysis',question_groups=groups,
                           selected_question=selected,answer=answer,note=None)

@app.route('/reports')
@login_required('reports')
def reports():
    available = [name for name, section in [('workers', 'workers'), ('incidents', 'incidents'), ('equipment', 'equipment')]
                 if allowed(section)] + ['alerts']
    return render_template('page.html', title='Generate Reports', section='reports', downloads=available,
                           note=None)

def create_full_report():
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, KeepTogether
    from reportlab.lib import colors
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.lib.enums import TA_CENTER
    from reportlab.graphics.shapes import Drawing, Rect, String

    workers = worker_data()
    incidents = read_data('incidents')
    equipment = equipment_data()
    alerts = make_alerts(workers, incidents, equipment)
    buffer = BytesIO()
    pdf = SimpleDocTemplate(buffer, pagesize=(595, 842), rightMargin=40,
                            leftMargin=40, topMargin=40, bottomMargin=40)
    styles = getSampleStyleSheet()
    styles['Title'].textColor = colors.HexColor('#17344A')
    styles['Heading2'].textColor = colors.HexColor('#17344A')
    parts = []

    def heading(title):
        parts.append(Spacer(1, 12))
        parts.append(Paragraph(title, styles['Heading2']))

    def paragraph(message):
        parts.append(Paragraph(str(message), styles['BodyText']))
        parts.append(Spacer(1, 7))

    def table(rows):
        cells = [[Paragraph(str(item), styles['BodyText']) for item in row] for row in rows]
        item = Table(cells, colWidths=[255, 255], repeatRows=1, hAlign='LEFT')
        item.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#e3edf3')),
            ('VALIGN', (0, 0), (-1, -1), 'TOP'),
            ('LINEBELOW', (0, 0), (-1, 0), 0.7, colors.HexColor('#17344A')),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 7),
            ('TOPPADDING', (0, 0), (-1, -1), 7),
        ]))
        parts.append(item)

    def chart(title, counts):
        counts = list(counts.items())[:6]
        if not counts:
            return
        heading(title)
        highest = max(float(value) for _, value in counts) or 1
        height = 25 * len(counts) + 15
        drawing = Drawing(510, height)
        for n, (label, value) in enumerate(counts):
            y = height - 25 * (n + 1)
            drawing.add(String(0, y + 4, str(label)[:29], fontSize=8))
            drawing.add(Rect(180, y, 260 * max(float(value), 0) / highest, 13,
                             fillColor=colors.HexColor('#e99a26'), strokeColor=None))
            drawing.add(String(450, y + 4, f'{float(value):g}', fontSize=8))
        parts.append(drawing)

    parts.append(Paragraph('Mining Health, Safety and Equipment Monitoring Report', styles['Title']))
    paragraph('Khwezi Mining | Generated ' + date.today().strftime('%d %B %Y'))
    paragraph('Based on the current workers.csv, incidents.csv and equipment.csv datasets. '
              'Worker and equipment values are current records; incidents cover all recorded dates.')

    heading('1. Monitoring Summary')
    ppe = (workers['ppe_compliant'] == 'Yes').mean() * 100 if len(workers) else 0
    average = equipment['availability'].mean() if len(equipment) else 0
    risky = int(workers['risk_level'].isin(['High', 'Critical']).sum())
    table([['Indicator', 'Value'], ['Workers', len(workers)], ['Safety incidents', len(incidents)],
           ['Near misses', int(workers['near_misses'].sum())],
           ['PPE compliance', f'{ppe:.1f}%'], ['High/Critical worker risks', risky],
           ['Equipment units', len(equipment)], ['Average availability', f'{average:.1f}%'],
           ['Active monitoring alerts', len(alerts)],
           ['Critical alerts', int((alerts['Severity'] == 'CRITICAL').sum())]])

    heading('2. Worker Health and Safety')
    chart('Worker Risk Levels', workers['risk_level'].value_counts().to_dict())
    paragraph('Workers with expired training: ' + str(int((workers['training_status'] == 'Expired').sum()))
              + '. Workers with high fatigue (7 or above): '
              + str(int((workers['fatigue_level'] >= 7).sum())) + '.')

    heading('3. Safety Incidents')
    chart('Incident Severity', incidents['severity'].value_counts().to_dict())
    chart('Incidents by Department', incidents['department'].value_counts().to_dict())
    if len(incidents):
        dates = pd.to_datetime(incidents['date'], errors='coerce').dropna()
        if len(dates):
            paragraph('Incident dates: ' + dates.min().strftime('%d %b %Y') + ' to '
                      + dates.max().strftime('%d %b %Y') + '.')
        chart('Incidents by Shift', incidents['shift'].value_counts().to_dict())

    heading('4. Equipment Condition and Maintenance')
    chart('Equipment Condition', equipment['condition'].value_counts().to_dict())
    chart('Maintenance Status', equipment['maintenance_check'].value_counts().to_dict())
    overdue = equipment[equipment['maintenance_check'] == 'Overdue']
    critical = equipment[equipment['condition'] == 'CRITICAL']
    paragraph(f'{len(overdue)} units are overdue for maintenance; '
              f'{len(critical)} units have critical condition findings; '
              f'{int((equipment["availability"] < 80).sum())} units have availability below 80%.')
    if len(critical):
        paragraph('Critical equipment IDs: ' + ', '.join(critical['equipment_id'].astype(str).tolist()[:20]))

    heading('5. Alerts and Notifications')
    chart('Alerts by Severity', alerts['Severity'].value_counts().to_dict())
    chart('Alerts by Category', alerts['Category'].value_counts().to_dict())
    for _, alert in alerts[alerts['Severity'] == 'CRITICAL'].head(12).iterrows():
        paragraph(f'<b>{alert["ID"]} - {alert["Parameter"]}:</b> '
                  f'{alert["Value"]}. {alert["Status"]}. {alert["Recommended Action"]}')
    if int((alerts['Severity'] == 'CRITICAL').sum()) > 12:
        paragraph('Only the first 12 critical alerts are listed above. Download the Alerts CSV for all details.')

    heading('6. Conclusions and Recommendations')
    recommendations = []
    if ppe < 90:
        recommendations.append('Improve PPE compliance through shift inspections.')
    if risky:
        recommendations.append('Review the controls for high and critical worker risks.')
    if int((workers['fatigue_level'] >= 7).sum()):
        recommendations.append('Assess fatigue levels and review work schedules.')
    if len(overdue):
        recommendations.append('Prioritise overdue equipment servicing.')
    if len(critical):
        recommendations.append('Inspect equipment with critical monitoring conditions.')
    if not recommendations:
        recommendations.append('Continue routine monitoring and preventive maintenance.')
    for n, recommendation in enumerate(recommendations, 1):
        paragraph(f'{n}. {recommendation}')
    pdf.build(parts)
    buffer.seek(0)
    return buffer.getvalue()

@app.route('/full-report')
@login_required('reports')
def full_report():
    if not all(allowed(section) for section in ['workers', 'incidents', 'equipment', 'maintenance', 'risk']):
        flash('This report requires access to safety and equipment records.')
        return redirect(url_for('reports'))
    content = create_full_report()
    return Response(content, mimetype='application/pdf',
                    headers={'Content-Disposition': 'attachment; filename=full_data_report.pdf'})

@app.route('/download/<name>')
@login_required('reports')
def download(name):
    if name not in ['workers', 'incidents', 'equipment', 'alerts'] or (name != 'alerts' and not allowed(name)):
        return redirect(url_for('reports'))
    if name == 'alerts':
        content = visible_alerts(make_alerts(worker_data(), read_data('incidents'), equipment_data())).to_csv(index=False)
    else:
        content = read_data(name).to_csv(index=False)
    return Response(content, mimetype='text/csv', headers={'Content-Disposition': f'attachment; filename={name}_report.csv'})

@app.route('/users', methods=['GET', 'POST'])
@login_required('users')
def users():
    if request.method == 'POST':
        table = read_data('users')
        username = request.form.get('username', '').strip()
        name = request.form.get('full_name', '').strip()
        role = request.form.get('role', '')
        password = request.form.get('password', '')
        if not username or not name or role not in ROLES or len(password) < 8 or username in table['username'].values:
            flash('Enter a unique username, a name, a role and a password of at least 8 characters.')
        else:
            row = {'username': username, 'full_name': name, 'role': role,
                   'password_hash': generate_password_hash(password), 'active': 'Yes'}
            save_data('users', pd.concat([table, pd.DataFrame([row])], ignore_index=True))
            flash('User created.')
            return redirect(url_for('users'))
    table = read_data('users')[['username', 'full_name', 'role', 'active']]
    return render_template('page.html', title='Access Control - Manage Users', section='users',
                           table=table, roles=ROLES, note=None)

if __name__ == '__main__':
    app.run(debug=False)