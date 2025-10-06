#!/usr/bin/env python3
"""
DietMate - A simple command-line diet tracking project in Python
Features:
- User sign up / login (password hashed)
- Set daily calorie goal
- Add & manage foods (name, calories per serving)
- Log meals (date, meal_type, food, servings)
- View daily summary (calories consumed vs goal)
- Suggest a simple meal plan to meet remaining calories
- Export logs as CSV

No external dependencies (built-in sqlite3, csv, datetime, getpass)
Run: python3 dietmate.py
"""

import sqlite3
import os
import sys
from getpass import getpass
from datetime import datetime, date
import csv
from werkzeug.security import generate_password_hash, check_password_hash

DB_PATH = os.path.join(os.path.expanduser('~'), '.dietmate.db')

# --- Database helpers ---

def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_conn()
    cur = conn.cursor()
    cur.executescript('''
    CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY,
        username TEXT UNIQUE NOT NULL,
        password_hash TEXT NOT NULL,
        calorie_goal INTEGER DEFAULT 2000
    );

    CREATE TABLE IF NOT EXISTS foods (
        id INTEGER PRIMARY KEY,
        user_id INTEGER NOT NULL,
        name TEXT NOT NULL,
        calories_per_serving REAL NOT NULL,
        serving_desc TEXT DEFAULT '1 serving',
        UNIQUE(user_id, name),
        FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
    );

    CREATE TABLE IF NOT EXISTS meals (
        id INTEGER PRIMARY KEY,
        user_id INTEGER NOT NULL,
        food_id INTEGER NOT NULL,
        meal_date TEXT NOT NULL,
        meal_type TEXT NOT NULL,
        servings REAL NOT NULL,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(user_id) REFERENCES users(id),
        FOREIGN KEY(food_id) REFERENCES foods(id)
    );
    ''')
    conn.commit()
    conn.close()

# --- User/account functions ---

def signup():
    conn = get_conn()
    cur = conn.cursor()
    print('\n--- Sign Up ---')
    username = input('Choose a username: ').strip()
    if not username:
        print('Username cannot be empty')
        return None
    password = getpass('Choose a password: ')
    password2 = getpass('Confirm password: ')
    if password != password2:
        print('Passwords do not match')
        return None
    pw_hash = generate_password_hash(password)
    try:
        cur.execute('INSERT INTO users (username, password_hash) VALUES (?, ?)', (username, pw_hash))
        conn.commit()
        print('Account created. You can now log in.')
        return None
    except sqlite3.IntegrityError:
        print('Username already taken')
        return None
    finally:
        conn.close()


def login():
    conn = get_conn()
    cur = conn.cursor()
    print('\n--- Login ---')
    username = input('Username: ').strip()
    password = getpass('Password: ')
    cur.execute('SELECT * FROM users WHERE username = ?', (username,))
    row = cur.fetchone()
    conn.close()
    if row and check_password_hash(row['password_hash'], password):
        print(f'Welcome, {username}!')
        return dict(id=row['id'], username=row['username'], calorie_goal=row['calorie_goal'])
    else:
        print('Invalid credentials')
        return None

# --- Food management ---

def add_food(user):
    conn = get_conn()
    cur = conn.cursor()
    print('\n--- Add Food ---')
    name = input('Food name: ').strip()
    if not name:
        print('Name required')
        return
    try:
        cal = float(input('Calories per serving (e.g. 250): ').strip())
    except ValueError:
        print('Invalid calories')
        return
    serving_desc = input('Serving description (default "1 serving"): ').strip() or '1 serving'
    try:
        cur.execute('INSERT INTO foods (user_id, name, calories_per_serving, serving_desc) VALUES (?, ?, ?, ?)',
                    (user['id'], name, cal, serving_desc))
        conn.commit()
        print('Food added')
    except sqlite3.IntegrityError:
        print('You already have this food. Use a different name.')
    finally:
        conn.close()


