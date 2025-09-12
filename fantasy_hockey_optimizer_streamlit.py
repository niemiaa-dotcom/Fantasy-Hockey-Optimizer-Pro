import streamlit as st
import pandas as pd
import numpy as np
from datetime import datetime, timedelta

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
- Simuloi pelaajien aktiivisia pelimääriä
- Vertaile pelaajia ja testi rosterimuutoksia
- Analysoi joukkueesi vahvuuksia ja heikkouksia
""")

# --- SIVUPALKKI: TIEDOSTONLATAUS ---
st.sidebar.header("📁 Tiedostojen lataus")

# Peliaikataulun lataus
schedule_file = st.sidebar.file_uploader(
    "Lataa NHL-peliaikataulu (CSV)", 
    type=["csv"],
    help="CSV-tiedoston tulee sisältää sarakkeet: Date, Visitor, Home"
)

if schedule_file:
    schedule = pd.read_csv(schedule_file)
    schedule['Date'] = pd.to_datetime(schedule['Date'])
    st.session_state['schedule'] = schedule
    st.sidebar.success("Peliaikataulu ladattu!")
else:
    st.session_state['schedule'] = pd.DataFrame()

# Rosterin lataus
roster_file = st.sidebar.file_uploader(
    "Lataa rosteri (CSV)", 
    type=["csv"],
    help="CSV-tiedoston tulee sisältää sarakkeet: name, team, positions"
)

if roster_file:
    roster = pd.read_csv(roster_file)
    st.session_state['roster'] = roster
    st.sidebar.success("Rosteri ladattu!")
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
    c_limit = st.number_input("Hyökkääjät (C)", 3, 1, 6)
    lw_limit = st.number_input("Vasen laitahyökkääjä (LW)", 3, 1, 6)
    rw_limit = st.number_input("Oikea laitahyökkääjä (RW)", 3, 1, 6)
    
with col2:
    d_limit = st.number_input("Puolustajat (D)", 4, 1, 8)
    g_limit = st.number_input("Maalivahdit (G)", 2, 1, 4)
    util_limit = st.number_input("UTIL-paikat", 1, 0, 3)

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

if not st.session_state['schedule'].empty and not st.session_state['roster'].empty:
    # Suodata peliaikataulu valitulle aikavälille
    schedule_filtered = st.session_state['schedule'][
        (st.session_state['schedule']['Date'] >= pd.to_datetime(start_date)) &
        (st.session_state['schedule']['Date'] <= pd.to_datetime(end_date))
    ]
    
    if schedule_filtered.empty:
        st.warning("Ei pelejä valitulla aikavälillä")
    else:
        # Yhdistä peliaikataulu ja rosteri
        schedule_long = pd.melt(
            schedule_filtered,
            id_vars=['Date'],
            value_vars=['Visitor', 'Home'],
            var_name='Type',
            value_name='Team'
        )
        
        df_merged = schedule_long.merge(
            st.session_state['roster'],
            left_on='Team',
            right_on='team',
            how='left'
        ).dropna(subset=['name'])
        
        # Optimointifunktio
        def optimize_roster(df, limits):
            # Ryhmitä pelaajat päivittäin
            daily_games = df.groupby('Date')['name'].apply(list).reset_index()
            
            results = []
            player_games = {}
            
            for _, row in daily_games.iterrows():
                date = row['Date']
                players = row['name']
                
                # Satunnainen järjestys pelaajille
                np.random.shuffle(players)
                
                active = {'C': [], 'LW': [], 'RW': [], 'D': [], 'G': [], 'UTIL': []}
                bench = []
                
                # Sijoita pelaajat aktiivisiin paikkoihin
                for player in players:
                    player_data = df[df['name'] == player].iloc[0]
                    positions = [p.strip() for p in player_data['positions'].split('/')]
                    
                    placed = False
                    
                    # Yritä sijoittaa ensisijaisiin paikkoihin
                    for pos in ['C', 'LW', 'RW', 'D', 'G']:
                        if pos in positions and len(active[pos]) < limits[pos]:
                            active[pos].append(player)
                            placed = True
                            break
                    
                    # Jos ei sijoitettu, yritä UTIL-paikkaa
                    if not placed and len(active['UTIL']) < limits['UTIL']:
                        active['UTIL'].append(player)
                        placed = True
                    
                    # Jos ei vieläkään sijoitettu, lisää penkille
                    if not placed:
                        bench.append(player)
                
                # Tallenna pelaajien pelimäärät
                for pos, players_list in active.items():
                    for player in players_list:
                        if player not in player_games:
                            player_games[player] = 0
                        player_games[player] += 1
                
                # Tallenna päivän tulokset
                results.append({
                    'Date': date.date(),
                    'Active': active,
                    'Bench': bench
                })
            
            return results, player_games
        
        # Suorita optimointi
        with st.spinner("Optimoidaan rosteria..."):
            daily_results, total_games = optimize_roster(df_merged, pos_limits)
        
        # Näytä tulokset
        st.subheader("Päivittäiset aktiiviset rosterit")
        
        # Luo päivittäiset tulokset DataFrameen
        daily_data = []
        for result in daily_results:
            active_str = ", ".join([
                f"{player} ({pos})" 
                for pos, players in result['Active'].items() 
                for player in players
            ])
            
            daily_data.append({
                'Päivä': result['Date'],
                'Aktiiviset pelaajat': active_str,
                'Penkki': ", ".join(result['Bench'])
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
        
        # Visualisoinnit (ilman plotlya)
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
            df_merged_sim = schedule_long.merge(
                sim_roster,
                left_on='Team',
                right_on='team',
                how='left'
            ).dropna(subset=['name'])
            
            _, sim_games = optimize_roster(df_merged_sim, pos_limits)
            
            # Vertaa tuloksia
            original_total = sum(total_games.values()) if 'total_games' in locals() else 0
            new_total = sum(sim_games.values())
            
            st.success(f"Kokonaispelit ennen: {original_total}")
            st.success(f"Kokonaispelit jälkeen: {new_total}")
            st.success(f"Muutos: {new_total - original_total} (+{((new_total/original_total - 1)*100):.1f}%)" if original_total > 0 else "Ei vertailukelpoista dataa")
            
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
       - Työkalu laskee automaattisesti optimaalisen päivittäisen käytön
       - Näet pelaajien kokonaispelimäärät valitulla aikavälillä
    
    5. **Simuloi muutoksia**:
       - Testaa, mitä tapahtuisi jos lisäisit uuden pelaajan
       - Vertaa eri pelaajien vaikutusta kokonaispelimääriin
    
    ### Vinkkejä:
    - Käytä simulaatioita testaamaan kauppojen ennen niiden tekemistä
    - Tarkista, onko rosterissasi liian monta pelaajaa samasta joukkueesta
    - Hyödynnä UTIL-paikkoja monipuolisten pelaajien hyödyntämiseen
    """)

# --- SIVUN ALAOSA ---
st.markdown("---")
st.markdown("Fantasy Hockey Optimizer Pro v1.0 | Tehdään ❤️:llä fantasy hockey -faneille")
