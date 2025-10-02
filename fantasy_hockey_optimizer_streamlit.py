
import streamlit as st
import datetime
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from collections import defaultdict
import itertools
import os
import gspread
from google.oauth2.service_account import Credentials

# Aseta sivun konfiguraatio
st.set_page_config(
    page_title="Fantasy Hockey Optimizer (APL)",
    page_icon="🏒",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Tiedostonimet
SCHEDULE_FILE = 'nhl_schedule_saved.csv'
ROSTER_FILE = 'my_roster_saved.csv'
OPPONENT_ROSTER_FILE = 'opponent_roster_saved.csv'

# Alusta session muuttujat
if 'schedule' not in st.session_state:
    st.session_state['schedule'] = pd.DataFrame()
if 'roster' not in st.session_state:
    st.session_state['roster'] = pd.DataFrame(columns=['name', 'team', 'positions', 'fantasy_points_avg'])
if 'opponent_roster' not in st.session_state:
    st.session_state['opponent_roster'] = pd.DataFrame(columns=['name', 'team', 'positions', 'fantasy_points_avg'])
if 'team_impact_results' not in st.session_state:
    st.session_state['team_impact_results'] = None

# --- GOOGLE SHEETS LATAUSFUNKTIOT ---
@st.cache_resource
def get_gspread_client():
    try:
        scopes = ['https://www.googleapis.com/auth/spreadsheets']
        creds_json = st.secrets["gcp_service_account"]
        creds = Credentials.from_service_account_info(creds_json, scopes=scopes)
        client = gspread.authorize(creds)
        return client
    except Exception as e:
        st.error(f"Virhe Google Sheets -tunnistautumisessa. Tarkista secrets.toml-tiedostosi: {e}")
        return None

def load_roster_from_gsheets():
    client = get_gspread_client()
    if client is None:
        st.error("Google Sheets -asiakas ei ole käytettävissä. Tarkista tunnistautuminen.")
        return pd.DataFrame()
    try:
        # 🔹 Käytetään samaa taulukkoa kuin free agents -data
        sheet_url = st.secrets["free_agents_sheet"]["url"]
        sheet = client.open_by_url(sheet_url)

        # 🔹 Avataan nimenomaan välilehti "ZeroxG"
        worksheet = sheet.worksheet("ZeroxG")

        # 🔹 Luetaan tiedot
        data = worksheet.get_all_records()
        df = pd.DataFrame(data)

        if df.empty:
            st.warning("⚠️ 'ZeroxG' välilehti on tyhjä tai sitä ei löytynyt.")
            return pd.DataFrame()

        # 🔹 Normalisoidaan sarakenimet
        df.columns = df.columns.str.strip().str.lower()

        # 🔹 Varmistetaan vaaditut sarakkeet
        required_columns = ['name', 'team', 'positions', 'fantasy_points_avg']
        missing_columns = [col for col in required_columns if col not in df.columns]
        if missing_columns:
            st.error(f"Seuraavat sarakkeet puuttuvat rosterivälilehdeltä 'ZeroxG': {', '.join(missing_columns)}")
            st.write("Löydetyt sarakkeet:", df.columns.tolist())
            return pd.DataFrame()

        # 🔹 Muunnetaan FP numeeriseksi ja täytetään puuttuvat nollalla
        df['fantasy_points_avg'] = pd.to_numeric(df['fantasy_points_avg'], errors='coerce').fillna(0)

        # 🔹 Palautetaan vain tarvittavat sarakkeet
        df = df[required_columns]

        st.success(f"Rosterivälilehti 'ZeroxG' ladattu: {len(df)} riviä.")
        return df

    except Exception as e:
        st.error(f"Virhe rosterin Google Sheets -tiedoston lukemisessa: {e}")
        return pd.DataFrame()

def load_opponent_roster_from_gsheets(selected_team_name: str) -> pd.DataFrame:
    """
    Lataa valitun vastustajan rosterin Google Sheets -välilehdeltä 'T2 Lindgren Roster'
    samasta tiedostosta kuin oma rosteri.
    """
    client = get_gspread_client()
    if client is None:
        st.error("Google Sheets -asiakas ei ole käytettävissä. Tarkista tunnistautuminen.")
        return pd.DataFrame()
    try:
        # Käytetään samaa tiedostoa kuin oma rosteri
        sheet_url = st.secrets["free_agents_sheet"]["url"]
        sheet = client.open_by_url(sheet_url)
        worksheet = sheet.worksheet("T2 Lindgren Roster")

        # Lataa data
        data = worksheet.get_all_records()
        df = pd.DataFrame(data)
        if df.empty:
            st.warning("Välilehti 'T2 Lindgren Roster' on tyhjä.")
            return pd.DataFrame()

        # Normalisoidaan sarakenimet
        df.columns = df.columns.str.strip().str.lower()

        # Varmistetaan että tarvittavat sarakkeet löytyvät
        required = ["fantasy team", "player name", "position(s)", "nhl team", "fp"]
        missing = [c for c in required if c not in df.columns]
        if missing:
            st.error(f"Puuttuvia sarakkeita 'T2 Lindgren Roster' -välilehdeltä: {missing}")
            st.write("Löydetyt sarakkeet:", df.columns.tolist())
            return pd.DataFrame()

        # Suodatetaan valitun joukkueen mukaan
        team_df = df[df["fantasy team"] == selected_team_name].copy()
        if team_df.empty:
            st.warning(f"Joukkueella '{selected_team_name}' ei löytynyt pelaajia.")
            return pd.DataFrame()

        # Muutetaan sarakenimet sovelluksen logiikkaan sopiviksi
        team_df = team_df.rename(columns={
            "player name": "name",
            "nhl team": "team",
            "position(s)": "positions",
            "fp": "fantasy_points_avg"
        })

        # Muutetaan FP numeroksi
        team_df["fantasy_points_avg"] = pd.to_numeric(team_df["fantasy_points_avg"], errors="coerce").fillna(0)

        # Säilytetään vain oleelliset sarakkeet
        team_df = team_df[["name", "team", "positions", "fantasy_points_avg"]]

        return team_df

    except Exception as e:
        st.error(f"Virhe vastustajan rosterin lataamisessa: {e}")
        return pd.DataFrame()



def load_free_agents_from_gsheets():
    client = get_gspread_client()
    if client is None:
        return pd.DataFrame()
    try:
        sheet_url = st.secrets["free_agents_sheet"]["url"]
        sheet = client.open_by_url(sheet_url)

        # Avataan nimenomaan "FA" välilehti
        worksheet = sheet.worksheet("FA")
        data = worksheet.get_all_records()
        df = pd.DataFrame(data)

        if df.empty:
            st.warning("⚠️ FA-välilehti on tyhjä tai sitä ei löytynyt.")
            return pd.DataFrame()

        # ✅ Normalisoidaan sarakenimet pieniksi kirjaimiksi
        df.columns = df.columns.str.strip().str.lower()

        # ✅ Sallitaan vaihtoehtoiset sarakenimet
        rename_map = {}
        if 'fp' in df.columns:
            rename_map['fp'] = 'fantasy_points_avg'
        elif 'fp/gp' in df.columns:
            rename_map['fp/gp'] = 'fantasy_points_avg'

        if 'player name' in df.columns:
            rename_map['player name'] = 'name'

        if rename_map:
            df = df.rename(columns=rename_map)

        required_columns = ['name', 'team', 'positions', 'fantasy_points_avg']
        missing_columns = [col for col in required_columns if col not in df.columns]
        if missing_columns:
            st.error(f"Seuraavat sarakkeet puuttuvat vapaiden agenttien tiedostosta: {', '.join(missing_columns)}")
            st.dataframe(df.head())  # näyttää mitä sarakkeita oikeasti löytyi
            return pd.DataFrame()

        # Muutetaan FP numeroksi
        df['fantasy_points_avg'] = pd.to_numeric(df['fantasy_points_avg'], errors='coerce')

        # Poistetaan rivit, joilta puuttuu pelipaikka
        df = df[df['positions'].notna() & (df['positions'].str.strip() != '')]

        # Täytetään puuttuvat FP:t nollalla
        df['fantasy_points_avg'] = df['fantasy_points_avg'].fillna(0)

        # Järjestetään sarakkeet
        df = df[required_columns]

        return df

    except Exception as e:
        st.error(f"Virhe vapaiden agenttien Google Sheets -tiedoston lukemisessa: {e}")
        return pd.DataFrame()


# --- SIVUPALKKI: TIEDOSTOJEN LATAUS ---
st.sidebar.header("📁 Tiedostojen lataus")

if st.sidebar.button("Tyhjennä kaikki välimuisti"):
    st.cache_data.clear()
    st.session_state['schedule'] = pd.DataFrame()
    st.session_state['roster'] = pd.DataFrame(columns=['name', 'team', 'positions', 'fantasy_points_avg'])
    st.session_state['opponent_roster'] = pd.DataFrame(columns=['name', 'team', 'positions', 'fantasy_points_avg'])
    st.sidebar.success("Välimuisti tyhjennetty!")
    st.rerun()

# Peliaikataulun lataus
schedule_file_exists = False
try:
    st.session_state['schedule'] = pd.read_csv(SCHEDULE_FILE)
    st.session_state['schedule']['Date'] = pd.to_datetime(st.session_state['schedule']['Date'])
    schedule_file_exists = True
except FileNotFoundError:
    schedule_file_exists = False

if schedule_file_exists and not st.sidebar.button("Lataa uusi aikataulu", key="upload_schedule_button"):
    st.sidebar.success("Peliaikataulu ladattu automaattisesti tallennetusta tiedostosta!")
else:
    schedule_file = st.sidebar.file_uploader(
        "Lataa NHL-peliaikataulu (CSV)",
        type=["csv"],
        help="CSV-tiedoston tulee sisältää sarakkeet: Date, Visitor, Home"
    )
    if schedule_file is not None:
        try:
            schedule = pd.read_csv(schedule_file)
            if not schedule.empty and all(col in schedule.columns for col in ['Date', 'Visitor', 'Home']):
                schedule['Date'] = pd.to_datetime(schedule['Date'])
                st.session_state['schedule'] = schedule
                schedule.to_csv(SCHEDULE_FILE, index=False)
                st.sidebar.success("Peliaikataulu ladattu ja tallennettu!")
                st.rerun()
            else:
                st.sidebar.error("Peliaikataulun CSV-tiedoston tulee sisältää sarakkeet: Date, Visitor, Home")
        except Exception as e:
            st.sidebar.error(f"Virhe peliaikataulun lukemisessa: {str(e)}")

# Rosterin lataus
st.sidebar.subheader("Lataa oma rosteri")
if st.sidebar.button("Lataa rosteri Google Sheetsistä", key="roster_button"):
    try:
        roster_df = load_roster_from_gsheets()
        if not roster_df.empty:
            st.session_state['roster'] = roster_df
            st.sidebar.success("Rosteri ladattu onnistuneesti Google Sheetsistä!")
            roster_df.to_csv(ROSTER_FILE, index=False)
        else:
            st.sidebar.error("Rosterin lataaminen epäonnistui. Tarkista Google Sheet -tiedoston sisältö.")
    except Exception as e:
        st.sidebar.error(f"Virhe rosterin lataamisessa: {e}")
    st.rerun()

# Vapaiden agenttien lataus
st.sidebar.subheader("Lataa vapaat agentit")
if st.sidebar.button("Lataa vapaat agentit Google Sheetsistä", key="free_agents_button_new"):
    try:
        free_agents_df = load_free_agents_from_gsheets()
        if not free_agents_df.empty:
            st.session_state['free_agents'] = free_agents_df
            st.sidebar.success("Vapaat agentit ladattu onnistuneesti!")
        else:
            st.sidebar.error("Vapaiden agenttien lataaminen epäonnistui. Tarkista Google Sheet -tiedoston sisältö.")
    except Exception as e:
        st.sidebar.error(f"Virhe vapaiden agenttien lataamisessa: {e}")
    st.rerun()

# Vastustajan rosterin lataus - KORJATTU VERSIO
st.sidebar.subheader("Lataa vastustajan rosteri")

# --- Vastustajan rosterin lataus Google Sheetistä ---
st.sidebar.subheader("📋 Lataa vastustajan rosteri")

client = get_gspread_client()
available_teams = []
if client:
    try:
        sheet_url = st.secrets["free_agents_sheet"]["url"]
        sheet = client.open_by_url(sheet_url)
        worksheet = sheet.worksheet("T2 Lindgren Roster")
        data = worksheet.get_all_records()
        df_vs = pd.DataFrame(data)
        if not df_vs.empty:
            df_vs.columns = df_vs.columns.str.strip().str.lower()
            if "fantasy team" in df_vs.columns:
                available_teams = sorted(df_vs["fantasy team"].dropna().unique().tolist())
    except Exception as e:
        st.sidebar.error(f"Virhe joukkueiden lataamisessa: {e}")

if available_teams:
    selected_opponent_team = st.sidebar.selectbox("Valitse vastustajan joukkue", [""] + available_teams)
    if selected_opponent_team and st.sidebar.button("Lataa valitun joukkueen rosteri"):
        opponent_df = load_opponent_roster_from_gsheets(selected_opponent_team)
        if not opponent_df.empty:
            st.session_state["opponent_roster"] = opponent_df
            st.sidebar.success(f"{selected_opponent_team} rosteri ladattu onnistuneesti! ({len(opponent_df)} pelaajaa)")
            st.dataframe(opponent_df)
        else:
            st.sidebar.error("Vastustajan rosterin lataus epäonnistui tai tulos on tyhjä.")
else:
    st.sidebar.warning("Ei joukkueita ladattavissa. Tarkista välilehti 'T2 Lindgren Roster'.")

# Nollauspainike
if st.sidebar.button("Nollaa vastustajan rosteri"):
    st.session_state["opponent_roster"] = None
    st.sidebar.info("Vastustajan rosteri nollattu.")


# --- SIVUPALKKI: ROSTERIN HALLINTA ---
st.sidebar.header("👥 Rosterin hallinta")

# Tyhjennä rosteri -painike
if st.sidebar.button("Tyhjennä koko oma rosteri", key="clear_roster_button"):
    st.session_state['roster'] = pd.DataFrame(columns=['name', 'team', 'positions', 'fantasy_points_avg'])
    if os.path.exists(ROSTER_FILE):
        os.remove(ROSTER_FILE)
    st.sidebar.success("Oma rosteri tyhjennetty!")
    st.rerun()

if not st.session_state['roster'].empty:
    st.sidebar.subheader("Nykyinen oma rosteri")
    st.sidebar.dataframe(st.session_state['roster'], use_container_width=True)

    # Poista pelaaja -valikko ja -painike
    remove_player = st.sidebar.selectbox(
        "Poista pelaaja",
        [""] + list(st.session_state['roster']['name']),
        key="remove_player_select"
    )
    if st.sidebar.button("Poista valittu pelaaja", key="remove_player_button") and remove_player:
        st.session_state['roster'] = st.session_state['roster'][
            st.session_state['roster']['name'] != remove_player
        ]
        if 'fantasy_points_avg' in st.session_state['roster'].columns:
            st.session_state['roster'].to_csv(ROSTER_FILE, index=False)
        else:
            st.session_state['roster'].to_csv(ROSTER_FILE, index=False, columns=['name', 'team', 'positions'])
        st.sidebar.success(f"Pelaaja {remove_player} poistettu!")
        st.rerun()

    # Lisää uusi pelaaja -lomake
    st.sidebar.subheader("Lisää uusi pelaaja")
    with st.sidebar.form("add_player_form"):
        new_name = st.text_input("Pelaajan nimi")
        new_team = st.text_input("Joukkue")
        new_positions = st.text_input("Pelipaikat (esim. C/LW)")
        new_fpa = st.number_input("FP/GP (Valinnainen)", min_value=0.0, step=0.1, format="%.2f")
        submitted = st.form_submit_button("Lisää pelaaja")

        if submitted and new_name and new_team and new_positions:
            new_player = pd.DataFrame({
                'name': [new_name],
                'team': [new_team],
                'positions': [new_positions],
                'fantasy_points_avg': [new_fpa]
            })
            if 'fantasy_points_avg' not in st.session_state['roster'].columns:
                st.session_state['roster']['fantasy_points_avg'] = 0.0
            st.session_state['roster'] = pd.concat([
                st.session_state['roster'],
                new_player
            ], ignore_index=True)
            st.session_state['roster'].to_csv(ROSTER_FILE, index=False)
            st.sidebar.success(f"Pelaaja {new_name} lisätty!")
            st.rerun()

# --- SIVUPALKKI: ASETUKSET ---
st.sidebar.header("⚙️ Asetukset")

st.sidebar.subheader("Aikaväli")
today = datetime.now().date()
two_weeks_from_now = today + timedelta(days=14)

start_date = st.sidebar.date_input("Alkupäivä", today)
end_date = st.sidebar.date_input("Loppupäivä", two_weeks_from_now)

if start_date > end_date:
    st.sidebar.error("Aloituspäivä ei voi olla loppupäivän jälkeen")

st.sidebar.subheader("Pelipaikkojen rajoitukset")
col1, col2 = st.sidebar.columns(2)
with col1:
    c_limit = st.number_input("Hyökkääjät (C)", min_value=1, max_value=6, value=3, key="c_limit")
    lw_limit = st.number_input("Vasen laitahyökkääjä (LW)", min_value=1, max_value=6, value=3, key="lw_limit")
    rw_limit = st.number_input("Oikea laitahyökkääjä (RW)", min_value=1, max_value=6, value=3, key="rw_limit")

with col2:
    d_limit = st.number_input("Puolustajat (D)", min_value=1, max_value=8, value=4, key="d_limit")
    g_limit = st.number_input("Maalivahdit (G)", min_value=1, max_value=4, value=2, key="g_limit")
    util_limit = st.number_input("UTIL-paikat", min_value=0, max_value=3, value=1, key="util_limit")

pos_limits = {
    'C': c_limit,
    'LW': lw_limit,
    'RW': rw_limit,
    'D': d_limit,
    'G': g_limit,
    'UTIL': util_limit
}

# --- PÄÄSIVU: OPTIMOINTIFUNKTIO ---
def optimize_roster_advanced(schedule_df, roster_df, limits, num_attempts=100):
    players_info = {}
    for _, player in roster_df.iterrows():
        positions_str = player['positions']
        if pd.isna(positions_str):
            positions_list = []
        elif isinstance(positions_str, str):
            # Käsitellään sekä '/' että ',' erottimet
            positions_list = [p.strip() for p in positions_str.replace(',', '/').split('/')]
        else:
            positions_list = positions_str
        
        players_info[player['name']] = {
            'team': player['team'],
            'positions': positions_list,
            'fpa': player.get('fantasy_points_avg', 0)
        }
    
    daily_results = []
    player_games = {name: 0 for name in players_info.keys()}          # aktiiviset pelit
    player_bench_games = {name: 0 for name in players_info.keys()}    # penkillä olleet pelit

    all_dates = sorted(schedule_df['Date'].unique())
    
    for date in all_dates:
        day_games = schedule_df[schedule_df['Date'] == date]
        
        available_players_teams = {game['Visitor'] for _, game in day_games.iterrows()} | {game['Home'] for _, game in day_games.iterrows()}
        available_players_set = {
            player_name for player_name, info in players_info.items() if info['team'] in available_players_teams
        }
        
        available_players = [
            {'name': name, 'team': players_info[name]['team'], 'positions': players_info[name]['positions'], 'fpa': players_info[name]['fpa']}
            for name in available_players_set
        ]
        
        best_assignment = None
        best_assignment_fp = -1.0
        
        for attempt in range(num_attempts):
            shuffled_players = available_players.copy()
            np.random.shuffle(shuffled_players)
            
            active = {pos: [] for pos in limits.keys()}
            bench = []
            
            for player_info in shuffled_players:
                placed = False
                player_name = player_info['name']
                positions_list = player_info['positions']
                
                # Sijoita ensisijaisille pelipaikoille
                for pos in positions_list:
                    if pos in limits and len(active[pos]) < limits[pos]:
                        active[pos].append(player_name)
                        placed = True
                        break
                
                # Jos ei sijoitettu, yritä UTIL
                if not placed and 'UTIL' in limits and len(active['UTIL']) < limits['UTIL']:
                    if any(pos in ['C', 'LW', 'RW', 'D'] for pos in positions_list):
                        active['UTIL'].append(player_name)
                        placed = True
                
                if not placed:
                    bench.append(player_name)
            
            # Parannetaan aktiivista kokoonpanoa penkin paremmilla pelaajilla
            improved = True
            while improved:
                improved = False
                bench_copy = sorted(bench, key=lambda name: players_info[name]['fpa'], reverse=True)
                
                for bench_player_name in bench_copy:
                    bench_player_fpa = players_info[bench_player_name]['fpa']
                    bench_player_positions = players_info[bench_player_name]['positions']
                    
                    swapped = False
                    for active_pos, active_players in active.items():
                        active_sorted = sorted([(name, i) for i, name in enumerate(active_players)], key=lambda x: players_info[x[0]]['fpa'])
                        for active_player_name, active_idx in active_sorted:
                            active_player_fpa = players_info[active_player_name]['fpa']
                            if bench_player_fpa > active_player_fpa and active_pos in bench_player_positions:
                                active_players[active_idx] = bench_player_name
                                bench.remove(bench_player_name)
                                bench.append(active_player_name)
                                improved = True
                                swapped = True
                                break
                        if swapped:
                            break
                    if swapped:
                        break

            # Lasketaan FP
            current_fp = sum(players_info[player_name]['fpa'] for players in active.values() for player_name in players)
            
            if current_fp > best_assignment_fp:
                best_assignment_fp = current_fp
                best_assignment = {'active': {pos: players[:] for pos, players in active.items()}, 'bench': bench[:]}
            elif current_fp == best_assignment_fp and best_assignment:
                current_active_count = sum(len(players) for players in active.values())
                best_active_count = sum(len(players) for players in best_assignment['active'].values())
                if current_active_count > best_active_count:
                    best_assignment = {'active': {pos: players[:] for pos, players in active.items()}, 'bench': bench[:]}

        if best_assignment is None:
            best_assignment = {'active': {pos: [] for pos in limits.keys()}, 'bench': [p['name'] for p in available_players]}
            
        daily_results.append({
            'Date': date.date(),
            'Active': best_assignment['active'],
            'Bench': best_assignment['bench']
        })
        
        # Päivitetään laskurit
        for pos, players in best_assignment['active'].items():
            for player_name in players:
                player_games[player_name] += 1

        for player_name in best_assignment['bench']:
            player_bench_games[player_name] += 1
    
    total_fantasy_points = sum(player_games[name] * players_info[name]['fpa'] for name in players_info)
    total_active_games = sum(player_games.values())

    # Palautetaan myös bench-pelit
    return daily_results, player_games, total_fantasy_points, total_active_games, player_bench_games


def simulate_team_impact(schedule_df, my_roster_df, opponent_roster_df, pos_limits):
    """
    Simuloi oman ja vastustajan joukkueen suorituskykyä annettujen kokoonpanojen ja pelipäivien perusteella.
    Palauttaa voittajajoukkueen sekä yksityiskohtaiset tulokset molemmille joukkueille.
    """
    if my_roster_df.empty or opponent_roster_df.empty:
        return "Täydennä molemmat rosterit ennen simulaatiota.", None, None

    # Suoritetaan optimointi omalle joukkueelle
    my_daily_results, my_player_games, my_total_points, my_total_games = optimize_roster_advanced(
        schedule_df, my_roster_df, pos_limits
    )

    # Suoritetaan optimointi vastustajalle
    opponent_pos_limits = {
        'C': 3, 'LW': 3, 'RW': 3, 'D': 4, 'G': 2, 'UTIL': 1
    }
    opponent_daily_results, opponent_player_games, opponent_total_points, opponent_total_games = optimize_roster_advanced(
        schedule_df, opponent_roster_df, opponent_pos_limits
    )

    # Määrää voittaja
    if my_total_points > opponent_total_points:
        winner = "Oma joukkue"
    elif opponent_total_points > my_total_points:
        winner = "Vastustaja"
    else:
        winner = "Tasapeli"
        
    # Palautetaan yksityiskohtaiset tulokset
    return winner, {
        "daily_results": my_daily_results,
        "player_games": my_player_games,
        "total_points": my_total_points,
        "total_games": my_total_games
    }, {
        "daily_results": opponent_daily_results,
        "player_games": opponent_player_games,
        "total_points": opponent_total_points,
        "total_games": opponent_total_games
    }

def calculate_team_impact_by_position(schedule_df, roster_df, pos_limits):
    """
    Laskee joukkueiden vaikutukset pelipaikoittain.
    Palauttaa sanakirjan, jossa avaimina ovat pelipaikat ja arvoina DataFrameja.
    """
    # Hae kaikki uniikit joukkueet aikataulusta
    all_teams = sorted(list(set(schedule_df['Home'].tolist() + schedule_df['Visitor'].tolist())))
    
    # Alustetaan tulokset jokaiselle pelipaikalle
    results = {}
    
    # Käydään läpi jokainen pelipaikka
    for pos in ['C', 'LW', 'RW', 'D', 'G']:
        impact_data = []
        
        # Käydään läpi jokainen joukkue
        for team in all_teams:
            # Luodaan simuloitu pelaaja tälle joukkueelle ja pelipaikalle
            sim_player = pd.DataFrame({
                'name': [f'SIM_{team}_{pos}'],
                'team': [team],
                'positions': [pos],
                'fantasy_points_avg': [0.0]
            })
            
            # Yhdistetään simuloitu pelaaja nykyiseen rosteriin
            sim_roster = pd.concat([roster_df, sim_player], ignore_index=True)
            
            # Suoritetaan optimointi
            _, player_games, *_ = optimize_roster_advanced(
                schedule_df, sim_roster, pos_limits, num_attempts=50
            )

            
            # Lasketaan kuinka monta peliä simuloitu pelaaja sai
            sim_games = player_games.get(f'SIM_{team}_{pos}', 0)
            
            impact_data.append({
                'Joukkue': team,
                'Lisäpelit': sim_games
            })
        
        # Luodaan DataFrame ja järjestetään se
        df = pd.DataFrame(impact_data).sort_values('Lisäpelit', ascending=False)
        results[pos] = df
    
    return results

def analyze_free_agents(team_impact_dict, free_agents_df):
    """
    Analysoi vapaat agentit aiemmin lasketun joukkueanalyysin perusteella.
    
    Args:
        team_impact_dict (dict): Sanakirja, joka sisältää joukkuekohtaiset lisäpelit.
        free_agents_df (pd.DataFrame): DataFrame, joka sisältää vapaiden agenttien tiedot.
            
    Returns:
        pd.DataFrame: Lajiteltu DataFrame optimaalisimmista vapaista agenteista.
    """
    if not team_impact_dict or free_agents_df.empty:
        st.warning("Joukkueanalyysiä tai vapaiden agenttien listaa ei ole ladattu.")
        return pd.DataFrame()

    # SUODATUS TÄSSÄ: Jätä pois pelaajat, joiden pelipaikka on "G"
    free_agents_df = free_agents_df[~free_agents_df['positions'].str.contains('G')].copy()
    if free_agents_df.empty:
        st.info("Vapaita agentteja ei löytynyt maalivahtien suodatuksen jälkeen.")
        return pd.DataFrame()
        
    team_impact_df_list = []
    for pos, df in team_impact_dict.items():
        if not df.empty and pos != 'G':  # Myös joukkueanalyysista pois maalivahdit
            df['position'] = pos
            team_impact_df_list.append(df)
    
    if not team_impact_df_list:
        st.warning("Joukkueanalyysin tuloksia ei löytynyt kenttäpelaajille.")
        return pd.DataFrame()

    combined_impact_df = pd.concat(team_impact_df_list, ignore_index=True)
    combined_impact_df.rename(columns={'Joukkue': 'team', 'Lisäpelit': 'extra_games_total'}, inplace=True)
    
    results = free_agents_df.copy()
    results['total_impact'] = 0.0
    results['games_added'] = 0.0
    
    # MUUTOS TÄSSÄ
    # Käsittele monipaikkaiset pelaajat
    results['positions_list'] = results['positions'].apply(lambda x: [p.strip() for p in str(x).replace('/', ',').split(',')])

    def calculate_impact(row):
        team = row['team']
        fpa = row['fantasy_points_avg']
        positions = row['positions_list']
        
        max_extra_games = 0.0
        
        if not positions:
            return 0.0, 0.0
        
        for pos in positions:
            match = combined_impact_df[(combined_impact_df['team'] == team) & (combined_impact_df['position'] == pos)]
            if not match.empty:
                extra_games = match['extra_games_total'].iloc[0]
                if extra_games > max_extra_games:
                    max_extra_games = extra_games
        
        total_impact = max_extra_games * fpa
        return total_impact, max_extra_games

    results[['total_impact', 'games_added']] = results.apply(calculate_impact, axis=1, result_type='expand')

    results['games_added'] = results['games_added'].astype(int)

    results.drop(columns=['positions_list'], inplace=True)
    results = results[['name', 'team', 'positions', 'games_added', 'fantasy_points_avg', 'total_impact']]
    
    results = results.sort_values(by='total_impact', ascending=False)
    
    return results
    
# --- PÄÄSIVU: KÄYTTÖLIITTYMÄ ---
tab1, tab2 = st.tabs(["Rosterin optimointi", "Joukkuevertailu"])

with tab1:
    st.header("📊 Nykyinen rosteri (APL)")
    if st.session_state['roster'].empty:
        st.warning("Lataa rosteri nähdäksesi pelaajat")
    else:
        roster_df = st.session_state['roster'].copy()
        roster_df.index = roster_df.index + 1
        roster_df = roster_df.reset_index()
        roster_df.rename(columns={"index": "Rivi"}, inplace=True)
        st.dataframe(roster_df, use_container_width=True, hide_index=True)

        
        st.subheader("Joukkueiden jakauma")
        team_counts = st.session_state['roster']['team'].value_counts()
        st.bar_chart(team_counts)
    
    st.header("🚀 Rosterin optimointi")
    
    if st.session_state['schedule'].empty or st.session_state['roster'].empty:
        st.warning("Lataa sekä peliaikataulu että rosteri aloittaaksesi optimoinnin")
    elif start_date > end_date:
        st.warning("Korjaa päivämääräväli niin että aloituspäivä on ennen loppupäivää")
    else:
        schedule_filtered = st.session_state['schedule'][
            (st.session_state['schedule']['Date'] >= pd.to_datetime(start_date)) &
            (st.session_state['schedule']['Date'] <= pd.to_datetime(end_date))
        ]
        
        if schedule_filtered.empty:
            st.warning("Ei pelejä valitulla aikavälillä")
        else:
            with st.spinner("Optimoidaan rosteria älykkäällä algoritmilla..."):
                daily_results, total_games, total_fp, total_active_games, player_bench_games = optimize_roster_advanced(
                    schedule_filtered,
                    st.session_state['roster'],
                    pos_limits
                )

            
            st.subheader("Päivittäiset aktiiviset rosterit")
            daily_data = []
            for result in daily_results:
                active_list = []
                if isinstance(result, dict) and 'Active' in result and result['Active'] is not None:
                    for pos, players in result['Active'].items():
                        for player in players:
                            active_list.append(f"{player} ({pos})")
                
                bench_list = []
                if isinstance(result, dict) and 'Bench' in result and result['Bench'] is not None:
                    bench_list = result['Bench']
                
                daily_data.append({
                    'Päivä': result['Date'] if isinstance(result, dict) and 'Date' in result else None,
                    'Aktiiviset pelaajat': ", ".join(active_list),
                    'Penkki': ", ".join(bench_list) if bench_list else "Ei pelaajia penkille"
                })

            daily_df = pd.DataFrame(daily_data)
            st.dataframe(daily_df, use_container_width=True)
            
            st.subheader("Pelaajien kokonaispelimäärät (aktiiviset ja penkillä)")
            games_df = pd.DataFrame({
                'Pelaaja': list(total_games.keys()),
                'Aktiiviset pelit': list(total_games.values()),
                'Pelit penkillä': [player_bench_games.get(p, 0) for p in total_games.keys()],
            })

            # Lasketaan myös yhteenlaskettu pelimäärä (aktiiviset + penkki)
            games_df['Yhteensä pelit'] = games_df['Aktiiviset pelit'] + games_df['Pelit penkillä']

            # Järjestetään näkyvyys järkevästi
            games_df = games_df.sort_values('Aktiiviset pelit', ascending=False)

            st.dataframe(games_df, use_container_width=True)

            # 📥 CSV-lataus
            csv = games_df.to_csv(index=False).encode('utf-8')
            st.download_button(
                "Lataa pelimäärät CSV-muodossa",
                data=csv,
                file_name='pelimäärät.csv',
                mime='text/csv'
            )
            
            st.subheader("📈 Analyysit")
            col1, col2 = st.columns(2)
            
            with col1:
                top_players = games_df.head(10)
                st.write("Top 10 eniten pelanneet pelaajat")
                st.dataframe(top_players)
            
            with col2:
                position_data = {}
                for _, row in st.session_state['roster'].iterrows():
                    positions = row['positions'].split('/')
                    for pos in positions:
                        pos_clean = pos.strip()
                        if pos_clean in ['C', 'LW', 'RW', 'D', 'G']:
                            if pos_clean not in position_data:
                                position_data[pos_clean] = 0
                            position_data[pos_clean] += total_games.get(row['name'], 0)
                
                pos_df = pd.DataFrame({
                    'Pelipaikka': list(position_data.keys()),
                    'Pelit': list(position_data.values())
                })
                st.write("Pelipaikkojen kokonaispelimäärät")
                st.dataframe(pos_df)

    st.subheader("Päivittäinen pelipaikkasaatavuus")
    st.markdown("Tämä matriisi näyttää, onko rosteriin mahdollista lisätä uusi pelaaja kyseiselle pelipaikalle.")

    if st.session_state['schedule'].empty or st.session_state['roster'].empty:
        st.warning("Lataa sekä peliaikataulu että rosteri näyttääksesi matriisin.")
    else:
        time_delta = end_date - start_date
        if time_delta.days > 30:
            st.info("Päivittäinen saatavuusmatriisi näytetään vain enintään 30 päivän aikavälillä.")
        else:
            players_info_dict = {}
            for _, row in st.session_state['roster'].iterrows():
                positions_list = [p.strip() for p in row['positions'].split('/')]
                players_info_dict[row['name']] = {'team': row['team'], 'positions': positions_list, 'fpa': row.get('fantasy_points_avg', 0)}

            def get_daily_active_slots(players_list, pos_limits):
                best_active_players_count = 0
                num_attempts = 50
                
                for _ in range(num_attempts):
                    shuffled_players = players_list.copy()
                    np.random.shuffle(shuffled_players)
                    active = {pos: [] for pos in pos_limits.keys()}
                    
                    for player_name in shuffled_players:
                        placed = False
                        positions = players_info_dict.get(player_name, {}).get('positions', [])
                        for pos in positions:
                            if pos in pos_limits and len(active[pos]) < pos_limits[pos] and pos != 'UTIL':
                                active[pos].append(player_name)
                                placed = True
                                break
                        if not placed and 'UTIL' in pos_limits and len(active['UTIL']) < pos_limits['UTIL'] and any(p in ['C', 'LW', 'RW', 'D'] for p in positions):
                            active['UTIL'].append(player_name)
                    
                    current_active_count = sum(len(p) for p in active.values())
                    if current_active_count > best_active_players_count:
                        best_active_players_count = current_active_count
                
                return best_active_players_count
                
            positions_to_show = ['C', 'LW', 'RW', 'D', 'G']
            availability_data = {pos: [] for pos in positions_to_show}
            dates = [start_date + timedelta(days=i) for i in range(time_delta.days + 1)]
            valid_dates = []

            for date in dates:
                day_games = st.session_state['schedule'][st.session_state['schedule']['Date'].dt.date == date]
                
                if day_games.empty:
                    continue

                available_players_today = [
                    player_name for player_name, info in players_info_dict.items()
                    if info['team'] in day_games['Visitor'].tolist() or info['team'] in day_games['Home'].tolist()
                ]

                valid_dates.append(date)

                for pos_check in positions_to_show:
                    sim_player_name = f'SIM_PLAYER_{pos_check}'
                    
                    sim_players_list = available_players_today + [sim_player_name]
                    players_info_dict[sim_player_name] = {'team': 'TEMP', 'positions': [pos_check], 'fpa': 0}
                    if pos_check in ['C', 'LW', 'RW', 'D']:
                        players_info_dict[sim_player_name]['positions'].append('UTIL')

                    original_active_count = get_daily_active_slots(available_players_today, pos_limits)
                    simulated_active_count = get_daily_active_slots(sim_players_list, pos_limits)
                    
                    can_fit = simulated_active_count > original_active_count
                    
                    availability_data[pos_check].append(can_fit)

                    del players_info_dict[sim_player_name]

            availability_df = pd.DataFrame(availability_data, index=valid_dates)
            
            def color_cells(val):
                color = 'green' if val else 'red'
                return f'background-color: {color}'

            st.dataframe(
                availability_df.style.applymap(color_cells),
                use_container_width=True
            )

    st.header("🔮 Simuloi uuden pelaajan vaikutus")
    if not st.session_state['roster'].empty and 'schedule' in st.session_state and not st.session_state['schedule'].empty and start_date <= end_date:
        st.subheader("Valitse vertailutyyppi")
        
        # Lisätään valintalaatikko vertailutyypille
        comparison_type = st.radio(
            "Valitse vertailutyyppi:",
            ["Vertaa kahta uutta pelaajaa", "Vertaa uutta pelaajaa Lindgren rostersissa olevan pudottamista"],
            key="comparison_type"
        )
        
        if comparison_type == "Vertaa kahta uutta pelaajaa":
            st.markdown("#### Pelaaja A")
            colA1, colA2, colA3, colA4 = st.columns(4)
            with colA1:
                sim_name_A = st.text_input("Pelaajan nimi", key="sim_name_A")
            with colA2:
                sim_team_A = st.text_input("Joukkue", key="sim_team_A")
            with colA3:
                sim_positions_A = st.text_input("Pelipaikat (esim. C/LW)", key="sim_positions_A")
            with colA4:
                sim_fpa_A = st.number_input("FP/GP", min_value=0.0, step=0.1, format="%.2f", key="sim_fpa_A")

            st.markdown("#### Pelaaja B")
            colB1, colB2, colB3, colB4 = st.columns(4)
            with colB1:
                sim_name_B = st.text_input("Pelaajan nimi", key="sim_name_B")
            with colB2:
                sim_team_B = st.text_input("Joukkue", key="sim_team_B")
            with colB3:
                sim_positions_B = st.text_input("Pelipaikat (esim. C/LW)", key="sim_positions_B")
            with colB4:
                sim_fpa_B = st.number_input("FP/GP", min_value=0.0, step=0.1, format="%.2f", key="sim_fpa_B")
            
            # Valinta poistettavalle pelaajalle (valinnainen)
            remove_sim_player = st.selectbox(
                "Pelaaja poistettavaksi rosterista (valinnainen)",
                [""] + list(st.session_state['roster']['name'])
            )

            removed_fpa = 0.0
            if remove_sim_player and not st.session_state['roster'].empty:
                removed_player_info = st.session_state['roster'][st.session_state['roster']['name'] == remove_sim_player]
                if 'fantasy_points_avg' in removed_player_info.columns and not pd.isna(removed_player_info['fantasy_points_avg'].iloc[0]):
                    removed_fpa_default = float(removed_player_info['fantasy_points_avg'].iloc[0])
                else:
                    removed_fpa_default = 0.0
                removed_fpa = st.number_input("Syötä poistettavan pelaajan FP/GP", min_value=0.0, step=0.1, format="%.2f", value=removed_fpa_default, key="removed_fpa")

        else:  # Vertaa uutta pelaajaa Lindgren rostersissa olevan pudottamista
            st.markdown("#### Uusi pelaaja")
            colA1, colA2, colA3, colA4 = st.columns(4)
            with colA1:
                new_player_name = st.text_input("Pelaajan nimi", key="new_player_name")
            with colA2:
                new_player_team = st.text_input("Joukkue", key="new_player_team")
            with colA3:
                new_player_positions = st.text_input("Pelipaikat (esim. C/LW)", key="new_player_positions")
            with colA4:
                new_player_fpa = st.number_input("FP/GP", min_value=0.0, step=0.1, format="%.2f", key="new_player_fpa")
            
            st.markdown("#### Pudotettava pelaaja")
            colB1, colB2, colB3, colB4 = st.columns(4)
            with colB1:
                # Valitse pudotettava pelaaja rosterista
                drop_player_name = st.selectbox(
                    "Valitse pudotettava pelaaja",
                    list(st.session_state['roster']['name']),
                    key="drop_player_name"
                )
            with colB2:
                # Näytä valitun pelaajan joukkue
                if drop_player_name:
                    drop_player_team = st.session_state['roster'][st.session_state['roster']['name'] == drop_player_name]['team'].iloc[0]
                    st.text_input("Joukkue", value=drop_player_team, disabled=True, key="drop_player_team_display")
                else:
                    st.text_input("Joukkue", value="", disabled=True, key="drop_player_team_empty")
            with colB3:
                # Näytä valitun pelaajan pelipaikat
                if drop_player_name:
                    drop_player_positions = st.session_state['roster'][st.session_state['roster']['name'] == drop_player_name]['positions'].iloc[0]
                    st.text_input("Pelipaikat", value=drop_player_positions, disabled=True, key="drop_player_positions_display")
                else:
                    st.text_input("Pelipaikat", value="", disabled=True, key="drop_player_positions_empty")
            with colB4:
                # Näytä valitun pelaajan FP/GP ja salli muokkaus
                if drop_player_name:
                    drop_player_fpa_default = st.session_state['roster'][st.session_state['roster']['name'] == drop_player_name]['fantasy_points_avg'].iloc[0]
                    if pd.isna(drop_player_fpa_default):
                        drop_player_fpa_default = 0.0
                    drop_player_fpa = st.number_input("FP/GP", min_value=0.0, step=0.1, format="%.2f", value=float(drop_player_fpa_default), key="drop_player_fpa")
                else:
                    drop_player_fpa = st.number_input("FP/GP", min_value=0.0, step=0.1, format="%.2f", value=0.0, key="drop_player_fpa_empty")

        if st.button("Suorita vertailu"):
            if comparison_type == "Vertaa kahta uutta pelaajaa":
                if sim_name_A and sim_team_A and sim_positions_A and sim_name_B and sim_team_B and sim_positions_B:
                    
                    original_roster_copy = st.session_state['roster'].copy()
                    if 'fantasy_points_avg' not in original_roster_copy.columns:
                        original_roster_copy['fantasy_points_avg'] = 0.0
                    
                    temp_roster = original_roster_copy.copy()
                    if remove_sim_player:
                        temp_roster = temp_roster[temp_roster['name'] != remove_sim_player].copy()
                    
                    # Pelaaja A:n simulointi
                    new_player_A = {'name': sim_name_A, 'team': sim_team_A, 'positions': sim_positions_A, 'fantasy_points_avg': sim_fpa_A}
                    sim_roster_A = pd.concat([temp_roster, pd.DataFrame([new_player_A])], ignore_index=True)

                    # Pelaaja B:n simulointi
                    new_player_B = {'name': sim_name_B, 'team': sim_team_B, 'positions': sim_positions_B, 'fantasy_points_avg': sim_fpa_B}
                    sim_roster_B = pd.concat([temp_roster, pd.DataFrame([new_player_B])], ignore_index=True)
                    
                    schedule_filtered = st.session_state['schedule'][
                        (st.session_state['schedule']['Date'] >= pd.to_datetime(start_date)) &
                        (st.session_state['schedule']['Date'] <= pd.to_datetime(end_date))
                    ]
                    
                    team_game_days = {}
                    for _, row in schedule_filtered.iterrows():
                        date = row['Date']
                        for team in [row['Visitor'], row['Home']]:
                            if team not in team_game_days:
                                team_game_days[team] = set()
                            team_game_days[team].add(date)

                    with st.spinner("Lasketaan alkuperäistä kokonaispelimäärää ja pisteitä..."):
                        _, original_total_games_dict, original_fp, _ = optimize_roster_advanced(
                            schedule_filtered,
                            st.session_state['roster'],
                            pos_limits
                        )
                        original_total_games = sum(original_total_games_dict.values())
                    
                    with st.spinner(f"Lasketaan {sim_name_A}:n vaikutusta..."):
                        _, total_games_A_dict, new_fp_A, _ = optimize_roster_advanced(
                            schedule_filtered,
                            sim_roster_A,
                            pos_limits
                        )
                        new_total_games_A = sum(total_games_A_dict.values())
                        player_A_impact_days = total_games_A_dict.get(sim_name_A, 0)
                    
                    with st.spinner(f"Lasketaan {sim_name_B}:n vaikutusta..."):
                        _, total_games_B_dict, new_fp_B, _ = optimize_roster_advanced(
                            schedule_filtered,
                            sim_roster_B,
                            pos_limits
                        )
                        new_total_games_B = sum(total_games_B_dict.values())
                        player_B_impact_days = total_games_B_dict.get(sim_name_B, 0)

                    st.subheader("Vertailun tulokset")
                    
                    col_vertailu_1, col_vertailu_2 = st.columns(2)
                    
                    with col_vertailu_1:
                        st.markdown(f"**Pelaaja A: {sim_name_A}**")
                        st.metric("Pelien muutos", f"{new_total_games_A - original_total_games}", help="Pelaajan lisäämisen vaikutus kokonaispelimäärään")
                        st.metric("Omat pelit", player_A_impact_days)
                        st.metric("Fantasiapiste-ero", f"{new_fp_A - original_fp:.2f}", help="Pelaajan lisäämisen vaikutus fantasiapisteisiin")
                        
                    with col_vertailu_2:
                        st.markdown(f"**Pelaaja B: {sim_name_B}**")
                        st.metric("Pelien muutos", f"{new_total_games_B - original_total_games}", help="Pelaajan lisäämisen vaikutus kokonaispelimäärään")
                        st.metric("Omat pelit", player_B_impact_days)
                        st.metric("Fantasiapiste-ero", f"{new_fp_B - original_fp:.2f}", help="Pelaajan lisäämisen vaikutus fantasiapisteisiin")
                        
                    st.markdown("---")
                    
                    st.subheader("Yhteenveto")
                    games_A_vs_B = (new_total_games_A - original_total_games) - (new_total_games_B - original_total_games)
                    fp_A_vs_B = (new_fp_A - original_fp) - (new_fp_B - original_fp)

                    if fp_A_vs_B > 0:
                        st.success(f"{sim_name_A} on parempi vaihtoehto! Rosterisi kokonais-FP olisi arviolta **{fp_A_vs_B:.2f}** pistettä suurempi kuin {sim_name_B}:llä.")
                    elif fp_A_vs_B < 0:
                        st.error(f"{sim_name_B} on parempi vaihtoehto! Rosterisi kokonais-FP olisi arviolta **{abs(fp_A_vs_B):.2f}** pistettä suurempi kuin {sim_name_A}:lla.")
                    else:
                        st.info("Fantasiapisteissä ei ole eroa näiden pelaajien välillä.")

                else:
                    st.warning("Syötä molempien pelaajien tiedot suorittaaksesi vertailun.")
            
            else:  # Vertaa uutta pelaajaa Lindgren rostersissa olevan pudottamista
                if new_player_name and new_player_team and new_player_positions and drop_player_name:
                    
                    # Luo uusi pelaaja
                    new_player = {'name': new_player_name, 'team': new_player_team, 'positions': new_player_positions, 'fantasy_points_avg': new_player_fpa}
                    
                    # Luo pudotettava pelaaja
                    drop_player = {'name': drop_player_name, 'team': drop_player_team, 'positions': drop_player_positions, 'fantasy_points_avg': drop_player_fpa}
                    
                    schedule_filtered = st.session_state['schedule'][
                        (st.session_state['schedule']['Date'] >= pd.to_datetime(start_date)) &
                        (st.session_state['schedule']['Date'] <= pd.to_datetime(end_date))
                    ]
                    
                    # Lasketaan alkuperäinen rosteri
                    with st.spinner("Lasketaan alkuperäistä kokonaispelimäärää ja pisteitä..."):
                        _, original_total_games_dict, original_fp, _ = optimize_roster_advanced(
                            schedule_filtered,
                            st.session_state['roster'],
                            pos_limits
                        )
                        original_total_games = sum(original_total_games_dict.values())
                    
                    # Luodaan muokattu rosteri: poistetaan pudotettava pelaaja ja lisätään uusi pelaaja
                    modified_roster = st.session_state['roster'][st.session_state['roster']['name'] != drop_player_name].copy()
                    modified_roster = pd.concat([modified_roster, pd.DataFrame([new_player])], ignore_index=True)
                    
                    # Lasketaan muokatun rosterin tulokset
                    with st.spinner(f"Lasketaan muutoksen vaikutusta..."):
                        _, modified_total_games_dict, modified_fp, _ = optimize_roster_advanced(
                            schedule_filtered,
                            modified_roster,
                            pos_limits
                        )
                        modified_total_games = sum(modified_total_games_dict.values())
                        new_player_impact_days = modified_total_games_dict.get(new_player_name, 0)
                    
                    st.subheader("Vertailun tulokset")
                    
                    col_vertailu_1, col_vertailu_2 = st.columns(2)
                    
                    with col_vertailu_1:
                        st.markdown(f"**Uusi pelaaja: {new_player_name}**")
                        st.metric("Pelien muutos", f"{modified_total_games - original_total_games}", help="Muutoksen vaikutus kokonaispelimäärään")
                        st.metric("Omat pelit", new_player_impact_days)
                        st.metric("Fantasiapiste-ero", f"{modified_fp - original_fp:.2f}", help="Muutoksen vaikutus fantasiapisteisiin")
                        
                    with col_vertailu_2:
                        st.markdown(f"**Pudotettava pelaaja: {drop_player_name}**")
                        st.metric("Menetetyt pelit", f"{original_total_games_dict.get(drop_player_name, 0)}", help="Pudotettavan pelaajan pelien määrä")
                        st.metric("Menetetyt FP", f"{original_total_games_dict.get(drop_player_name, 0) * drop_player_fpa:.2f}", help="Pudotettavan pelaajan menettämät pisteet")
                        
                    st.markdown("---")
                    
                    st.subheader("Yhteenveto")
                    
                    if modified_fp > original_fp:
                        st.success(f"Muutos on kannattava! Rosterisi kokonais-FP olisi arviolta **{modified_fp - original_fp:.2f}** pistettä suurempi.")
                    elif modified_fp < original_fp:
                        st.error(f"Muutos ei ole kannattava. Rosterisi kokonais-FP olisi arviolta **{original_fp - modified_fp:.2f}** pistettä pienempi.")
                    else:
                        st.info("Fantasiapisteissä ei ole eroa.")

                else:
                    st.warning("Syötä uuden pelaajan tiedot ja valitse pudotettava pelaaja suorittaaksesi vertailun.")
    else:
        st.info("Lataa rosteri ja peliaikataulu, jotta voit vertailla pelaajia.")

    # Alkuperäinen joukkueanalyysi osio
    st.markdown("---")
    st.header("🔍 Joukkueanalyysi")
    st.markdown("""
    Tämä osio simuloi kuvitteellisen pelaajan lisäämisen jokaisesta joukkueesta
    ja näyttää, mikä joukkue tuottaisi eniten aktiivisia pelejä kullekin pelipaikalle
    ottaen huomioon nykyisen rosterisi.
    """)
    if st.session_state['schedule'].empty or st.session_state['roster'].empty:
        st.warning("Lataa sekä peliaikataulu että rosteri aloittaaksesi analyysin.")
    else:
        schedule_filtered = st.session_state['schedule'][
            (st.session_state['schedule']['Date'] >= pd.to_datetime(start_date)) &
            (st.session_state['schedule']['Date'] <= pd.to_datetime(end_date))
        ]

        if not schedule_filtered.empty:
            if st.button("Suorita joukkueanalyysi"):
                st.session_state['team_impact_results'] = calculate_team_impact_by_position(
                    schedule_filtered,
                    st.session_state['roster'],
                    pos_limits
                )
            
            if st.session_state['team_impact_results'] is not None:
                for pos, df in st.session_state['team_impact_results'].items():
                    st.subheader(f"Joukkueet pelipaikalle: {pos}")
                    st.dataframe(df, use_container_width=True)

# --- Vapaiden agenttien analyysi ---
if st.session_state.get('free_agents') is not None and not st.session_state['free_agents'].empty and \
   st.session_state.get('team_impact_results') is not None and st.session_state['team_impact_results']:
    st.header("Vapaiden agenttien analyysi")
    
    # Suodatusvalikot
    all_positions = sorted(list(set(p.strip() for player_pos in st.session_state['free_agents']['positions'].unique() for p in player_pos.replace('/', ',').split(','))))
    # TÄSSÄ MUUTOS: selectboxista multiselectiin
    selected_pos = st.multiselect("Suodata pelipaikkojen mukaan:", all_positions, default=all_positions)
    
    all_teams = sorted(st.session_state['free_agents']['team'].unique())
    selected_team = st.selectbox("Suodata joukkueen mukaan:", ["Kaikki"] + list(all_teams))

    if st.button("Suorita vapaiden agenttien analyysi", key="free_agent_analysis_button_new"):
        with st.spinner("Analysoidaan vapaat agentit..."):
            free_agent_results = analyze_free_agents(
                st.session_state['team_impact_results'],
                st.session_state['free_agents']
            )
        
        filtered_results = free_agent_results.copy()
        
        # PÄIVITETTY SUODATUSLOGIIKKA
        if selected_pos: # Tarkistaa, että lista ei ole tyhjä
            # Suodata tulokset pelaajan pelipaikkojen ja valitun listan perusteella
            filtered_results = filtered_results[filtered_results['positions'].apply(
                lambda x: any(pos in x.split('/') for pos in selected_pos)
            )]
        
        if selected_team != "Kaikki":
            filtered_results = filtered_results[filtered_results['team'] == selected_team]
            
        if not filtered_results.empty:
            st.dataframe(filtered_results.style.format({
                'total_impact': "{:.2f}",
                'fantasy_points_avg': "{:.1f}"
            }), use_container_width=True)
        else:
            st.error("Analyysituloksia ei löytynyt valituilla suodattimilla.")
            
with tab2:
    st.header("🆚 Joukkuevertailu")
    st.markdown("Vertaa oman ja vastustajan joukkueiden ennakoituja tuloksia valitulla aikavälillä.")
    
    if st.session_state['roster'].empty or st.session_state['opponent_roster'].empty:
        st.warning("Lataa molemmat rosterit vertailua varten.")
    elif st.session_state['schedule'].empty:
        st.warning("Lataa peliaikataulu vertailua varten.")
    else:
        schedule_filtered = st.session_state['schedule'][
            (st.session_state['schedule']['Date'] >= pd.to_datetime(start_date)) &
            (st.session_state['schedule']['Date'] <= pd.to_datetime(end_date))
        ]

        if schedule_filtered.empty:
            st.warning("Ei pelejä valitulla aikavälillä.")
        else:
            if st.button("Suorita joukkuevertailu", key="roster_compare_button"):
                with st.spinner("Vertailu käynnissä..."):

                    # Oma rosteri
                    _, my_games_dict, my_fp, my_total_games, my_bench_games = optimize_roster_advanced(
                        schedule_filtered, 
                        st.session_state['roster'], 
                        pos_limits
                    )

                    # Vastustajan rosteri
                    _, opponent_games_dict, opponent_fp, opponent_total_games, opponent_bench_games = optimize_roster_advanced(
                        schedule_filtered, 
                        st.session_state['opponent_roster'], 
                        pos_limits
                    )

                    # Kootaan omien pelaajien tiedot DataFrameen
                    my_players_data = []
                    for name, games in my_games_dict.items():
                        fpa = st.session_state['roster'][st.session_state['roster']['name'] == name]['fantasy_points_avg'].iloc[0] if not st.session_state['roster'][st.session_state['roster']['name'] == name].empty else 0
                        total_fp_player = games * fpa
                        my_players_data.append({
                            'Pelaaja': name,
                            'Aktiiviset pelit': games,
                            'Ennakoidut FP': round(total_fp_player, 2)
                        })
                    my_df = pd.DataFrame(my_players_data).sort_values(by='Ennakoidut FP', ascending=False)

                    # Kootaan vastustajan pelaajien tiedot DataFrameen
                    opponent_players_data = []
                    for name, games in opponent_games_dict.items():
                        fpa = st.session_state['opponent_roster'][st.session_state['opponent_roster']['name'] == name]['fantasy_points_avg'].iloc[0] if not st.session_state['opponent_roster'][st.session_state['opponent_roster']['name'] == name].empty else 0
                        total_fp_player = games * fpa
                        opponent_players_data.append({
                            'Pelaaja': name,
                            'Aktiiviset pelit': games,
                            'Ennakoidut FP': round(total_fp_player, 2)
                        })
                    opponent_df = pd.DataFrame(opponent_players_data).sort_values(by='Ennakoidut FP', ascending=False)
                    
                    st.subheader("Yksityiskohtainen vertailu")
                    col1_detail, col2_detail = st.columns(2)
                    with col1_detail:
                        st.markdown("**Oma joukkueesi**")
                        st.dataframe(my_df, use_container_width=True)
                    with col2_detail:
                        st.markdown("**Vastustajan joukkue**")
                        st.dataframe(opponent_df, use_container_width=True)
                        
                    st.subheader("Yhteenveto")
                    vertailu_col1, vertailu_col2 = st.columns(2)
                    with vertailu_col1:
                        st.metric("Oman joukkueen aktiiviset pelit", my_total_games)
                    with vertailu_col2:
                        st.metric("Vastustajan aktiiviset pelit", opponent_total_games)

                    st.markdown("---")
                    
                    vertailu_fp_col1, vertailu_fp_col2 = st.columns(2)
                    with vertailu_fp_col1:
                        st.metric("Oman joukkueen FP", f"{my_fp:.2f}")
                    with vertailu_fp_col2:
                        st.metric("Vastustajan FP", f"{opponent_fp:.2f}")


                    if my_total_games > opponent_total_games:
                        st.success(f"Oma joukkueesi saa arviolta **{my_total_games - opponent_total_games}** enemmän aktiivisia pelejä kuin vastustaja.")
                    elif my_total_games < opponent_total_games:
                        st.error(f"Vastustajan joukkue saa arviolta **{opponent_total_games - my_total_games}** enemmän aktiivisia pelejä kuin sinun joukkueesi.")
                    else:
                        st.info("Ennakoiduissa aktiivisissa peleissä ei ole eroa.")

                    if my_fp > opponent_fp:
                        st.success(f"Oma joukkueesi saa arviolta **{my_fp - opponent_fp:.2f}** enemmän fantasiapisteitä kuin vastustaja. Hyvin todennäköisesti voitat tämän viikon!")
                    elif my_fp < opponent_fp:
                        st.error(f"Vastustajasi saa arviolta **{opponent_fp - my_fp:.2f}** enemmän fantasiapisteitä kuin sinun joukkueesi. Sinun kannattaa harkita rosterisi muutoksia.")
                    else:
                        st.info("Ennakoiduissa fantasiapisteissä ei ole eroa.")
