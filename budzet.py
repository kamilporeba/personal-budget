import streamlit as st
import pandas as pd
import sqlite3
import plotly.express as px
from datetime import datetime, date
import os
import math

# Spróbuj zaimportować bibliotekę do PostgreSQL (dla chmury)
try:
    import psycopg2
except ImportError:
    pass

# --- KONFIGURACJA STRONY ---
st.set_page_config(page_title="Mój Budżet (YNAB Style)", page_icon="💰", layout="wide")

# --- CSS DLA LEPSZEGO WYGLĄDU ---
st.markdown("""
    <style>
    .metric-card {
        background-color: #f0f2f6;
        padding: 15px;
        border-radius: 10px;
        border-left: 5px solid #4CAF50;
    }
    .stProgress > div > div > div > div {
        background-color: #4CAF50;
    }
    .savings-card {
        border: 1px solid #e0e0e0;
        border-radius: 10px;
        padding: 20px;
        margin-bottom: 20px;
        background-color: #ffffff;
        box-shadow: 0 2px 4px rgba(0,0,0,0.05);
    }
    .login-container {
        max-width: 400px;
        margin: auto;
        padding: 50px;
        border: 1px solid #ddd;
        border-radius: 10px;
        background-color: #f9f9f9;
        text-align: center;
    }
    </style>
    """, unsafe_allow_html=True)

# --- KONFIGURACJA UŻYTKOWNIKÓW ---
USERS = {
    "Kamil": "Kamil",
    "Ania": "Ania"
}

# --- OBSŁUGA SESJI (LOGOWANIE) ---
if 'logged_in' not in st.session_state:
    st.session_state['logged_in'] = False
if 'username' not in st.session_state:
    st.session_state['username'] = None

def login():
    st.markdown("<div style='text-align: center;'><h1>🔐 BudgetFlow - Logowanie</h1></div>", unsafe_allow_html=True)
    
    col1, col2, col3 = st.columns([1, 2, 1])
    with col2:
        username = st.text_input("Użytkownik")
        password = st.text_input("Hasło", type="password")
        
        if st.button("Zaloguj się", use_container_width=True):
            if username in USERS and USERS[username] == password:
                st.session_state['logged_in'] = True
                st.session_state['username'] = username
                st.success(f"Witaj, {username}!")
                st.rerun()
            else:
                st.error("Błędny login lub hasło")

def logout():
    st.session_state['logged_in'] = False
    st.session_state['username'] = None
    st.rerun()

# --- OBSŁUGA BAZY DANYCH (HYBRYDOWA: SQLite + PostgreSQL) ---
DB_FILE = 'finanse.db'

# Sprawdzamy, czy w sekretach Streamlit jest URL do bazy danych (Supabase)
# Jeśli tak -> tryb CHMURA (PostgreSQL)
# Jeśli nie (lub błąd odczytu) -> tryb LOKALNY (SQLite)
IS_CLOUD_DB = False
try:
    # Dostęp do st.secrets może rzucić błąd, jeśli plik secrets.toml nie istnieje (lokalnie)
    if "DATABASE_URL" in st.secrets:
        IS_CLOUD_DB = True
except Exception:
    # Jeśli wystąpi błąd (np. brak pliku sekretów), zakładamy tryb lokalny
    pass

def get_connection():
    """Tworzy połączenie z odpowiednią bazą danych"""
    if IS_CLOUD_DB:
        return psycopg2.connect(st.secrets["DATABASE_URL"])
    else:
        return sqlite3.connect(DB_FILE)

def run_query(query, params=(), fetch=False):
    """
    Uniwersalna funkcja do SQL. 
    Automatycznie zamienia ? na %s jeśli używamy PostgreSQL.
    """
    conn = get_connection()
    c = conn.cursor()
    
    # Konwersja składni z SQLite (?) na Postgres (%s)
    if IS_CLOUD_DB:
        query = query.replace('?', '%s')
        
    try:
        c.execute(query, params)
        if fetch:
            data = c.fetchall()
            # W Postgres kolumny są zwracane jako tuple, nazwy kolumn trzeba pobrać osobno
            # Ale dla zgodności z kodem pandas.read_sql, tutaj zwracamy surowe dane
            # Pandas obsłuży to w get_transactions_df
            return data
        conn.commit()
    except Exception as e:
        st.error(f"Błąd bazy danych: {e}")
    finally:
        conn.close()

