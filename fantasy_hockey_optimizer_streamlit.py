import streamlit as st
import datetime
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from collections import defaultdict
import itertools
import os
import time # UUSI: Tokenin vanhenemiseen
import requests # UUSI: Yahoo API -kutsuille
import gspread
from google.oauth2.service_account import Credentials

# Huom: xmltodict on usein tarpeen Yahoo API:n XML-vastausten käsittelyyn.
# Jos et halua käsitellä XML:ää suoraan, sinun on ehkä asennettava:
# import xmltodict

# --- KONFIGURAATIO JA TIEDOSTOT ---
SCHEDULE_FILE = 'nhl_schedule_saved.csv'
ROSTER_FILE = 'my_roster_saved.csv'
OPPONENT_ROSTER_FILE = 'opponent_roster_saved.csv'
FREE_AGENTS_FILE = 'free_agents_saved.csv'

# Aseta sivun konfiguraatio
st.set_page_config(
    page_title="Fantasy Hockey Optimizer Pro",
    page_icon="🏒",
    layout="wide",
    initial_sidebar_state="expanded"
)

# --- SESSION MUUTTUJIEN ALUSTUS ---
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
if 'optimization_results' not in st.session_state:
    st.session_state['optimization_results'] = None

# --- GOOGLE SHEETS LATAUSFUNKTIOT (Kuten aiemmin) ---

@st.cache_resource
def get_gspread_client():
    """Alustaa gspread-asiakasohjelman palvelutilin tunnistetiedoilla."""
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
    """Lataa oman rosterin Google Sheetsistä."""
    # ... (Sama koodi kuin aiemmin)
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
        st.error(f"Virhe Google Sheets -rosterin lukemisessa: {e}")
        return pd.DataFrame()

def load_free_agents_from_gsheets():
    """Lataa vapaat agentit Google Sheetsistä."""
    # ... (Sama koodi kuin aiemmin)
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
       
        df['fantasy_points_avg'] = pd.to_numeric(df['fantasy_points_avg'], errors='coerce').fillna(0)
        df = df[required_columns]
        return df
    except Exception as e:
        st.error(f"Virhe vapaiden agenttien Google Sheets -tiedoston lukemisessa: {e}")
        return pd.DataFrame()


# --- YAHOO OAUTH2 FUNKTIOT (UUDET) ---

# TÄRKEÄÄ: MÄÄRITÄ NÄMÄ ARVOT secrets.toml-tiedostoon Streamlit Cloudissa
# [yahoo]
# client_id = "YOUR_CLIENT_ID"
# client_secret = "YOUR_CLIENT_SECRET"
# redirect_uri = "https://<your-streamlit-app-url>.streamlit.app" # Tämän täytyy olla tarkka

YAHOO_OAUTH_URL = "https://api.login.yahoo.com/oauth2/request_auth"
YAHOO_TOKEN_URL = "https://api.login.yahoo.com/oauth2/get_token"
YAHOO_API_BASE = "https://fantasysports.yahooapis.com/fantasy/v2"

def get_yahoo_oauth2_url():
    """Luo Yahoo Oauth 2.0 -kirjautumislinkin."""
    try:
        client_id = st.secrets["yahoo"]["client_id"]
        redirect_uri = st.secrets["yahoo"]["redirect_uri"]
        
        params = {
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "language": "fi-FI"
        }
        # Huomaa: Yahoo käyttää oletusarvoisesti fantasy-rajoitusta
        
        from urllib.parse import urlencode
        return f"{YAHOO_OAUTH_URL}?{urlencode(params)}"
        
    except KeyError as e:
        st.error(f"Yahoo-salaisuudet puuttuvat secrets.toml-tiedostosta: {e}")
        return None

def exchange_code_for_token(auth_code):
    """Vaihtaa authorization coden access tokeniin."""
    try:
        client_id = st.secrets["yahoo"]["client_id"]
        client_secret = st.secrets["yahoo"]["client_secret"]
        redirect_uri = st.secrets["yahoo"]["redirect_uri"]

        headers = {
            "Content-Type": "application/x-www-form-urlencoded"
        }
        
        data = {
            "client_id": client_id,
            "client_secret": client_secret,
            "redirect_uri": redirect_uri,
            "code": auth_code,
            "grant_type": "authorization_code"
        }
        
        response = requests.post(YAHOO_TOKEN_URL, headers=headers, data=data)
        response.raise_for_status() # Nosta virhe, jos vastaus on huono (4xx tai 5xx)
        
        token_info = response.json()
        
        # Tallenna token tiedot
        st.session_state['yahoo_access_token'] = token_info.get("access_token")
        st.session_state['yahoo_refresh_token'] = token_info.get("refresh_token")
        
        # Laske vanhenemisaika
        expires_in = token_info.get("expires_in", 3600)
        st.session_state['yahoo_token_expires_at'] = time.time() + int(expires_in)
        
        return token_info
        
    except Exception as e:
        st.error(f"Virhe tokenin vaihtamisessa: {e}")
        return None

def refresh_yahoo_token():
    """Päivittää access tokenin refresh tokenilla."""
    # TÄTÄ FUNKTIOTA TARVITAAN, MUTTA SITÄ EI OLE TEHTY TÄYDELLISESTI TÄSSÄ ESIMERKISSÄ
    # Koska access token vanhenee nopeasti (yleensä 1 tunti), tämä on kriittinen
    pass # Toteutus jätetty pois koodin lyhyyden takia

