import streamlit as st
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from collections import defaultdict

# Set page configuration
st.set_page_config(
    page_title="Fantasy Hockey Optimizer Pro",
    page_icon="🏒",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Title and Introduction
st.title("🏒 Fantasy Hockey Optimizer Pro")
st.markdown("""
**Optimoi fantasy hockey rosterisi NHL-kauden aikataulun perusteella!**
- Kukin pelaaja voi olla vain yhdellä pelipaikalla per päivä
- Pelimäärät kertyvät vain peleistä, joissa pelaajan joukkue on mukana
- Älykäs optimointi huomioi pelaajien monipuolisuuden ja vaihtoehtoiset sijoittelut
- Näet tarkasti ketkä pelaajat ovat aktiivisia ja ketkä penkillä
""")

# --- SIDEBAR: FILE UPLOAD ---
st.sidebar.header("📁 Tiedostojen lataus")

# Schedule upload
schedule_file = st.sidebar.file_uploader(
    "Lataa NHL-peliaikataulu (CSV)",
    type=["csv"],
    help="CSV-tiedoston tulee sisältää sarakkeet: Date, Visitor, Home"
)

# Initialize session state variables
if 'schedule' not in st.session_state:
    st.session_state['schedule'] = pd.DataFrame()
if 'roster' not in st.session_state:
    st.session_state['roster'] = pd.DataFrame(columns=['name', 'team', 'positions'])

# Check if file is uploaded first
if schedule_file is not None:
    try:
        schedule = pd.read_csv(schedule_file)
        # Check if DataFrame is not empty and contains required columns
        if not schedule.empty and all(col in schedule.columns for col in ['Date', 'Visitor', 'Home']):
            schedule['Date'] = pd.to_datetime(schedule['Date'])
            st.session_state['schedule'] = schedule
            st.sidebar.success("Peliaikataulu ladattu!")
        else:
            st.sidebar.error("Peliaikataulun CSV-tiedoston tulee sisältää sarakkeet: Date, Visitor, Home")
    except Exception as e:
        st.sidebar.error(f"Virhe peliaikataulun lukemisessa: {str(e)}")

# Roster upload
roster_file = st.sidebar.file_uploader(
    "Lataa rosteri (CSV)",
    type=["csv"],
    help="CSV-tiedoston tulee sisältää sarakkeet: name, team, positions"
)

# Check if file is uploaded first
if roster_file is not None:
    try:
        roster = pd.read_csv(roster_file)
        # Check if DataFrame is not empty and contains required columns
        if not roster.empty and all(col in roster.columns for col in ['name', 'team', 'positions']):
            st.session_state['roster'] = roster
            st.sidebar.success("Rosteri ladattu!")
        else:
            st.sidebar.error("Rosterin CSV-tiedoston tulee sisältää sarakkeet: name, team, positions")
    except Exception as e:
        st.sidebar.error(f"Virhe rosterin lukemisessa: {str(e)}")

# --- SIDEBAR: ROSTER MANAGEMENT ---
st.sidebar.header("👥 Rosterin hallinta")

# Display current roster
if not st.session_state['roster'].empty:
    st.sidebar.subheader("Nykyinen rosteri")
    st.sidebar.dataframe(st.session_state['roster'])

    # Remove player
    remove_player = st.sidebar.selectbox(
        "Poista pelaaja",
        [""] + list(st.session_state['roster']['name'])
    )
    if st.sidebar.button("Poista valittu pelaaja") and remove_player:
        st.session_state['roster'] = st.session_state['roster'][
            st.session_state['roster']['name'] != remove_player
        ]
        st.sidebar.success(f"Pelaaja {remove_player} poistettu!")
        st.rerun()

    # Add player
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
            st.sidebar.success(f"Pelaaja {new_name} lisätty!")
            st.rerun()

# --- SIDEBAR: SETTINGS ---
st.sidebar.header("⚙️ Asetukset")

# Date selection
st.sidebar.subheader("Aikaväli")
today = datetime.now().date()
start_date = st.sidebar.date_input("Alkupäivä", today - timedelta(days=30))
end_date = st.sidebar.date_input("Loppupäivä", today)

# Check if dates are sensible
if start_date > end_date:
    st.sidebar.error("Aloituspäivä ei voi olla loppupäivän jälkeen")

# Position limits
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

# --- MAIN PAGE: ROSTER DISPLAY ---
st.header("📊 Nykyinen rosteri")
if st.session_state['roster'].empty:
    st.warning("Lataa rosteri nähdäksesi pelaajat")
else:
    st.dataframe(st.session_state['roster'], use_container_width=True)

    # Team distribution
    st.subheader("Joukkueiden jakauma")
    team_counts = st.session_state['roster']['team'].value_counts()
    st.bar_chart(team_counts)

# --- MAIN PAGE: OPTIMIZATION ---
st.header("🚀 Rosterin optimointi")

# Check if both files are loaded and dates are okay
if st.session_state['schedule'].empty or st.session_state['roster'].empty:
    st.warning("Lataa sekä peliaikataulu että rosteri aloittaaksesi optimoinnin")
elif start_date > end_date:
    st.warning("Korjaa päivämääräväli niin että aloituspäivä on ennen loppupäivää")
else:
    # Filter schedule for the selected date range
    schedule_filtered = st.session_state['schedule'][
        (st.session_state['schedule']['Date'] >= pd.to_datetime(start_date)) &
        (st.session_state['schedule']['Date'] <= pd.to_datetime(end_date))
    ]

    if schedule_filtered.empty:
        st.warning("Ei pelejä valitulla aikavälillä")
    else:
        # Create team game days
        team_game_days = {}
        for _, row in schedule_filtered.iterrows():
            date = row['Date']
            for team in [row['Visitor'], row['Home']]:
                if team not in team_game_days:
                    team_game_days[team] = set()
                team_game_days[team].add(date)

        # Fully revised optimization function for multi-position players
        def optimize_roster_advanced(schedule_df, roster_df, limits, team_days, num_attempts=200):
            # Create player information
            players_info = {}
            for _, player in roster_df.iterrows():
                # Handle potential NaN values and ensure positions is a list
                positions_str = player['positions']
                if pd.isna(positions_str):
                    positions_list = []
                elif isinstance(positions_str, str):
                    positions_list = [p.strip() for p in positions_str.split('/')]
                else:
                    positions_list = positions_str  # Assume it's already a list

                players_info[player['name']] = {
                    'team': player['team'],
                    'positions': positions_list
                }

            # Group games by day
            daily_results = []
            player_games = {name: 0 for name in players_info.keys()}

            # Iterate through each day
            for date in sorted(schedule_df['Date'].unique()):
                # Get games for the day
                day_games = schedule_df[schedule_df['Date'] == date]

                # Get players whose team has a game today
                available_players = []
                for _, game in day_games.iterrows():
                    for team in [game['Visitor'], game['Home']]:
                        for player_name, info in players_info.items():
                            if info['team'] == team and player_name not in [p['name'] for p in available_players]:
                                available_players.append({
                                    'name': player_name,
                                    'team': team,
                                    'positions': info['positions']  # This is now a list
                                })

                # Multiple attempts to find the best placement
                best_assignment = None
                max_active = 0

                for attempt in range(num_attempts):
                    # Shuffle players randomly
                    shuffled_players = available_players.copy()
                    np.random.shuffle(shuffled_players)

                    # Initialize positions
                    active = {
                        'C': [], 'LW': [], 'RW': [], 'D': [], 'G': [], 'UTIL': []
                    }
                    bench = []

                    # Phase 1: Place players in primary positions
                    for player_info in shuffled_players:
                        placed = False
                        player_name = player_info['name']
                        positions_list = player_info['positions'] # This is already a list

                        # Try to place in one of the player's positions
                        for pos in positions_list:
                            if pos in limits and len(active[pos]) < limits[pos]:
                                active[pos].append(player_name)
                                placed = True
                                break

                        # If not placed in a specific position, try UTIL
                        if not placed and len(active['UTIL']) < limits['UTIL']:
                            # Check if player fits UTIL (forward or defenseman)
                            if any(pos in ['C', 'LW', 'RW', 'D'] for pos in positions_list):
                                active['UTIL'].append(player_name)
                                placed = True

                        # If still not placed, add to bench
                        if not placed:
                            bench.append(player_name)

                    # Phase 2: Try to improve placement by swapping player positions
                    all_players = []
                    for pos, players in active.items():
                        for player_name in players:
                            player_positions = players_info[player_name]['positions']
                            all_players.append({
                                'name': player_name,
                                'positions': player_positions,
                                'current_pos': pos,
                                'active': True
                            })

                    for player_name in bench:
                        player_positions = players_info[player_name]['positions']
                        all_players.append({
                            'name': player_name,
                            'positions': player_positions,
                            'current_pos': None,
                            'active': False
                        })

                    # Try to improve placement
                    improved = True
                    while improved:
                        improved = False

                        # Iterate through all inactive players
                        for bench_player in [p for p in all_players if not p['active']]:
                            bench_positions = bench_player['positions']

                            # Iterate through all active players
                            for active_player in [p for p in all_players if p['active']]:
                                active_positions = active_player['positions']

                                # Check if bench player can replace active player
                                if active_player['current_pos'] in bench_positions:
                                    # Check if active player can move to another position
                                    for new_pos in active_positions:
                                        if new_pos != active_player['current_pos'] and new_pos in limits and len(active[new_pos]) < limits[new_pos]:
                                            # Swap is possible!
                                            # Remove active player from current position
                                            active[active_player['current_pos']].remove(active_player['name'])
                                            # Add them to the new position
                                            active[new_pos].append(active_player['name'])
                                            # Add bench player to the freed position
                                            active[active_player['current_pos']].append(bench_player['name'])
                                            # Update player states
                                            active_player['current_pos'] = new_pos
                                            bench_player['active'] = True
                                            bench_player['current_pos'] = active_player['current_pos']
                                            # Remove player from bench
                                            if bench_player['name'] in bench:
                                                bench.remove(bench_player['name'])
                                            improved = True
                                            break
                                        if improved:
                                            break
                                    if improved:
                                        break
                                if improved:
                                    break

                    # Phase 3: Try one more time to place players remaining on the bench
                    for player_name in bench.copy():  # Use a copy as we're modifying the list
                        placed = False

                        positions_list = players_info[player_name]['positions']

                        # Try to place in one of the player's positions
                        for pos in positions_list:
                            if pos in limits and len(active[pos]) < limits[pos]:
                                active[pos].append(player_name)
                                bench.remove(player_name)
                                placed = True
                                break

                        # If not placed in a specific position, try UTIL
                        if not placed and len(active['UTIL']) < limits['UTIL']:
                            if any(pos in ['C', 'LW', 'RW', 'D'] for pos in positions_list):
                                active['UTIL'].append(player_name)
                                bench.remove(player_name)
                                placed = True

                    # Phase 4: Multi-position player optimization - NEW IMPROVEMENT
                    for pos_name in ['C', 'LW', 'RW', 'D', 'G']:
                        for player_name in active[pos_name].copy():  # Use a copy as we're modifying the list
                            player_positions = players_info[player_name]['positions']

                            if len(player_positions) > 1:
                                for other_pos in player_positions:
                                    if other_pos != pos_name and other_pos in limits and len(active[other_pos]) < limits[other_pos]:
                                        # Check if there's a player on the bench who can fill this spot
                                        for bench_player_name in bench.copy():
                                            bench_player_positions = players_info[bench_player_name]['positions']

                                            # If bench player can play in this position
                                            if pos_name in bench_player_positions:
                                                # Move multi-position player to another spot
                                                active[pos_name].remove(player_name)
                                                active[other_pos].append(player_name)

                                                # Move bench player to active roster
                                                active[pos_name].append(bench_player_name)
                                                bench.remove(bench_player_name)

                                                # Update all_players list
                                                for p in all_players:
                                                    if p['name'] == player_name:
                                                        p['current_pos'] = other_pos
                                                    elif p['name'] == bench_player_name:
                                                        p['active'] = True
                                                        p['current_pos'] = pos_name
                                                break
                                            if player_name in active[pos_name]: # Check if player was moved
                                                break
                                        if player_name in active[pos_name]: # Check if player was moved
                                            break

                    # Calculate the number of active players
                    total_active = sum(len(players) for players in active.values())

                    # Save the best assignment
                    if total_active > max_active:
                        max_active = total_active
                        best_assignment = {
                            'active': active.copy(),
                            'bench': bench.copy()
                        }

                # Ensure best_assignment is not None
                if best_assignment is None:
                    best_assignment = {
                        'active': {
                            'C': [], 'LW': [], 'RW': [], 'D': [], 'G': [], 'UTIL': []
                        },
                        'bench': [p['name'] for p in available_players]
                    }

                # Ensure all players are accounted for
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

                # Update player game counts
                if best_assignment['active'] is not None:
                    for pos, players in best_assignment['active'].items():
                        for player_name in players:
                            player_games[player_name] += 1

            return daily_results, player_games

        # Run optimization
        with st.spinner("Optimoidaan rosteria älykkäällä algoritmilla..."):
            daily_results, total_games = optimize_roster_advanced(
                schedule_filtered,
                st.session_state['roster'],
                pos_limits,
                team_game_days
            )

        # Display results
        st.subheader("Päivittäiset aktiiviset rosterit")

        # Create daily results DataFrame
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

        # Game count summary
        st.subheader("Pelaajien kokonaispelimäärät")

        games_df = pd.DataFrame({
            'Pelaaja': list(total_games.keys()),
            'Pelit': list(total_games.values())
        }).sort_values('Pelit', ascending=False)

        st.dataframe(games_df, use_container_width=True)

        # Download button
        csv = games_df.to_csv(index=False).encode('utf-8')
        st.download_button(
            "Lataa pelimäärät CSV-muodossa",
            data=csv,
            file_name='pelimäärät.csv',
            mime='text/csv'
        )

        # Visualizations
        st.subheader("📈 Analyysit")

        col1, col2 = st.columns(2)

        with col1:
            # Top 10 players
            top_players = games_df.head(10)
            st.write("Top 10 eniten pelanneet pelaajat")
            st.dataframe(top_players)

        with col2:
            # Position distribution
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

# --- SIMULATION ---
st.header("🔮 Simuloi uuden pelaajan vaikutus")

if not st.session_state['roster'].empty and not schedule_filtered.empty and start_date <= end_date:
    st.subheader("Lisää uusi pelaaja")

    col1, col2, col3 = st.columns(3)

    with col1:
        sim_name = st.text_input("Pelaajan nimi", key="sim_name")
    with col2:
        sim_team = st.text_input("Joukkue", key="sim_team")
    with col3:
        sim_positions = st.text_input("Pelipaikat (esim. C/LW)", key="sim_positions")

    if st.button("Simuloi pelaajan lisääminen"):
        if sim_name and sim_team and sim_positions:
            # Create new player info
            new_player_info = {
                'name': sim_name,
                'team': sim_team,
                'positions': sim_positions
            }

            # Run corrected simulation
            with st.spinner("Lasketaan uuden pelaajan vaikutusta..."):
                # CALCULATE ORIGINAL STATE (without new player)
                original_total_games = 0
                original_daily_active_counts = {} # To store daily active counts for original roster

                for date in sorted(schedule_filtered['Date'].unique()):
                    day_games = schedule_filtered[schedule_filtered['Date'] == date]
                    daily_active_count = 0
                    if not day_games.empty:
                        # Create daily team game days
                        day_team_days = {}
                        for _, game in day_games.iterrows():
                            for team in [game['Visitor'], game['Home']]:
                                if team not in day_team_days:
                                    day_team_days[team] = set()
                                day_team_days[team].add(game['Date'])

                        daily_results_original, _ = optimize_roster_advanced(
                            schedule_filtered[schedule_filtered['Date'] == date],
                            st.session_state['roster'],
                            pos_limits,
                            day_team_days
                        )
                        if isinstance(daily_results_original, list):
                            for result in daily_results_original:
                                if isinstance(result, dict) and 'Active' in result and result['Active'] is not None:
                                    daily_active_count += sum(len(players) for players in result['Active'].values())
                    original_daily_active_counts[date.date()] = daily_active_count
                    original_total_games += daily_active_count

                # CALCULATE NEW STATE (with new player)
                new_roster = pd.concat([
                    st.session_state['roster'],
                    pd.DataFrame([new_player_info])
                ], ignore_index=True)

                new_total_games = 0
                player_impact_days = 0  # Days the new player is active
                new_daily_active_counts = {} # To store daily active counts for new roster

                for date in sorted(schedule_filtered['Date'].unique()):
                    day_games = schedule_filtered[schedule_filtered['Date'] == date]
                    daily_active_count_with = 0
                    new_player_active_today = False

                    if not day_games.empty:
                        # Check if new player's team is playing today
                        new_player_team_playing = sim_team in day_games[['Visitor', 'Home']].values

                        if new_player_team_playing:
                            # Create daily team game days
                            day_team_days = {}
                            for _, game in day_games.iterrows():
                                for team in [game['Visitor'], game['Home']]:
                                    if team not in day_team_days:
                                        day_team_days[team] = set()
                                    day_team_days[team].add(game['Date'])

                            daily_results_with, _ = optimize_roster_advanced(
                                schedule_filtered[schedule_filtered['Date'] == date],
                                new_roster,
                                pos_limits,
                                day_team_days
                            )

                            if isinstance(daily_results_with, list):
                                for result in daily_results_with:
                                    if isinstance(result, dict) and 'Active' in result and result['Active'] is not None:
                                        daily_active_count_with += sum(len(players) for players in result['Active'].values())
                                        # Check if the new player is in the active list for this day
                                        if sim_name in [p for players in result['Active'].values() for p in players]:
                                            new_player_active_today = True

                    new_daily_active_counts[date.date()] = daily_active_count_with
                    if new_player_active_today:
                        player_impact_days += 1
                    new_total_games += daily_active_count_with


                # Calculate the impact
                games_increase = new_total_games - original_total_games
                st.subheader("Simulaation tulokset")

                st.markdown(f"**Alkuperäinen kokonaispelimäärä:** {original_total_games}")
                st.markdown(f"**Kokonaispelimäärä uudella pelaajalla:** {new_total_games}")
                st.markdown(f"**Pelimäärän lisäys:** {games_increase}")
                st.markdown(f"**Päiviä, jolloin uusi pelaaja on aktiivinen:** {player_impact_days}")

                if games_increase > 0:
                    st.success(f"Uuden pelaajan lisääminen **lisäsi** rosterisi kokonaispelimäärää yhteensä **{games_increase}** pelillä.")
                elif games_increase < 0:
                    st.warning(f"Uuden pelaajan lisääminen **vähensi** rosterisi kokonaispelimäärää yhteensä **{abs(games_increase)}** pelillä.")
                else:
                    st.info("Uuden pelaajan lisääminen ei vaikuttanut kokonaispelimääriin.")

                # Display daily comparison
                st.subheader("Päivittäinen vertailu")
                comparison_data = []
                for date in sorted(schedule_filtered['Date'].unique()):
                    comparison_data.append({
                        'Päivä': date.date(),
                        'Aktiivisia (ilman uutta)': original_daily_active_counts.get(date.date(), 0),
                        'Aktiivisia (uuden kanssa)': new_daily_active_counts.get(date.date(), 0)
                    })
                comparison_df = pd.DataFrame(comparison_data)
                st.dataframe(comparison_df, use_container_width=True)

        else:
            st.error("Syötä kaikki tiedot uudelle pelaajalle.")
else:
    st.warning("Lataa peliaikataulu ja rosteri, ja varmista että päivämääräväli on kelvollinen, ennen kuin voit simuloida uutta pelaajaa.")
