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
import requests
import xml.etree.ElementTree as ET
import time
import altair as alt

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
        yahoo_injury_statuses = {"IR", "IR+", "DTD", "O", "OUT", "INJ", "IR-NR", "IR-LT"}
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
        yahoo_injury_statuses = {"IR", "IR+", "DTD", "O", "OUT", "INJ", "IR-NR","IR-LT"}

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

# --- YAHOO API FUNKTIOT (VALIOLIIKA) ---

# Yahoo ID mappaukset
STAT_MAP_VALIOLIIKA = {
    '1': 'Goals',
    '2': 'Assists',
    '4': 'Points',       # P
    '8': 'PPP',          # Power Play Points
    '14': 'SOG',
    '31': 'Hits',
    '32': 'Blocks',
    '19': 'Wins',
    '26': 'SV%'          # Save Percentage (Yleensä ID 26)
}

# Valioliika Joukkueet (ID 1533)
# HUOM: Tarkista että järjestys on oikea Yahoo-liigassasi!
TEAMS_VALIOLIIKA = [
    ('465.l.1533.t.1', 'Mighty Moose'),
    ('465.l.1533.t.3', 'Bastuwhisk Mountain Bang'),
    ('465.l.1533.t.5', 'Lempäälän Laamat'),
    ('465.l.1533.t.6', 'N.Y. Rillataan'),
    ('465.l.1533.t.10', 'SalmonRapid Slicks'),
    ('465.l.1533.t.9', 'Talkkarit'),
    ('465.l.1533.t.8', 'Backwoods Clumsy Tinkerers'),
    ('465.l.1533.t.12', 'Kynäniskat'),
    ('465.l.1533.t.7', 'Oracles of Salmon Rapids'),
    ('465.l.1533.t.11', 'Lutakon Ketut'),
    ('465.l.1533.t.2', 'Animaali'),
    ('465.l.1533.t.4', 'Laajasalon Dynamo')
]

def get_yahoo_access_token():
    try:
        token_url = "https://api.login.yahoo.com/oauth2/get_token"
        redirect_uri = 'https://localhost:8501' 
        payload = {
            'client_id': st.secrets["yahoo"]["client_id"],
            'client_secret': st.secrets["yahoo"]["client_secret"],
            'refresh_token': st.secrets["yahoo"]["refresh_token"],
            'redirect_uri': redirect_uri, 
            'grant_type': 'refresh_token'
        }
        resp = requests.post(token_url, data=payload)
        resp.raise_for_status()
        return resp.json()['access_token']
    except Exception as e:
        st.error(f"Virhe Yahoo-kirjautumisessa: {e}")
        return None

def calculate_roto_scores(df):
    """Laskee Roto-pisteet (Rank) annetulle datalle."""
    if df.empty: return df
    
    df_roto = df.copy()
    
    # --- MUUTOS: Lisätty 'Points' tähän listaan ---
    categories = ['Goals', 'Assists', 'Points', 'PPP', 'SOG', 'Hits', 'Blocks', 'Wins', 'SV%']
    
    roto_cols = []
    for cat in categories:
        if cat in df_roto.columns:
            # Rank laskee sijoituksen. method='min' tasapisteissä.
            df_roto[f'{cat} (Roto)'] = df_roto[cat].rank(ascending=True, method='min')
            roto_cols.append(f'{cat} (Roto)')
    
    df_roto['Total Roto'] = df_roto[roto_cols].sum(axis=1)
    return df_roto


def fetch_yahoo_league_stats():
    access_token = get_yahoo_access_token()
    if not access_token: return pd.DataFrame()

    headers = {'Authorization': f'Bearer {access_token}'}
    rows = []
    ns = {'f': 'http://fantasysports.yahooapis.com/fantasy/v2/base.rng'}
    
    my_bar = st.progress(0, text="Haetaan dataa Yahoosta...")
    
    for i, (team_key, team_name) in enumerate(TEAMS_VALIOLIIKA):
        url = f"https://fantasysports.yahooapis.com/fantasy/v2/team/{team_key}/stats;type=season"
        try:
            r = requests.get(url, headers=headers)
            if r.status_code != 200: continue

            root = ET.fromstring(r.content)
            stats_node = root.find('.//f:team_stats/f:stats', ns)
            
            row_data = {'Team': team_name}

            if stats_node:
                for stat in stats_node.findall('f:stat', ns):
                    stat_id = stat.find('f:stat_id', ns).text
                    stat_val = stat.find('f:value', ns).text
                    if stat_val == '-': stat_val = 0
                    if stat_id in STAT_MAP_VALIOLIIKA:
                        row_data[STAT_MAP_VALIOLIIKA[stat_id]] = float(stat_val) if stat_val else 0

            rows.append(row_data)
        except Exception:
            pass
        my_bar.progress((i + 1) / len(TEAMS_VALIOLIIKA))
        time.sleep(0.1)

    my_bar.empty()
    df = pd.DataFrame(rows)
    
    # --- MUUTOS: Lasketaan Points (G + A) ---
    if 'Goals' in df.columns and 'Assists' in df.columns:
        df['Points'] = df['Goals'] + df['Assists']
    
    # Varmistetaan että Points on mukana listassa
    target_cols = ['Team', 'Goals', 'Assists', 'Points', 'PPP', 'SOG', 'Hits', 'Blocks', 'Wins', 'SV%']
    existing = [c for c in target_cols if c in df.columns]
    
    return df[existing]

