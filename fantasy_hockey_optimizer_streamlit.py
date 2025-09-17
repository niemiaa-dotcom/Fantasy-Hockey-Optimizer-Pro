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
    page_title="Fantasy Hockey Optimizer Pro",
    page_icon="🏒",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Tiedostonimet
SCHEDULE_FILE = 'nhl_schedule_saved.csv'
ROSTER_FILE = 'my_roster_saved.csv'
OPPONENT_ROSTER_FILE = 'opponent_roster_saved.csv'
FREE_AGENTS_FILE = 'free_agents_saved.csv'

# Alusta session muuttujat
if 'schedule' not in st.session_state:
    st.session_state['schedule'] = pd.DataFrame()
if 'roster' not in st.session_state:
    st.session_state['roster'] = pd.DataFrame(columns=['name', 'team', 'positions', 'fantasy_points_avg'])
if 'opponent_roster' not in st.session_state:
    st.session_state['opponent_roster'] = pd.DataFrame(columns=['name', 'team', 'positions', 'fantasy_points_avg'])
if 'team_impact_results' not in st.session_state:
    st.session_state['team_impact_results'] = None
if 'free_agents' not in st.session_state:
    st.session_state['free_agents'] = pd.DataFrame()
if 'free_agent_results' not in st.session_state:
    st.session_state['free_agent_results'] = pd.DataFrame()

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
    st.session_state['team_impact_results'] = None
    st.sidebar.success("Välimuisti tyhjennetty!")
    st.rerun()

# Peliaikataulun lataus
schedule_file_exists = os.path.exists(SCHEDULE_FILE)
if schedule_file_exists:
    try:
        st.session_state['schedule'] = pd.read_csv(SCHEDULE_FILE)
        st.session_state['schedule']['Date'] = pd.to_datetime(st.session_state['schedule']['Date']).dt.date
    except Exception as e:
        st.sidebar.error(f"Virhe peliaikataulun lukemisessa: {str(e)}. Yritä ladata tiedosto uudelleen.")
        os.remove(SCHEDULE_FILE)
        st.session_state['schedule'] = pd.DataFrame()
        st.rerun()

if st.sidebar.button("Lataa uusi aikataulu", key="upload_schedule_button"):
    schedule_file_exists = False

if schedule_file_exists:
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
                schedule['Date'] = pd.to_datetime(schedule['Date']).dt.date
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

# Korjattu vastustajan rosterin latauslogiikka
st.sidebar.subheader("Lataa vastustajan rosteri (CSV)")
if st.sidebar.button("Nollaa vastustajan rosteri", key="reset_opponent_roster"):
    st.session_state['opponent_roster'] = pd.DataFrame(columns=['name', 'team', 'positions', 'fantasy_points_avg'])
    st.session_state['team_impact_results'] = None
    if os.path.exists(OPPONENT_ROSTER_FILE):
        os.remove(OPPONENT_ROSTER_FILE)
    st.sidebar.success("Vastustajan rosteri nollattu onnistuneesti!")
    