def init_db_structure():
    """Tworzy tabele jeśli nie istnieją (działa na obu bazach)"""
    conn = get_connection()
    c = conn.cursor()
    
    # Składnia SQL dla obu baz jest podobna dla CREATE TABLE
    # Używamy typów danych kompatybilnych (TEXT, REAL, INTEGER)
    
    # 1. Tabela transactions
    c.execute('''CREATE TABLE IF NOT EXISTS transactions (
                    id SERIAL PRIMARY KEY,
                    date TEXT,
                    amount REAL,
                    category TEXT,
                    description TEXT,
                    type TEXT,
                    subcategory TEXT DEFAULT 'Ogólne',
                    user_id TEXT DEFAULT 'Kamil'
                )''' if IS_CLOUD_DB else '''CREATE TABLE IF NOT EXISTS transactions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    date TEXT,
                    amount REAL,
                    category TEXT,
                    description TEXT,
                    type TEXT,
                    subcategory TEXT DEFAULT 'Ogólne',
                    user_id TEXT DEFAULT 'Kamil'
                )''')
    
    # 2. Tabela monthly_budgets
    c.execute('''CREATE TABLE IF NOT EXISTS monthly_budgets (
                    user_id TEXT,
                    category TEXT,
                    subcategory TEXT,
                    month INTEGER,
                    year INTEGER,
                    limit_amount REAL,
                    PRIMARY KEY (user_id, category, subcategory, month, year)
                )''')

    # 3. Tabela savings_goals
    c.execute('''CREATE TABLE IF NOT EXISTS savings_goals (
                    id SERIAL PRIMARY KEY,
                    name TEXT,
                    target_amount REAL,
                    deadline TEXT,
                    linked_category TEXT,
                    linked_subcategory TEXT,
                    user_id TEXT
                )''' if IS_CLOUD_DB else '''CREATE TABLE IF NOT EXISTS savings_goals (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT,
                    target_amount REAL,
                    deadline TEXT,
                    linked_category TEXT,
                    linked_subcategory TEXT,
                    user_id TEXT
                )''')

    conn.commit()
    conn.close()

# Inicjalizacja przy starcie
# Jeśli plik lokalny nie istnieje (a jesteśmy lokalnie) lub zawsze w chmurze
if IS_CLOUD_DB:
    init_db_structure()
elif not os.path.exists(DB_FILE):
    init_db_structure()
else:
    # Lokalnie uruchamiamy migrację/init dla pewności
    init_db_structure()

# Jeśli nie zalogowany, pokaż login i przerwij
if not st.session_state['logged_in']:
    login()
    st.stop()

# --- ZMIENNA GLOBALNA: AKTUALNY UŻYTKOWNIK ---
CURRENT_USER = st.session_state['username']

# --- FUNKCJE POMOCNICZE (Z FILTROWANIEM PO USERZE) ---
def get_transactions_df():
    conn = get_connection()
    query = "SELECT * FROM transactions WHERE user_id = ? ORDER BY date DESC"
    if IS_CLOUD_DB: query = query.replace('?', '%s')
    
    # pandas.read_sql_query wymaga obiektu połączenia
    # Dla psycopg2 (postgres) i sqlite3 działa tak samo
    try:
        df = pd.read_sql_query(query, conn, params=(CURRENT_USER,))
    finally:
        conn.close()
    
    # Konwersja daty i obsługa brakujących kolumn
    if 'date' in df.columns and not df.empty:
        df['date'] = pd.to_datetime(df['date'])
    
    if not df.empty:
        if 'subcategory' not in df.columns:
            df['subcategory'] = 'Ogólne'
        df['subcategory'] = df['subcategory'].fillna('Ogólne')
    
    # Jeśli DataFrame jest pusty, ale ma kolumny, pandas czasem nie ustawia typów
    # Zwracamy pusty DF z odpowiednimi kolumnami jeśli trzeba, ale logika UI to obsłuży
    return df

def get_budget_for_month(month, year):
    conn = get_connection()
    query = "SELECT category, subcategory, limit_amount FROM monthly_budgets WHERE month = ? AND year = ? AND user_id = ?"
    if IS_CLOUD_DB: query = query.replace('?', '%s')
    
    try:
        df = pd.read_sql_query(query, conn, params=(month, year, CURRENT_USER))
    finally:
        conn.close()

    if not df.empty:
         df['subcategory'] = df['subcategory'].fillna('Ogólne')
    return df

