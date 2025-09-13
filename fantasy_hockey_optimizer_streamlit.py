import streamlit as st
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from collections import defaultdict
import itertools
import os

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

# Alusta session muuttujat
if 'schedule' not in st.session_state:
    st.session_state['schedule'] = pd.DataFrame()
if 'roster' not in st.session_state:
    st.session_state['roster'] = pd.DataFrame(columns=['name', 'team', 'positions'])
if 'team_impact_results' not in st.session_state:
    st.session_state['team_impact_results'] = None

# --- SIVUPALKKI: TIEDOSTOJEN LATAUS ---
st.sidebar.header("📁 Tiedostojen lataus")

# Tarkista, onko tallennettu aikataulutiedosto olemassa
schedule_file_exists = False
try:
    if SCHEDULE_FILE in st.secrets:
        pass
    else:
        st.session_state['schedule'] = pd.read_csv(SCHEDULE_FILE)
        st.session_state['schedule']['Date'] = pd.to_datetime(st.session_state['schedule']['Date'])
        schedule_file_exists = True
except FileNotFoundError:
    schedule_file_exists = False

# Tiedoston lataus käyttöliittymä
if schedule_file_exists and not st.sidebar.button("Lataa uusi aikataulu"):
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

# Rosterin lataus (sama logiikka)
roster_file_exists = False
try:
    st.session_state['roster'] = pd.read_csv(ROSTER_FILE)
    roster_file_exists = True
except FileNotFoundError:
    roster_file_exists = False

if roster_file_exists and not st.sidebar.button("Lataa uusi rosteri"):
    st.sidebar.success("Rosteri ladattu automaattisesti tallennetusta tiedostosta!")
else:
    roster_file = st.sidebar.file_uploader(
        "Lataa rosteri (CSV)", 
        type=["csv"],
        help="CSV-tiedoston tulee sisältää sarakkeet: name, team, positions"
    )
    if roster_file is not None:
        try:
            roster = pd.read_csv(roster_file)
            if not roster.empty and all(col in roster.columns for col in ['name', 'team', 'positions']):
                st.session_state['roster'] = roster
                roster.to_csv(ROSTER_FILE, index=False)
                st.sidebar.success("Rosteri ladattu ja tallennettu!")
                st.rerun()
            else:
                st.sidebar.error("Rosterin CSV-tiedoston tulee sisältää sarakkeet: name, team, positions")
        except Exception as e:
            st.sidebar.error(f"Virhe rosterin lukemisessa: {str(e)}")

# --- SIVUPALKKI: ROSTERIN HALLINTA ---
st.sidebar.header("👥 Rosterin hallinta")

if not st.session_state['roster'].empty:
    st.sidebar.subheader("Nykyinen rosteri")
    st.sidebar.dataframe(st.session_state['roster'])
    
    remove_player = st.sidebar.selectbox(
        "Poista pelaaja", 
        [""] + list(st.session_state['roster']['name'])
    )
    if st.sidebar.button("Poista valittu pelaaja") and remove_player:
        st.session_state['roster'] = st.session_state['roster'][
            st.session_state['roster']['name'] != remove_player
        ]
        st.session_state['roster'].to_csv(ROSTER_FILE, index=False)
        st.sidebar.success(f"Pelaaja {remove_player} poistettu!")
        st.rerun()
    
    st.sidebar.subheader("Lisää uusi pelaaja")
    with st.sidebar.form("add_player_form"):
        new_name = st.text_input("Pelaajan nimi")
        new_team = st.text_input("Joukkue")
        new_positions = st.text_input("Pelipaikat (esim. C/LW)")
        submitted = st.form_submit_button("Lisää pelaaja")
        
        if submitted and new_name and new_team and new_positions:
            new_player = pd.DataFrame({
                'name': [new_name],
                'team': [new_team],
                'positions': [new_positions]
            })
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
start_date = st.sidebar.date_input("Alkupäivä", today - timedelta(days=30))
end_date = st.sidebar.date_input("Loppupäivä", today)

if start_date > end_date:
    st.sidebar.error("Aloituspäivä ei voi olla loppupäivän jälkeen")