def fetch_yahoo_matchups(week=None):
    access_token = get_yahoo_access_token()
    if not access_token: return pd.DataFrame()

    first_team_key = TEAMS_VALIOLIIKA[0][0]
    league_key = ".".join(first_team_key.split(".")[:3])
    headers = {'Authorization': f'Bearer {access_token}'}
    url = f"https://fantasysports.yahooapis.com/fantasy/v2/league/{league_key}/scoreboard"
    if week: url += f";week={week}"

    try:
        r = requests.get(url, headers=headers)
        r.raise_for_status()
        root = ET.fromstring(r.content)
        ns = {'f': 'http://fantasysports.yahooapis.com/fantasy/v2/base.rng'}
        matchups = root.findall('.//f:matchup', ns)
        data = []
        
        for matchup in matchups:
            teams = matchup.findall('.//f:team', ns)
            if len(teams) != 2: continue
            
            # Parsitaan joukkueet ja niiden statsit tästä matchupista
            matchup_stats = {}
            for t in teams:
                t_name = t.find('f:name', ns).text
                t_stats_node = t.find('.//f:team_stats/f:stats', ns)
                stats = {'Team': t_name}
                if t_stats_node:
                    for stat in t_stats_node.findall('f:stat', ns):
                        stat_id = stat.find('f:stat_id', ns).text
                        stat_val = stat.find('f:value', ns).text
                        if stat_val == '-': stat_val = 0
                        if stat_id in STAT_MAP_VALIOLIIKA:
                            stats[STAT_MAP_VALIOLIIKA[stat_id]] = float(stat_val) if stat_val else 0
                
                # --- MUUTOS: Lasketaan Points (G + A) tässä vaiheessa ---
                if 'Goals' in stats and 'Assists' in stats:
                    stats['Points'] = stats['Goals'] + stats['Assists']
                
                matchup_stats[t_name] = stats
            
            t0 = list(matchup_stats.values())[0]
            t1 = list(matchup_stats.values())[1]
            
            # Tallennetaan molemmat näkökulmat
            row0 = t0.copy()
            row0['Opponent'] = t1['Team']
            for k, v in t1.items():
                if k != 'Team': row0[f'Opp_{k}'] = v
            data.append(row0)

            row1 = t1.copy()
            row1['Opponent'] = t0['Team']
            for k, v in t0.items():
                if k != 'Team': row1[f'Opp_{k}'] = v
            data.append(row1)

        return pd.DataFrame(data)
    except Exception as e:
        st.error(f"Virhe: {e}")
        return pd.DataFrame()

def fetch_cumulative_matchups_roto(start_week, end_week):
    all_weeks = []
    my_bar = st.progress(0, text=f"Haetaan viikkoja {start_week}-{end_week}...")
    
    for i, week in enumerate(range(start_week, end_week + 1)):
        df = fetch_yahoo_matchups(week=week)
        if not df.empty:
            df['Week'] = week
            all_weeks.append(df)
        my_bar.progress((i + 1) / (end_week - start_week + 1))
        time.sleep(0.1)
    
    my_bar.empty()
    if not all_weeks: return pd.DataFrame()
    
    combined = pd.concat(all_weeks)
    
    # Aggregointi
    agg_rules = {}
    opp_agg_rules = {}
    
    # --- MUUTOS: Varmistetaan että 'Points' on mukana listassa ---
    cats_to_sum = list(STAT_MAP_VALIOLIIKA.values())
    if 'Points' not in cats_to_sum:
        cats_to_sum.append('Points')

    for cat in cats_to_sum:
        # Tarkistetaan onko kategoria datassa
        if cat in combined.columns:
            if cat == 'SV%':
                agg_rules[cat] = 'mean'
            else:
                agg_rules[cat] = 'sum'
        
        # Tarkistetaan onko vastustajan kategoria datassa
        if f'Opp_{cat}' in combined.columns:
            if cat == 'SV%':
                opp_agg_rules[f'Opp_{cat}'] = 'mean'
            else:
                opp_agg_rules[f'Opp_{cat}'] = 'sum'
            
    # Yhdistetään säännöt
    final_agg = {**agg_rules, **opp_agg_rules}
    final_agg['Opponent'] = lambda x: ', '.join(x.unique())
    
    summary = combined.groupby('Team').agg(final_agg).reset_index()
    
    # Laske Roto-pisteet tälle jaksolle (Oma suoritus)
    summary = calculate_roto_scores(summary)
    
    # Laske Roto-pisteet vastustajan suoritukselle (Opponent Strength)
    opp_cols = [c for c in summary.columns if c.startswith('Opp_')]
    opp_df = summary[['Team'] + opp_cols].copy()
    
    # Nimetään uudelleen jotta calculate_roto_scores toimii
    rename_dict = {c: c.replace('Opp_', '') for c in opp_cols}
    opp_df = opp_df.rename(columns=rename_dict)
    
    opp_roto = calculate_roto_scores(opp_df)
    summary['Opponent Total Roto'] = opp_roto['Total Roto']
    
    return summary
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
def load_schedule_from_gsheets():
    client = get_gspread_client()
    if client is None:
        st.error("Google Sheets -asiakas ei ole käytettävissä. Tarkista tunnistautuminen.")
        return pd.DataFrame()

    try:
        sheet_url = st.secrets["free_agents_sheet"]["url"]  # sama tiedosto kuin rosterit
        sheet = client.open_by_url(sheet_url)
        worksheet = sheet.worksheet("Schedule")  # välilehden nimi oltava täsmälleen "Schedule"
        data = worksheet.get_all_records()
        df = pd.DataFrame(data)

        if df.empty:
            st.error("⚠️ 'Schedule' välilehti on tyhjä tai sitä ei löytynyt.")
            return pd.DataFrame()

        # Normalisoidaan sarakenimet
        df.columns = df.columns.str.strip()

        required = ["Date", "Visitor", "Home"]
        missing = [c for c in required if c not in df.columns]
        if missing:
            st.error(f"Puuttuvia sarakkeita aikataulusta: {missing}")
            return pd.DataFrame()

        # Muutetaan päivämäärät
        df["Date"] = pd.to_datetime(df["Date"], errors="coerce")
        return df

    except Exception as e:
        st.error(f"Virhe aikataulun lukemisessa: {e}")
        return pd.DataFrame()

