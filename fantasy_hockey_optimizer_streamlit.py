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

# --- SIVUPALKKI: TIEDOSTOJEN LATAUS ---
st.sidebar.header("📁 Tiedostojen lataus")

if st.sidebar.button("Tyhjennä kaikki välimuisti"):
    st.cache_data.clear()
    st.session_state['schedule'] = pd.DataFrame()
    st.session_state['roster'] = pd.DataFrame(columns=['name', 'team', 'positions', 'fantasy_points_avg'])
    st.session_state['opponent_roster'] = pd.DataFrame(columns=['name', 'team', 'positions', 'fantasy_points_avg'])
    st.sidebar.success("Välimuisti tyhjennetty!")
    st.rerun()

def load_csv_file(file_path, name, expected_cols):
    file_exists = False
    try:
        df = pd.read_csv(file_path)
        if 'fantasy_points_avg' not in df.columns:
            df['fantasy_points_avg'] = 0.0
        df['fantasy_points_avg'] = pd.to_numeric(df['fantasy_points_avg'], errors='coerce').fillna(0)
        file_exists = True
    except FileNotFoundError:
        df = pd.DataFrame()

    if file_exists and not st.sidebar.button(f"Lataa uusi {name}"):
        st.sidebar.success(f"{name} ladattu automaattisesti tallennetusta tiedostosta!")
        return df
    else:
        uploaded_file = st.sidebar.file_uploader(
            f"Lataa {name} (CSV)",
            type=["csv"],
            key=f"file_uploader_{name}"
        )
        if uploaded_file is not None:
            try:
                df = pd.read_csv(uploaded_file)
                if not df.empty and all(col in df.columns for col in expected_cols):
                    if 'fantasy_points_avg' not in df.columns:
                        df['fantasy_points_avg'] = 0.0
                    df['fantasy_points_avg'] = pd.to_numeric(df['fantasy_points_avg'], errors='coerce').fillna(0)
                    df.to_csv(file_path, index=False)
                    st.sidebar.success(f"{name} ladattu ja tallennettu!")
                    st.rerun()
                else:
                    st.sidebar.error(f"Tiedoston tulee sisältää sarakkeet: {', '.join(expected_cols)}")
            except Exception as e:
                st.sidebar.error(f"Virhe tiedoston lukemisessa: {str(e)}")
        return pd.DataFrame(columns=expected_cols)

st.session_state['schedule'] = load_csv_file(SCHEDULE_FILE, "NHL-peliaikataulu", ['Date', 'Visitor', 'Home'])
if not st.session_state['schedule'].empty:
    st.session_state['schedule']['Date'] = pd.to_datetime(st.session_state['schedule']['Date'])

st.session_state['roster'] = load_csv_file(ROSTER_FILE, "rosteri", ['name', 'team', 'positions', 'fantasy_points_avg'])
st.session_state['opponent_roster'] = load_csv_file(OPPONENT_ROSTER_FILE, "vastustajan rosteri", ['name', 'team', 'positions', 'fantasy_points_avg'])


# --- SIVUPALKKI: ROSTERIN HALLINTA ---
st.sidebar.header("👥 Rosterin hallinta")

if st.sidebar.button("Tyhjennä oma rosteri"):
    st.session_state['roster'] = pd.DataFrame(columns=['name', 'team', 'positions', 'fantasy_points_avg'])
    if os.path.exists(ROSTER_FILE):
        os.remove(ROSTER_FILE)
    st.sidebar.success("Rosteri tyhjennetty!")
    st.rerun()

if not st.session_state['roster'].empty:
    st.sidebar.subheader("Nykyinen rosteri")
    st.sidebar.dataframe(st.session_state['roster'], use_container_width=True)
    
    remove_player = st.sidebar.selectbox(
        "Poista pelaaja", 
        [""] + list(st.session_state['roster']['name'])
    )
    if st.sidebar.button("Poista valittu pelaaja") and remove_player:
        st.session_state['roster'] = st.session_state['roster'][
            st.session_state['roster']['name'] != remove_player
        ]
        if 'fantasy_points_avg' in st.session_state['roster'].columns:
            st.session_state['roster'].to_csv(ROSTER_FILE, index=False)
        else:
            st.session_state['roster'].to_csv(ROSTER_FILE, index=False, columns=['name', 'team', 'positions'])
        st.sidebar.success(f"Pelaaja {remove_player} poistettu!")
        st.rerun()
    
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
start_date = st.sidebar.date_input("Alkupäivä", today)
end_date = st.sidebar.date_input("Loppupäivä", today + timedelta(days=6))

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