st.sidebar.subheader("Pelipaikkojen rajoitukset")
col1, col2 = st.sidebar.columns(2)
with col1:
    c_limit = st.number_input("Hyökkääjät (C)", min_value=1, max_value=6, value=3)
    lw_limit = st.number_input("Vasen laitahyökkääjä (LW)", min_value=1, max_value=6, value=3)
    rw_limit = st.number_input("Oikea laitahyökkääjä (RW)", min_value=1, max_value=6, value=3)
    
with col2:
    d_limit = st.number_input("Puolustajat (D)", min_value=1, max_value=8, value=4)
    g_limit = st.number_input("Maalivahdit (G)", min_value=1, max_value=4, value=2)
    util_limit = st.number_input("UTIL-paikat", min_value=0, max_value=3, value=1)

pos_limits = {
    'C': c_limit,
    'LW': lw_limit,
    'RW': rw_limit,
    'D': d_limit,
    'G': g_limit,
    'UTIL': util_limit
}

# --- PÄÄSIVU: OPTIMOINTIFUNKTIO ---
@st.cache_data
def optimize_roster_advanced(schedule_df, roster_df, limits, team_days, num_attempts=200):
    players_info = {}
    for _, player in roster_df.iterrows():
        positions_str = player['positions']
        if pd.isna(positions_str):
            positions_list = []
        elif isinstance(positions_str, str):
            positions_list = [p.strip() for p in positions_str.split('/')]
        else:
            positions_list = positions_str
        
        players_info[player['name']] = {
            'team': player['team'],
            'positions': positions_list
        }
    
    daily_results = []
    player_games = {name: 0 for name in players_info.keys()}
    
    for date in sorted(schedule_df['Date'].unique()):
        day_games = schedule_df[schedule_df['Date'] == date]
        
        available_players = []
        for _, game in day_games.iterrows():
            for team in [game['Visitor'], game['Home']]:
                for player_name, info in players_info.items():
                    if info['team'] == team and player_name not in [p['name'] for p in available_players]:
                        available_players.append({
                            'name': player_name,
                            'team': team,
                            'positions': info['positions']
                        })
        
        best_assignment = None
        max_active = 0
        
        for attempt in range(num_attempts):
            shuffled_players = available_players.copy()
            np.random.shuffle(shuffled_players)
            
            active = {
                'C': [], 'LW': [], 'RW': [], 'D': [], 'G': [], 'UTIL': []
            }
            bench = []
            
            for player_info in shuffled_players:
                placed = False
                player_name = player_info['name']
                positions_list = player_info['positions']
                
                for pos in positions_list:
                    if pos in limits and len(active[pos]) < limits[pos]:
                        active[pos].append(player_name)
                        placed = True
                        break
                
                if not placed and len(active['UTIL']) < limits['UTIL']:
                    if any(pos in ['C', 'LW', 'RW', 'D'] for pos in positions_list):
                        active['UTIL'].append(player_name)
                        placed = True
                
                if not placed:
                    bench.append(player_name)
            
            improved = True
            while improved:
                improved = False
                
                active_players_list = []
                for pos, players in active.items():
                    for player_name in players:
                        active_players_list.append({'name': player_name, 'current_pos': pos, 'positions': players_info[player_name]['positions']})
                
                bench_players_list = [{'name': name, 'current_pos': None, 'positions': players_info[name]['positions']} for name in bench]

                for bench_player in bench_players_list:
                    for active_player in active_players_list:
                        if active_player['current_pos'] in bench_player['positions']:
                            for new_pos in active_player['positions']:
                                if new_pos != active_player['current_pos'] and new_pos in limits and len(active[new_pos]) < limits[new_pos]:
                                    active[active_player['current_pos']].remove(active_player['name'])
                                    active[active_player['current_pos']].append(bench_player['name'])
                                    active[new_pos].append(active_player['name'])
                                    bench.remove(bench_player['name'])
                                    improved = True
                                    break
                        if improved:
                            break
                    if improved:
                        break
            
            total_active = sum(len(players) for players in active.values())
            
            if total_active > max_active:
                max_active = total_active
                best_assignment = {
                    'active': active.copy(),
                    'bench': bench.copy()
                }

        if best_assignment is None:
            best_assignment = {
                'active': {
                    'C': [], 'LW': [], 'RW': [], 'D': [], 'G': [], 'UTIL': []
                },
                'bench': [p['name'] for p in available_players]
            }
        
        all_player_names = [p['name'] for p in available_players]
        active_player_names = set()
        
        if best_assignment['active'] is not None:
            for pos, players in best_assignment['active'].items():
                active_player_names.update(players)
        
        final_bench = [name for name in all_player_names if name not in active_player_names]
        
        daily_results.append({
            'Date': date.date(),
            'Active': best_assignment['active'],
            'Bench': final_bench
        })
        
        if best_assignment['active'] is not None:
            for pos, players in best_assignment['active'].items():
                for player_name in players:
                    player_games[player_name] += 1
    
    return daily_results, player_games

