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
    page_title="Fantasy Hockey Optimizer (Valioliika)",
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
    st.session_state['opponent_roster'] = (pd.DataFrame(), pd.DataFrame())
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
        return pd.DataFrame(), pd.DataFrame()
    try:
        sheet_url = st.secrets["free_agents_sheet"]["url"]
        sheet = client.open_by_url(sheet_url)
        worksheet = sheet.worksheet("Moose")
        data = worksheet.get_all_records()
        df = pd.DataFrame(data)

        if df.empty:
            st.warning("⚠️ 'Moose' välilehti on tyhjä tai sitä ei löytynyt.")
            return pd.DataFrame(), pd.DataFrame()

        df.columns = df.columns.str.strip().str.lower()
        required_columns = ['name', 'positions', 'team', 'fantasy_points_avg', 'injury status']
        missing_columns = [col for col in required_columns if col not in df.columns]
        if missing_columns:
            st.error(f"Seuraavat sarakkeet puuttuvat: {', '.join(missing_columns)}")
            return pd.DataFrame(), pd.DataFrame()

        df = df.rename(columns={"injury status": "injury_status"})
        df['fantasy_points_avg'] = pd.to_numeric(df['fantasy_points_avg'], errors='coerce').fillna(0)
        df['injury_status'] = df['injury_status'].fillna("").astype(str).str.strip().str.upper()

        # Yahoo-statukset
        yahoo_injury_statuses = {"IR", "IR+", "DTD", "O", "OUT", "INJ"}
        injured = df[df['injury_status'].isin(yahoo_injury_statuses)]
        healthy = df[~df.index.isin(injured.index)]

        return healthy, injured

    except Exception as e:
        st.error(f"Virhe rosterin lukemisessa: {e}")
        return pd.DataFrame(), pd.DataFrame()




