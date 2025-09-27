import streamlit as st
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from collections import defaultdict
import itertools
import os
import gspread
from google.oauth2.service_account import Credentials
import requests
import json
import time
from urllib.parse import urlencode


# Yahoo Fantasy API -asetukset
YAHOO_OAUTH_REQUEST_TOKEN_URL = 'https://api.login.yahoo.com/oauth/v2/get_request_token'
YAHOO_OAUTH_ACCESS_TOKEN_URL = 'https://api.login.yahoo.com/oauth/v2/get_token'
YAHOO_OAUTH_AUTHORIZE_URL = 'https://api.login.yahoo.com/oauth/v2/request_auth'
YAHOO_FANTASY_API_BASE_URL = 'https://fantasysports.yahooapis.com/fantasy/v2'

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

# Alusta session muuttujat
if 'schedule' not in st.session_state:
    st.session_state['schedule'] = pd.DataFrame()
if 'roster' not in st.session_state:
    st.session_state['roster'] = pd.DataFrame(columns=['name', 'team', 'positions', 'fantasy_points_avg'])
if 'opponent_roster' not in st.session_state:
    st.session_state['opponent_roster'] = pd.DataFrame(columns=['name', 'team', 'positions', 'fantasy_points_avg'])
if 'team_impact_results' not in st.session_state:
    st.session_state['team_impact_results'] = None
if 'yahoo_oauth_token' not in st.session_state:
    st.session_state['yahoo_oauth_token'] = None
if 'yahoo_oauth_token_secret' not in st.session_state:
    st.session_state['yahoo_oauth_token_secret'] = None
if 'yahoo_oauth_verifier' not in st.session_state:
    st.session_state['yahoo_oauth_verifier'] = None
if 'yahoo_access_token' not in st.session_state:
    st.session_state['yahoo_access_token'] = None
if 'yahoo_access_token_secret' not in st.session_state:
    st.session_state['yahoo_access_token_secret'] = None
if 'yahoo_league_id' not in st.session_state:
    st.session_state['yahoo_league_id'] = None
if 'yahoo_team_id' not in st.session_state:
    st.session_state['yahoo_team_id'] = None
if 'free_agents' not in st.session_state:
    st.session_state['free_agents'] = pd.DataFrame()

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

        # Muunna 'fantasy_points_avg' numeeriseksi ja täytä puuttuvat arvot nollalla
        df['fantasy_points_avg'] = pd.to_numeric(df['fantasy_points_avg'], errors='coerce')
        
        # Järjestä sarakkeet oikein ennen palautusta
        df = df[required_columns]

        return df
    except Exception as e:
        st.error(f"Virhe vapaiden agenttien Google Sheets -tiedoston lukemisessa: {e}")
        return pd.DataFrame()

# --- YAHOO FANTASY API FUNKTIOT ---
def get_yahoo_oauth():
    """Hanki OAuth-tunnisteet Yahoo Fantasy API:lle"""
    try:
        consumer_key = st.secrets["yahoo"]["consumer_key"]
        consumer_secret = st.secrets["yahoo"]["consumer_secret"]
        callback_url = st.secrets["yahoo"]["callback_url"]
        
        # Luo OAuth1-asiakas
        oauth = OAuth1(
            consumer_key,
            consumer_secret,
            callback_uri=callback_url
        )
        
        # Pyydä request token
        response = requests.post(
            YAHOO_OAUTH_REQUEST_TOKEN_URL,
            auth=oauth,
            params={"oauth_callback": callback_url}
        )
        
        if response.status_code != 200:
            st.error(f"Virhe request tokenin haussa: {response.status_code} - {response.text}")
            return None, None, None
        
        # Jäsennä vastaus
        token_data = parse_qs(response.text)
        oauth_token = token_data['oauth_token'][0]
        oauth_token_secret = token_data['oauth_token_secret'][0]
        
        # Tallenna tokenit session tilaan
        st.session_state['yahoo_oauth_token'] = oauth_token
        st.session_state['yahoo_oauth_token_secret'] = oauth_token_secret
        
        # Luo valtuutusosoite
        auth_url = f"{YAHOO_OAUTH_AUTHORIZE_URL}?oauth_token={oauth_token}"
        
        return auth_url, oauth_token, oauth_token_secret
    except Exception as e:
        st.error(f"Virhe OAuth-tunnisteiden haussa: {str(e)}")
        return None, None, None