def get_savings_goals_df():
    conn = get_connection()
    query = "SELECT * FROM savings_goals WHERE user_id = ? ORDER BY deadline ASC"
    if IS_CLOUD_DB: query = query.replace('?', '%s')
    
    try:
        df = pd.read_sql_query(query, conn, params=(CURRENT_USER,))
    finally:
        conn.close()

    if not df.empty and 'deadline' in df.columns:
        df['deadline'] = pd.to_datetime(df['deadline'])
    return df

def get_unique_categories_hierarchy():
    conn = get_connection()
    query_b = "SELECT DISTINCT category, subcategory FROM monthly_budgets WHERE user_id = ?"
    query_t = "SELECT DISTINCT category, subcategory FROM transactions WHERE user_id = ?"
    if IS_CLOUD_DB:
        query_b = query_b.replace('?', '%s')
        query_t = query_t.replace('?', '%s')
    
    try:
        df_b = pd.read_sql_query(query_b, conn, params=(CURRENT_USER,))
        df_t = pd.read_sql_query(query_t, conn, params=(CURRENT_USER,))
    finally:
        conn.close()
        
    df_all = pd.concat([df_b, df_t]).drop_duplicates().dropna()
    
    hierarchy = {}
    for _, row in df_all.iterrows():
        cat = row['category']
        sub = row['subcategory']
        if not sub: sub = "Ogólne"
        if cat not in hierarchy:
            hierarchy[cat] = set()
        hierarchy[cat].add(sub)
        
    for cat in hierarchy:
        hierarchy[cat] = sorted(list(hierarchy[cat]))
    return hierarchy

# --- UI APLIKACJI ---

# Sidebar Header z informacją o użytkowniku i trybie bazy
db_status = "☁️ Chmura" if IS_CLOUD_DB else "💾 Lokalna"
st.sidebar.markdown(f"👤 **{CURRENT_USER}** | {db_status}")
if st.sidebar.button("Wyloguj"):
    logout()
st.sidebar.divider()

st.title(f"💰 BudgetFlow")

# Pasek boczny nawigacji
menu = st.sidebar.radio("Menu", ["Dashboard", "Dodaj Transakcje / Import CSV", "Planowanie Budżetu", "Cele Oszczędnościowe", "Raport P&L"])

# --- GLOBALNE FILTRY DATY ---
current_month = datetime.now().month
current_year = datetime.now().year