def load_opponent_roster_from_gsheets(selected_team_name: str) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Lataa vastustajan rosterin Google Sheetsistä ja jakaa sen terveisiin ja loukkaantuneisiin Yahoo-statusten mukaan."""
    client = get_gspread_client()
    if client is None:
        st.error("Google Sheets -asiakas ei ole käytettävissä. Tarkista tunnistautuminen.")
        return pd.DataFrame(), pd.DataFrame()

    try:
        sheet_url = st.secrets["free_agents_sheet"]["url"]
        sheet = client.open_by_url(sheet_url)
        worksheet = sheet.worksheet("Valioliika Roster")
        data = worksheet.get_all_records()
        df = pd.DataFrame(data)

        if df.empty:
            st.warning("Välilehti 'T2 Lindgren Roster' on tyhjä.")
            return pd.DataFrame(), pd.DataFrame()

        # Normalisoidaan sarakenimet
        df.columns = df.columns.str.strip().str.lower()
        required = ["fantasy team", "player name", "position(s)", "nhl team", "fp", "injury status"]
        missing = [c for c in required if c not in df.columns]
        if missing:
            st.error(f"Puuttuvia sarakkeita: {missing}")
            return pd.DataFrame(), pd.DataFrame()

        # Suodatetaan valitun joukkueen mukaan
        team_df = df[df["fantasy team"] == selected_team_name].copy()
        if team_df.empty:
            st.warning(f"Joukkueella '{selected_team_name}' ei löytynyt pelaajia.")
            return pd.DataFrame(), pd.DataFrame()

        # Uudelleennimetään sarakkeet
        team_df = team_df.rename(columns={
            "player name": "name",
            "nhl team": "team",
            "position(s)": "positions",
            "fp": "fantasy_points_avg",
            "injury status": "injury_status"
        })

        # Muutetaan FP numeroksi
        team_df["fantasy_points_avg"] = pd.to_numeric(team_df["fantasy_points_avg"], errors="coerce").fillna(0)

        # Normalisoidaan injury_status
        team_df["injury_status"] = (
            team_df["injury_status"]
            .fillna("")
            .astype(str)
            .str.strip()
            .str.upper()
        )



        # Yahoo-statukset jotka lasketaan loukkaantuneiksi
        yahoo_injury_statuses = {"IR", "IR+", "DTD", "O", "OUT", "INJ"}

        # Loukkaantuneet = vain nämä
        injured = team_df[team_df["injury_status"].isin(yahoo_injury_statuses)]

        # Kaikki muu = terveet
        healthy = team_df[~team_df["injury_status"].isin(yahoo_injury_statuses)]

        return healthy, injured

    except Exception as e:
        st.error(f"Virhe vastustajan rosterin lataamisessa: {e}")
        return pd.DataFrame(), pd.DataFrame()


def load_free_agents_from_gsheets():
    client = get_gspread_client()
    if client is None:
        return pd.DataFrame()
    try:
        sheet_url = st.secrets["free_agents_sheet"]["url"]
        sheet = client.open_by_url(sheet_url)

        # Avataan nimenomaan "Valioliika FA" välilehti
        worksheet = sheet.worksheet("Valioliika FA")
        data = worksheet.get_all_records()
        df = pd.DataFrame(data)

        if df.empty:
            st.warning("⚠️ Valioliika FA-välilehti on tyhjä tai sitä ei löytynyt.")
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

# --- SIVUPALKKI: OMA ROSTERI ---
st.sidebar.subheader("📋 Lataa oma rosteri")

if st.sidebar.button("Lataa rosteri Google Sheetsistä", key="roster_button"):
    try:
        healthy, injured = load_roster_from_gsheets()

        if not healthy.empty or not injured.empty:
            # Tallennetaan kaikki kolme versiota session_stateen
            st.session_state['roster_healthy'] = healthy
            st.session_state['roster_injured'] = injured
            st.session_state['roster'] = pd.concat([healthy, injured], ignore_index=True)

            # Debug: näytä ladattujen pelaajien määrät
            st.sidebar.write(f"✅ Terveitä: {len(healthy)}, Loukkaantuneita: {len(injured)}")

            # Tallennetaan myös CSV:hen
            st.session_state['roster'].to_csv(ROSTER_FILE, index=False)

            st.sidebar.success("Rosteri ladattu onnistuneesti Google Sheetsistä!")
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
# --- SIVUPALKKI: VASTUSTAJAN ROSTERI ---
st.sidebar.subheader("📋 Lataa vastustajan rosteri")

# Alustetaan aina tupleksi, jos ei vielä olemassa
if "opponent_roster" not in st.session_state:
    st.session_state["opponent_roster"] = (pd.DataFrame(), pd.DataFrame())

client = get_gspread_client()
available_teams = []
if client:
    try:
        sheet_url = st.secrets["free_agents_sheet"]["url"]
        sheet = client.open_by_url(sheet_url)
        worksheet = sheet.worksheet("Valioliika Roster")
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
        opponent_healthy, opponent_injured = load_opponent_roster_from_gsheets(selected_opponent_team)

        if not opponent_healthy.empty or not opponent_injured.empty:
            st.session_state["opponent_roster"] = (opponent_healthy, opponent_injured)
            st.sidebar.success(
                f"{selected_opponent_team} rosteri ladattu onnistuneesti! "
                f"({len(opponent_healthy) + len(opponent_injured)} pelaajaa)"
            )
        else:
            st.sidebar.error("Vastustajan rosterin lataus epäonnistui tai tulos on tyhjä.")

# Nollauspainike
if st.sidebar.button("Nollaa vastustajan rosteri"):
    st.session_state["opponent_roster"] = (pd.DataFrame(), pd.DataFrame())
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
    st.header("📊 Nykyinen rosteri (Valioliika)")

    # Puretaan rosterit turvallisesti
    my_roster = st.session_state.get("roster", pd.DataFrame())
    opponent_healthy, opponent_injured = st.session_state.get(
        "opponent_roster", (pd.DataFrame(), pd.DataFrame())
    )

    # Alustetaan aina, jotta NameError ei voi tulla
    healthy = st.session_state.get("roster_healthy", pd.DataFrame())
    injured = st.session_state.get("roster_injured", pd.DataFrame())
    roster_to_use = pd.DataFrame()

    # Tarkistus: molemmat rosterit oltava ladattuna
    if my_roster.empty:
        st.warning("Lataa oma rosteri nähdäksesi pelaajat.")
    else:
    # jatka näyttämään oma rosteri

        # Toggle: näytetäänkö kaikki vai vain terveet
        show_all = st.toggle("Näytä kaikki pelaajat (myös loukkaantuneet)",
                             value=False, key="show_all_roster")

        if show_all:
            if not healthy.empty or not injured.empty:
                roster_to_use = pd.concat([healthy, injured])
        else:
            roster_to_use = healthy

        # Näytetään analyysissä käytettävä rosteri
        if not roster_to_use.empty:
            roster_to_use = roster_to_use.reset_index(drop=True)
            roster_to_use.index = roster_to_use.index + 1
            roster_to_use = roster_to_use.reset_index().rename(columns={"index": "Rivi"})

            st.subheader("✅ Analyysissä käytettävä rosteri")
            st.dataframe(roster_to_use, use_container_width=True, hide_index=True)

        # Näytetään loukkaantuneet erikseen
        if not injured.empty:
            st.subheader("🚑 Loukkaantuneet pelaajat")
            st.dataframe(injured.reset_index(drop=True),
                         use_container_width=True, hide_index=True)

    st.subheader("Joukkueiden jakauma")
    if not my_roster.empty:
        team_counts = my_roster['team'].value_counts()
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
                    roster_to_use,
                    pos_limits,
                    num_attempts=200   # esim. 200 yritystä
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

# --- Simuloi uuden pelaajan vaikutus ---
st.header("🔮 Simuloi uuden pelaajan vaikutus")

if not st.session_state['roster'].empty and 'schedule' in st.session_state and not st.session_state['schedule'].empty and start_date <= end_date:
    st.subheader("Valitse vertailutyyppi")
    comparison_type = st.radio(
        "Valitse vertailutyyppi:",
        ["Vertaa kahta uutta pelaajaa", "Lisää uusi pelaaja ja poista valittu omasta rosterista"],
        key="comparison_type"
    )

    # --- Syötteet ---
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

        remove_sim_player = st.selectbox(
            "Pelaaja poistettavaksi rosterista (valinnainen)",
            [""] + list(st.session_state['roster']['name'])
        )

    else:
        st.markdown("#### Pudotettava pelaaja")
        drop_player_name = st.selectbox(
            "Valitse pudotettava pelaaja",
            list(st.session_state['roster']['name']),
            key="drop_player_name"
        )

        st.markdown("#### Lisättävä pelaaja")
        colN1, colN2, colN3, colN4 = st.columns(4)
        with colN1:
            new_player_name = st.text_input("Pelaajan nimi", key="new_player_name")
        with colN2:
            new_player_team = st.text_input("Joukkue", key="new_player_team")
        with colN3:
            new_player_positions = st.text_input("Pelipaikat (esim. C/LW)", key="new_player_positions")
        with colN4:
            new_player_fpa = st.number_input("FP/GP", min_value=0.0, step=0.1, format="%.2f", key="new_player_fpa")

    # --- Suoritus ---
    if st.button("Suorita vertailu"):
        schedule_filtered = st.session_state['schedule'][
            (st.session_state['schedule']['Date'] >= pd.to_datetime(start_date)) &
            (st.session_state['schedule']['Date'] <= pd.to_datetime(end_date))
        ]
        if schedule_filtered.empty:
            st.warning("Ei pelejä valitulla aikavälillä.")
            st.stop()

        # Baseline (oma rosteri sellaisenaan): sama purku ja yritysmäärä kuin optimointiosiossa
        daily_base, base_games_dict, base_fp, base_total_active_games, base_bench_dict = optimize_roster_advanced(
            schedule_filtered, st.session_state['roster'], pos_limits, num_attempts=200
        )

        # --- Kahden uuden pelaajan vertailu ---
        if comparison_type == "Vertaa kahta uutta pelaajaa":
            # Validointi
            if not (sim_name_A and sim_team_A and sim_positions_A):
                st.warning("Täytä Pelaaja A: nimi, joukkue ja pelipaikat.")
                st.stop()
            if not (sim_name_B and sim_team_B and sim_positions_B):
                st.warning("Täytä Pelaaja B: nimi, joukkue ja pelipaikat.")
                st.stop()

            # Rakennetaan pohja-rosteri mahdollisella pudotuksella
            base_for_compare = st.session_state['roster'].copy()
            if remove_sim_player:
                base_for_compare = base_for_compare[base_for_compare['name'] != remove_sim_player]

            # Skenaario A
            sim_roster_A = pd.concat([base_for_compare, pd.DataFrame([{
                'name': sim_name_A,
                'team': sim_team_A,
                'positions': sim_positions_A,
                'fantasy_points_avg': sim_fpa_A
            }])], ignore_index=True)
            daily_A, games_A_dict, fp_A, total_active_A, bench_A_dict = optimize_roster_advanced(
                schedule_filtered, sim_roster_A, pos_limits, num_attempts=200
            )

            # Skenaario B
            sim_roster_B = pd.concat([base_for_compare, pd.DataFrame([{
                'name': sim_name_B,
                'team': sim_team_B,
                'positions': sim_positions_B,
                'fantasy_points_avg': sim_fpa_B
            }])], ignore_index=True)
            daily_B, games_B_dict, fp_B, total_active_B, bench_B_dict = optimize_roster_advanced(
                schedule_filtered, sim_roster_B, pos_limits, num_attempts=200
            )

            # Pelaajakohtaiset pelit
            player_A_active = games_A_dict.get(sim_name_A, 0)
            player_B_active = games_B_dict.get(sim_name_B, 0)
            dropped_active = base_games_dict.get(remove_sim_player, 0) if remove_sim_player else 0

            # Yhteenveto molemmista skenaarioista rinnakkain
            st.subheader("Skenaarioiden vertailu (kokonaisluvut)")
            colA, colB = st.columns(2)
            with colA:
                st.markdown(f"**Skenaario A: {sim_name_A}**")
                st.metric("Aktiiviset pelit (yht.)", total_active_A)
                st.metric("Fantasiapisteet (yht.)", f"{fp_A:.1f}")
                st.metric("Lisättävän pelaajan omat pelit", player_A_active)
                if remove_sim_player:
                    st.metric(f"{remove_sim_player} menetetyt pelit (baseline)", dropped_active)
            with colB:
                st.markdown(f"**Skenaario B: {sim_name_B}**")
                st.metric("Aktiiviset pelit (yht.)", total_active_B)
                st.metric("Fantasiapisteet (yht.)", f"{fp_B:.1f}")
                st.metric("Lisättävän pelaajan omat pelit", player_B_active)
                if remove_sim_player:
                    st.metric(f"{remove_sim_player} menetetyt pelit (baseline)", dropped_active)

            # Erot baselineen
            st.subheader("Erot verrattuna baselineen")
            colDA, colDB = st.columns(2)
            with colDA:
                st.markdown(f"**Erot skenaario A → baseline**")
                st.metric("Δ Aktiiviset pelit (yht.)", f"{total_active_A - base_total_active_games:+}")
                st.metric("Δ Fantasiapisteet (yht.)", f"{fp_A - base_fp:+.1f}")
            with colDB:
                st.markdown(f"**Erot skenaario B → baseline**")
                st.metric("Δ Aktiiviset pelit (yht.)", f"{total_active_B - base_total_active_games:+}")
                st.metric("Δ Fantasiapisteet (yht.)", f"{fp_B - base_fp:+.1f}")

            st.caption(
                "Huom: Kokonaispelimäärä voi muuttua myös muiden pelaajien takia (esim. UTIL vapautuu), "
                "ei vain lisättävän/pudotettavan pelaajan pelien eron vuoksi."
            )

        # --- Yksi lisäys ja pudotus ---
        else:
            # Validointi
            if not drop_player_name:
                st.warning("Valitse pudotettava pelaaja.")
                st.stop()
            if not (new_player_name and new_player_team and new_player_positions):
                st.warning("Täytä lisättävän pelaajan kentät (nimi, joukkue, pelipaikat).")
                st.stop()

            # Baseline: pudotettava mukana
            base_drop_active = base_games_dict.get(drop_player_name, 0)
            base_drop_fpa = (
                st.session_state['roster']
                .loc[st.session_state['roster']['name'] == drop_player_name, 'fantasy_points_avg']
            )
            base_drop_fpa = float(base_drop_fpa.iloc[0]) if not base_drop_fpa.empty else 0.0

            # Swap: pudotettava pois, uusi sisään
            new_player_row = {
                'name': new_player_name,
                'team': new_player_team,
                'positions': new_player_positions,
                'fantasy_points_avg': new_player_fpa
            }
            swap_roster = st.session_state['roster'][st.session_state['roster']['name'] != drop_player_name].copy()
            swap_roster = pd.concat([swap_roster, pd.DataFrame([new_player_row])], ignore_index=True)

            daily_swap, swap_games_dict, swap_fp, swap_total_active_games, swap_bench_dict = optimize_roster_advanced(
                schedule_filtered, swap_roster, pos_limits, num_attempts=200
            )
            new_player_active = swap_games_dict.get(new_player_name, 0)

            # Rinnakkainen näyttö
            st.subheader("Skenaarioiden vertailu (kokonaisluvut)")
            colBL, colSW = st.columns(2)
            with colBL:
                st.markdown(f"**Baseline (pudotettava mukana): {drop_player_name}**")
                st.metric("Aktiiviset pelit (yht.)", base_total_active_games)
                st.metric("Fantasiapisteet (yht.)", f"{base_fp:.1f}")
                st.metric(f"{drop_player_name} aktiiviset pelit", base_drop_active)
                st.metric(f"{drop_player_name} ennakoidut FP", f"{base_drop_active * base_drop_fpa:.1f}")
            with colSW:
                st.markdown(f"**Swap (pudotettava pois, uusi sisään): {new_player_name}**")
                st.metric("Aktiiviset pelit (yht.)", swap_total_active_games)
                st.metric("Fantasiapisteet (yht.)", f"{swap_fp:.1f}")
                st.metric(f"{new_player_name} aktiiviset pelit", new_player_active)
                st.metric(f"{new_player_name} ennakoidut FP", f"{new_player_active * new_player_fpa:.1f}")

            # Erot baselineen
            st.subheader("Erot verrattuna baselineen")
            st.metric("Δ Aktiiviset pelit (yht.)", f"{swap_total_active_games - base_total_active_games:+}")
            st.metric("Δ Fantasiapisteet (yht.)", f"{swap_fp - base_fp:+.1f}")

            st.caption(
                "Huom: Kokonaispelimäärä voi kasvaa pienistäkin muutoksista, koska pudottaminen voi vapauttaa paikan "
                "toiselle pelaajalle aktiiviseen rosteriin (myös UTIL-paikalle), vaikka lisättävän pelaajan pelimäärä olisi sama."
            )
else:
    st.info("Tarvitaan rosteri, otteluohjelma ja validi aikaväli (start_date ≤ end_date).")



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

    # Puretaan rosterit turvallisesti
    my_roster = st.session_state.get("roster", pd.DataFrame())
    opponent_healthy, opponent_injured = st.session_state.get("opponent_roster", (pd.DataFrame(), pd.DataFrame()))

    # Tarkistetaan että molemmilla on dataa
    if my_roster.empty or (opponent_healthy.empty and opponent_injured.empty):
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
            # --- Togglejen tila säilyy session_statessa ---
            if "show_all_my_roster" not in st.session_state:
                st.session_state["show_all_my_roster"] = False
            if "show_all_opponent_roster" not in st.session_state:
                st.session_state["show_all_opponent_roster"] = False

            st.session_state["show_all_my_roster"] = st.toggle(
                "Oman joukkueen analyysissä mukana myös loukkaantuneet",
                value=st.session_state["show_all_my_roster"],
                key="show_all_my_roster_toggle"
            )
            st.session_state["show_all_opponent_roster"] = st.toggle(
                "Vastustajan analyysissä mukana myös loukkaantuneet",
                value=st.session_state["show_all_opponent_roster"],
                key="show_all_opponent_roster_toggle"
            )

            if st.button("Suorita joukkuevertailu", key="roster_compare_button"):
                with st.spinner("Vertailu käynnissä..."):

                    # --- Oma rosteri ---
                    my_healthy = st.session_state.get('roster_healthy', pd.DataFrame())
                    my_injured = st.session_state.get('roster_injured', pd.DataFrame())

                    if st.session_state["show_all_my_roster"]:
                        my_roster_to_use = pd.concat([my_healthy, my_injured])
                    else:
                        my_roster_to_use = my_healthy

                    _, my_games_dict, my_fp, my_total_games, my_bench_games = optimize_roster_advanced(
                        schedule_filtered, my_roster_to_use, pos_limits
                    )

                    # --- Vastustajan rosteri ---
                    if st.session_state["show_all_opponent_roster"]:
                        opponent_roster_to_use = pd.concat([opponent_healthy, opponent_injured])
                    else:
                        opponent_roster_to_use = opponent_healthy

                    _, opponent_games_dict, opponent_fp, opponent_total_games, opponent_bench_games = optimize_roster_advanced(
                        schedule_filtered, opponent_roster_to_use, pos_limits
                    )

                    # --- Oma joukkue DataFrame ---
                    my_players_data = []
                    for name, games in my_games_dict.items():
                        fpa = my_roster_to_use.loc[my_roster_to_use['name'] == name, 'fantasy_points_avg'].iloc[0] \
                              if not my_roster_to_use[my_roster_to_use['name'] == name].empty else 0
                        my_players_data.append({
                            'Pelaaja': name,
                            'Aktiiviset pelit': games,
                            'Ennakoidut FP': round(games * fpa, 2)
                        })
                    my_df = pd.DataFrame(my_players_data).sort_values(by='Ennakoidut FP', ascending=False)

                    # --- Vastustajan joukkue DataFrame ---
                    opponent_players_data = []
                    for name, games in opponent_games_dict.items():
                        fpa = opponent_roster_to_use.loc[opponent_roster_to_use['name'] == name, 'fantasy_points_avg'].iloc[0] \
                              if not opponent_roster_to_use[opponent_roster_to_use['name'] == name].empty else 0
                        opponent_players_data.append({
                            'Pelaaja': name,
                            'Aktiiviset pelit': games,
                            'Ennakoidut FP': round(games * fpa, 2)
                        })
                    opponent_df = pd.DataFrame(opponent_players_data).sort_values(by='Ennakoidut FP', ascending=False)

                    # --- Näytetään tulokset ---
                    st.subheader("Yksityiskohtainen vertailu")
                    col1_detail, col2_detail = st.columns(2)

                    with col1_detail:
                        st.markdown("**Oma joukkueesi**")
                        if not my_df.empty:
                            my_display = my_df.merge(
                                my_roster_to_use[["name", "positions", "team"]],
                                left_on="Pelaaja", right_on="name", how="left"
                            ).drop(columns=["name"])
                            my_display.insert(0, "#", range(1, len(my_display) + 1))
                            st.dataframe(
                                my_display[["#", "Pelaaja", "positions", "team", "Aktiiviset pelit", "Ennakoidut FP"]],
                                use_container_width=True, hide_index=True
                            )
                        # Loukkaantuneet vain jos EI sisällytetty päärosteriin
                        if not my_injured.empty and not st.session_state["show_all_my_roster"]:
                            st.markdown("🚑 **Loukkaantuneet**")
                            st.dataframe(
                                my_injured.reset_index(drop=True)[["name", "positions", "team", "fantasy_points_avg"]],
                                use_container_width=True, hide_index=True
                            )

                    with col2_detail:
                        st.markdown("**Vastustajan joukkue**")
                        if not opponent_df.empty:
                            opp_display = opponent_df.merge(
                                opponent_roster_to_use[["name", "positions", "team"]],
                                left_on="Pelaaja", right_on="name", how="left"
                            ).drop(columns=["name"])
                            opp_display.insert(0, "#", range(1, len(opp_display) + 1))
                            st.dataframe(
                                opp_display[["#", "Pelaaja", "positions", "team", "Aktiiviset pelit", "Ennakoidut FP"]],
                                use_container_width=True, hide_index=True
                            )
                        if not opponent_injured.empty and not st.session_state["show_all_opponent_roster"]:
                            st.markdown("🚑 **Loukkaantuneet**")
                            st.dataframe(
                                opponent_injured.reset_index(drop=True)[["name", "positions", "team", "fantasy_points_avg"]],
                                use_container_width=True, hide_index=True
                            )

                # --- Yhteenveto: FP ja pelimäärät markdown-tyylillä ---
                    st.subheader("📊 Yhteenveto")
                    
                    col1, col2 = st.columns(2)
                    
                    with col1:
                        st.markdown(f"""
                        ### 🟦 Oma joukkue  
                        **{round(my_fp, 2)} FP**  
                        {my_total_games} peliä
                        """)
                    
                    with col2:
                        st.markdown(f"""
                        ### 🟥 Vastustaja  
                        **{round(opponent_fp, 2)} FP**  
                        {opponent_total_games} peliä
                        """)
                    
                    # Voittoviesti
                    if my_fp > opponent_fp:
                        st.success(f"✅ Oma joukkueesi on vahvempi! (+{round(my_fp - opponent_fp, 2)} FP, "
                                   f"{my_total_games} vs {opponent_total_games} peliä)")
                    elif opponent_fp > my_fp:
                        st.error(f"❌ Vastustaja on vahvempi. ({round(opponent_fp - my_fp, 2)} FP enemmän, "
                                 f"{opponent_total_games} vs {my_total_games} peliä)")
                    else:
                        st.info(f"Tasapeli – molemmilla joukkueilla yhtä paljon pisteitä "
                                f"({my_total_games} vs {opponent_total_games} peliä)")
                    