if "schedule" not in st.session_state or st.session_state["schedule"].empty:
    st.session_state["schedule"] = load_schedule_from_gsheets()

if not st.session_state["schedule"].empty:
    st.sidebar.success("Peliaikataulu ladattu onnistuneesti Google Sheetistä ✅")


# --- SIVUPALKKI: OMA ROSTERI ---

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
    
    if st.sidebar.button("Poista valittu pelaaja") and remove_player:
        st.session_state['roster'] = st.session_state['roster'][st.session_state['roster']['name'] != remove_player]

        # Päivitä myös healthy/injured
        if "roster_healthy" in st.session_state:
            st.session_state['roster_healthy'] = st.session_state['roster_healthy'][st.session_state['roster_healthy']['name'] != remove_player]
        if "roster_injured" in st.session_state:
            st.session_state['roster_injured'] = st.session_state['roster_injured'][st.session_state['roster_injured']['name'] != remove_player]
    
        st.session_state['roster'].to_csv(ROSTER_FILE, index=False)
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

    # Lasketaan baseline: montako peliä nykyinen rosteri saa
    _, base_player_games, *_ = optimize_roster_advanced(
        schedule_df, roster_df, pos_limits, num_attempts=50
    )
    base_total = sum(base_player_games.values())
    
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
            
            # Suoritetaan optimointi simuloidulla pelaajalla
            _, sim_player_games, *_ = optimize_roster_advanced(
                schedule_df, sim_roster, pos_limits, num_attempts=50
            )
            sim_total = sum(sim_player_games.values())
            
            # Erotus kertoo todellisen lisäyksen
            added_games = sim_total - base_total
            
            impact_data.append({
                'Joukkue': team,
                'Lisäpelit': max(0, added_games)  # ei negatiivisia
            })
        
        # Luodaan DataFrame ja järjestetään se
        df = pd.DataFrame(impact_data).sort_values('Lisäpelit', ascending=False)
        results[pos] = df
    
    return results


def analyze_free_agents(team_impact_dict, free_agents_df, roster_df):
    """
    Analysoi vapaat agentit aiemmin lasketun joukkueanalyysin perusteella.
    Suodattaa pois kaikki jo rosterissa olevat pelaajat (terveet ja loukkaantuneet).
    """
    if not team_impact_dict or free_agents_df.empty:
        st.warning("Joukkueanalyysiä tai vapaiden agenttien listaa ei ole ladattu.")
        return pd.DataFrame()

    # Poista kaikki rosterissa olevat pelaajat (terveet + loukkaantuneet)
    current_names = set(st.session_state['roster']['name']) if not st.session_state['roster'].empty else set()
    fa_df = free_agents_df[~free_agents_df['name'].isin(current_names)].copy()

    # Jätä pois maalivahdit
    fa_df = fa_df[~fa_df['positions'].str.contains('G')].copy()
    if fa_df.empty:
        st.info("Vapaita agentteja ei löytynyt maalivahtien suodatuksen jälkeen.")
        return pd.DataFrame()

    # Yhdistä joukkueanalyysin tulokset
    team_impact_df_list = []
    for pos, df in team_impact_dict.items():
        if not df.empty and pos != 'G':
            df = df.copy()
            df['position'] = pos
            team_impact_df_list.append(df)

    if not team_impact_df_list:
        st.warning("Joukkueanalyysin tuloksia ei löytynyt kenttäpelaajille.")
        return pd.DataFrame()

    combined_impact_df = pd.concat(team_impact_df_list, ignore_index=True)
    combined_impact_df.rename(columns={'Joukkue': 'team', 'Lisäpelit': 'extra_games_total'}, inplace=True)

    results = fa_df.copy()
    results['total_impact'] = 0.0
    results['games_added'] = 0.0

    # Käsittele monipaikkaiset pelaajat
    results['positions_list'] = results['positions'].apply(
        lambda x: [p.strip() for p in str(x).replace('/', ',').split(',')]
    )

    def calculate_impact(row):
        team = row['team']
        fpa = row['fantasy_points_avg']
        positions = row['positions_list']
        max_extra_games = 0.0
        if not positions:
            return 0.0, 0.0
        for pos in positions:
            match = combined_impact_df[
                (combined_impact_df['team'] == team) & (combined_impact_df['position'] == pos)
            ]
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

def load_all_team_rosters_from_gsheets():
    client = get_gspread_client()
    if client is None:
        return {}

    sheet_url = st.secrets["free_agents_sheet"]["url"]
    sheet = client.open_by_url(sheet_url)
    worksheet = sheet.worksheet("Valioliika Roster")  # vaihda tarvittaessa oikeaan välilehteen
    data = worksheet.get_all_records()
    df = pd.DataFrame(data)

    # Normalisoi sarakkeet turvallisesti
    df.columns = df.columns.map(str).str.strip().str.lower()

    required = ["fantasy team", "player name", "position(s)", "nhl team", "fp", "injury status"]
    if not all(c in df.columns for c in required):
        st.error(f"Rosteritaulukosta puuttuu vaadittuja sarakkeita. Löytyi: {df.columns.tolist()}")
        return {}

    # Normalisoi injury_status
    df["injury status"] = df["injury status"].fillna("").astype(str).str.strip().str.upper()
    yahoo_injury_statuses = {"IR", "IR+", "DTD", "O", "OUT", "INJ", "IR-NR", "IR-LT"}

    # Muodosta dict: {joukkue_nimi: DataFrame} – vain terveet
    team_rosters = {}
    for team in df["fantasy team"].dropna().unique():
        team_df = df[df["fantasy team"] == team].copy()
        team_df = team_df.rename(columns={
            "player name": "name",
            "nhl team": "team",
            "position(s)": "positions",
            "fp": "fantasy_points_avg",
            "injury status": "injury_status"
        })
        team_df["fantasy_points_avg"] = pd.to_numeric(
            team_df["fantasy_points_avg"], errors="coerce"
        ).fillna(0)

        # ✅ Suodata pois loukkaantuneet
        healthy_df = team_df[~team_df["injury_status"].isin(yahoo_injury_statuses)].copy()

        team_rosters[team] = healthy_df

    return team_rosters