# --- WIDOK 1: DASHBOARD ---
if menu == "Dashboard":
    st.header("📊 Twój Przegląd Finansowy")
    
    df_trans = get_transactions_df()
    
    col1, col2 = st.columns(2)
    with col1:
        month_filter = st.selectbox("Miesiąc", range(1, 13), index=current_month-1, key="dash_month")
    with col2:
        year_filter = st.selectbox("Rok", range(2023, 2030), index=0 if current_year == 2023 else current_year-2023, key="dash_year")

    df_budget_month = get_budget_for_month(month_filter, year_filter)

    if df_trans.empty:
        st.info("Brak transakcji. Dodaj pierwszą transakcję!")
    else:
        mask = (df_trans['date'].dt.month == month_filter) & (df_trans['date'].dt.year == year_filter)
        df_filtered = df_trans[mask]

        income = df_filtered[df_filtered['type'] == 'Wpływ']['amount'].sum()
        expenses = df_filtered[df_filtered['type'] == 'Wydatek']['amount'].sum()
        balance = income - expenses
        total_budgeted = df_budget_month['limit_amount'].sum() if not df_budget_month.empty else 0

        kpi1, kpi2, kpi3, kpi4 = st.columns(4)
        kpi1.metric("Wpływy", f"{income:.2f} PLN")
        kpi2.metric("Wydatki", f"{expenses:.2f} PLN", delta_color="inverse")
        kpi3.metric("Zaplanowano", f"{total_budgeted:.2f} PLN")
        kpi4.metric("Bilans", f"{balance:.2f} PLN", delta=f"{balance:.2f} PLN")

        st.divider()

        c1, c2 = st.columns([2, 1])

        with c1:
            st.subheader(f"Realizacja Budżetu ({month_filter}/{year_filter})")
            
            expenses_grouped = df_filtered[df_filtered['type'] == 'Wydatek'].groupby(['category', 'subcategory'])['amount'].sum().reset_index()
            
            if not df_budget_month.empty:
                merged = pd.merge(df_budget_month, expenses_grouped, on=['category', 'subcategory'], how='left').fillna(0)
                merged.rename(columns={'amount': 'spent', 'limit_amount': 'budget'}, inplace=True)
                merged = merged.sort_values(by=['category', 'subcategory'])

                if not merged.empty:
                    merged['percent'] = (merged['spent'] / merged['budget']) * 100
                    merged['percent'] = merged['percent'].fillna(0)
                    
                    current_cat = ""
                    for index, row in merged.iterrows():
                        if row['category'] != current_cat:
                            st.markdown(f"##### 📂 {row['category']}")
                            current_cat = row['category']
                        
                        col_text, col_bar = st.columns([2, 3])
                        with col_text:
                            st.write(f"↳ {row['subcategory']}")
                            left = row['budget'] - row['spent']
                            st.caption(f"{row['spent']:.0f} / {row['budget']:.0f} PLN (Zostało: {left:.0f})")
                        with col_bar:
                            val = min(row['percent'] / 100, 1.0)
                            st.progress(val, text=f"{row['percent']:.1f}%")
                else:
                    st.info("Brak zdefiniowanych kategorii.")
            else:
                st.warning("Nie zdefiniowano budżetu.")

        with c2:
            st.subheader("Struktura Wydatków")
            if not df_filtered.empty and expenses > 0:
                expenses_only = df_filtered[df_filtered['type'] == 'Wydatek']
                
                # WYKRES SUNBURST
                fig = px.sunburst(expenses_only, path=['category', 'subcategory'], values='amount', color='category')
                st.plotly_chart(fig, use_container_width=True)
                
                # TABELA PROCENTOWA
                expenses_by_main = expenses_only.groupby('category')['amount'].sum().reset_index()
                expenses_by_main['Udział %'] = (expenses_by_main['amount'] / expenses * 100)
                
                st.divider()
                st.markdown("###### Udział w budżecie (Kategorie Główne)")
                st.dataframe(
                    expenses_by_main.sort_values('amount', ascending=False).style.format({
                        'amount': '{:.2f} PLN', 
                        'Udział %': '{:.1f}%'
                    }),
                    use_container_width=True,
                    hide_index=True,
                    column_config={"category": "Kategoria", "amount": "Kwota"}
                )
            else:
                st.write("Brak wydatków.")