def list_foods(user):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute('SELECT * FROM foods WHERE user_id = ? ORDER BY name', (user['id'],))
    rows = cur.fetchall()
    conn.close()
    if not rows:
        print('No foods added yet.')
        return []
    print('\nYour foods:')
    for r in rows:
        print(f"{r['id']}: {r['name']} — {r['calories_per_serving']} kcal ({r['serving_desc']})")
    return rows

# --- Meal logging & summary ---

def log_meal(user):
    foods = list_foods(user)
    if not foods:
        print('Add foods before logging a meal.')
        return
    try:
        fid = int(input('\nEnter food id to log: ').strip())
    except ValueError:
        print('Invalid id')
        return
    if not any(f['id'] == fid for f in foods):
        print('Food id not found')
        return
    meal_date = input('Date (YYYY-MM-DD) [default today]: ').strip() or date.today().isoformat()
    try:
        datetime.strptime(meal_date, '%Y-%m-%d')
    except ValueError:
        print('Bad date format')
        return
    meal_type = input('Meal type (breakfast/lunch/dinner/snack): ').strip() or 'meal'
    try:
        servings = float(input('Servings (e.g. 1, 0.5): ').strip())
    except ValueError:
        print('Invalid servings')
        return
    conn = get_conn()
    cur = conn.cursor()
    cur.execute('INSERT INTO meals (user_id, food_id, meal_date, meal_type, servings) VALUES (?, ?, ?, ?, ?)',
                (user['id'], fid, meal_date, meal_type, servings))
    conn.commit()
    conn.close()
    print('Meal logged.')


def get_daily_summary(user, target_date=None):
    if not target_date:
        target_date = date.today().isoformat()
    conn = get_conn()
    cur = conn.cursor()
    cur.execute('''
        SELECT m.id, m.meal_type, m.servings, f.name, f.calories_per_serving,
               (m.servings * f.calories_per_serving) AS total_cal
        FROM meals m JOIN foods f ON m.food_id = f.id
        WHERE m.user_id = ? AND m.meal_date = ?
        ORDER BY m.created_at
    ''', (user['id'], target_date))
    rows = cur.fetchall()
    conn.close()
    total = sum(r['total_cal'] for r in rows) if rows else 0
    return rows, total


def view_summary(user):
    d = input('Date to view (YYYY-MM-DD) [default today]: ').strip() or date.today().isoformat()
    try:
        datetime.strptime(d, '%Y-%m-%d')
    except ValueError:
        print('Bad date format'); return
    rows, total = get_daily_summary(user, d)
    print(f"\nSummary for {d} — Goal: {user['calorie_goal']} kcal")
    if not rows:
        print('No meals logged')
    else:
        for r in rows:
            print(f"{r['meal_type']}: {r['name']} x{r['servings']} = {r['total_cal']:.1f} kcal")
        print(f"Total: {total:.1f} kcal — Remaining: {user['calorie_goal'] - total:.1f} kcal")

# --- Simple meal planner ---