def analyze_all_teams(schedule_df, team_rosters, pos_limits, start_date, end_date):
    results = []
    schedule_filtered = schedule_df[
        (schedule_df['Date'] >= pd.to_datetime(start_date)) &
        (schedule_df['Date'] <= pd.to_datetime(end_date))
    ]

    for team_name, roster_df in team_rosters.items():
        if roster_df.empty:
            continue

        # ✅ Ota vain 20 parasta pelaajaa FP/game mukaan
        if "fantasy_points_avg" not in roster_df.columns:
            st.warning(f"Joukkue {team_name} ei sisällä saraketta fantasy_points_avg")
            continue

        top20 = roster_df.sort_values("fantasy_points_avg", ascending=False).head(20)

        _, player_games, total_fp, total_active_games, _ = optimize_roster_advanced(
            schedule_filtered, top20, pos_limits, num_attempts=200
        )
        results.append({
            "Joukkue": team_name,
            "Aktiiviset pelit": total_active_games,
            "Ennakoidut FP": round(total_fp, 1)
        })

    return pd.DataFrame(results).sort_values("Ennakoidut FP", ascending=False)

def build_lineup_matrix(daily_results, max_bench=10):
    # Määritellään slotit
    slots = (
        [f"C{i+1}" for i in range(3)] +
        [f"LW{i+1}" for i in range(3)] +
        [f"RW{i+1}" for i in range(3)] +
        [f"D{i+1}" for i in range(4)] +
        ["UTIL1"] +
        [f"G{i+1}" for i in range(2)] +
        [f"Bench{i+1}" for i in range(max_bench)]
    )

    # Kerätään data
    table = {slot: {} for slot in slots}
    for result in daily_results:
        date = result["Date"]
        active = result.get("Active", {})
        bench = result.get("Bench", [])

        # Täytetään aktiiviset
        for pos, players in active.items():
            for i, player in enumerate(players):
                if pos in ["C", "LW", "RW", "D", "G"]:
                    slot_name = f"{pos}{i+1}"
                elif pos == "UTIL":
                    slot_name = "UTIL1"
                else:
                    continue
                if slot_name in table:
                    surname = player.split()[-1]
                    positions = None
                    if "roster" in st.session_state and not st.session_state["roster"].empty:
                        match = st.session_state["roster"][st.session_state["roster"]["name"] == player]
                        if not match.empty:
                            positions = match["positions"].iloc[0]
                            # Poista UTIL näkyvistä
                            if isinstance(positions, str):
                                positions = "/".join([p for p in positions.split("/") if p != "UTIL"])
                    if positions:
                        display_name = f"{surname} {positions}"
                    else:
                        display_name = surname
                    table[slot_name][date] = display_name


        # Täytetään penkki
        for i, player in enumerate(bench):
            if i < max_bench:
                surname = player.split()[-1]
                positions = None
                if "roster" in st.session_state and not st.session_state["roster"].empty:
                    match = st.session_state["roster"][st.session_state["roster"]["name"] == player]
                    if not match.empty:
                        positions = match["positions"].iloc[0]
                        # Poista UTIL näkyvistä
                        if isinstance(positions, str):
                            positions = "/".join([p for p in positions.split("/") if p != "UTIL"])
                if positions:
                    display_name = f"{surname} {positions}"
                else:
                    display_name = surname
                table[f"Bench{i+1}"][date] = display_name


    # Muodostetaan DataFrame
    df = pd.DataFrame(table).T  # slotit riveiksi
    df = df[sorted(df.columns)]  # järjestä päivät

    # ✅ Muodostetaan uudet otsikot: YYYY-MM-DD (Mon)
    new_cols = []
    for d in df.columns:
        try:
            d = pd.to_datetime(d)
            new_cols.append(f"{d.strftime('%Y-%m-%d')} ({d.strftime('%a')})")
        except Exception:
            new_cols.append(str(d))
    df.columns = new_cols

    return df



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
    
    st.header("🚀 Rosterin optimointi (Valioliika)")
    
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

            # Rakennetaan matriisi optimoinnin tuloksista
            lineup_df = build_lineup_matrix(daily_results, max_bench=5)
            
            # Näytetään taulukko käyttöliittymässä
            st.dataframe(lineup_df, use_container_width=True, height=800)
            
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
                    # Laske baseline aktiiviset
                    original_active_count = get_daily_active_slots(available_players_today, pos_limits)
                    
                    # Luo simuloitu pelaaja
                    sim_player_name = f"SIM_PLAYER_{pos_check}"
                    sim_players_list = available_players_today + [sim_player_name]
                    players_info_dict[sim_player_name] = {
                        "team": "TEMP",
                        "positions": [pos_check],
                        "fpa": 0
                    }
                    if pos_check in ["C", "LW", "RW", "D"]:
                        players_info_dict[sim_player_name]["positions"].append("UTIL")
                    
                    # Laske simuloidut aktiiviset
                    simulated_active_count = get_daily_active_slots(sim_players_list, pos_limits)
                    
                    # Lisää vain jos aktiivisten määrä kasvaa
                    if simulated_active_count > original_active_count:
                        availability_data[pos_check].append(1)
                    else:
                        availability_data[pos_check].append(0)


                    del players_info_dict[sim_player_name]

            # Muodostetaan indeksi, jossa mukana viikonpäivä
            index_with_weekdays = [f"{d.strftime('%Y-%m-%d')} ({d.strftime('%a')})" for d in valid_dates]
            
            availability_df = pd.DataFrame(availability_data, index=index_with_weekdays)

            
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
            comparison_type = st.radio(
                "Valitse vertailutyyppi:",
                ["Vertaa kahta uutta pelaajaa", "Lisää uusi pelaaja ja poista valittu omasta rosterista"],
                key="comparison_type"
            )
        
            # --- Käytettävä rosteri: sama logiikka kuin Rosterin optimoinnissa ---
            healthy = st.session_state.get("roster_healthy", pd.DataFrame())
            injured = st.session_state.get("roster_injured", pd.DataFrame())
            if st.session_state.get("show_all_roster", False):
                roster_to_use = pd.concat([healthy, injured]) if not healthy.empty or not injured.empty else healthy
            else:
                roster_to_use = healthy
        
            # --- Syötteet ---
        if comparison_type == "Lisää uusi pelaaja ja poista valittu omasta rosterista":
            drop_options = ["(ei pudotettavaa)"] + list(roster_to_use['name'])
            drop_player_name = st.selectbox(
                "Valitse pudotettava pelaaja", drop_options, key="drop_player_name"
            )
            if drop_player_name == "(ei pudotettavaa)":
                drop_player_name = None
        
            st.markdown("#### Lisättävä pelaaja")
            if "free_agents" in st.session_state and not st.session_state["free_agents"].empty:
                fa_df = st.session_state["free_agents"]
                selected_fa = st.selectbox(
                    "Valitse vapaa agentti",
                    [""] + list(fa_df["name"].unique()),
                    key="new_player_select"
                )
                if selected_fa:
                    fa_row = fa_df[fa_df["name"] == selected_fa].iloc[0]
                    new_player_name = fa_row["name"]
                    new_player_team = fa_row["team"]
                    new_player_positions = fa_row["positions"]
                    new_player_fpa = float(fa_row["fantasy_points_avg"])
                else:
                    new_player_name, new_player_team, new_player_positions, new_player_fpa = "", "", "", 0.0
            else:
                new_player_name = st.text_input("Pelaajan nimi", key="new_player_name")
                new_player_team = st.text_input("Joukkue", key="new_player_team")
                new_player_positions = st.text_input("Pelipaikat (esim. C/LW)", key="new_player_positions")
                new_player_fpa = st.number_input("FP/GP", min_value=0.0, step=0.1, format="%.2f", key="new_player_fpa")
        
            # ✅ Suorita vertailu -painike
            if st.button("Suorita vertailu", key="swap_compare_button"):
                if not (new_player_name and new_player_team and new_player_positions):
                    st.warning("Täytä lisättävän pelaajan kentät (nimi, joukkue, pelipaikat).")
                    st.stop()
        
                # Baseline: nykyinen rosteri
                daily_base, base_games_dict, base_fp, base_total_active_games, base_bench_dict = optimize_roster_advanced(
                    schedule_filtered, roster_to_use, pos_limits, num_attempts=200
                )
        
                # Swap: pudotettava pois, uusi sisään
                swap_roster = roster_to_use.copy()
                if drop_player_name:
                    swap_roster = swap_roster[swap_roster['name'] != drop_player_name]
                swap_roster = pd.concat([swap_roster, pd.DataFrame([{
                    'name': new_player_name,
                    'team': new_player_team,
                    'positions': new_player_positions,
                    'fantasy_points_avg': new_player_fpa
                }])], ignore_index=True)
        
                daily_swap, swap_games_dict, swap_fp, swap_total_active_games, swap_bench_dict = optimize_roster_advanced(
                    schedule_filtered, swap_roster, pos_limits, num_attempts=200
                )
        
                # Lisättävän pelaajan omat pelit
                new_player_active = swap_games_dict.get(new_player_name, 0)
        
                # Tulosten näyttö
                st.subheader("Skenaarioiden vertailu")
                col1, col2 = st.columns(2)
                with col1:
                    st.markdown("**Baseline (nykyinen rosteri)**")
                    st.metric("Aktiiviset pelit (yht.)", base_total_active_games)
                    st.metric("Fantasiapisteet (yht.)", f"{base_fp:.1f}")
                with col2:
                    st.markdown(f"**Swap (uusi pelaaja: {new_player_name})**")
                    st.metric("Aktiiviset pelit (yht.)", swap_total_active_games)
                    st.metric("Fantasiapisteet (yht.)", f"{swap_fp:.1f}")
                    st.metric(f"{new_player_name} aktiiviset pelit", new_player_active)
                    st.metric(f"{new_player_name} ennakoidut FP", f"{new_player_active * new_player_fpa:.1f}")
        
                st.subheader("Erot")
                st.metric("Δ Aktiiviset pelit (kokonaisuus)", f"{swap_total_active_games - base_total_active_games:+}")
                st.metric("Δ Fantasiapisteet (kokonaisuus)", f"{swap_fp - base_fp:+.1f}")

            
        elif comparison_type == "Vertaa kahta uutta pelaajaa":
            st.markdown("#### Uusi pelaaja A")
            if "free_agents" in st.session_state and not st.session_state["free_agents"].empty:
                fa_df = st.session_state["free_agents"]
                selected_fa_A = st.selectbox("Valitse vapaa agentti (pelaaja A)", [""] + list(fa_df["name"].unique()), key="fa_select_A")
                if selected_fa_A:
                    fa_row_A = fa_df[fa_df["name"] == selected_fa_A].iloc[0]
                    sim_name_A, sim_team_A, sim_positions_A, sim_fpa_A = fa_row_A["name"], fa_row_A["team"], fa_row_A["positions"], float(fa_row_A["fantasy_points_avg"])
                else:
                    sim_name_A, sim_team_A, sim_positions_A, sim_fpa_A = "", "", "", 0.0
            else:
                sim_name_A = st.text_input("Pelaajan nimi", key="sim_name_A")
                sim_team_A = st.text_input("Joukkue", key="sim_team_A")
                sim_positions_A = st.text_input("Pelipaikat (esim. C/LW)", key="sim_positions_A")
                sim_fpa_A = st.number_input("FP/GP", min_value=0.0, step=0.1, format="%.2f", key="sim_fpa_A")
        
            st.markdown("#### Uusi pelaaja B")
            if "free_agents" in st.session_state and not st.session_state["free_agents"].empty:
                fa_df = st.session_state["free_agents"]
                selected_fa_B = st.selectbox("Valitse vapaa agentti (pelaaja B)", [""] + list(fa_df["name"].unique()), key="fa_select_B")
                if selected_fa_B:
                    fa_row_B = fa_df[fa_df["name"] == selected_fa_B].iloc[0]
                    sim_name_B, sim_team_B, sim_positions_B, sim_fpa_B = fa_row_B["name"], fa_row_B["team"], fa_row_B["positions"], float(fa_row_B["fantasy_points_avg"])
                else:
                    sim_name_B, sim_team_B, sim_positions_B, sim_fpa_B = "", "", "", 0.0
            else:
                sim_name_B = st.text_input("Pelaajan nimi", key="sim_name_B")
                sim_team_B = st.text_input("Joukkue", key="sim_team_B")
                sim_positions_B = st.text_input("Pelipaikat (esim. C/LW)", key="sim_positions_B")
                sim_fpa_B = st.number_input("FP/GP", min_value=0.0, step=0.1, format="%.2f", key="sim_fpa_B")
        
            if st.button("Suorita vertailu", key="compare_two_button"):
                if not (sim_name_A and sim_team_A and sim_positions_A and sim_name_B and sim_team_B and sim_positions_B):
                    st.warning("Täytä molempien pelaajien tiedot.")
                    st.stop()
        
                roster_copy = roster_to_use.copy()
                if 'fantasy_points_avg' not in roster_copy.columns:
                    roster_copy['fantasy_points_avg'] = 0.0
        
                roster_A = pd.concat([roster_copy, pd.DataFrame([{
                    'name': sim_name_A, 'team': sim_team_A, 'positions': sim_positions_A, 'fantasy_points_avg': sim_fpa_A
                }])], ignore_index=True)
        
                roster_B = pd.concat([roster_copy, pd.DataFrame([{
                    'name': sim_name_B, 'team': sim_team_B, 'positions': sim_positions_B, 'fantasy_points_avg': sim_fpa_B
                }])], ignore_index=True)
        
                schedule_filtered = st.session_state['schedule'][
                    (st.session_state['schedule']['Date'] >= pd.to_datetime(start_date)) &
                    (st.session_state['schedule']['Date'] <= pd.to_datetime(end_date))
                ]
        
                _, games_A, fp_A, total_games_A, _ = optimize_roster_advanced(schedule_filtered, roster_A, pos_limits, num_attempts=200)
                _, games_B, fp_B, total_games_B, _ = optimize_roster_advanced(schedule_filtered, roster_B, pos_limits, num_attempts=200)
        
                # Pelaajakohtaiset aktiiviset pelit
                new_player_A_games = games_A.get(sim_name_A, 0)
                new_player_B_games = games_B.get(sim_name_B, 0)
        
                st.subheader("Vertailun tulokset")
                colA, colB = st.columns(2)
                with colA:
                    st.markdown(f"**{sim_name_A} ({sim_team_A})**")
                    st.metric("Aktiiviset pelit (yht.)", total_games_A)
                    st.metric("Fantasiapisteet (yht.)", f"{fp_A:.1f}")
                    st.metric(f"{sim_name_A} aktiiviset pelit", new_player_A_games)
                    st.metric(f"{sim_name_A} ennakoidut FP", f"{new_player_A_games * sim_fpa_A:.1f}")
        
                with colB:
                    st.markdown(f"**{sim_name_B} ({sim_team_B})**")
                    st.metric("Aktiiviset pelit (yht.)", total_games_B)
                    st.metric("Fantasiapisteet (yht.)", f"{fp_B:.1f}")
                    st.metric(f"{sim_name_B} aktiiviset pelit", new_player_B_games)
                    st.metric(f"{sim_name_B} ennakoidut FP", f"{new_player_B_games * sim_fpa_B:.1f}")
        
                st.subheader("Erot")
                delta_games = total_games_A - total_games_B
                delta_fp = fp_A - fp_B
                st.metric("Δ Aktiiviset pelit (kokonaisuus)", f"{delta_games:+}", delta=f"{delta_games:+}")
                st.metric("Δ Fantasiapisteet (kokonaisuus)", f"{delta_fp:+.1f}", delta=f"{delta_fp:+.1f}")


        
        
        # --- Joukkueanalyysi ---
        st.markdown("---")
        st.header("🔍 Joukkueanalyysi")
        st.markdown("""
        Tämä osio simuloi kuvitteellisen pelaajan lisäämisen jokaisesta joukkueesta ja näyttää,
        mikä joukkue tuottaisi eniten aktiivisia pelejä kullekin pelipaikalle ottaen huomioon nykyisen rosterisi.
        """)
        
        if st.session_state['schedule'].empty or roster_to_use.empty:
            st.warning("Lataa sekä peliaikataulu että rosteri aloittaaksesi analyysin.")
        else:
            # ✅ Suodatetaan aikataulu valitun aikavälin mukaan – varmistetaan että tyypit täsmäävät
            schedule_filtered = st.session_state['schedule'][
                (st.session_state['schedule']['Date'] >= pd.to_datetime(start_date)) &
                (st.session_state['schedule']['Date'] <= pd.to_datetime(end_date))
            ]
        
            # Näytetään nappi aina, vaikka schedule_filtered olisi tyhjä
            if st.button("Suorita joukkueanalyysi"):
                if schedule_filtered.empty:
                    st.warning("Valitulla aikavälillä ei löytynyt otteluita.")
                else:
                    with st.spinner("Lasketaan joukkueanalyysiä..."):
                        st.session_state['team_impact_results'] = calculate_team_impact_by_position(
                            schedule_filtered, roster_to_use, pos_limits
                        )
        
            # Näytetään tulokset, jos analyysi on ajettu
            if st.session_state.get('team_impact_results') is not None:
                for pos, df in st.session_state['team_impact_results'].items():
                    st.subheader(f"Joukkueet pelipaikalle: {pos}")
                    st.dataframe(df, use_container_width=True)
        
    
                # --- Vapaiden agenttien analyysi UI ---
                st.markdown("---")
                st.header("🆓 Vapaiden agenttien analyysi")
                
                # Nappi analyysin ajamiseen
                if st.button("Suorita vapaiden agenttien analyysi", key="free_agent_analysis_button_new"):
                    if st.session_state.get('team_impact_results') is None:
                        st.warning("Suorita ensin joukkueanalyysi.")
                    elif st.session_state['free_agents'].empty:
                        st.warning("Lataa vapaat agentit (CSV tai Google Sheet).")
                    else:
                        with st.spinner("Analysoidaan vapaat agentit..."):
                            free_agent_results = analyze_free_agents(
                                st.session_state['team_impact_results'],
                                st.session_state['free_agents'],
                                roster_to_use
                            )
                            st.session_state['free_agent_results'] = free_agent_results
                
                # Näytetään suodatusvalikot ja tulokset vain jos analyysi on ajettu
                if st.session_state.get('free_agent_results') is not None and not st.session_state['free_agent_results'].empty:
                
                    # --- Suodatusvalikot ---
                    all_positions = sorted(list(set(
                        p.strip()
                        for player_pos in st.session_state['free_agents']['positions'].unique()
                        for p in str(player_pos).replace('/', ',').split(',')
                    )))
                    all_teams = sorted(st.session_state['free_agents']['team'].unique())
                
                    # Alustetaan session_state jos ei vielä ole
                    if "fa_selected_pos" not in st.session_state:
                        st.session_state["fa_selected_pos"] = all_positions
                    if "fa_selected_team" not in st.session_state:
                        st.session_state["fa_selected_team"] = "Kaikki"
                
                    # Multiselect pelipaikoille
                    st.session_state["fa_selected_pos"] = st.multiselect(
                        "Suodata pelipaikkojen mukaan:",
                        all_positions,
                        default=st.session_state["fa_selected_pos"],
                        key="fa_pos_filter_v1"
                    )
                
                    # Selectbox joukkueelle
                    st.session_state["fa_selected_team"] = st.selectbox(
                        "Suodata joukkueen mukaan:",
                        ["Kaikki"] + list(all_teams),
                        index=(["Kaikki"] + list(all_teams)).index(st.session_state["fa_selected_team"])
                        if st.session_state["fa_selected_team"] in ["Kaikki"] + list(all_teams) else 0,
                        key="fa_team_filter_v1"
                    )
                
                    # --- Suodatus tuloksiin ---
                    filtered_results = st.session_state['free_agent_results'].copy()
                
                    if st.session_state["fa_selected_pos"]:
                        filtered_results = filtered_results[
                            filtered_results['positions'].apply(
                                lambda x: any(pos in x.split('/') for pos in st.session_state["fa_selected_pos"])
                            )
                        ]
                
                    if st.session_state["fa_selected_team"] != "Kaikki":
                        filtered_results = filtered_results[
                            filtered_results['team'] == st.session_state["fa_selected_team"]
                        ]
                
                    # Näytetään tulokset
                    st.dataframe(
                        filtered_results.style.format({
                            'total_impact': "{:.2f}",
                            'fantasy_points_avg': "{:.1f}"
                        }),
                        use_container_width=True
                    )