# --- UUSI TOIMINNALLISUUS: SIMULOI JOUKKUEEN VAIKUTUS ---
@st.cache_data
def simulate_team_impact(schedule_df, roster_df, limits, team_days):
    nhl_teams = sorted(list(set(schedule_df['Home'].unique()) | set(schedule_df['Visitor'].unique())))
    positions_to_simulate = ['C', 'LW', 'RW', 'D', 'G']
    
    impact_data = []

    with st.spinner("Lasketaan alkuperäinen kokonaispelimäärä..."):
        _, original_games = optimize_roster_advanced(schedule_df, roster_df, limits, team_days)
        original_total = sum(original_games.values())

    with st.spinner("Simuloidaan joukkueiden optimaalista vaikutusta..."):
        for team in nhl_teams:
            for position in positions_to_simulate:
                
                positions_str = position
                sim_player_name = f"SIM_{team}_{position}"
                
                sim_player = pd.DataFrame([{
                    'name': sim_player_name,
                    'team': team,
                    'positions': positions_str
                }])
                
                sim_roster = pd.concat([roster_df, sim_player], ignore_index=True)
                
                _, simulated_games_dict = optimize_roster_advanced(schedule_df, sim_roster, limits, team_days)
                
                simulated_total = sum(simulated_games_dict.values())
                total_game_change = simulated_total - original_total

                impact_data.append({
                    'Joukkue': team,
                    'Pelipaikka': position,
                    'Kokonaispelimäärän muutos': total_game_change
                })

            if 'UTIL' in limits:
                positions_str = 'C/LW/RW/D'
                sim_player_name = f"SIM_{team}_UTIL"
                
                sim_player = pd.DataFrame([{
                    'name': sim_player_name,
                    'team': team,
                    'positions': positions_str
                }])
                sim_roster = pd.concat([roster_df, sim_player], ignore_index=True)
                _, simulated_games_dict = optimize_roster_advanced(schedule_df, sim_roster, limits, team_days)
                
                simulated_total = sum(simulated_games_dict.values())
                total_game_change = simulated_total - original_total

                impact_data.append({
                    'Joukkue': team,
                    'Pelipaikka': 'UTIL',
                    'Kokonaispelimäärän muutos': total_game_change
                })
                
    impact_df = pd.DataFrame(impact_data)
    
    results_by_position = {}
    for pos in positions_to_simulate + ['UTIL']:
        pos_df = impact_df[impact_df['Pelipaikka'] == pos].sort_values(by='Kokonaispelimäärän muutos', ascending=False)
        pos_df = pos_df[pos_df['Kokonaispelimäärän muutos'] > 0]
        if not pos_df.empty:
            results_by_position[pos] = pos_df.head(10).reset_index(drop=True)
    
    return results_by_position

# --- PÄÄSIVU: KÄYTTÖLIITTYMÄ ---
st.header("📊 Nykyinen rosteri")
if st.session_state['roster'].empty:
    st.warning("Lataa rosteri nähdäksesi pelaajat")
else:
    st.dataframe(st.session_state['roster'], use_container_width=True)
    
    st.subheader("Joukkueiden jakauma")
    team_counts = st.session_state['roster']['team'].value_counts()
    st.bar_chart(team_counts)