def make_yahoo_api_request(url, params=None):
    """Tee API-pyyntö Yahoo Fantasylle"""
    try:
        consumer_key = st.secrets["yahoo"]["consumer_key"]
        consumer_secret = st.secrets["yahoo"]["consumer_secret"]
        
        # Tarkista, onko meillä access token
        if not st.session_state['yahoo_access_token'] or not st.session_state['yahoo_access_token_secret']:
            st.error("Sinun täytyy ensin kirjautua Yahoo Fantasyyn")
            return None
        
        # Luo OAuth1-asiakas
        oauth = OAuth1(
            consumer_key,
            consumer_secret,
            resource_owner_key=st.session_state['yahoo_access_token'],
            resource_owner_secret=st.session_state['yahoo_access_token_secret']
        )
        
        # Tee API-pyyntö
        response = requests.get(url, auth=oauth, params=params)
        if response.status_code != 200:
            st.error(f"Virhe API-pyynnössä: {response.text}")
            return None
        
        return response.json()
    except Exception as e:
        st.error(f"Virhe API-pyynnössä: {str(e)}")
        return None

def get_yahoo_user_games():
    """Hae käyttäjän pelit"""
    url = f"{YAHOO_FANTASY_API_BASE_URL}/users;use_login=1/games"
    response = make_yahoo_api_request(url)
    return response

def get_yahoo_leagues(game_key):
    """Hae käyttäjän liigat pelin perusteella"""
    url = f"{YAHOO_FANTASY_API_BASE_URL}/users;use_login=1/games;game_keys={game_key}/leagues"
    response = make_yahoo_api_request(url)
    return response

def get_yahoo_teams(league_key):
    """Hae joukkueet liigasta"""
    url = f"{YAHOO_FANTASY_API_BASE_URL}/league/{league_key}/teams"
    response = make_yahoo_api_request(url)
    return response

def get_yahoo_roster(team_key):
    """Hae joukkueen rosteri"""
    url = f"{YAHOO_FANTASY_API_BASE_URL}/team/{team_key}/roster"
    response = make_yahoo_api_request(url)
    return response

def get_yahoo_players(league_key, position=None, status=None):
    """Hae pelaajia liigasta"""
    params = {}
    if position:
        params['position'] = position
    if status:
        params['status'] = status
    
    url = f"{YAHOO_FANTASY_API_BASE_URL}/league/{league_key}/players"
    response = make_yahoo_api_request(url, params=params)
    return response

def parse_yahoo_roster(roster_data):
    """Jäsennä Yahoo-rosteri sovelluksen muotoon"""
    if not roster_data or 'fantasy_content' not in roster_data:
        return pd.DataFrame()
    
    try:
        players = []
        roster = roster_data['fantasy_content']['team'][1]['roster']['0']['players']
        
        for player_key in roster:
            player_data = roster[player_key]['player'][0]
            
            name = player_data[2]['name']['full']
            team = player_data[3]['editorial_team_abbr']
            positions = '/'.join(player_data[4]['position_type'])
            
            # Hae fantasiapisteet
            fantasy_points = 0.0
            if 'player_stats' in player_data[1]:
                stats = player_data[1]['player_stats']['stats']
                for stat in stats:
                    if stat['stat']['stat_id'] == '60':  # Fantasiapisteet
                        fantasy_points = float(stat['stat']['value'])
                        break
            
            players.append({
                'name': name,
                'team': team,
                'positions': positions,
                'fantasy_points_avg': fantasy_points
            })
        
        return pd.DataFrame(players)
    except Exception as e:
        st.error(f"Virhe rosterin jäsentämisessä: {str(e)}")
        return pd.DataFrame()