with tab2:
    st.header("🆚 Joukkuevertailu (Valioliika)")
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

    import altair as alt  # varmista että tämä on tiedoston yläosassa

 # 2. Category Points (Roto)
    st.markdown("---")
    st.header("📊 Category Points (Roto Standings)")
    
    if st.button("🔄 Hae koko kauden Roto-tilastot Yahoosta"):
        df = fetch_yahoo_league_stats()
        if not df.empty:
            # Laske Roto-pisteet (Rank)
            df = calculate_roto_scores(df)
            df = df.sort_values("Total Roto", ascending=False).reset_index(drop=True)
            st.session_state['valio_roto_stats'] = df
            st.success("Tiedot päivitetty!")
            
    if 'valio_roto_stats' in st.session_state:
        roto_df = st.session_state['valio_roto_stats']
        
        # Määritellään halutut sarakkeet
        raw_cols_target = ['Goals', 'Assists', 'Points', 'PPP', 'SOG', 'Hits', 'Blocks', 'Wins', 'SV%']
        
        # 1. Tarkistetaan mitkä raakadatasarakkeet ovat olemassa
        raw_cols_present = [c for c in raw_cols_target if c in roto_df.columns]
        
        # 2. Generoidaan Roto-sarakkeiden nimet ja TARKISTETAAN ETTÄ NE OVAT OLEMASSA
        # Tämä on kriittinen korjaus: tarkistetaan 'if f"{c} (Roto)" in roto_df.columns'
        roto_cols_present = [f'{c} (Roto)' for c in raw_cols_present if f'{c} (Roto)' in roto_df.columns]
        
        st.subheader("Sarjataulukko (Total Roto Points)")
        
        # Luodaan näyttölista turvallisesti
        display_cols = ['Team', 'Total Roto'] + roto_cols_present
        # Varmistus: otetaan vain ne jotka löytyvät
        display_cols = [c for c in display_cols if c in roto_df.columns]
        
        disp = roto_df[display_cols]
        
        # Formatoidaan numerot (jätetään Team pois muotoilusta)
        numeric_cols = [c for c in display_cols if c != 'Team']
        st.dataframe(disp.style.format("{:.1f}", subset=numeric_cols), use_container_width=True)
        
        st.subheader("Raakatilastot")
        raw_display_cols = ['Team'] + raw_cols_present
        st.dataframe(roto_df[raw_display_cols], use_container_width=True)

        # Kaavio
        # Lisätään ylimääräinen tarkistus varmuuden vuoksi
        valid_chart_cols = [c for c in roto_cols_present if c in roto_df.columns]
        
        # Kaavio - Varmistettu versio
        valid_chart_cols = [c for c in roto_cols_present if c in roto_df.columns]
        
        # Tarkistetaan että Team-sarake ja datapisteet ovat olemassa
        if valid_chart_cols and 'Team' in roto_df.columns:
            try:
                # 1. Luodaan erillinen, puhdas kopio datasta vain kaaviota varten
                # Tämä estää indeksien tai piilosarakkeiden aiheuttamat ongelmat
                plot_df = roto_df[['Team'] + valid_chart_cols].copy()
                
                # 2. Meltataan tämä puhdas kopio
                chart_data = plot_df.melt(
                    id_vars=['Team'], 
                    value_vars=valid_chart_cols, 
                    var_name='Category', 
                    value_name='Points'
                )
                
                # 3. Siistitään nimet ja piirretään
                chart_data['Category'] = chart_data['Category'].str.replace(' (Roto)', '')
                
                chart = alt.Chart(chart_data).mark_bar().encode(
                    y=alt.X('Team', sort='-x'),
                    x='Points',
                    color='Category',
                    tooltip=['Team', 'Category', 'Points']
                ).properties(height=600)
                
                st.altair_chart(chart, use_container_width=True)
                
            except Exception as e:
                st.warning(f"Kaavion luonti epäonnistui: {e}")
        else:
            if 'Team' not in roto_df.columns:
                st.error("Virhe: 'Team'-sarake puuttuu datasta.")
            else:
                st.warning("Ei Roto-pisteitä visualisoitavaksi.")

 # 3. Matchup Center (Roto Context)
    st.markdown("---")
    st.header("⚔️ Matchup Center (Roto Analysis)")
    st.caption("Analysoi matchupit Roto-pisteiden valossa: 'Oma taso' vs 'Vastustajan taso'")
    
    col_c1, col_c2 = st.columns([3, 1], vertical_alignment="bottom")
    with col_c1:
        wr = st.slider("Viikot", 1, 26, (1, 4))
    with col_c2:
        run_mc = st.button("Hae Matchupit", use_container_width=True)
        
    if run_mc:
        st.session_state['valio_matchup_df'] = fetch_cumulative_matchups_roto(wr[0], wr[1])
        
    if 'valio_matchup_df' in st.session_state:
        df = st.session_state['valio_matchup_df']
        if not df.empty:
            
            st.subheader(f"Tulokset: Viikot {wr[0]} - {wr[1]}")
            
            # Näytetään päätaulukko
            display_cols = ['Team', 'Total Roto', 'Opponent Total Roto', 'Opponent']
            st.dataframe(
                df[display_cols].style.format("{:.1f}", subset=['Total Roto', 'Opponent Total Roto']),
                use_container_width=True
            )
            
            # Scatter Plot: Oma Roto vs Vastustajan Roto (Onni)
            st.markdown("#### 📈 Oma Suoritus vs Vastustajan Suoritus (Roto Pisteet)")
            st.caption("Oikea alakulma = Pelasit hyvin (korkea Roto) ja vastustaja huonosti (matala Roto). Vasen yläkulma = Pelasit huonosti ja vastustaja hyvin.")
            
            chart = alt.Chart(df).mark_circle(size=200).encode(
                x=alt.X('Total Roto', title='Omat Roto-pisteet (Suoritus)', scale=alt.Scale(zero=False)),
                y=alt.Y('Opponent Total Roto', title='Vastustajan Roto-pisteet (Kovuus)', scale=alt.Scale(zero=False)),
                color=alt.Color('Total Roto', scale=alt.Scale(scheme='greens')),
                tooltip=['Team', 'Total Roto', 'Opponent Total Roto', 'Opponent']
            ).properties(height=500).interactive()
            
            text = chart.mark_text(dx=12).encode(text='Team')
            
            # Keskiarvoviivat
            mid_x = alt.Chart(df).mark_rule(color='gray', strokeDash=[5,5]).encode(x='mean(Total Roto)')
            mid_y = alt.Chart(df).mark_rule(color='gray', strokeDash=[5,5]).encode(y='mean(Opponent Total Roto)')
            
            st.altair_chart(chart + text + mid_x + mid_y, use_container_width=True)