# --- PÄÄSIVU: OPTIMOINTI ---
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
        team_game_days = {}
        for _, row in schedule_filtered.iterrows():
            date = row['Date']
            for team in [row['Visitor'], row['Home']]:
                if team not in team_game_days:
                    team_game_days[team] = set()
                team_game_days[team].add(date)
        
        with st.spinner("Optimoidaan rosteria älykkäällä algoritmilla..."):
            daily_results, total_games = optimize_roster_advanced(
                schedule_filtered, 
                st.session_state['roster'], 
                pos_limits,
                team_game_days
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

---

### Päivittäinen pelipaikkasaatavuus 🗓️

st.subheader("Päivittäinen pelipaikkasaatavuus")
st.markdown("Tämä matriisi näyttää, onko kyseisenä päivänä **mahdollista sijoittaa** pelaaja, joka edustaa kyseistä pelipaikkaa (myös UTIL-paikan kautta).")

if st.session_state['schedule'].empty or st.session_state['roster'].empty:
    st.warning("Lataa sekä peliaikataulu että rosteri näyttääksesi matriisin.")
else:
    time_delta = end_date - start_date
    if time_delta.days > 30:
        st.info("Päivittäinen saatavuusmatriisi näytetään vain enintään 30 päivän aikavälillä.")
    else:
        # Määritä pelipaikat, jotka sisällytetään matriisiin (poissuljetaan UTIL)
        positions_to_show = ['C', 'LW', 'RW', 'D', 'G']
        availability_data = {pos: [] for pos in positions_to_show}
        dates = [start_date + timedelta(days=i) for i in range(time_delta.days + 1)]

        for date in dates:
            day_games = st.session_state['schedule'][st.session_state['schedule']['Date'].dt.date == date]
            
            # Hae kaikki pelaajat, joilla on peli kyseisenä päivänä
            players_playing_today = st.session_state['roster'][
                st.session_state['roster']['team'].isin(list(day_games['Visitor']) + list(day_games['Home']))
            ].copy() # Käytä kopioita välttääksesi SettingWithCopyWarning
            
            # Simuloi rosterin täyttöä tälle päivälle
            # Luo lista kaikista pelaajista, jotka voivat pelata tänään
            current_roster_for_day = players_playing_today.to_dict('records')
            
            # Lasketaan kuinka monta pelaajaa on jo sijoitettu kullekin pelipaikalle
            # ja kuinka monta pelaajaa on vapaana UTIL-paikalle.
            
            # Ensimmäinen läpikäynti: sijoita pelaajat ensisijaisille paikoille
            assigned_players = set()
            roster_slots = {pos: 0 for pos in pos_limits.keys()} # Laskee kuinka monta pelaajaa on jo sijoitettu
            
            # Listaa pelaajat, jotka ovat pelipaikkoja C, LW, RW, D, G
            primary_position_players = []
            for p in current_roster_for_day:
                p_positions = [pos.strip() for pos in p['positions'].split('/')]
                for primary_pos in positions_to_show: # Vain C, LW, RW, D, G
                    if primary_pos in p_positions:
                        primary_position_players.append({'name': p['name'], 'positions': p_positions})
                        break # Pelaaja lisätty jo yhteen pääpaikkaan
            
            # Yritä sijoittaa pelaajat ensisijaisiin paikkoihin
            players_placed_primarily = set()
            for p in primary_position_players:
                if len(players_placed_primarily) >= sum(pos_limits[pos] for pos in positions_to_show): # Tarkista rajat
                     break
                placed = False
                for pos in p['positions']:
                    if pos in pos_limits and pos != 'UTIL':
                        if roster_slots[pos] < pos_limits[pos]:
                            roster_slots[pos] += 1
                            players_placed_primarily.add(p['name'])
                            placed = True
                            break
                if not placed:
                    pass # Pelaaja ei mahtunut ensisijaisiin paikkoihin

            # Tarkista, mahtuuko tyypillinen pelaaja (ei UTIL)
            # Jos on vapaita paikkoja missä tahansa ensisijaisessa paikassa
            # tai jos UTIL-paikkoja on vapaana ja pelaaja on kenttäpelaaja
            space_available = False
            
            # Tarkista ensisijaiset paikat
            for pos in positions_to_show:
                if roster_slots[pos] < pos_limits[pos]:
                    space_available = True
                    break
            
            # Jos ensisijaiset paikat ovat täynnä, tarkista UTIL
            if not space_available and 'UTIL' in pos_limits and pos_limits['UTIL'] > 0:
                # Lasketaan pelaajat, jotka on sijoitettu ensisijaisiin paikkoihin
                # ja tarkistetaan onko vapaata UTIL-paikkaa
                players_in_primary_slots = roster_slots['C'] + roster_slots['LW'] + roster_slots['RW'] + roster_slots['D'] + roster_slots['G']
                # Huom:UTIL-paikan vapaiden paikkojen laskenta on monimutkaisempi, koska se voi ottaa eri tyyppisiä pelaajia.
                # Yksinkertaistettu lähestymistapa: Jos on pelaajia, jotka eivät mahtuneet ensisijaisiin paikkoihin,
                # ja UTIL-paikkoja on vapana, oletetaan että mahtuu.
                
                # Lasketaan pelaajat, jotka pelasi tänään MUTTA eivät mahtuneet ensisijaisiin paikkoihin.
                non_primary_players_count = len(players_playing_today) - len(players_placed_primarily)
                
                # Jos on pelaajia jotka jäi sijoittamatta ensisijaisiin paikkoihin
                # ja jos UTIL-paikkoja on vapaana (kokonaispelaajien määrä rosterissa < maksimi + UTIL)
                # Tässä käytetään nyt karkeampaa arviota: jos UTIL-paikkoja on
                # JA pelaajia on jäljellä, jotka eivät mahtuneet ensisijaisiin paikkoihin.
                
                # Simulaatio:
                # Otetaan kaikki pelaajat, jotka pelaavat tänään.
                # Yritetään ensin sijoittaa heidät ensisijaisiin paikkoihin.
                # Jos ensisijaiset paikat täyttyvät, tarkistetaan vapautuvat UTIL-paikat.
                
                # Yksinkertaistettu logiikka: Onko jokin pelipaikka täynnä?
                # Jos jokin pelipaikka (C, LW, RW, D, G) on täynnä, mutta UTIL-paikka on vapaana,
                # ja pelaaja voi pelata siellä, silloin mahtuu.
                
                # Uusi yksinkertaistettu tarkistus:
                # Onko ketään pelaajaa, jolle löytyisi paikka joko suoraan pelipaikalleen TAI UTIL-paikalle?
                
                potential_players_for_slots = []
                
                # Kerätään pelaajat, jotka pelaavat tänään ja heidän pelipaikkansa
                players_today_info = []
                for _, player in players_playing_today.iterrows():
                    player_positions = [p.strip() for p in player['positions'].split('/')]
                    players_today_info.append({'name': player['name'], 'positions': player_positions})

                # Lasketaan vapaat paikat jokaiselle pelipaikalle (mukaan lukien UTIL)
                filled_slots = {pos: 0 for pos in pos_limits.keys()}
                
                # Yritetään ensin täyttää ensisijaiset paikat
                current_assignment = {} # {pelaaja_nimi: sijoitettu_paikka}
                
                # Yritä sijoittaa ensisijaisille paikoille
                for p_info in players_today_info:
                    placed = False
                    for pos in p_info['positions']:
                        if pos != 'UTIL' and pos in pos_limits:
                            if filled_slots[pos] < pos_limits[pos]:
                                filled_slots[pos] += 1
                                current_assignment[p_info['name']] = pos
                                placed = True
                                break
                    if not placed:
                        # Jos pelaaja ei mahtunut ensisijaiselle paikalleen, säilytetään hänet vapaana
                        pass

                # Tarkistetaan UTIL-paikat, jos on vielä vapaita paikkoja
                # Lasketaan kuinka monta pelaajaa on jo sijoitettu
                total_assigned_primary = sum(filled_slots[pos] for pos in positions_to_show)
                
                # Mahtuuko pelaaja rosteriin?
                # Joko mahtuu ensisijaiseen paikkaan TAI UTIL-paikalle.
                
                can_any_player_fit = False
                
                # Tarkista, onko ensisijaisissa paikoissa vapaata tilaa
                for pos in positions_to_show:
                    if filled_slots[pos] < pos_limits[pos]:
                        can_any_player_fit = True
                        break
                
                # Jos ensisijaiset paikat ovat täynnä, tarkista UTIL
                if not can_any_player_fit and pos_limits.get('UTIL', 0) > 0:
                    # Kuinka monta pelaajaa on yhteensä, joilla on peli tänään?
                    num_players_playing_today = len(players_today_info)
                    # Kuinka monta paikkaa on yhteensä (ensisijaiset + UTIL)
                    total_available_slots = sum(pos_limits.values())
                    
                    # Jos pelaajia on vähemmän kuin paikkoja, silloin mahtuu
                    if num_players_playing_today <= total_available_slots:
                        can_any_player_fit = True
                    else:
                        # Jos pelaajia on enemmän kuin paikkoja, tarkistetaan mahtuuko pelaaja
                        # jos joku pelaaja voi siirtyä UTIL-paikalle
                        
                        # Kuinka monta paikkaa on jo täytetty ensisijaisilla paikoilla
                        currently_filled_primary = sum(filled_slots[pos] for pos in positions_to_show)
                        
                        # Kuinka monta UTIL-paikkaa on vapaana?
                        available_util_slots = pos_limits.get('UTIL', 0)
                        
                        # Jos pelaajia on yhteensä vähemmän kuin ensisijaiset + UTIL paikat
                        if num_players_playing_today < currently_filled_primary + available_util_slots:
                            can_any_player_fit = True
                        # Jos pelaajia on tasan paikkojen määrä, tarkistetaan voiko joku siirtyä UTIL-paikalle
                        elif num_players_playing_today == currently_filled_primary + available_util_slots:
                            # Tarkista, löytyykö pelaajia, jotka voisivat pelata UTIL-paikalla
                            # Tässä yksinkertaistetaan: jos pelaajia on yhteensä 'vähemmän tai yhtä paljon'
                            # kuin käytettävissä olevia paikkoja (ensisijaiset + UTIL), oletetaan mahtuvan.
                            can_any_player_fit = True

                # Jos yksikään pelaaja ei mahdu, tämä päivä on "täynnä"
                # Päivittäinen matriisi näyttää, voidaanko kyseisen pelipaikan pelaaja sijoittaa
                # Eli jos voidaan sijoittaa ainakin yksi pelaaja (joka edustaa tätä pelipaikkaa)
                
                # Tarkistetaan, onko mahdollista sijoittaa pelaaja tälle pelipaikalle
                # Tässä yritetään löytää edes yksi pelaaja, joka mahtuisi aktiiviseen rosteriin
                # joko suoralle paikalle tai UTIL-paikalle.
                
                possible_to_fit_player_for_pos = False
                
                # Käydään läpi kaikki pelaajat, joilla on peli tänään
                for p_info in players_today_info:
                    can_player_fit_directly = False
                    # Tarkista ensisijaiset paikat
                    for pos in p_info['positions']:
                        if pos != 'UTIL' and pos in pos_limits:
                            if filled_slots[pos] < pos_limits[pos]:
                                can_player_fit_directly = True
                                break
                    
                    # Jos ei mahtunut suoraan, tarkista UTIL
                    if not can_player_fit_directly:
                        # Onko UTIL-paikkoja vapaana?
                        # Lasketaan kuinka monta pelaajaa on sijoitettu (ensisijaiset + UTIL)
                        currently_assigned_count = sum(filled_slots.values()) # Tämä on hieman epätarkka, UTIL pitäisi laskea erikseen
                        
                        # Uudelleenlaskenta: Kuinka monta paikkaa on täytetty yhteensä
                        total_filled_slots = sum(filled_slots[p] for p in positions_to_show)
                        if 'UTIL' in pos_limits:
                            total_filled_slots += (len(players_today_info) - total_filled_slots) if len(players_today_info) > total_filled_slots else 0 # karkeasti arvio
                        
                        if pos_limits.get('UTIL', 0) > 0: # Onko UTIL-paikkoja edes olemassa
                             # Tarkista, mahtuuko pelaaja, jos ensisijaiset paikat ovat täynnä
                            if total_filled_slots < sum(pos_limits.values()): # Onko yhteensä paikkoja vapaana
                                possible_to_fit_player_for_pos = True
                                break # Riittää että yksi pelaaja mahtuu
                                
                    else: # Mahtui suoraan
                        possible_to_fit_player_for_pos = True
                        break # Riittää että yksi pelaaja mahtuu
                        
                # Tallenna tulos matriisiin
                availability_data[pos].append(possible_to_fit_player_for_pos)
                
        availability_df = pd.DataFrame(availability_data, index=dates)
        
        def color_cells(val):
            # Vihreä jos True (mahtuu), punainen jos False (ei mahdu)
            color = 'green' if val else 'red'
            return f'background-color: {color}'

        st.dataframe(
            availability_df.style.applymap(color_cells),
            use_container_width=True
        )

---

### Simuloitu vaikutus 🔮

st.header("🔮 Simuloi uuden pelaajan vaikutus")
if not st.session_state['roster'].empty and 'schedule' in st.session_state and not st.session_state['schedule'].empty and start_date <= end_date:
    st.subheader("Lisää uusi pelaaja")
    col1, col2, col3 = st.columns(3)
    
    with col1:
        sim_name = st.text_input("Pelaajan nimi", key="sim_name")
    with col2:
        sim_team = st.text_input("Joukkue", key="sim_team")
    with col3:
        sim_positions = st.text_input("Pelipaikat (esim. C/LW)", key="sim_positions")
    
    remove_sim_player = st.selectbox(
        "Pelaaja poistettavaksi rosterista (valinnainen)",
        [""] + list(st.session_state['roster']['name'])
    )

    if st.button("Suorita simulaatio"):
        if sim_name and sim_team and sim_positions:
            
            if remove_sim_player:
                sim_roster = st.session_state['roster'][
                    st.session_state['roster']['name'] != remove_sim_player
                ].copy()
            else:
                sim_roster = st.session_state['roster'].copy()
            
            new_player_info = {
                'name': sim_name,
                'team': sim_team,
                'positions': sim_positions
            }
            
            sim_roster = pd.concat([
                sim_roster,
                pd.DataFrame([new_player_info])
            ], ignore_index=True)

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

            with st.spinner("Lasketaan alkuperäistä kokonaispelimäärää..."):
                _, original_total_games_dict = optimize_roster_advanced(
                    schedule_filtered,
                    st.session_state['roster'],
                    pos_limits,
                    team_game_days
                )
                original_total = sum(original_total_games_dict.values())
            
            with st.spinner("Lasketaan uuden pelaajan vaikutusta..."):
                _, new_total_games_dict = optimize_roster_advanced(
                    schedule_filtered,
                    sim_roster,
                    pos_limits,
                    team_game_days
                )
                new_total = sum(new_total_games_dict.values())
            
            player_impact_days = new_total_games_dict.get(sim_name, 0)

            st.subheader(f"Simuloinnin tulos: {sim_name} ({sim_team})")
            
            col_a, col_b, col_c = st.columns(3)
            
            col_a.metric(
                "Alkuperäinen kokonaispelimäärä",
                original_total
            )
            col_b.metric(
                "Uusi kokonaispelimäärä",
                new_total
            )
            
            change = new_total - original_total
            col_c.metric(
                "Muutos",
                f"{change}"
            )
            
            st.write(f"Uusi pelaaja, **{sim_name}**, lisäsi kokonaispelimäärää {change} pelillä.")
            st.write(f"Hän pelasi itse {player_impact_days} peliä tällä aikavälillä.")
        else:
            st.warning("Syötä kaikki pelaajan tiedot suorittaaksesi simulaation.")

---

### Joukkueanalyysi 🔍

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
        team_game_days = {}
        for _, row in schedule_filtered.iterrows():
            date = row['Date']
            for team in [row['Visitor'], row['Home']]:
                if team not in team_game_days:
                    team_game_days[team] = set()
                team_game_days[team].add(date)

        if st.button("Suorita joukkueanalyysi"):
            st.session_state['team_impact_results'] = simulate_team_impact(
                schedule_filtered,
                st.session_state['roster'],
                pos_limits,
                team_game_days
            )
        
        if st.session_state['team_impact_results'] is not None:
            for pos, df in st.session_state['team_impact_results'].items():
                st.subheader(f"Top 10 joukkuetta pelipaikalle: {pos}")
                df.columns = ['Joukkue', 'Pelipaikka', 'Kokonaispelimäärän muutos']
                st.dataframe(df, use_container_width=True)