def parse_yahoo_players(players_data):
    """Jäsennä Yahoo-pelaajat sovelluksen muotoon"""
    if not players_data or 'fantasy_content' not in players_data:
        return pd.DataFrame()
    
    try:
        players = []
        players_list = players_data['fantasy_content']['league'][1]['players']
        
        for player_key in players_list:
            player_data = players_list[player_key]['player'][0]
            
            name = player_data[2]['name']['full']
            team = player_data[3]['editorial_team_abbr']
            positions = '/'.join(player_data[4]['position_type'])
            
            # Hae fantasiapisteet
            fantasy_points = 0.0
            if 'player_stats' in player_data[1]:
                stats = player_data[1]['player_stats']['stats']
                for stat in stats:
                    if stat['stat']['stat_id'] == '60':  # Fantasiapisteet
                        fantasy_points = float(stat['stat']['value'])
                        break
            
            players.append({
                'name': name,
                'team': team,
                'positions': positions,
                'fantasy_points_avg': fantasy_points
            })
        
        return pd.DataFrame(players)
    except Exception as e:
        st.error(f"Virhe pelaajien jäsentämisessä: {str(e)}")
        return pd.DataFrame()

# --- SIVUPALKKI: TIEDOSTOJEN LATAUS ---
st.sidebar.header("📁 Tiedostojen lataus")

if st.sidebar.button("Tyhjennä kaikki välimuisti"):
    st.cache_data.clear()
    st.session_state['schedule'] = pd.DataFrame()
    st.session_state['roster'] = pd.DataFrame(columns=['name', 'team', 'positions', 'fantasy_points_avg'])
    st.session_state['opponent_roster'] = pd.DataFrame(columns=['name', 'team', 'positions', 'fantasy_points_avg'])
    st.session_state['free_agents'] = pd.DataFrame()
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

# --- SIVUPALKKI: YAHOO FANTASY INTEGRAATIO ---
st.sidebar.header("🏒 Yahoo Fantasy")

# Tarkista, onko käyttäjä jo kirjautunut
if st.session_state['yahoo_access_token'] and st.session_state['yahoo_access_token_secret']:
    st.sidebar.success("Olet kirjautunut Yahoo Fantasyyn!")
    
    # Näytä kirjautumisen ulos -painike
    if st.sidebar.button("Kirjaudu ulos Yahoo Fantasysta"):
        st.session_state['yahoo_access_token'] = None
        st.session_state['yahoo_access_token_secret'] = None
        st.session_state['yahoo_league_id'] = None
        st.session_state['yahoo_team_id'] = None
        st.sidebar.success("Kirjauduttu ulos!")
        st.rerun()
    
    # Hae käyttäjän pelit
    if st.sidebar.button("Hae Yahoo Fantasy -tiedot"):
        with st.spinner("Haetaan Yahoo Fantasy -tietoja..."):
            # Hae käyttäjän pelit
            games_data = get_yahoo_user_games()
            
            if games_data and 'fantasy_content' in games_data:
                games = games_data['fantasy_content']['users']['0']['user'][1]['games']
                
                # Oletetaan, että käytössä on jääkiekko (game_key '331')
                hockey_game = None
                for game_key in games:
                    if games[game_key]['game'][0]['code'] == 'nhl':
                        hockey_game = games[game_key]['game']
                        break
                
                if hockey_game:
                    game_key = hockey_game[0]['game_key']
                    game_season = hockey_game[0]['season']
                    
                    # Hae liigat
                    leagues_data = get_yahoo_leagues(game_key)
                    
                    if leagues_data and 'fantasy_content' in leagues_data:
                        leagues = leagues_data['fantasy_content']['users']['0']['user'][1]['games']['0']['game'][1]['leagues']
                        
                        if leagues:
                            # Oletetaan, että käyttäjällä on vain yksi liiga
                            league_key = list(leagues.values())[0][0]['league_key']
                            league_name = list(leagues.values())[0][0]['name']
                            
                            st.session_state['yahoo_league_id'] = league_key
                            
                            # Hae joukkueet
                            teams_data = get_yahoo_teams(league_key)
                            
                            if teams_data and 'fantasy_content' in teams_data:
                                teams = teams_data['fantasy_content']['league'][1]['teams']
                                
                                # Hae käyttäjän joukkue
                                user_team = None
                                for team_key in teams:
                                    team = teams[team_key]['team']
                                    if team[0]['is_owned_by_current_login'] == 1:
                                        user_team = team
                                        break
                                
                                if user_team:
                                    team_key = user_team[0]['team_key']
                                    team_name = user_team[2]['name']
                                    
                                    st.session_state['yahoo_team_id'] = team_key
                                    
                                    st.sidebar.success(f"Löytyi liiga: {league_name} ja joukkue: {team_name}")
                                    
                                    # Hae rosteri
                                    roster_data = get_yahoo_roster(team_key)
                                    
                                    if roster_data:
                                        roster_df = parse_yahoo_roster(roster_data)
                                        
                                        if not roster_df.empty:
                                            st.session_state['roster'] = roster_df
                                            roster_df.to_csv(ROSTER_FILE, index=False)
                                            st.sidebar.success("Rosteri ladattu Yahoo Fantasysta!")
                                            
                                            # Hae vapaat agentit
                                            free_agents_data = get_yahoo_players(league_key, status='A')
                                            
                                            if free_agents_data:
                                                free_agents_df = parse_yahoo_players(free_agents_data)
                                                
                                                if not free_agents_df.empty:
                                                    st.session_state['free_agents'] = free_agents_df
                                                    st.sidebar.success("Vapaat agentit ladattu Yahoo Fantasysta!")
                                                else:
                                                    st.sidebar.warning("Vapaita agentteja ei löytynyt")
                                            else:
                                                st.sidebar.warning("Vapaiden agenttien haku epäonnistui")
                                        else:
                                            st.sidebar.warning("Rosteria ei löytynyt")
                                    else:
                                        st.sidebar.warning("Rosterin haku epäonnistui")
                                else:
                                    st.sidebar.warning("Joukkuettasi ei löytynyt")
                            else:
                                st.sidebar.warning("Joukkueiden haku epäonnistui")
                        else:
                            st.sidebar.warning("Liigoja ei löytynyt")
                    else:
                        st.sidebar.warning("Liigojen haku epäonnistui")
                else:
                    st.sidebar.warning("Jääkiekkopeliä ei löytynyt")
            else:
                st.sidebar.warning("Tietojen haku epäonnistui")
        
        st.rerun()