opponent_roster_file = st.sidebar.file_uploader(
    "Lataa vastustajan rosteri (CSV)",
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
            opponent_roster['fantasy_points_avg'] = pd.to_numeric(opponent_roster['fantasy_points_avg'], errors='coerce').fillna(0)
            st.session_state['opponent_roster'] = opponent_roster
            opponent_roster.to_csv(OPPONENT_ROSTER_FILE, index=False)
            st.sidebar.success("Vastustajan rosteri ladattu ja tallennettu!")
            st.rerun()
        else:
            st.sidebar.error("Vastustajan rosterin CSV-tiedoston tulee sisältää sarakkeet: name, team, positions, (fantasy_points_avg)")
    except Exception as e:
        st.sidebar.error(f"Virhe vastustajan rosterin lukemisessa: {str(e)}")

if 'opponent_roster' in st.session_state and not st.session_state['opponent_roster'].empty:
    st.sidebar.success("Vastustajan rosteri ladattu!")


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
            st.experimental_rerun()

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
                
                for pos in positions_list:
                    if pos in limits and pos != 'UTIL' and len(active[pos]) < limits[pos]:
                        active[pos].append(player_name)
                        placed = True
                        break
                
                if not placed and 'UTIL' in limits and len(active['UTIL']) < limits['UTIL']:
                    if any(pos in ['C', 'LW', 'RW', 'D'] for pos in positions_list):
                        active['UTIL'].append(player_name)
                        placed = True
                
                if not placed:
                    bench.append(player_name)
            
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
            'Date': date,
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
    if my_roster_df.empty or opponent_roster_df.empty:
        return "Täydennä molemmat rosterit ennen simulaatiota.", None, None

    my_daily_results, my_player_games, my_total_points, my_total_games = optimize_roster_advanced(
        schedule_df, my_roster_df, pos_limits
    )

    opponent_pos_limits = {
        'C': 3, 'LW': 3, 'RW': 3, 'D': 4, 'G': 2, 'UTIL': 1
    }
    opponent_daily_results, opponent_player_games, opponent_total_points, opponent_total_games = optimize_roster_advanced(
        schedule_df, opponent_roster_df, opponent_pos_limits
    )

    if my_total_points > opponent_total_points:
        winner = "Oma joukkue"
    elif opponent_total_points > my_total_points:
        winner = "Vastustaja"
    else:
        winner = "Tasapeli"
        
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
    
def analyze_free_agents(free_agents_df, my_roster_df, schedule_df, pos_limits):
    if free_agents_df.empty:
        st.warning("Vapaiden agenttien lista on tyhjä.")
        return pd.DataFrame()
    
    if my_roster_df.empty:
        st.warning("Oma rosteri on tyhjä. Lisää pelaajia ensin.")
        return pd.DataFrame()

    free_agents_df = free_agents_df[~free_agents_df['positions'].str.contains('G')].copy()
    if free_agents_df.empty:
        st.info("Vapaita agentteja ei löytynyt maalivahtien suodatuksen jälkeen.")
        return pd.DataFrame()

    results = []
    
    _, original_player_games, original_total_fp, _ = optimize_roster_advanced(schedule_df, my_roster_df, pos_limits)

    for index, fa_row in free_agents_df.iterrows():
        fa_name = fa_row['name']
        fa_team = fa_row['team']
        fa_positions = fa_row['positions']
        fa_fpa = fa_row['fantasy_points_avg']

        new_player_df = pd.DataFrame([{
            'name': fa_name,
            'team': fa_team,
            'positions': fa_positions,
            'fantasy_points_avg': fa_fpa
        }])
        sim_roster = pd.concat([my_roster_df, new_player_df], ignore_index=True)
        
        _, sim_player_games, sim_total_fp, _ = optimize_roster_advanced(schedule_df, sim_roster, pos_limits)
        
        added_games = sim_player_games.get(fa_name, 0)
        fp_change = sim_total_fp - original_total_fp

        results.append({
            'name': fa_name,
            'team': fa_team,
            'positions': fa_positions,
            'games_added': added_games,
            'fantasy_points_avg': fa_fpa,
            'total_impact': fp_change
        })
        
    results_df = pd.DataFrame(results)
    
    results_df = results_df.sort_values(by='total_impact', ascending=False)
    
    return results_df

# Uusi, refaktoroitu funktio joukkuevertailun näyttämiseen
def display_team_comparison_analysis(my_results, opponent_results):
    my_fp = my_results['total_points']
    opponent_fp = opponent_results['total_points']
    my_total_games = my_results['total_games']
    opponent_total_games = opponent_results['total_games']

    st.subheader("Yhteenveto")
    
    if my_fp > opponent_fp:
        winner_text = "Oma joukkue"
    elif opponent_fp > my_fp:
        winner_text = "Vastustaja"
    else:
        winner_text = "Tasapeli"

    st.markdown(f"**Tämän viikon voittaja on todennäköisesti:** **{winner_text}**")

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
    
    st.markdown("---")
    st.subheader("Yksityiskohtaiset tulokset")
    
    col_my, col_opponent = st.columns(2)
    
    with col_my:
        st.markdown("#### Oma joukkue")
        my_roster_df_display = st.session_state['roster'].copy()
        my_roster_df_display['Pelit'] = my_roster_df_display['name'].map(my_results['player_games']).fillna(0).astype(int)
        my_roster_df_display['Kokonais FP'] = my_roster_df_display['Pelit'] * my_roster_df_display['fantasy_points_avg']
        my_roster_df_display = my_roster_df_display[['name', 'team', 'positions', 'fantasy_points_avg', 'Pelit', 'Kokonais FP']]
        my_roster_df_display.rename(columns={'name': 'Pelaaja', 'team': 'Joukkue', 'positions': 'Pelipaikat', 'fantasy_points_avg': 'FP/GP'}, inplace=True)
        st.dataframe(my_roster_df_display, use_container_width=True, hide_index=True)
    
    with col_opponent:
        st.markdown("#### Vastustajan joukkue")
        opponent_roster_df_display = st.session_state['opponent_roster'].copy()
        opponent_roster_df_display['Pelit'] = opponent_roster_df_display['name'].map(opponent_results['player_games']).fillna(0).astype(int)
        opponent_roster_df_display['Kokonais FP'] = opponent_roster_df_display['Pelit'] * opponent_roster_df_display['fantasy_points_avg']
        opponent_roster_df_display = opponent_roster_df_display[['name', 'team', 'positions', 'fantasy_points_avg', 'Pelit', 'Kokonais FP']]
        opponent_roster_df_display.rename(columns={'name': 'Pelaaja', 'team': 'Joukkue', 'positions': 'Pelipaikat', 'fantasy_points_avg': 'FP/GP'}, inplace=True)
        st.dataframe(opponent_roster_df_display, use_container_width=True, hide_index=True)


# --- PÄÄSIVU: KÄYTTÖLIITTYMÄ ---
tab1, tab2, tab3 = st.tabs(["Rosterin optimointi", "Joukkueiden vertailu", "Vapaat agentit"])

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
            (st.session_state['schedule']['Date'] >= start_date) &
            (st.session_state['schedule']['Date'] <= end_date)
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
                    'Päivä': result['Date'],
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
                    winner, my_results, opponent_results = simulate_team_impact(
                        schedule_filtered, 
                        st.session_state['roster'], 
                        st.session_state['opponent_roster'], 
                        pos_limits
                    )

                    if my_results and opponent_results:
                        st.session_state['team_impact_results'] = {
                            'my_results': my_results,
                            'opponent_results': opponent_results
                        }
                    else:
                        st.session_state['team_impact_results'] = None
                        st.error("Simulaatio epäonnistui. Tarkista, että rosterit ovat oikein.")
            
            if st.session_state['team_impact_results'] is not None:
                display_team_comparison_analysis(
                    st.session_state['team_impact_results']['my_results'],
                    st.session_state['team_impact_results']['opponent_results']
                )

with tab3:
    st.header("🔍 Vapaat agentit")

    if st.session_state['roster'].empty or st.session_state['schedule'].empty or st.session_state['free_agents'].empty:
        st.warning("Lataa ensin oma rosteri, peliaikataulu ja vapaat agentit sivupalkista.")
    else:
        schedule_filtered = st.session_state['schedule'][
            (st.session_state['schedule']['Date'] >= start_date) &
            (st.session_state['schedule']['Date'] <= end_date)
        ]
        
        if st.button("Analysoi vapaat agentit"):
            with st.spinner("Analysoidaan vapaiden agenttien vaikutusta..."):
                free_agent_analysis_df = analyze_free_agents(
                    st.session_state['free_agents'], 
                    st.session_state['roster'], 
                    schedule_filtered, 
                    pos_limits
                )
            st.session_state['free_agent_results'] = free_agent_analysis_df
            st.success("Vapaat agentit analysoitu onnistuneesti!")
            st.rerun()

        if 'free_agent_results' in st.session_state and not st.session_state['free_agent_results'].empty:
            st.subheader("Optimaalisimmat vapaat agentit")
            st.dataframe(st.session_state['free_agent_results'], use_container_width=True)