# --- FUNKTIOT ---
def optimize_roster_advanced(schedule_df, roster_df, limits, num_attempts=200):
    players_info = {}
    for _, player in roster_df.iterrows():
        positions_str = player['positions']
        if pd.isna(positions_str):
            positions_list = []
        elif isinstance(positions_str, str):
            positions_list = [p.strip() for p in positions_str.split('/')]
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
        
        available_players = []
        for _, game in day_games.iterrows():
            for team in [game['Visitor'], game['Home']]:
                for player_name, info in players_info.items():
                    if info['team'] == team and player_name not in [p['name'] for p in available_players]:
                        available_players.append({
                            'name': player_name,
                            'team': team,
                            'positions': info['positions'],
                            'fpa': info['fpa']
                        })
        
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
                
                bench_copy = bench.copy()
                bench_sorted = sorted(bench_copy, key=lambda name: players_info[name]['fpa'], reverse=True)
                
                for bench_player_name in bench_sorted:
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

            current_fp = 0
            for pos, players in active.items():
                for player_name in players:
                    current_fp += players_info[player_name]['fpa']

            if current_fp > best_assignment_fp:
                best_assignment_fp = current_fp
                best_assignment = {
                    'active': active.copy(),
                    'bench': bench.copy()
                }
            
            elif current_fp == best_assignment_fp:
                current_active_count = sum(len(players) for players in active.values())
                best_active_count = sum(len(players) for players in best_assignment['active'].values())
                if current_active_count > best_active_count:
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
            'Bench': final_bench,
            'Daily_FP': best_assignment_fp
        })
        
        if best_assignment['active'] is not None:
            for pos, players in best_assignment['active'].items():
                for player_name in players:
                    player_games[player_name] += 1
    
    total_fantasy_points = 0
    for player_name, games_played in player_games.items():
        if player_name in players_info:
            fpa = players_info[player_name]['fpa']
            total_fantasy_points += games_played * fpa
    
    total_active_games = sum(player_games.values())

    return daily_results, player_games, total_fantasy_points, total_active_games

def simulate_team_impact(schedule_df, roster_df, limits):
    players_info = {}
    for _, player in roster_df.iterrows():
        positions_str = player['positions']
        if pd.isna(positions_str):
            positions_list = []
        elif isinstance(positions_str, str):
            positions_list = [p.strip() for p in positions_str.split('/')]
        else:
            positions_list = []
        players_info[player['name']] = {
            'team': player['team'],
            'positions': positions_list,
            'fpa': player.get('fantasy_points_avg', 0)
        }

    unique_teams = pd.unique(schedule_df[['Visitor', 'Home']].values.ravel('K'))
    impact_data = defaultdict(lambda: defaultdict(int))
    
    original_total_games_dict = {}
    if not roster_df.empty:
        _, original_total_games_dict, _, _ = optimize_roster_advanced(schedule_df, roster_df, limits)
    original_total_games_by_pos = defaultdict(int)
    for player_name, games in original_total_games_dict.items():
        player_info = players_info.get(player_name)
        if player_info and player_info['positions']:
            player_pos = player_info['positions'][0]
            original_total_games_by_pos[player_pos] += games

    for team in unique_teams:
        for pos in ['C', 'LW', 'RW', 'D', 'G']:
            temp_roster = roster_df.copy()
            dummy_player = pd.DataFrame([
                {'name': 'DUMMY_PLAYER', 'team': team, 'positions': pos, 'fantasy_points_avg': 0}
            ])
            temp_roster = pd.concat([temp_roster, dummy_player], ignore_index=True)

            _, new_total_games_dict, _, _ = optimize_roster_advanced(schedule_df, temp_roster, limits)
            
            new_total_games_by_pos = defaultdict(int)
            for player_name, games in new_total_games_dict.items():
                player_info = players_info.get(player_name)
                if player_info and player_info['positions']:
                    player_pos = player_info['positions'][0]
                    new_total_games_by_pos[player_pos] += games
                elif player_name == 'DUMMY_PLAYER':
                    new_total_games_by_pos[pos] += games

            impact = new_total_games_by_pos[pos] - original_total_games_by_pos[pos]
            impact_data[team][pos] = impact
            
    pos_dfs = {}
    for pos in ['C', 'LW', 'RW', 'D', 'G']:
        rows = []
        for team, data in impact_data.items():
            rows.append({'Joukkue': team, 'Pelipaikka': pos, 'Simuloitu pelimäärän muutos': data.get(pos, 0)})
        
        pos_df = pd.DataFrame(rows).sort_values(by='Simuloitu pelimäärän muutos', ascending=False)
        pos_dfs[pos] = pos_df
        
    return pos_dfs