# --- WIDOK 2: TRANSAKCJE ---
elif menu == "Dodaj Transakcje / Import CSV":
    
    hierarchy = get_unique_categories_hierarchy()
    main_categories = sorted(list(hierarchy.keys()))
    if not main_categories: main_categories = ["Inne"]

    tab1, tab2 = st.tabs(["✍️ Ręczne Dodawanie", "📂 Import CSV"])

    with tab1:
        st.subheader("Nowa Transakcja")
        
        st.info("Najpierw wybierz kategorię, aby zobaczyć dostępne subkategorie (lub wpisz nowe).")
        col_c1, col_c2 = st.columns(2)
        with col_c1:
            sel_category = st.selectbox("Wybierz Kategorię Główną", ["Nowa Kategoria..."] + main_categories)
            if sel_category == "Nowa Kategoria...":
                final_category = st.text_input("Wpisz nazwę nowej kategorii")
            else:
                final_category = sel_category
        
        with col_c2:
            available_subs = hierarchy.get(sel_category, [])
            sel_subcategory = st.selectbox("Wybierz Subkategorię", ["Nowa Subkategoria..."] + available_subs)
            if sel_subcategory == "Nowa Subkategoria...":
                final_subcategory = st.text_input("Wpisz nazwę nowej subkategorii")
            else:
                final_subcategory = sel_subcategory

        with st.form("main_trans_form", clear_on_submit=True):
            col_d1, col_d2 = st.columns(2)
            with col_d1:
                date = st.date_input("Data")
            with col_d2:
                amount = st.number_input("Kwota (PLN)", min_value=0.01, format="%.2f")
            
            desc = st.text_input("Opis / Sklep")
            trans_type = st.selectbox("Typ", ["Wydatek", "Wpływ"])
            
            submitted = st.form_submit_button("Dodaj Transakcję")
            if submitted:
                if not final_category: final_category = "Inne"
                if not final_subcategory: final_subcategory = "Ogólne"
                
                # Dodajemy user_id
                run_query("INSERT INTO transactions (date, amount, category, subcategory, description, type, user_id) VALUES (?, ?, ?, ?, ?, ?, ?)",
                          (date, amount, final_category, final_subcategory, desc, trans_type, CURRENT_USER))
                st.success(f"Dodano: {final_category} > {final_subcategory}")
                st.rerun()

    with tab2:
        st.subheader("Import CSV")
        uploaded_file = st.file_uploader("Wgraj plik CSV", type=['csv'])
        if uploaded_file:
            df_temp = pd.read_csv(uploaded_file, sep=None, engine='python')
            st.dataframe(df_temp.head())
            col_date = st.selectbox("Kolumna DATY", df_temp.columns)
            col_amount = st.selectbox("Kolumna KWOTY", df_temp.columns)
            col_desc = st.selectbox("Kolumna OPISU", df_temp.columns)
            
            def_cat = st.text_input("Domyślna kategoria", "Do kategoryzacji")
            def_sub = st.text_input("Domyślna subkategoria", "Import")

            if st.button("Importuj"):
                count = 0
                for i, row in df_temp.iterrows():
                    try:
                        p_date = pd.to_datetime(str(row[col_date])).strftime('%Y-%m-%d')
                        raw_amt = str(row[col_amount]).replace(' ', '').replace(',', '.').replace('\xa0', '')
                        amt = float(raw_amt)
                        t_type = "Wpływ" if amt > 0 else "Wydatek"
                        
                        # Import z user_id
                        run_query("INSERT INTO transactions (date, amount, category, subcategory, description, type, user_id) VALUES (?, ?, ?, ?, ?, ?, ?)",
                                  (p_date, abs(amt), def_cat, def_sub, row[col_desc], t_type, CURRENT_USER))
                        count += 1
                    except: pass
                st.success(f"Zaimportowano {count}!")
                st.rerun()

    st.divider()
    st.subheader("Edycja Transakcji")
    df_trans = get_transactions_df()
    if not df_trans.empty:
        edited_df = st.data_editor(
            df_trans[['id', 'date', 'category', 'subcategory', 'amount', 'description']],
            hide_index=True,
            key="editor"
        )
        if st.button("Zapisz zmiany w tabeli"):
            conn = get_connection()
            c = conn.cursor()
            
            update_query = "UPDATE transactions SET category=?, subcategory=?, description=? WHERE id=? AND user_id=?"
            if IS_CLOUD_DB: update_query = update_query.replace('?', '%s')
            
            try:
                for index, row in edited_df.iterrows():
                    c.execute(update_query, (row['category'], row['subcategory'], row['description'], row['id'], CURRENT_USER))
                conn.commit()
                st.success("Zapisano!")
                st.rerun()
            except Exception as e:
                st.error(f"Błąd zapisu: {e}")
            finally:
                conn.close()

