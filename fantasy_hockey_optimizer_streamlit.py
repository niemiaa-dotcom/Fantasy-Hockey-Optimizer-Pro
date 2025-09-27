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
import requests # Tarvitaan kustomiin Yahoo OAuth-kutsuun
import json # Tarvitaan vastauksen käsittelyyn
import time # Tarvitaan tokenin vanhenemisen laskemiseen
from urllib.parse import urlencode, parse_qs # Tarvitaan OAuth-URLien luomiseen

# --- YAHOO OAuth ASETUKSET & VAKIOT ---
YAHOO_OAUTH2_AUTH_URL = 'https://api.login.yahoo.com/oauth2/request_auth'
YAHOO_OAUTH2_TOKEN_URL = 'https://api.login.yahoo.com/oauth2/get_token'
YAHOO_FANTASY_API_BASE_URL = 'https://fantasysports.yahooapis.com/fantasy/v2'

# TÄRKEÄÄ: VAIHDA TÄHÄN SOVELLUKSESI URL (esim. https://your-app.streamlit.app)
REDIRECT_URI = 'http://localhost:8501' # Oletus Streamlit paikallinen portti

# --- FUNKTIOT (YAHOO OAuth 2.0) ---

@st.cache_data(ttl=3600)
def yahoo_api_request(url_path: str):
    """Suorittaa pyynnön Yahoo Fantasy API:an, varmistaa tokenin voimassaolon."""
    
    if 'yahoo_access_token' not in st.session_state or 'yahoo_token_expires_at' not in st.session_state:
        st.error("Et ole kirjautunut sisään Yahoo Fantasyn kautta.")
        return None

    # 1. Tarkista tokenin vanheneminen ja päivitä se tarvittaessa
    if time.time() > st.session_state['yahoo_token_expires_at'] - 60: # Päivitetään minuutti ennen vanhenemista
        if not refresh_yahoo_token():
            st.error("Tokenin päivitys epäonnistui. Kirjaudu sisään uudelleen.")
            return None

    # 2. Tee API-kutsu
    headers = {
        'Authorization': f'Bearer {st.session_state["yahoo_access_token"]}',
        'Content-Type': 'application/json'
    }
    full_url = f"{YAHOO_FANTASY_API_BASE_URL}{url_path}"

    try:
        response = requests.get(full_url, headers=headers)
        response.raise_for_status() # Nosta virhe huonolle vastaukselle (4xx tai 5xx)
        
        # Yahoo palauttaa XML:ää. Käsittele tämä tarpeidesi mukaan.
        # Tämä koodi palauttaa raakaa tekstiä jatkokäsittelyä varten (esim. XML-parsinta)
        return response.text 
    except requests.exceptions.RequestException as e:
        st.error(f"Yahoo API -kutsu epäonnistui: {e}")
        return None

def refresh_yahoo_token():
    """Päivittää vanhentuneen Access Tokenin Refresh Tokenilla."""
    
    if 'yahoo_refresh_token' not in st.session_state:
        return False

    try:
        # 1. Valmistele pyyntö
        auth_header = requests.auth.HTTPBasicAuth(st.secrets["yahoo"]["client_id"], st.secrets["yahoo"]["client_secret"])
        data = {
            'grant_type': 'refresh_token',
            'redirect_uri': REDIRECT_URI,
            'refresh_token': st.session_state['yahoo_refresh_token']
        }

        # 2. Suorita pyyntö
        response = requests.post(YAHOO_OAUTH2_TOKEN_URL, auth=auth_header, data=data)
        response.raise_for_status()
        token_data = response.json()
        
        # 3. Päivitä session tila
        st.session_state['yahoo_access_token'] = token_data['access_token']
        st.session_state['yahoo_refresh_token'] = token_data.get('refresh_token', st.session_state['yahoo_refresh_token'])
        st.session_state['yahoo_token_expires_at'] = time.time() + token_data['expires_in']
        return True

    except requests.exceptions.RequestException as e:
        st.error(f"Refresh Token -virhe: {e}")
        return False

# Apufunktio: Haetaan käyttäjän pelit (käytetään API-testiin)
def get_yahoo_user_games():
    """Hakee käyttäjän pelit. Palauttaa raa'an XML-datan."""
    # Esimerkki: hakee XML-tiedot käyttäjän peleistä
    return yahoo_api_request("/users;use_login=1/games")

def load_data_from_yahoo_fantasy(game_key: str, league_id: str, team_name: str, roster_type: str):
    """Lataa rosterin tai vapaat agentit Yahoo Fantasysta.
    Tämä käyttää nyt kustomoitua Yahoo OAuth -virtaa."""
    
    league_key = f"{game_key}.l.{league_id}"
    
    try:
        if roster_type == 'my_roster':
            # Haetaan liigan joukkueet
            url_path_teams = f"/league/{league_key}/teams"
            st.info(f"Yritetään hakea joukkueet liigasta {league_id}...")
            xml_teams = yahoo_api_request(url_path_teams)

            if not xml_teams:
                st.error("Joukkueiden haku epäonnistui.")
                return pd.DataFrame()
                
            # TÄRKEÄÄ: TÄHÄN TULEE XML-KÄSITTELY LOGIIKKA
            # Koska emme voi käsitellä XML:ää täällä, näytetään vain viesti.
            st.warning("Yahoo palauttaa XML:ää. Käsittely puuttuu.")
            
            # Simuloidaan datan palautus (Käytä oikeaa XML-parsintaa sovelluksessa!)
            # Tähän tarvitaan XML-parsinta, jolla löydät oman joukkueesi avaimen (team_key)
            st.error("XML-parsinta puuttuu. Ei voida hakea rosteria.")
            return pd.DataFrame()

        elif roster_type == 'free_agents':
            # Haetaan vapaat agentit
            url_path_fa = f"/league/{league_key}/players;status=FA"
            st.info(f"Yritetään hakea vapaat agentit liigasta {league_id}...")
            xml_fa = yahoo_api_request(url_path_fa)
            
            if not xml_fa:
                st.error("Vapaiden agenttien haku epäonnistui.")
