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

# Yritä tuoda 'yahoofantasy' kirjasto. Tämä epäonnistuu, jos sitä ei ole asennettu.
try:
    from yahoofantasy import Context
    YAHOO_FANTASY_AVAILABLE = True
except ImportError:
    YAHOO_FANTASY_AVAILABLE = False

# Aseta sivun konfiguraatio
st.set_page_config(
    page_title="Fantasy Hockey Optimizer Yahoo",
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
if 'free_agents' not in st.session_state:
    st.session_state['free_agents'] = pd.DataFrame()
if 'team_impact_results' not in st.session_state:
    st.session_state['team_impact_results'] = None

# --- YAHOO FANTASY FUNKTIO (Lopullinen ja korjattu) ---

@st.cache_data(show_spinner="Ladataan dataa Yahoo Fantasysta...")
def load_data_from_yahoo_fantasy(league_id: str, team_name: str, roster_type: str):
    """Lataa rosterin tai vapaat agentit Yahoo Fantasysta käyttäen raakaa Refresh Tokenia."""
    
    if not YAHOO_FANTASY_AVAILABLE:
        st.error("Kirjasto 'yahoofantasy' ei ole asennettuna. Asenna: pip install yahoofantasy")
        return pd.DataFrame()

    try:
        # 1. Tarkistetaan salaisuudet
        if ("yahoo" not in st.secrets or 
            "client_id" not in st.secrets["yahoo"] or 
            "client_secret" not in st.secrets["yahoo"] or 
            "raw_refresh_token" not in st.secrets["yahoo"]): 
            
            st.warning("Yahoo-datan lataus epäonnistui: 'client_id', 'client_secret' tai 'raw_refresh_token' puuttuvat secrets.toml-tiedostosta.")
            return pd.DataFrame()

        # 2. Alustetaan Yahoo Fantasy Context
        sc = Context(
            client_id=st.secrets["yahoo"]["client_id"],
            client_secret=st.secrets["yahoo"]["client_secret"],
            refresh_token=st.secrets["yahoo"]["raw_refresh_token"]
        )
        
        # 3. LIIGAN HAKU (LOPULLINEN KORJAUS VIRHEESEEN 'Context' object has no attribute 'league')
        lg = None
        user = sc.get_user()
        user_leagues = user.leagues()
        
        # Etsitään haluttu liiga ID:n perusteella
        lg = next((l for l in user_leagues if l.league_id == league_id), None)
        
        if lg is None:
            st.error(f"Liigaa ID:llä {league_id} ei löytynyt Yahoo Fantasysta tällä käyttäjällä. Tarkista ID.")
            return pd.DataFrame()
            
        data = []
        
        if roster_type == 'my_roster':
            # Etsitään oma joukkue nimen perusteella
            teams = lg.teams()
            my_team = next((t for t in teams if t.name == team_name), None)
            if not my_team:
                st.error(f"Joukkue nimellä '{team_name}' ei löytynyt liigasta ID:llä {league_id}.")
                return pd.DataFrame()

            roster_data = my_team.roster() 
            
            for p in roster_data:
                data.append({
                    'name': p.name,
                    'team': p.editorial_team_abbr, 
                    'positions': "/".join(p.eligible_positions), 
                    'fantasy_points_avg': 0.0
                })
            
            st.success(f"Rosteri ladattu joukkueelle '{team_name}'!")
            return pd.DataFrame(data)

        elif roster_type == 'free_agents':
            # Haetaan vapaat agentit (top-200)
            free_agents = lg.free_agents(limit=200) 
            
            for p in free_agents:
                data.append({
                    'name': p.name,
                    'team': p.editorial_team_abbr, 
                    'positions': "/".join(p.eligible_positions), 
                    'fantasy_points_avg': 0.0
                })
            
            st.success("Vapaat agentit ladattu onnistuneesti!")
            return pd.DataFrame(data)
            
    except Exception as e:
        # Yleinen virheen käsittely
        if "Authentication failed" in str(e) or "access token is missing" in str(e) or "Client ID, secret, and refresh token are required" in str(e):
            st.error("Yahoo-autentikointi epäonnistui. Varmista, että 'raw_refresh_token' on oikein secrets.toml-tiedostossa.")
        else:
            st.error(f"Virhe Yahoo-datan latauksessa: {e}")
            st.warning("Tarkista konsoli saadaksesi lisätietoja virheestä.")
        return pd.DataFrame()

# --- GOOGLE SHEETS LATAUSFUNKTIOT (Muokkaamaton) ---
@st.cache_resource
def get_gspread_client():
    # ... (muokkaamaton)
    try:
        scopes = ['https://www.googleapis.com/auth/spreadsheets']
        creds_json = st.secrets["gcp_service_account"]
        creds = Credentials.from_service_account_info(creds_json, scopes=scopes)
        client = gspread.authorize(creds)
        return client
    except Exception as e:
        #st.error(f"Virhe Google Sheets -tunnistautumisessa. Tarkista secrets.toml-tiedostosi: {e}")
        return None

def load_roster_from_gsheets():
    client = get_gspread_client()
    if client is None:
        return pd.DataFrame()
    try:
        sheet_url = st.secrets["roster_sheet"]["url"]
        sheet = client.open_by_url(sheet_url).sheet1
        data = sheet.get_all_records()
        df = pd.DataFrame(data)
        if 'fantasy_points_avg' not in df.columns:
            df['fantasy_points_avg'] = 0.0
        df['fantasy_points_avg'] = pd.to_numeric(df['fantasy_points_avg'], errors='coerce').fillna(0)
        return df
    except Exception as e:
        st.error(f"Virhe Google Sheets -tiedoston lukemisessa: {e}")
        return pd.DataFrame()

def load_free_agents_from_gsheets():
    client = get_gspread_client()
    if client is None:
        return pd.DataFrame()
    try:
        sheet_url = st.secrets["free_agents_sheet"]["url"]
        sheet = client.open_by_url(sheet_url).sheet1
        data = sheet.get_all_records()
        df = pd.DataFrame(data)

        required_columns = ['name', 'team', 'positions', 'fantasy_points_avg']
        missing_columns = [col for col in required_columns if col not in df.columns]
        if missing_columns:
            st.error(f"Seuraavat sarakkeet puuttuvat vapaiden agenttien tiedostosta: {', '.join(missing_columns)}")
            return pd.DataFrame()

        df['fantasy_points_avg'] = pd.to_numeric(df['fantasy_points_avg'], errors='coerce')
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
# ... (muokkaamaton)
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

# UUSI YAHOO LATAUS VALINTA
if YAHOO_FANTASY_AVAILABLE:
    with st.sidebar.expander("Lataa Yahoo Fantasysta"):
        yahoo_league_id = st.text_input("Yahoo League ID (esim. nhl.l.XXXXXX)", key="yahoo_roster_league_id")
        yahoo_team_name = st.text_input("Oman joukkueen nimi Yahoo Fantasyssä", key="yahoo_roster_team_name")
        if st.button("Lataa Yahoo-rosteri", key="yahoo_roster_button") and yahoo_league_id and yahoo_team_name:
            roster_df = load_data_from_yahoo_fantasy(yahoo_league_id, yahoo_team_name, 'my_roster')
            if not roster_df.empty:
                st.session_state['roster'] = roster_df
                roster_df.to_csv(ROSTER_FILE, index=False)
                st.rerun()

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

# UUSI YAHOO LATAUS VALINTA
if YAHOO_FANTASY_AVAILABLE:
    with st.sidebar.expander("Lataa Yahoo Fantasysta"):
        yahoo_fa_league_id = st.text_input("Yahoo League ID (FA)", key="yahoo_fa_league_id")
        if st.button("Lataa Yahoo vapaat agentit", key="yahoo_fa_button") and yahoo_fa_league_id:
            # Käytetään tyhjää joukkueen nimeä FA-latauksessa
            free_agents_df = load_data_from_yahoo_fantasy(yahoo_fa_league_id, "", 'free_agents')
            if not free_agents_df.empty:
                st.session_state['free_agents'] = free_agents_df
                st.rerun()

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
# ... (muokkaamaton - säilytetty vanha logiikka tiedostolataajalle)
if 'opponent_roster' in st.session_state and st.session_state['opponent_roster'] is not None and not st.session_state['opponent_roster'].empty:
    st.sidebar.success("Vastustajan rosteri ladattu!")
    
    if st.sidebar.button("Lataa uusi vastustajan rosteri"):
        st.session_state['opponent_roster'] = None
        st.rerun()
else:
    st.sidebar.info("Lataa vastustajan rosteri CSV-tiedostona")
    opponent_roster_file = st.sidebar.file_uploader(
        "Valitse CSV-tiedosto",
        type=["csv"],
        key="opponent_roster_uploader",
        help="CSV-tiedoston tulee sisältää sarakkeet: name, team, positions, (fantasy_points_avg)"
    )
    
    if opponent_roster_file is not None:
        try:
            opponent_roster = pd.read_csv(opponent_roster_file)
            if not opponent_roster.empty and all(col in opponent_roster.columns for col in ['name', 'team', 'positions']):
                if 'fantasy_points_avg' not in opponent_roster.columns:
                    opponent_roster['fantasy_points_avg'] = 0.0
                    st.sidebar.info("Lisätty puuttuva 'fantasy_points_avg'-sarake oletusarvolla 0.0")
                opponent_roster['fantasy_points_avg'] = pd.to_numeric(opponent_roster['fantasy_points_avg'], errors='coerce').fillna(0)
                st.session_state['opponent_roster'] = opponent_roster
                opponent_roster.to_csv(OPPONENT_ROSTER_FILE, index=False)
                st.sidebar.success("Vastustajan rosteri ladattu ja tallennettu!")
                st.rerun()
            else:
                st.sidebar.error("Vastustajan rosterin CSV-tiedoston tulee sisältää sarakkeet: name, team, positions, (fantasy_points_avg)")
        except Exception as e:
            st.sidebar.error(f"Virhe vastustajan rosterin lukemisessa: {str(e)}")

# Nollauspainike
if st.sidebar.button("Nollaa vastustajan rosteri"):
    st.session_state['opponent_roster'] = None
    st.rerun()


# --- SIVUPALKKI: ROSTERIN HALLINTA ---
# ... (muokkaamaton)
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
# ... (muokkaamaton)
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
# ... (muokkaamaton - optimize_roster_advanced, simulate_team_impact, calculate_team_impact_by_position, analyze_free_agents)
def optimize_roster_advanced(schedule_df, roster_df, limits, num_attempts=100):
    players_info = {}
    for _, player in roster_df.iterrows():
        positions_str = player['positions']
        if pd.isna(positions_str):
            positions_list = []
        elif isinstance(positions_str, str):
            positions_list = [p.strip() for p in positions_str.replace(',', '/').split('/')]
        else:
            positions_list = positions_str
        
        players_info[player['name']] = {
            'team': player['team'],
            'positions': positions_list,
            'fpa': player.get('fantasy_points_avg', 0)
        }
    
    daily_results = []
    player_games = {name: 0 for name in players_info.keys()}
    
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
                
                # Sijoita ensin ensisijaisille paikoille
                for pos in positions_list:
                    if pos in limits and len(active[pos]) < limits[pos]:
                        active[pos].append(player_name)
                        placed = True
                        break
                
                # Jos ei sijoitettu, yritä UTIL-paikkaa
                if not placed and 'UTIL' in limits and len(active['UTIL']) < limits['UTIL']:
                    # Tarkista, että pelaaja voi pelata UTIL-paikalla (ei G)
                    if any(pos in ['C', 'LW', 'RW', 'D'] for pos in positions_list):
                        active['UTIL'].append(player_name)
                        placed = True
                
                if not placed:
                    bench.append(player_name)
            
            # Optimointi: vaihda penkillä olevia parempia pelaajia heikompien tilalle
            improved = True
            while improved:
                improved = False
                
                bench_copy = sorted(bench, key=lambda name: players_info[name]['fpa'], reverse=True)
                
                for bench_player_name in bench_copy:
                    bench_player_fpa = players_info[bench_player_name]['fpa']
                    bench_player_positions = players_info[bench_player_name]['positions']
                    
                    swapped = False
                    for active_pos, active_players in active.items():
                        # Järjestä aktiiviset pelaajat FP/GP:n mukaan
                        active_sorted = sorted([(name, i) for i, name in enumerate(active_players)], key=lambda x: players_info[x[0]]['fpa'])
                        
                        for active_player_name, active_idx in active_sorted:
                            active_player_fpa = players_info[active_player_name]['fpa']

                            # Tarkista, voidaanko tehdä parantava vaihto
                            if (
                                bench_player_fpa > active_player_fpa and 
                                active_pos in bench_player_positions
                            ):
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

            # Laske nykyisen kokoonpanon pisteet
            current_fp = sum(
                players_info[player_name]['fpa']
                for players in active.values()
                for player_name in players
            )
            
            if current_fp > best_assignment_fp:
                best_assignment_fp = current_fp
                best_assignment = {
                    'active': {pos: players[:] for pos, players in active.items()},
                    'bench': bench[:]
                }
            
            elif current_fp == best_assignment_fp and best_assignment:
                current_active_count = sum(len(players) for players in active.values())
                best_active_count = sum(len(players) for players in best_assignment['active'].values())
                if current_active_count > best_active_count:
                    best_assignment = {
                        'active': {pos: players[:] for pos, players in active.items()},
                        'bench': bench[:]
                    }

        if best_assignment is None:
            best_assignment = {
                'active': {pos: [] for pos in limits.keys()},
                'bench': [p['name'] for p in available_players]
            }
            
        daily_results.append({
            'Date': date.date(),
            'Active': best_assignment['active'],
            'Bench': best_assignment['bench']
        })
        
        for pos, players in best_assignment['active'].items():
            for player_name in players:
                player_games[player_name] += 1
    
    total_fantasy_points = sum(
        player_games[name] * players_info[name]['fpa'] for name in players_info
    )
    
    total_active_games = sum(player_games.values())

    return daily_results, player_games, total_fantasy_points, total_active_games

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
            _, player_games, _, _ = optimize_roster_advanced(
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
        #st.warning("Joukkueanalyysiä tai vapaiden agenttien listaa ei ole ladattu.")
        return pd.DataFrame()

    # SUODATUS TÄSSÄ: Jätä pois pelaajat, joiden pelipaikka on "G"
    free_agents_df = free_agents_df[~free_agents_df['positions'].str.contains('G')].copy()
    if free_agents_df.empty:
        #st.info("Vapaita agentteja ei löytynyt maalivahtien suodatuksen jälkeen.")
        return pd.DataFrame()
        
    team_impact_df_list = []
    for pos, df in team_impact_dict.items():
        if not df.empty and pos != 'G':  # Myös joukkueanalyysista pois maalivahdit
            df['position'] = pos
            team_impact_df_list.append(df)
    
    if not team_impact_df_list:
        #st.warning("Joukkueanalyysin tuloksia ei löytynyt kenttäpelaajille.")
        return pd.DataFrame()

    combined_impact_df = pd.concat(team_impact_df_list, ignore_index=True)
    combined_impact_df.rename(columns={'Joukkue': 'team', 'Lisäpelit': 'extra_games_total'}, inplace=True)
    
    results = free_agents_df.copy()
    results['total_impact'] = 0.0
    results['games_added'] = 0.0
    
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
tab1, tab2, tab3 = st.tabs(["Rosterin optimointi", "Joukkueiden vertailu", "Joukkuevertailu"])

with tab1:
    st.header("📊 Nykyinen rosteri")
    if st.session_state['roster'].empty:
        st.warning("Lataa rosteri nähdäksesi pelaajat")
    else:
        st.dataframe(st.session_state['roster'], use_container_width=True)
        
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
                daily_results, total_games, total_fp, total_active_games = optimize_roster_advanced(
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
            
            st.subheader("Pelaajien kokonaispelimäärät")
            games_df = pd.DataFrame({
                'Pelaaja': list(total_games.keys()),
                'Pelit': list(total_games.values())
            }).sort_values('Pelit', ascending=False)
            st.dataframe(games_df, use_container_width=True)
            
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
                    player_name for player_name, info in players_info_dict.items() if info['team'] in day_games['Visitor'].tolist() or info['team'] in day_games['Home'].tolist()
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
            
    # UUSI OSA VAPAIDEN AGENTTIEN ANALYYSILLE
    st.header("✨ Vapaiden agenttien analyysi")
    st.markdown("Analysoi, kuinka paljon vapaat agentit tuottavat lisäpelejä ja pisteitä rosteriisi. Voit simuloida pelaajan pudottamista rosteristasi, jolloin analyysi ottaa sen huomioon.")
    
    if st.session_state['roster'].empty or st.session_state['schedule'].empty or 'free_agents' not in st.session_state or st.session_state['free_agents'].empty:
        st.warning("Lataa ensin peliaikataulu, oma rosteri ja vapaat agentit!")
    else:
        # Valinta pudotettavalle pelaajalle
        drop_player = st.selectbox(
            "Valitse pelaaja pudotettavaksi rosterista (valinnainen)",
            [""] + list(st.session_state['roster']['name']),
            help="Analyysi simuloidaan, ikään kuin valittu pelaaja ei olisi rosterissasi."
        )
        
        # Luo rosteri analyysiä varten
        if drop_player:
            roster_for_analysis = st.session_state['roster'][st.session_state['roster']['name'] != drop_player].copy()
        else:
            roster_for_analysis = st.session_state['roster'].copy()
        
        with st.spinner("Analysoidaan vapaiden agenttien vaikutusta..."):
            schedule_filtered = st.session_state['schedule'][
                (st.session_state['schedule']['Date'] >= pd.to_datetime(start_date)) &
                (st.session_state['schedule']['Date'] <= pd.to_datetime(end_date))
            ]
            if schedule_filtered.empty:
                st.warning("Ei pelejä valitulla aikavälillä.")
            else:
                team_impact_results = calculate_team_impact_by_position(
                    schedule_filtered, 
                    roster_for_analysis, 
                    pos_limits
                )
                free_agent_analysis = analyze_free_agents(
                    team_impact_results, 
                    st.session_state['free_agents']
                )

                if not free_agent_analysis.empty:
                    st.subheader("Vapaiden agenttien vaikutus nykyiseen rosteriin")
                    st.info("Taulukko on lajiteltu **total_impact**-sarakkeen mukaan, joka kuvastaa pelaajan kokonaisvaikutusta (saadut lisäpelit * FP/GP).")
                    st.dataframe(free_agent_analysis, use_container_width=True)
                    csv = free_agent_analysis.to_csv(index=False).encode('utf-8')
                    st.download_button(
                        "Lataa tulokset CSV-muodossa",
                        data=csv,
                        file_name='vapaiden_agenttien_analyysi.csv',
                        mime='text/csv'
                    )
                else:
                    st.info("Ei analysoitavia vapaita agentteja tai tietoja puuttuu.")

with tab2:
    st.header("🆚 Joukkueiden vertailu")
    if st.session_state['roster'].empty or st.session_state['opponent_roster'] is None or st.session_state['opponent_roster'].empty:
        st.warning("Lataa molemmat rosterit aloittaaksesi vertailun.")
    else:
        schedule_filtered = st.session_state['schedule'][
            (st.session_state['schedule']['Date'] >= pd.to_datetime(start_date)) &
            (st.session_state['schedule']['Date'] <= pd.to_datetime(end_date))
        ]
        
        if schedule_filtered.empty:
            st.warning("Ei pelejä valitulla aikavälillä. Valitse toinen aikaväli.")
        else:
            with st.spinner("Simuloidaan joukkueiden ottelua..."):
                winner, my_results, opponent_results = simulate_team_impact(
                    schedule_filtered,
                    st.session_state['roster'],
                    st.session_state['opponent_roster'],
                    pos_limits
                )
            
            my_total_games = my_results['total_games']
            my_fp = my_results['total_points']
            opponent_total_games = opponent_results['total_games']
            opponent_fp = opponent_results['total_points']

            st.subheader(f"Ennuste: {winner} voittaa!")

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
                st.error(f"Vastustajasi saa arviolta **{opponent_fp - my_fp:.2f}** enemmän fantasiapisteitä. Tämän perusteella vastustajalla on parempi mahdollisuus voittoon.")
            else:
                st.info("Ennakoiduissa fantasiapisteissä ei ole eroa.")


with tab3:
    st.header("📈 Joukkuevertailu pelipaikkoittain")
    if st.session_state['roster'].empty or st.session_state['opponent_roster'] is None or st.session_state['opponent_roster'].empty:
        st.warning("Lataa molemmat rosterit aloittaaksesi vertailun.")
    else:
        st.info("Tämä analyysi näyttää pelipaikoittaisten pelaajien kokonaispelimäärät joukkueissa.")
        
        schedule_filtered = st.session_state['schedule'][
            (st.session_state['schedule']['Date'] >= pd.to_datetime(start_date)) &
            (st.session_state['schedule']['Date'] <= pd.to_datetime(end_date))
        ]
        
        if schedule_filtered.empty:
            st.warning("Ei pelejä valitulla aikavälillä.")
        else:
            with st.spinner("Lasketaan joukkueiden aktiivisia pelejä..."):
                _, my_player_games, _, _ = optimize_roster_advanced(
                    schedule_filtered,
                    st.session_state['roster'],
                    pos_limits
                )
                _, opponent_player_games, _, _ = optimize_roster_advanced(
                    schedule_filtered,
                    st.session_state['opponent_roster'],
                    pos_limits
                )

            def get_position_games(player_games_dict, roster_df):
                pos_games = defaultdict(int)
                for player_name, games in player_games_dict.items():
                    positions_str = roster_df[roster_df['name'] == player_name]['positions'].iloc[0]
                    positions = [p.strip() for p in positions_str.replace(',', '/').split('/')]
                    if len(positions) == 1:
                        pos_games[positions[0]] += games
                    else:
                        for pos in positions:
                            pos_games[pos] += games
                return dict(pos_games)
            
            my_pos_games = get_position_games(my_player_games, st.session_state['roster'])
            opponent_pos_games = get_position_games(opponent_player_games, st.session_state['opponent_roster'])

            all_positions = sorted(list(set(my_pos_games.keys()) | set(opponent_pos_games.keys())))
            
            compare_data = {
                'Pelipaikka': all_positions,
                'Oma joukkue': [my_pos_games.get(pos, 0) for pos in all_positions],
                'Vastustaja': [opponent_pos_games.get(pos, 0) for pos in all_positions],
                'Ero': [my_pos_games.get(pos, 0) - opponent_pos_games.get(pos, 0) for pos in all_positions]
            }

            compare_df = pd.DataFrame(compare_data)
            
            st.dataframe(compare_df, use_container_width=True)
            
            st.subheader("Visuaalinen vertailu")
            
            if not compare_df.empty:
                chart_df = compare_df.set_index('Pelipaikka').T
                st.bar_chart(chart_df)