# --- WIDOK 3: PLANOWANIE BUDŻETU ---
elif menu == "Planowanie Budżetu":
    st.header("🗂 Planowanie Budżetu (Subkategorie)")
    
    c1, c2, c3 = st.columns([1, 1, 2])
    with c1:
        plan_month = st.selectbox("Miesiąc", range(1, 13), index=current_month-1, key="p_m")
    with c2:
        plan_year = st.selectbox("Rok", range(2023, 2030), index=0 if current_year == 2023 else current_year-2023, key="p_y")
    with c3:
        st.write("")
        st.write("")
        if st.button("📥 Skopiuj budżet z poprzedniego miesiąca"):
            prev_m = plan_month - 1 if plan_month > 1 else 12
            prev_y = plan_year if plan_month > 1 else plan_year - 1
            prev_b = get_budget_for_month(prev_m, prev_y)
            if not prev_b.empty:
                cnt = 0
                for _, row in prev_b.iterrows():
                    run_query("INSERT INTO monthly_budgets (user_id, category, subcategory, month, year, limit_amount) VALUES (?, ?, ?, ?, ?, ?)",
                              (CURRENT_USER, row['category'], row['subcategory'], plan_month, plan_year, row['limit_amount']))
                    cnt += 1
                st.success(f"Skopiowano {cnt} pozycji!")
                st.rerun()

    st.divider()
    col1, col2 = st.columns([1, 2])
    
    with col1:
        st.subheader("Dodaj Pozycję Budżetową")
        with st.form("add_budget_item"):
            cat_in = st.text_input("Kategoria (np. Kredyty)")
            sub_in = st.text_input("Subkategoria (np. Auto)")
            lim_in = st.number_input("Limit (PLN)", min_value=0.0)
            if st.form_submit_button("Dodaj / Aktualizuj"):
                if cat_in and sub_in:
                    # Używamy INSERT (jeśli używamy ON CONFLICT to składnia Postgres jest inna niż SQLite)
                    # Dla uproszczenia w multi-db: Najpierw DELETE potem INSERT (brzydkie ale skuteczne na obu)
                    run_query("DELETE FROM monthly_budgets WHERE user_id=? AND category=? AND subcategory=? AND month=? AND year=?",
                              (CURRENT_USER, cat_in, sub_in, plan_month, plan_year))
                    
                    run_query("INSERT INTO monthly_budgets (user_id, category, subcategory, month, year, limit_amount) VALUES (?, ?, ?, ?, ?, ?)",
                              (CURRENT_USER, cat_in, sub_in, plan_month, plan_year, lim_in))
                    st.success("Zapisano!")
                    st.rerun()
                else:
                    st.warning("Podaj kategorię i subkategorię")

    with col2:
        st.subheader(f"Budżet na {plan_month}/{plan_year}")
        df_plan = get_budget_for_month(plan_month, plan_year)
        if not df_plan.empty:
            # Sortowanie
            df_plan = df_plan.sort_values(by=['category', 'subcategory'])
            edited_plan = st.data_editor(df_plan, use_container_width=True, hide_index=True)
            
            if st.button("Zapisz zmiany limitów"):
                for _, row in edited_plan.iterrows():
                    # DELETE + INSERT (Uniwersalne)
                    run_query("DELETE FROM monthly_budgets WHERE user_id=? AND category=? AND subcategory=? AND month=? AND year=?",
                              (CURRENT_USER, row['category'], row['subcategory'], plan_month, plan_year))
                    
                    run_query("INSERT INTO monthly_budgets (user_id, category, subcategory, month, year, limit_amount) VALUES (?, ?, ?, ?, ?, ?)",
                              (CURRENT_USER, row['category'], row['subcategory'], plan_month, plan_year, row['limit_amount']))
                st.success("Zaktualizowano!")
                st.rerun()
            
            # Usuwanie
            st.divider()
            to_del = st.selectbox("Wybierz pozycję do usunięcia", 
                                  df_plan.apply(lambda x: f"{x['category']} - {x['subcategory']}", axis=1))
            if st.button("Usuń"):
                cat_d, sub_d = to_del.split(" - ", 1)
                run_query("DELETE FROM monthly_budgets WHERE user_id=? AND category=? AND subcategory=? AND month=? AND year=?",
                          (CURRENT_USER, cat_d, sub_d, plan_month, plan_year))
                st.rerun()

