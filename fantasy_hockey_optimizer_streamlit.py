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
if 'optimization_results' not in st.session_state:
    st.session_state['optimization_results'] = None

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
    st.session_state['optimization_results'] = None
    st.sidebar.success("Välimuisti tyhjennetty!")
    st.rerun()

# Peliaikataulun lataus
st.sidebar.subheader("Lataa NHL-peliaikataulu")

schedule_file_uploader = st.sidebar.file_uploader(
    "Lataa NHL-peliaikataulu (CSV)",
    type=["csv"],
    key="schedule_uploader",
    help="CSV-tiedoston tulee sisältää sarakkeet: Date, Visitor, Home"
)

# Käsittele lataus
if schedule_file_uploader is not None:
    try:
        schedule = pd.read_csv(schedule_file_uploader)
        if not schedule.empty and all(col in schedule.columns for col in ['Date', 'Visitor', 'Home']):
            schedule['Date'] = pd.to_datetime(schedule['Date']).dt.date
            st.session_state['schedule'] = schedule
            schedule.to_csv(SCHEDULE_FILE, index=False)
            st.sidebar.success("Peliaikataulu ladattu ja tallennettu!")
        else:
            st.sidebar.error("Peliaikataulun CSV-tiedoston tulee sisältää sarakkeet: Date, Visitor, Home")
    except Exception as e:
        st.sidebar.error(f"Virhe peliaikataulun lukemisessa: {str(e)}")

# Lataa tallennettu tiedosto, jos uutta ei ole ladattu
if st.session_state['schedule'].empty and os.path.exists(SCHEDULE_FILE):
    try:
        st.session_state['schedule'] = pd.read_csv(SCHEDULE_FILE)
        st.session_state['schedule']['Date'] = pd.to_datetime(st.session_state['schedule']['Date']).dt.date
        st.sidebar.info("Peliaikataulu ladattu automaattisesti tallennetusta tiedostosta.")
    except Exception as e:
        st.sidebar.error(f"Virhe tallennetun aikataulun lukemisessa: {str(e)}")
        os.remove(SCHEDULE_FILE)
        st.session_state['schedule'] = pd.DataFrame()


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
                opponent_roster['fantasy_points_avg'] =