def suggest_meal_plan(user):
    # Find remaining calories for today
    rows, total = get_daily_summary(user, date.today().isoformat())
    remaining = user['calorie_goal'] - total
    print(f"\nRemaining calories for today: {remaining:.1f} kcal")
    if remaining <= 0:
        print('You have met or exceeded your goal for today.')
        return
    # Get user's foods sorted by calories per serving (descending) — we'll attempt to suggest combos
    conn = get_conn()
    cur = conn.cursor()
    cur.execute('SELECT id, name, calories_per_serving, serving_desc FROM foods WHERE user_id = ? ORDER BY calories_per_serving DESC', (user['id'],))
    foods = cur.fetchall()
    conn.close()
    if not foods:
        print('Add some foods first so I can suggest a plan.')
        return
    # Greedy building: try to pick up to 3 items that fit remaining calories
    plan = []
    rem = remaining
    for f in foods:
        if rem <= 0:
            break
        max_serv = int(rem // f['calories_per_serving'])
        if max_serv <= 0:
            # try fractional serving
            frac = rem / f['calories_per_serving']
            if frac >= 0.25:  # don't suggest tiny fractions
                plan.append((f['name'], round(frac, 2), f['serving_desc'], round(frac * f['calories_per_serving'], 1)))
                rem -= frac * f['calories_per_serving']
        else:
            take = min(max_serv, 2)  # at most 2 servings of a single item to keep it realistic
            plan.append((f['name'], take, f['serving_desc'], round(take * f['calories_per_serving'], 1)))
            rem -= take * f['calories_per_serving']
    print('\nSuggested meal plan to fill remaining calories:')
    if not plan:
        print('No suitable suggestions — maybe add some low-calorie foods or change your goal')
        return
    for p in plan:
        print(f"- {p[0]} x{p[1]} ({p[2]}) ≈ {p[3]} kcal")
    print(f"Estimated extra kcal: {remaining - rem:.1f} kcal — Unfilled: {rem:.1f} kcal")

# --- Export ---

def export_csv(user):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute('''
        SELECT m.meal_date, m.meal_type, f.name, m.servings, f.calories_per_serving,
               (m.servings * f.calories_per_serving) AS total_cal
        FROM meals m JOIN foods f ON m.food_id = f.id
        WHERE m.user_id = ?
        ORDER BY m.meal_date, m.created_at
    ''', (user['id'],))
    rows = cur.fetchall()
    conn.close()
    if not rows:
        print('No meal records to export')
        return
    out_path = os.path.join(os.getcwd(), f'dietmate_export_{user["username"]}_{date.today().isoformat()}.csv')
    with open(out_path, 'w', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        writer.writerow(['date', 'meal_type', 'food_name', 'servings', 'cal_per_serv', 'total_calories'])
        for r in rows:
            writer.writerow([r['meal_date'], r['meal_type'], r['name'], r['servings'], r['calories_per_serving'], r['total_cal']])
    print(f'Exported to {out_path}')

# --- Settings ---

def set_calorie_goal(user):
    try:
        g = int(input(f'Enter new daily calorie goal (current {user["calorie_goal"]}): ').strip())
    except ValueError:
        print('Invalid number'); return
    conn = get_conn()
    cur = conn.cursor()
    cur.execute('UPDATE users SET calorie_goal = ? WHERE id = ?', (g, user['id']))
    conn.commit(); conn.close()
    user['calorie_goal'] = g
    print('Goal updated')

# --- Main loop ---

def main_menu(user):
    while True:
        print('\n--- DietMate Main Menu ---')
        print('1) Add food')
        print('2) List foods')
        print('3) Log a meal')
        print('4) View daily summary')
        print('5) Suggest meal plan')
        print('6) Export logs to CSV')
        print('7) Set calorie goal')
        print('8) Logout')
        choice = input('Choose: ').strip()
        if choice == '1':
            add_food(user)
        elif choice == '2':
            list_foods(user)
        elif choice == '3':
            log_meal(user)
        elif choice == '4':
            view_summary(user)
        elif choice == '5':
            suggest_meal_plan(user)
        elif choice == '6':
            export_csv(user)
        elif choice == '7':
            set_calorie_goal(user)
        elif choice == '8':
            print('Logging out...')
            break
        else:
            print('Invalid choice')


def welcome():
    print('Welcome to DietMate (CLI)')
    while True:
        print('\n1) Sign up')
        print('2) Login')
        print('3) Exit')
        c = input('Choose: ').strip()
        if c == '1':
            signup()
        elif c == '2':
            user = login()
            if user:
                main_menu(user)
        elif c == '3':
            print('Bye!')
            sys.exit(0)
        else:
            print('Invalid')

if __name__ == '__main__':
    init_db()
    try:
        welcome()
    except KeyboardInterrupt:
        print('\nInterrupted — exiting')