# --- WIDOK 4: CELE OSZCZĘDNOŚCIOWE ---
elif menu == "Cele Oszczędnościowe":
    st.header("🎯 Cele Oszczędnościowe (Savings Goals)")
    st.markdown("Zdefiniuj swoje cele. Trafią one automatycznie do kategorii **'Cele'** w Twoim budżecie.")

    # Pobieranie danych
    goals_df = get_savings_goals_df()
    df_trans = get_transactions_df() # Potrzebne do śledzenia wpłat

    # --- FORMULARZ DODAWANIA CELU ---
    with st.expander("➕ Dodaj Nowy Cel", expanded=not goals_df.empty):
        with st.form("new_goal_form"):
            c1, c2 = st.columns(2)
            with c1:
                # Uproszczone: Nazwa celu to jednocześnie subkategoria
                goal_name = st.text_input("Nazwa Celu / Subkategorii (np. Wakacje, Komunia)")
                target_amount = st.number_input("Kwota Docelowa (PLN)", min_value=1.0)
            
            with c2:
                deadline = st.date_input("Termin realizacji", value=datetime(current_year+1, 1, 1))
                st.info("Ten cel zostanie automatycznie przypisany do kategorii głównej **Cele**.")

            if st.form_submit_button("Zapisz Cel"):
                if goal_name and target_amount > 0:
                    # Stała kategoria "Cele"
                    cat_val = "Cele"
                    sub_val = goal_name
                    
                    # 1. Zapis do tabeli celów (Z USER_ID)
                    run_query("INSERT INTO savings_goals (name, target_amount, deadline, linked_category, linked_subcategory, user_id) VALUES (?, ?, ?, ?, ?, ?)",
                              (goal_name, target_amount, deadline, cat_val, sub_val, CURRENT_USER))
                    
                    # 2. Synchronizacja z budżetem
                    exists = run_query("SELECT 1 FROM monthly_budgets WHERE user_id=? AND category=? AND subcategory=? AND month=? AND year=?", 
                                     (CURRENT_USER, cat_val, sub_val, current_month, current_year), fetch=True)
                    
                    if not exists:
                        run_query("INSERT INTO monthly_budgets (user_id, category, subcategory, month, year, limit_amount) VALUES (?, ?, ?, ?, ?, ?)", 
                                  (CURRENT_USER, cat_val, sub_val, current_month, current_year, 0.0))
                        st.toast(f"Zsynchronizowano z budżetem: {cat_val} > {sub_val}")

                    st.success(f"Dodano cel: {goal_name}")
                    st.rerun()
                else:
                    st.error("Uzupełnij nazwę i kwotę!")

    st.divider()

    # --- LISTA CELÓW I POSTĘPY ---
    if goals_df.empty:
        st.info("Nie masz jeszcze zdefiniowanych celów oszczędnościowych.")
    else:
        st.subheader("Twoje Cele")
        
        for index, row in goals_df.iterrows():
            # 1. Obliczenie ile już odłożono (Suma wydatków w kategorii Cele > [Nazwa Celu])
            mask = (df_trans['category'] == row['linked_category']) & (df_trans['subcategory'] == row['linked_subcategory'])
            saved_so_far = df_trans[mask]['amount'].sum()
            
            # 2. Obliczenia czasu
            today = pd.Timestamp.now()
            target_date = row['deadline']
            
            # Różnica w miesiącach
            months_left = (target_date.year - today.year) * 12 + target_date.month - today.month
            if today.day > target_date.day:
                months_left -= 1 
            
            months_left = max(0, months_left)
            
            # 3. Ile brakuje
            remaining = row['target_amount'] - saved_so_far
            progress_pct = min(saved_so_far / row['target_amount'], 1.0) if row['target_amount'] > 0 else 0
            
            # 4. Miesięczna rata
            if months_left > 0 and remaining > 0:
                monthly_needed = remaining / months_left
            else:
                monthly_needed = 0

            # --- WYŚWIETLANIE KARTY CELU ---
            with st.container():
                st.markdown(f"""
                <div class="savings-card">
                    <h3>🎯 {row['name']}</h3>
                    <p style="color:gray; font-size:0.9em;">Kategoria budżetowa: <b>{row['linked_category']} > {row['linked_subcategory']}</b> | Termin: {target_date.strftime('%Y-%m-%d')}</p>
                </div>
                """, unsafe_allow_html=True)
                
                c1, c2, c3 = st.columns([2, 1, 1])
                with c1:
                    st.progress(progress_pct, text=f"Postęp: {progress_pct*100:.1f}%")
                    st.write(f"Odłożono: **{saved_so_far:,.2f} PLN** z {row['target_amount']:,.2f} PLN")
                
                with c2:
                    if remaining <= 0:
                        st.success("🎉 Cel osiągnięty!")
                    else:
                        st.metric("Brakuje", f"{remaining:,.2f} PLN")
                
                with c3:
                    if remaining > 0:
                        if months_left > 0:
                            st.metric("Odkładaj miesięcznie", f"{monthly_needed:,.2f} PLN", help=f"Przez {months_left} miesięcy")
                        else:
                            st.error("Termin minął!")
                    
                if st.button(f"Usuń cel: {row['name']}", key=f"del_goal_{row['id']}"):
                    run_query("DELETE FROM savings_goals WHERE id = ? AND user_id = ?", (row['id'], CURRENT_USER))
                    st.rerun()
            st.divider()