else:
    # Näytä kirjautumispainike
    if st.sidebar.button("Kirjaudu Yahoo Fantasyyn"):
        auth_url, oauth_token, oauth_token_secret = get_yahoo_oauth()
        
        if auth_url:
            st.sidebar.markdown(f"""
            ### Kirjaudu Yahoo Fantasyyn
            
            1. Klikkaa [tästä]({auth_url}) avataksesi Yahoo-sivun
            2. Anna lupa sovellukselle
            3. Kopioi palautusosoitteesta (callback URL) `oauth_verifier`-arvo
            4. Liitä se alla olevaan kenttään
            """)
            
            oauth_verifier = st.sidebar.text_input("Liitä oauth_verifier tähän")
            
            if st.sidebar.button("Vahvista kirjautuminen"):
                if oauth_verifier:
                    access_token, access_token_secret = get_yahoo_access_token(
                        oauth_token, oauth_token_secret, oauth_verifier
                    )
                    
                    if access_token and access_token_secret:
                        st.sidebar.success("Kirjautuminen onnistui!")
                        st.rerun()
                    else:
                        st.sidebar.error("Kirjautuminen epäonnistui")
                else:
                    st.sidebar.error("Syötä oauth_verifier")

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

if 'opponent_roster' in st.session_state and st.session_state['opponent_roster'] is not None and not st.session_state['opponent_roster'].empty:
    st.sidebar.success("Vastustajan rosteri ladattu!")
    
    # Näytä latauspainike vain jos rosteri on jo ladattu
    if st.sidebar.button("Lataa uusi vastustajan rosteri"):
        st.session_state['opponent_roster'] = None
        st.rerun()