def get_yahoo_user_games():
    """Hakee käyttäjän fantasiapelit Yahoo API:n avulla."""
    if 'yahoo_access_token' not in st.session_state:
        return None
    
    # Huomaa: Tämä on vain testikutsu. Fantasypelaajien haku on monimutkaisempaa.
    url = f"{YAHOO_API_BASE}/users;use_login=1/games" 
    
    try:
        headers = {
            "Authorization": f"Bearer {st.session_state['yahoo_access_token']}",
            "Accept": "application/json" # TAI 'application/xml'
        }
        response = requests.get(url, headers=headers)
        response.raise_for_status()
        
        # Yahoo palauttaa oletuksena XML:ää, vaikka Accept: application/json olisi lähetetty.
        # Jos haluat käsitellä JSON-vastausta, sinun on käytettävä oikeaa muotoa
        # Tässä esimerkissä vain palautetaan vastausteksti
        return response.text
        
    except requests.exceptions.RequestException as e:
        st.error(f"API-kutsu epäonnistui: {e}")
        return None
        
        
# --- OPTIMOINTI JA SIMULOINTILOGIIKKA (Kuten aiemmin) ---

# optimize_roster_advanced
def optimize_roster_advanced(schedule_df, roster_df, limits, num_attempts=100):
    # ... (Kaikki optimize_roster_advanced-funktio tähän)
    if roster_df.empty:
        return [], {}, 0.0, 0
        
    players_info = {}
    for _, player in roster_df.iterrows():
        positions_str = player.get('positions')
        if pd.isna(positions_str):
            positions_list = []
        elif isinstance(positions_str, str):
            positions_list = [p.strip() for p in positions_str.replace(',', '/').split('/')]
        else:
            positions_list = []
        
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
        
        available_players_teams = {game['Visitor'] for _, game in day_games.iterrows()} | \
                                  {game['Home'] for _, game in day_games.iterrows()}
        available_players_set = {
            player_name for player_name, info in players_info.items() if info['team'] in available_players_teams
        }
        
        available_players = [
            {'name': name, 'team': players_info[name]['team'], 'positions': players_info[name]['positions'], 'fpa': players_info[name]['fpa']}
            for name in available_players_set
        ]
        
        if not available_players:
            daily_results.append({'Date': date, 'Active': {pos: [] for pos in limits.keys()}, 'Bench': []})
            continue

        best_assignment = None
        best_assignment_fp = -1.0
        
        for attempt in range(num_attempts):
            shuffled_players = available_players.copy()
            np.random.shuffle(shuffled_players)
            
            active = {pos: [] for pos in limits.keys()}
            bench = []
            
            # 1. Alustava sijoittelu
            for player_info in shuffled_players:
                placed = False
                player_name = player_info['name']
                positions_list = player_info['positions']
                
                for pos in [p for p in positions_list if p in limits and p != 'UTIL']:
                    if len(active[pos]) < limits[pos]:
                        active[pos].append(player_name)
                        placed = True
                        break
                
                if not placed and 'UTIL' in limits and len(active['UTIL']) < limits['UTIL']:
                    if any(pos in ['C', 'LW', 'RW', 'D'] for pos in positions_list):
                        active['UTIL'].append(player_name)
                        placed = True
                
                if not placed:
                    bench.append(player_name)
            
            # 2. Parantelu (Swap-optimointi)
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
                            
                            is_eligible = False
                            if active_pos == 'UTIL':
                                if any(pos in ['C', 'LW', 'RW', 'D'] for pos in bench_player_positions):
                                    is_eligible = True
                            elif active_pos in bench_player_positions:
                                is_eligible = True

                            if bench_player_fpa > active_player_fpa and is_eligible:
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
                    best_assignment_fp = current_fp
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
        
        for players in best_assignment['active'].values():
            for player_name in players:
                player_games[player_name] += 1
    
    total_fantasy_points = sum(
        player_games[name] * players_info[name]['fpa'] for name in players_info
    )
    total_active_games = sum(player_games.values())

    return daily_results, player_games, total_fantasy_points, total_active_games

# simulate_team_impact
def simulate_team_impact(schedule_df, my_roster_df, opponent_roster_df, pos_limits):
    # ... (Sama koodi kuin aiemmin)
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
        
    return "OK", {
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
    
# analyze_free_agents
def analyze_free_agents(free_agents_df, my_roster_df, schedule_df, pos_limits):
    # ... (Sama koodi kuin aiemmin)
    if free_agents_df.empty:
        st.warning("Vapaiden agenttien lista on tyhjä.")
        return pd.DataFrame()
    
    if my_roster_df.empty:
        st.warning("Oma rosteri on tyhjä. Lisää pelaajia ensin.")
        return pd.DataFrame()

    free_agents_df = free_agents_df.copy()
    free_agents_df = free_agents_df[~free_agents_df['positions'].str.contains('G', na=False)].copy()
    if free_agents_df.empty:
        st.info("Vapaita agentteja ei löytynyt maalivahtien suodatuksen jälkeen.")
        return pd.DataFrame()

    results = []
    
    _, _, original_total_fp, _ = optimize_roster_advanced(schedule_df, my_roster_df, pos_limits)

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

# display_team_comparison_analysis
def display_team_comparison_analysis(my_results, opponent_results):
    # ... (Kaikki display_team_comparison_analysis-funktio tähän)
    if not my_results or not opponent_results:
        st.error("Tuloksia ei ole saatavilla vertailua varten.")
        return
        
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
        my_roster_df_display['Kokonais FP'] =