# --- WIDOK 5: RAPORT P&L ---
elif menu == "Raport P&L":
    st.header("📈 Statement of Income")
    
    # KROK 1: Pobieramy dane
    df_all = get_transactions_df()

    if df_all.empty:
        st.info("Brak danych transakcyjnych dla tego użytkownika. Dodaj pierwsze transakcje, aby zobaczyć raport.")
    else:
        # KROK 2: Konfiguracja (pokazujemy tylko jeśli są dane)
        with st.expander("Konfiguracja", expanded=True):
            c1, c2, c3 = st.columns(3)
            y_pl = st.selectbox("Rok", range(2023, 2031), index=0)
            p_type = st.radio("Okres", ["Miesiąc", "Rok"], horizontal=True)
            if p_type == "Miesiąc":
                m_pl = st.selectbox("Miesiąc", range(1, 13))
                mask = (df_all['date'].dt.year == y_pl) & (df_all['date'].dt.month == m_pl)
                lbl = f"{m_pl}/{y_pl}"
            else:
                mask = (df_all['date'].dt.year == y_pl)
                lbl = f"Rok {y_pl}"

        df_pl = df_all[mask]
        
        incomes = df_pl[df_pl['type'] == 'Wpływ']
        expenses = df_pl[df_pl['type'] == 'Wydatek']
        
        tot_inc = incomes['amount'].sum()
        tot_exp = expenses['amount'].sum()
        net = tot_inc - tot_exp
        
        # --- GENEROWANIE HTML ---
        style = """
        <style>
            .pnl-table { width: 100%; max-width: 800px; font-family: monospace; border-collapse: collapse; background: white; padding: 20px; box-shadow: 0 2px 5px rgba(0,0,0,0.1); }
            .pnl-row td { padding: 4px 10px; }
            .pnl-header { font-weight: bold; padding-top: 15px; font-size: 1.1em; }
            .cat-row td { font-weight: bold; padding-top: 10px; }
            .sub-row td:first-child { padding-left: 30px; color: #555; }
            .total-line { border-top: 1px solid #000; font-weight: bold; }
            .double-line { border-bottom: 4px double #000; font-weight: bold; font-size: 1.2em; }
            .text-right { text-align: right; }
        </style>
        """
        
        html = f"{style}<div style='display:flex;justify-content:center'><table class='pnl-table'>"
        
        # INCOME
        html += "<tr><td colspan='3' class='pnl-header'>Income</td></tr>"
        if not incomes.empty:
            # Grupowanie
            inc_g = incomes.groupby(['category', 'subcategory'])['amount'].sum().reset_index()
            cats = inc_g['category'].unique()
            for c in cats:
                c_sum = inc_g[inc_g['category'] == c]['amount'].sum()
                html += f"<tr class='cat-row'><td>{c}</td><td></td><td class='text-right'>{c_sum:,.2f}</td></tr>"
                subs = inc_g[inc_g['category'] == c]
                for _, r in subs.iterrows():
                    html += f"<tr class='sub-row'><td>{r['subcategory']}</td><td class='text-right'>{r['amount']:,.2f}</td><td></td></tr>"
        
        html += f"<tr><td></td><td class='total-line'>Total Income</td><td class='text-right total-line'>{tot_inc:,.2f}</td></tr>"
        
        # EXPENSES
        html += "<tr><td colspan='3' class='pnl-header'>Less: Expenses</td></tr>"
        if not expenses.empty:
            exp_g = expenses.groupby(['category', 'subcategory'])['amount'].sum().reset_index()
            cats = exp_g['category'].unique()
            for c in cats:
                c_sum = exp_g[exp_g['category'] == c]['amount'].sum()
                # Wiersz kategorii
                html += f"<tr class='cat-row'><td>{c}</td><td></td><td class='text-right'>{c_sum:,.2f}</td></tr>"
                # Wiersze subkategorii
                subs = exp_g[exp_g['category'] == c]
                for _, r in subs.iterrows():
                    html += f"<tr class='sub-row'><td>{r['subcategory']}</td><td class='text-right'>{r['amount']:,.2f}</td><td></td></tr>"

        html += f"<tr><td></td><td class='total-line'>Total Expenses</td><td class='text-right total-line'>{tot_exp:,.2f}</td></tr>"
        
        # NET PROFIT
        html += f"<tr><td class='pnl-header'>Net Profit</td><td></td><td class='text-right double-line'>{net:,.2f}</td></tr>"
        html += "</table></div>"
        
        st.markdown(html, unsafe_allow_html=True)