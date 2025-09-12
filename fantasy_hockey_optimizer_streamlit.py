import streamlit as st
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from collections import defaultdict

# Aseta sivun konfiguraatio
st.set_page_config(
    page_title="Fantasy Hockey Optimizer Pro",
    page_icon="🏒",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Otsikko ja johdanto
st.title("🏒 Fantasy Hockey Optimizer Pro")
st.markdown("""
**Optimoi fantasy hockey rosterisi NHL-kauden aikataulun perusteella!**
- Kukin pelaaja voi olla vain yhdellä pelipaikalla per päivä
- Pelimäärät kertyvät vain peleistä, joissa pelaajan joukkue on mukana
- Älykäs optimointi huomioi pelaajien monipuolisuuden ja vaihtoehtoiset sijoittelut
- Näet tarkasti ketkä pelaajat ovat aktiivisia ja ketkä penkillä
""")

# --- SIVUPALKKI: TIEDOSTONLATAUS ---
st.sidebar.header("📁 Tiedostojen lataus")

# Peliaikataulun lataus
schedule_file = st.sidebar.file_uploader(
    "Lataa NHL-peliaikataulu (CSV)", 
    type=["csv"],
    help="CSV-tiedoston tulee sisältää sarakkeet: Date, Visitor, Home"
)

# KORJAUS: Tarkista ensin onko tiedosto ladattu
if schedule_file is not None:
    try:
        schedule = pd.read_csv(schedule_file)
        # Tarkista että DataFrame ei ole tyhjä ja sisältää tarvittavat sarakkeet
        if not schedule.empty and 'Date' in schedule.columns:
            schedule['Date'] = pd.to_datetime(schedule['Date'])
            st.session_state['schedule'] = schedule
            st.sidebar.success("Peliaikataulu ladattu!")
        else:
            st.sidebar.error("Peliaikataulun CSV-tiedoston tulee sisältää 'Date'-sarake")
    except Exception as e:
        st.sidebar.error(f"Virhe peliaikataulun lukemisessa: {str(e)}")
else:
    st.session_state['schedule'] = pd.DataFrame()

# Rosterin lataus
roster_file = st.sidebar.file_uploader(
    "Lataa rosteri (CSV)", 
    type=["csv"],
    help="CSV-tiedoston tulee sisältää sarakkeet: name, team, positions"
)

# KORJAUS: Tarkista ensin onko tiedosto ladattu
if roster_file is not None:
    try:
        roster = pd.read_csv(roster_file)
        # Tarkista että DataFrame ei ole tyhjä ja sisältää tarvittavat sarakkeet
        if not roster.empty and all(col in roster.columns for col in ['name', 'team', 'positions']):
            st.session_state['roster'] = roster
            st.sidebar.success("Rosteri ladattu!")
        else:
            st.sidebar.error("Rosterin CSV-tiedoston tulee sisältää sarakkeet: name, team, positions")
    except Exception as e:
        st.sidebar.error(f"Virhe rosterin lukemisessa: {str(e)}")
else:
    st.session_state['roster'] = pd.DataFrame(columns=['name', 'team', 'positions'])

# --- SIVUPALKKI: ROSTERIN HALLINTA ---
st.sidebar.header("👥 Rosterin hallinta")

# Näytä nykyinen rosteri
if not st.session_state['roster'].empty:
    st.sidebar.subheader("Nykyinen rosteri")
    st.sidebar.dataframe(st.session_state['roster'])
    
    # Poista pelaaja
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
    
    # Lisää pelaaja
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

# --- SIVUPALKKI: ASETUKSET ---
st.sidebar.header("⚙️ Asetukset")

# Päivämäärävalinta
st.sidebar.subheader("Aikaväli")
today = datetime.now().date()
start_date = st.sidebar.date_input("Alkupäivä", today - timedelta(days=30))
end_date = st.sidebar.date_input("Loppupäivä", today)

# Pelipaikkojen rajoitukset
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

# --- PÄÄSIVU: ROSTERIN NÄYTTÖ ---
st.header("📊 Nykyinen rosteri")

if st.session_state['roster'].empty:
    st.warning("Lataa rosteri nähdäksesi pelaajat")
else:
    st.dataframe(st.session_state['roster'], use_container_width=True)
    
    # Joukkueiden jakauma
    st.subheader("Joukkueiden jakauma")
    team_counts = st.session_state['roster']['team'].value_counts()
    st.bar_chart(team_counts)

# --- PÄÄSIVU: OPTIMOINTI ---
st.header("🚀 Rosterin optimointi")

# KORJAUS: Tarkista että molemmat tiedostot on ladattu
if st.session_state['schedule'].empty or st.session_state['roster'].empty:
    st.warning("Lataa sekä peliaikataulu että rosteri aloittaaksesi optimoinnin")
else:
    # Suodata peliaikataulu valitulle aikavälille
    schedule_filtered = st.session_state['schedule'][
        (st.session_state['schedule']['Date'] >= pd.to_datetime(start_date)) &
        (st.session_state['schedule']['Date'] <= pd.to_datetime(end_date))
    ]
    
    if schedule_filtered.empty:
        st.warning("Ei pelejä valitulla aikavälillä")
    else:
        # Luo joukkueiden pelipäivät
        team_game_days = {}
        for _, row in schedule_filtered.iterrows():
            date = row['Date']
            for team in [row['Visitor'], row['Home']]:
                if team not in team_game_days:
                    team_game_days[team] = set()
                team_game_days[team].add(date)
        
        # KORJATTU optimointifunktio
        def optimize_roster_advanced(schedule_df, roster_df, limits, team_days, num_attempts=50):
            # Luo pelaajien tiedot
            players_info = {}
            for _, player in roster_df.iterrows():
                players_info[player['name']] = {
                    'team': player['team'],
                    'positions': [p.strip() for p in player['positions'].split('/')]
                }
            
            # Ryhmitä pelit päivittäin
            daily_results = []
            player_games = {name: 0 for name in players_info.keys()}
            
            # Käy läpi jokainen päivä
            for date in sorted(schedule_df['Date'].unique()):
                # Hae päivän pelit
                day_games = schedule_df[schedule_df['Date'] == date]
                
                # Hae pelaajat, joiden joukkueella on peli tänään
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
                
                # PARANNETTU ALGORITMI: Useita yrityksiä löytää paras sijoittelu
                best_assignment = None
                max_active = 0
                
                for attempt in range(num_attempts):
                    # Sekoita pelaajat satunnaisjärjestykseen
                    shuffled_players = available_players.copy()
                    np.random.shuffle(shuffled_players)
                    
                    # Alusta pelipaikat
                    active = {
                        'C': [], 'LW': [], 'RW': [], 'D': [], 'G': [], 'UTIL': []
                    }
                    bench = []
                    
                    # Vaihe 1: Sijoita pelaajat ensisijaisiin paikkoihin
                    for player in shuffled_players:
                        placed = False
                        
                        # Yritä sijoittaa ensisijaisiin paikkoihin
                        for pos in ['C', 'LW', 'RW', 'D', 'G']:
                            if pos in player['positions'] and pos in limits and len(active[pos]) < limits[pos]:
                                active[pos].append(player['name'])
                                placed = True
                                break
                        
                        # Jos ei sijoitettu, yritä UTIL-paikkaa
                        if not placed and 'UTIL' in limits and len(active['UTIL']) < limits['UTIL']:
                            # Tarkista, että pelaaja sopii UTIL-paikkaan (hyökkääjä tai puolustaja)
                            if any(pos in ['C', 'LW', 'RW', 'D'] for pos in player['positions']):
                                active['UTIL'].append(player['name'])
                                placed = True
                        
                        # Jos ei vieläkään sijoitettu, lisää penkille
                        if not placed:
                            bench.append(player['name'])
                    
                    # Vaihe 2: Yritä parantaa sijoittelua vaihtamalla pelaajien paikkoja
                    # Luo lista kaikista pelaajista (aktiiviset + penkki)
                    all_players = []
                    for pos, players in active.items():
                        for player_name in players:
                            all_players.append({
                                'name': player_name,
                                'positions': players_info[player_name]['positions'],
                                'current_pos': pos,
                                'active': True
                            })
                    
                    for player_name in bench:
                        all_players.append({
                            'name': player_name,
                            'positions': players_info[player_name]['positions'],
                            'current_pos': None,
                            'active': False
                        })
                    
                    # Yritä parantaa sijoittelua
                    improved = True
                    while improved:
                        improved = False
                        
                        # Käy läpi kaikki epäaktiiviset pelaajat
                        for bench_player in [p for p in all_players if not p['active']]:
                            # Käy läpi kaikki aktiiviset pelaajat
                            for active_player in [p for p in all_players if p['active']]:
                                # Tarkista voiko penkkipelaaja korvata aktiivisen pelaajan
                                if active_player['current_pos'] in bench_player['positions']:
                                    # Tarkista voiko aktiivinen pelaaja siirtyä toiseen paikkaan
                                    for new_pos in active_player['positions']:
                                        # KORJAUS: Varmista että new_pos on validi pelipaikka
                                        if new_pos != active_player['current_pos'] and new_pos in active and len(active[new_pos]) < limits[new_pos]:
                                            # Vaihto on mahdollinen!
                                            # Poista aktiivinen pelaaja nykyisestä paikastaan
                                            active[active_player['current_pos']].remove(active_player['name'])
                                            # Lisää hänet uuteen paikkaan
                                            active[new_pos].append(active_player['name'])
                                            # Lisää penkkipelaaja vapautuneeseen paikkaan
                                            active[active_player['current_pos']].append(bench_player['name'])
                                            # Päivitä pelaajien tilat
                                            active_player['current_pos'] = new_pos
                                            bench_player['active'] = True
                                            bench_player['current_pos'] = active_player['current_pos']
                                            # Poista pelaaja penkilta
                                            if bench_player['name'] in bench:
                                                bench.remove(bench_player['name'])
                                            improved = True
                                            break
                                    if improved:
                                        break
                            if improved:
                                break
                    
                    # Laske aktiivisten pelaajien määrä
                    total_active = sum(len(players) for players in active.values())
                    
                    # Tallenna paras sijoittelu
                    if total_active > max_active:
                        max_active = total_active
                        best_assignment = {
                            'active': active.copy(),
                            'bench': bench.copy()
                        }
                
                # KORJAUS: Varmista, että best_assignment ei ole None
                if best_assignment is None:
                    # Jos mikään sijoittelu ei ollut parempi kuin 0, luo tyhjä sijoittelu
                    best_assignment = {
                        'active': {
                            'C': [], 'LW': [], 'RW': [], 'D': [], 'G': [], 'UTIL': []
                        },
                        'bench': [p['name'] for p in available_players]
                    }
                
                # KORJAUS: Varmista, että kaikki pelaajat on huomioitu
                # Rakenna uusi lista kaikista pelaajista
                all_player_names = [p['name'] for p in available_players]
                active_player_names = set()
                
                # KORJAUS: Tarkista että best_assignment['active'] ei ole None
                if best_assignment['active'] is not None:
                    for pos, players in best_assignment['active'].items():
                        active_player_names.update(players)
                
                # Päivitä penkki: kaikki pelaajat, jotka eivät ole aktiivisia
                final_bench = [name for name in all_player_names if name not in active_player_names]
                
                daily_results.append({
                    'Date': date.date(),
                    'Active': best_assignment['active'],
                    'Bench': final_bench
                })
                
                # Päivitä pelaajien pelimäärät
                if best_assignment['active'] is not None:
                    for pos, players in best_assignment['active'].items():
                        for player_name in players:
                            player_games[player_name] += 1
            
            return daily_results, player_games
        
        # Suorita optimointi
        with st.spinner("Optimoidaan rosteria älykkäällä algoritmilla..."):
            daily_results, total_games = optimize_roster_advanced(
                schedule_filtered, 
                st.session_state['roster'], 
                pos_limits,
                team_game_days
            )
        
        # Näytä tulokset
        st.subheader("Päivittäiset aktiiviset rosterit")
        
        # Luo päivittäiset tulokset DataFrameen
        daily_data = []
        for result in daily_results:
            active_list = []
            # KORJAUS: Tarkista että result['Active'] ei ole None
            if result['Active'] is not None:
                for pos, players in result['Active'].items():
                    for player in players:
                        active_list.append(f"{player} ({pos})")
            
            daily_data.append({
                'Päivä': result['Date'],
                'Aktiiviset pelaajat': ", ".join(active_list),
                'Penkki': ", ".join(result['Bench']) if result['Bench'] else "Ei pelaajia penkille"
            })
        
        daily_df = pd.DataFrame(daily_data)
        st.dataframe(daily_df, use_container_width=True)
        
        # Pelimäärien yhteenveto
        st.subheader("Pelaajien kokonaispelimäärät")
        
        games_df = pd.DataFrame({
            'Pelaaja': list(total_games.keys()),
            'Pelit': list(total_games.values())
        }).sort_values('Pelit', ascending=False)
        
        st.dataframe(games_df, use_container_width=True)
        
        # Latauspainike
        csv = games_df.to_csv(index=False).encode('utf-8')
        st.download_button(
            "Lataa pelimäärät CSV-muodossa",
            data=csv,
            file_name='pelimäärät.csv',
            mime='text/csv'
        )
        
        # Visualisoinnit
        st.subheader("📈 Analyysit")
        
        col1, col2 = st.columns(2)
        
        with col1:
            # Top 10 pelaajaa
            top_players = games_df.head(10)
            st.write("Top 10 eniten pelanneet pelaajat")
            st.dataframe(top_players)
        
        with col2:
            # Pelipaikkojen jakauma
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

# --- SIMULOINTI ---
st.header("🔮 Simuloi rosterimuutoksia")

if not st.session_state['roster'].empty:
    st.subheader("Lisää uusi pelaaja")
    
    col1, col2, col3 = st.columns(3)
    
    with col1:
        sim_name = st.text_input("Pelaajan nimi")
    with col2:
        sim_team = st.text_input("Joukkue")
    with col3:
        sim_positions = st.text_input("Pelipaikat")
    
    if st.button("Simuloi pelaajan lisääminen"):
        if sim_name and sim_team and sim_positions:
            # Luo kopio rosterista
            sim_roster = st.session_state['roster'].copy()
            
            # Lisää uusi pelaaja
            new_player = pd.DataFrame({
                'name': [sim_name],
                'team': [sim_team],
                'positions': [sim_positions]
            })
            sim_roster = pd.concat([sim_roster, new_player], ignore_index=True)
            
            # Suorita optimointi uudella rosterilla
            _, sim_games = optimize_roster_advanced(
                schedule_filtered, 
                sim_roster, 
                pos_limits,
                team_game_days
            )
            
            # Vertaa tuloksia
            original_total = sum(total_games.values()) if 'total_games' in locals() else 0
            new_total = sum(sim_games.values())
            
            st.success(f"Kokonaispelit ennen: {original_total}")
            st.success(f"Kokonaispelit jälkeen: {new_total}")
            if original_total > 0:
                change_pct = ((new_total/original_total - 1)*100)
                st.success(f"Muutos: {new_total - original_total} ({change_pct:+.1f}%)")
            else:
                st.success("Ei vertailukelpoista dataa")
            
            # Näytä uuden pelaajan pelimäärä
            if sim_name in sim_games:
                st.info(f"{sim_name} pelisi {sim_games[sim_name]} peliä")

# --- OHJEET ---
with st.expander("📖 Käyttöohjeet"):
    st.markdown("""
    ### Miten käytät tätä työkalua:
    
    1. **Lataa tiedostot**:
       - Lataa NHL-peliaikataulu CSV-muodossa (sisältää sarakkeet: Date, Visitor, Home)
       - Lataa rosterisi CSV-muodossa (sisältää sarakkeet: name, team, positions)
    
    2. **Hallinnoi rosteria**:
       - Lisää tai poista pelaajia sivupalkista
       - Tarkista joukkueiden jakauma
    
    3. **Määritä asetukset**:
       - Valitse aikaväli, jolta haluat analysoida
       - Aseta pelipaikkojen rajoitukset (hyökkääjät, puolustajat, maalivahdit jne.)
    
    4. **Optimoi rosteri**:
       - Työkalu käyttää älykästä algoritmia löytääkseen optimaalisen sijoittelun
       - Se huomioi pelaajien monipuolisuuden ja vaihtoehtoiset sijoittelut
       - Pelaajat sijoitetaan vain yhdelle pelipaikalle per päivä
    
    5. **Tulosten tulkinta**:
       - **Aktiiviset pelaajat**: Pelaajat, jotka on sijoitettu rosteriin tietylle päivälle
       - **Penkki**: Pelaajat, joiden joukkueella on peli, mutta heitä ei voitu sijoittaa aktiiviseen rosteriin
       - **Kokonaispelimäärät**: Kuinka monta kertaa kukin pelaaja olisi aktiivinen valitulla aikavälillä
    
    ### Tärkeät parannukset:
    - **Älykäs sijoittelu**: Algoritmi yrittää löytää parhaan mahdollisen sijoittelun
    - **Paikkojen vaihto**: Pelaajia voidaan siirtää paikasta toiseen vapauttaen tilaa muille
    - **Täydellinen pelaajaseuranta**: Kaikki pelaajat (sekä aktiiviset että penkillä olevat) näytetään selkeästi
    - **Virheenkäsittely**: Tarkistukset varmistavat, että tiedostot ovat oikeassa muodossa
    - **Varovainen käsittely**: Varmistetaan ettei yritetä käsitellä None-arvoja
    - **Validit pelipaikat**: Varmistetaan että pelaajat sijoitetaan vain määriteltyihin pelipaikkoihin
    """)

# --- SIVUN ALAOSA ---
st.markdown("---")
st.markdown("Fantasy Hockey Optimizer Pro v3.4 | Validit pelipaikat")