else:
    # Näytä tiedostolataaja
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
            # Korjattu rivi, joka käsittelee sekä '/' että ',' erottimia
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
tab1, tab2, tab3, tab4 = st.tabs([
    "Rosterin optimointi",
    "Joukkueiden vertailu",
    "Matchup",
    "Yahoo Fantasy API"
])

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
            ["Vertaa kahta uutta pelaajaa", "Vertaa uutta pelaajaa vs. rosterissa olevan pudottamista"],
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

        else:  # Vertaa uutta pelaajaa vs. rosterissa olevan pudottamista
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
            
            else:  # Vertaa uutta pelaajaa vs. rosterissa olevan pudottamista
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
                        st.metric("Menetetyt pelit", original_total_games_dict.get(drop_player_name, 0))
                        st.metric("Menetetyt FP/GP", f"{drop_player_fpa:.2f}")
                        st.metric("Menetetyt pisteet", f"{original_total_games_dict.get(drop_player_name, 0) * drop_player_fpa:.2f}")
                        
                    st.markdown("---")
                    
                    st.subheader("Yhteenveto")
                    fp_difference = modified_fp - original_fp

                    if fp_difference > 0:
                        st.success(f"Muutos on kannattava! Rosterisi kokonais-FP olisi arviolta **{fp_difference:.2f}** pistettä suurempi.")
                    elif fp_difference < 0:
                        st.error(f"Muutos ei ole kannattava. Rosterisi kokonais-FP olisi arviolta **{abs(fp_difference):.2f}** pistettä pienempi.")
                    else:
                        st.info("Fantasiapisteissä ei ole muutosta.")

                else:
                    st.warning("Syötä uuden pelaajan ja valitse pudotettava pelaaja suorittaaksesi vertailun.")

with tab2:
    st.header("🏆 Joukkueiden vertailu")
    
    if st.session_state['schedule'].empty or st.session_state['roster'].empty or st.session_state['opponent_roster'].empty:
        st.warning("Lataa peliaikataulu, oma rosteri ja vastustajan rosteri aloittaaksesi vertailun")
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
            with st.spinner("Simuloidaan joukkueiden suorituskykyä..."):
                winner, my_results, opponent_results = simulate_team_impact(
                    schedule_filtered,
                    st.session_state['roster'],
                    st.session_state['opponent_roster'],
                    pos_limits
                )
            
            st.subheader("Tulokset")
            col1, col2, col3 = st.columns(3)
            
            with col1:
                st.metric("Voittaja", winner)
            
            with col2:
                st.metric("Oma joukkue FP", f"{my_results['total_points']:.2f}")
            
            with col3:
                st.metric("Vastustaja FP", f"{opponent_results['total_points']:.2f}")
            
            st.markdown("---")
            
            st.subheader("Pelaajien pelimäärät")
            col1, col2 = st.columns(2)
            
            with col1:
                st.write("Oma joukkue")
                my_games_df = pd.DataFrame({
                    'Pelaaja': list(my_results['player_games'].keys()),
                    'Pelit': list(my_results['player_games'].values())
                }).sort_values('Pelit', ascending=False)
                st.dataframe(my_games_df, use_container_width=True)
            
            with col2:
                st.write("Vastustaja")
                opponent_games_df = pd.DataFrame({
                    'Pelaaja': list(opponent_results['player_games'].keys()),
                    'Pelit': list(opponent_results['player_games'].values())
                }).sort_values('Pelit', ascending=False)
                st.dataframe(opponent_games_df, use_container_width=True)

with tab3:
    st.header("📊 Matchup")
    
    if st.session_state['schedule'].empty or st.session_state['roster'].empty:
        st.warning("Lataa peliaikataulu ja oma rosteri aloittaaksesi analyysin")
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
            st.subheader("Joukkueiden vaikutukset pelipaikoittain")
            
            with st.spinner("Lasketaan joukkueiden vaikutuksia..."):
                team_impact_results = calculate_team_impact_by_position(
                    schedule_filtered,
                    st.session_state['roster'],
                    pos_limits
                )
            
            st.session_state['team_impact_results'] = team_impact_results
            
            # Näytä tulokset pelipaikoittain
            for pos, df in team_impact_results.items():
                st.write(f"**{pos}**")
                st.dataframe(df, use_container_width=True)
            
            st.subheader("Vapaiden agenttien analyysi")
            
            # Tarkista, onko vapaita agentteja ladattu
            if 'free_agents' in st.session_state and not st.session_state['free_agents'].empty:
                free_agents_df = st.session_state['free_agents']
                
                with st.spinner("Analysoidaan vapaita agentteja..."):
                    analysis_results = analyze_free_agents(
                        team_impact_results,
                        free_agents_df
                    )
                
                if not analysis_results.empty:
                    st.dataframe(analysis_results, use_container_width=True)
                    
                    csv = analysis_results.to_csv(index=False).encode('utf-8')
                    st.download_button(
                        "Lataa analyysi CSV-muodossa",
                        data=csv,
                        file_name='vapaiden_agenttien_analyysi.csv',
                        mime='text/csv'
                    )
                else:
                    st.warning("Vapaiden agenttien analyysi epäonnistui")
            else:
                st.warning("Lataa vapaat agentit aloittaaksesi analyysin")