# --- PÄÄSIVU: VÄLILEHDET ---
tab1, tab2, tab3 = st.tabs(["📊 Pääanalyysi", "🔮 Pelaajavertailu", "🆚 Joukkuevertailu"])

with tab1:
    st.header("📊 Pääanalyysi")

    if st.session_state['roster'].empty:
        st.warning("Lataa rosteri nähdäksesi pelaajat")
    else:
        st.dataframe(st.session_state['roster'], use_container_width=True)
        st.subheader("Joukkueiden jakauma")
        team_counts = st.session_state['roster']['team'].value_counts()
        st.bar_chart(team_counts)

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
            
            st.subheader("Pelipaikkojen täyttöaste")
            filled_positions_data = []
            for result in daily_results:
                date_str = result['Date'].strftime('%b %d')
                row = {'Päivä': date_str}
                for pos in ['C', 'LW', 'RW', 'D', 'G', 'UTIL']:
                    filled = len(result['Active'].get(pos, []))
                    total = pos_limits[pos]
                    row[pos] = f"{filled}/{total}"
                filled_positions_data.append(row)
            filled_positions_df = pd.DataFrame(filled_positions_data)
            st.dataframe(filled_positions_df, use_container_width=True)

            st.subheader("Päivittäisten pelien yhteenveto")
            summary_data = []
            for result in daily_results:
                num_active = sum(len(v) for v in result['Active'].values())
                num_bench = len(result['Bench'])
                summary_data.append({
                    'Päivä': result['Date'],
                    'Aktiivisia pelaajia': num_active,
                    'Penkkipelaajia': num_bench,
                    'Ennakoidut FP': result['Daily_FP']
                })
            summary_df = pd.DataFrame(summary_data)
            st.dataframe(summary_df, use_container_width=True)
            
            with st.expander("Näytä päivittäiset aktiiviset rosterit"):
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
                
                detailed_df = pd.DataFrame(daily_data)
                st.dataframe(detailed_df, use_container_width=True)

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
    st.header("🔮 Pelaajavertailu")
    st.markdown("Vertaa kahden pelaajan vaikutusta rosteriisi.")
    
    if not st.session_state['roster'].empty and 'schedule' in st.session_state and not st.session_state['schedule'].empty and start_date <= end_date:
        
        st.subheader("Vertaa kahta pelaajaa")
        
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

        if st.button("Suorita vertailu", key="player_compare_button"):
            if sim_name_A and sim_team_A and sim_positions_A and sim_name_B and sim_team_B and sim_positions_B:
                
                original_roster_copy = st.session_state['roster'].copy()
                if 'fantasy_points_avg' not in original_roster_copy.columns:
                    original_roster_copy['fantasy_points_avg'] = 0.0
                
                temp_roster = original_roster_copy.copy()
                if remove_sim_player:
                    temp_roster = temp_roster[temp_roster['name'] != remove_sim_player].copy()
                
                new_player_A = {'name': sim_name_A, 'team': sim_team_A, 'positions': sim_positions_A, 'fantasy_points_avg': sim_fpa_A}
                sim_roster_A = pd.concat([temp_roster, pd.DataFrame([new_player_A])], ignore_index=True)

                new_player_B = {'name': sim_name_B, 'team': sim_team_B, 'positions': sim_positions_B, 'fantasy_points_avg': sim_fpa_B}
                sim_roster_B = pd.concat([temp_roster, pd.DataFrame([new_player_B])], ignore_index=True)
                
                schedule_filtered = st.session_state['schedule'][
                    (st.session_state['schedule']['Date'] >= pd.to_datetime(start_date)) &
                    (st.session_state['schedule']['Date'] <= pd.to_datetime(end_date))
                ]
                
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
    else:
        st.info("Lataa rosteri ja peliaikataulu, jotta voit vertailla pelaajia.")

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
            if st.button("Suorita joukkueanalyysi", key="team_analyze_button"):
                st.session_state['team_impact_results'] = simulate_team_impact(
                    schedule_filtered,
                    st.session_state['roster'],
                    pos_limits
                )
            
            if st.session_state['team_impact_results'] is not None:
                for pos, df in st.session_state['team_impact_results'].items():
                    st.subheader(f"Top 10 joukkuetta pelipaikalle: {pos}")
                    st.dataframe(df, use_container_width=True)

with tab3:
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
                    
                    # Lasketaan oma rosteri
                    _, my_games_dict, my_fp, my_total_games = optimize_roster_advanced(
                        schedule_filtered, st.session_state['roster'], pos_limits
                    )
                    
                    # Lasketaan vastustajan rosteri
                    _, opponent_games_dict, opponent_fp, opponent_total_games = optimize_roster_advanced(
                        schedule_filtered, st.session_state['opponent_roster'], pos_limits
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