with tab4:
    st.header("📡 Yahoo Fantasy Sports -kirjautuminen")

    import requests
    from urllib.parse import urlencode

    AUTH_URL = "https://api.login.yahoo.com/oauth2/request_auth"
    TOKEN_URL = "https://api.login.yahoo.com/oauth2/get_token"
    API_BASE = "https://fantasysports.yahooapis.com/fantasy/v2"

    def get_login_link():
        params = {
            "client_id": st.secrets["yahoo_oauth2"]["client_id"],
            "redirect_uri": st.secrets["yahoo_oauth2"]["redirect_uri"],
            "response_type": "code",
            "language": "en-us",
            "scope": "fspt-r"  # tai fspt-w jos tarvitset kirjoitusoikeuksia
        }
        return f"{AUTH_URL}?{urlencode(params)}"

    def exchange_code_for_token(auth_code: str):
        data = {
            "grant_type": "authorization_code",
            "redirect_uri": st.secrets["yahoo_oauth2"]["redirect_uri"],
            "code": auth_code
        }
        auth = (
            st.secrets["yahoo_oauth2"]["client_id"],
            st.secrets["yahoo_oauth2"]["client_secret"]
        )
        resp = requests.post(TOKEN_URL, data=data, auth=auth)
        if resp.status_code == 200:
            token_info = resp.json()
            st.session_state["yahoo_access_token"] = token_info["access_token"]
            st.session_state["yahoo_refresh_token"] = token_info.get("refresh_token")
            st.success("✅ Yahoo Fantasy -kirjautuminen onnistui!")
        else:
            st.error(f"Virhe tokenin haussa: {resp.status_code} - {resp.text}")

    def refresh_token():
        if "yahoo_refresh_token" not in st.session_state:
            st.error("Ei refresh tokenia.")
            return
        data = {
            "grant_type": "refresh_token",
            "redirect_uri": st.secrets["yahoo_oauth2"]["redirect_uri"],
            "refresh_token": st.session_state["yahoo_refresh_token"]
        }
        auth = (
            st.secrets["yahoo_oauth2"]["client_id"],
            st.secrets["yahoo_oauth2"]["client_secret"]
        )
        resp = requests.post(TOKEN_URL, data=data, auth=auth)
        if resp.status_code == 200:
            token_info = resp.json()
            st.session_state["yahoo_access_token"] = token_info["access_token"]
            st.success("🔄 Access token uusittu.")
        else:
            st.error(f"Virhe tokenin uusinnassa: {resp.status_code} - {resp.text}")

    def yahoo_api_get(endpoint):
        if "yahoo_access_token" not in st.session_state:
            st.error("Kirjaudu ensin sisään.")
            return None
        headers = {"Authorization": f"Bearer {st.session_state['yahoo_access_token']}"}
        resp = requests.get(f"{API_BASE}/{endpoint}", headers=headers)
        if resp.status_code != 200:
            st.error(f"Virhe API-pyynnössä: {resp.status_code} - {resp.text}")
            return None
        return resp.text

    # --- UI ---
    query_params = st.query_params
    if "code" in query_params and "yahoo_access_token" not in st.session_state:
        code = query_params["code"][0]
        exchange_code_for_token(code)

    if "yahoo_access_token" not in st.session_state:
        st.markdown(f"[Kirjaudu Yahoo Fantasyyn]({get_login_link()})")
    else:
        st.success("Olet kirjautunut sisään Yahoo Fantasyyn ✅")
        if st.button("🔄 Uusi token"):
            refresh_token()

        st.subheader("Testaa API-yhteys")
        if st.button("📊 Testaa token ja hae omat pelit"):
            data = yahoo_api_get("users;use_login=1/games")
            if data:
                st.code(data)

