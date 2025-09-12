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

# [Edellinen koodi pysyy samana, lisätään vain uusi visualisointi osio]

# --- SIMULOINTI ---
st.header("🔮 Simuloi uuden pelaajan vaikutus")

if not st.session_state['roster'].empty and not schedule_filtered.empty:
    st.subheader("Lisää uusi pelaaja")
    
    col1, col2, col3 = st.columns(3)
    
    with col1:
        sim_name = st.text_input("Pelaajan nimi")
    with col2:
        sim_team = st.text_input("Joukkue")
    with col3:
        sim_positions = st.text_input("Pelipaikat (esim. C/LW)")
    
    if st.button("Simuloi pelaajan lisääminen"):
        if sim_name and sim_team and sim_positions:
            # Luo uuden pelaajan tiedot
            new_player_info = {
                'name': sim_name,
                'team': sim_team,
                'positions': sim_positions
            }
            
            # Suorita korjattu simulaatio
            with st.spinner("Lasketaan uuden pelaajan vaikutusta..."):
                # LASKE ALKUPERÄINEN TILANNE (ilman uutta pelaajaa)
                original_total = 0
                for date in sorted(schedule_filtered['Date'].unique()):
                    # Hae päivän pelit
                    day_games = schedule_filtered[schedule_filtered['Date'] == date]
                    
                    # Hae pelaajat, joiden joukkueella on peli tänään
                    available_players = []
                    for _, game in day_games.iterrows():
                        for team in [game['Visitor'], game['Home']]:
                            for _, player in st.session_state['roster'].iterrows():
                                if player['team'] == team and player['name'] not in [p['name'] for p in available_players]:
                                    available_players.append({
                                        'name': player['name'],
                                        'team': team,
                                        'positions': [p.strip() for p in player['positions'].split('/')]
                                    })
                    
                    # Optimoi päivän rosteri ja laske aktiiviset pelaajat
                    daily_active = 0
                    if available_players:
                        _, daily_results = optimize_roster_advanced(
                            pd.DataFrame([day_games]), 
                            st.session_state['roster'], 
                            pos_limits,
                            {team: {date} for team in [game['Visitor'], game['Home']] for _, game in day_games.iterrows()}
                        )
                        for result in daily_results:
                            if result['Active']:
                                daily_active += sum(len(players) for players in result['Active'].values())
                    
                    original_total += daily_active
                
                # LASKE UUSI TILANNE (uudella pelaajalla)
                # Luo uusi rosteri
                new_roster = pd.concat([
                    st.session_state['roster'],
                    pd.DataFrame([new_player_info])
                ], ignore_index=True)
                
                new_total = 0
                player_impact_days = 0  # Päivät, joina uusi pelaaja on aktiivinen
                
                # UUSI: Päiväkohtainen analyysi
                daily_impact_data = []
                
                for date in sorted(schedule_filtered['Date'].unique()):
                    # Hae päivän pelit
                    day_games = schedule_filtered[schedule_filtered['Date'] == date]
                    
                    # Tarkista onko uuden pelaajan joukkueella peli tänään
                    new_player_team_playing = sim_team in day_games[['Visitor', 'Home']].values
                    
                    if new_player_team_playing:
                        # Hae pelaajat ilman uutta pelaajaa
                        available_players_without = []
                        for _, game in day_games.iterrows():
                            for team in [game['Visitor'], game['Home']]:
                                for _, player in st.session_state['roster'].iterrows():
                                    if player['team'] == team and player['name'] not in [p['name'] for p in available_players_without]:
                                        available_players_without.append({
                                            'name': player['name'],
                                            'team': team,
                                            'positions': [p.strip() for p in player['positions'].split('/')]
                                        })
                        
                        # Optimoi ilman uutta pelaajaa
                        daily_active_without = 0
                        if available_players_without:
                            _, daily_results_without = optimize_roster_advanced(
                                pd.DataFrame([day_games]), 
                                st.session_state['roster'], 
                                pos_limits,
                                {team: {date} for team in [game['Visitor'], game['Home']] for _, game in day_games.iterrows()}
                            )
                            for result in daily_results_without:
                                if result['Active']:
                                    daily_active_without += sum(len(players) for players in result['Active'].values())
                        
                        # Hae pelaajat uudella pelaajalla
                        available_players_with = []
                        for _, game in day_games.iterrows():
                            for team in [game['Visitor'], game['Home']]:
                                for _, player in new_roster.iterrows():
                                    if player['team'] == team and player['name'] not in [p['name'] for p in available_players_with]:
                                        available_players_with.append({
                                            'name': player['name'],
                                            'team': team,
                                            'positions': [p.strip() for p in player['positions'].split('/')]
                                        })
                        
                        # Optimoi uudella pelaajalla
                        daily_active_with = 0
                        player_is_active = False
                        player_position = None
                        
                        if available_players_with:
                            _, daily_results_with = optimize_roster_advanced(
                                pd.DataFrame([day_games]), 
                                new_roster, 
                                pos_limits,
                                {team: {date} for team in [game['Visitor'], game['Home']] for _, game in day_games.iterrows()}
                            )
                            for result in daily_results_with:
                                if result['Active']:
                                    day_active_count = sum(len(players) for players in result['Active'].values())
                                    daily_active_with = day_active_count
                                    
                                    # Tarkista onko uusi pelaaja aktiivinen
                                    for pos, players in result['Active'].items():
                                        if sim_name in players:
                                            player_is_active = True
                                            player_position = pos
                                            break
                        
                        # Laske ero
                        daily_difference = daily_active_with - daily_active_without
                        
                        # Tallenna päivän tiedot
                        daily_impact_data.append({
                            'Päivä': date,
                            'Aktiiviset ilman': daily_active_without,
                            'Aktiiviset kanssa': daily_active_with,
                            'Ero': daily_difference,
                            'Uusi pelaaja aktiivinen': player_is_active,
                            'Sijainti': player_position if player_is_active else None
                        })
                        
                        # Päivitä kokonaistulokset
                        new_total += daily_active_with
                        if player_is_active:
                            player_impact_days += 1
                    else:
                        # Jos uuden pelaajan joukkueella ei ole peliä, tulos on sama
                        daily_impact_data.append({
                            'Päivä': date,
                            'Aktiiviset ilman': None,
                            'Aktiiviset kanssa': None,
                            'Ero': 0,
                            'Uusi pelaaja aktiivinen': False,
                            'Sijainti': None
                        })
                        new_total += daily_active_without  # Käytä samaa arvoa kuin ilman uutta pelaajaa
                
                # Näytä kokonaistulokset
                st.subheader("Kokonaisvaikutus")
                
                col1, col2, col3 = st.columns(3)
                
                with col1:
                    st.metric("Kokonaispelit ennen", original_total)
                with col2:
                    st.metric("Kokonaispelit jälkeen", new_total)
                with col3:
                    difference = new_total - original_total
                    st.metric("Muutos", difference, delta=difference)
                
                st.subheader(f"Uuden pelaajan ({sim_name}) vaikutus")
                
                if player_impact_days > 0:
                    st.success(f"{sim_name} olisi aktiivinen {player_impact_days} päivänä valitulla aikavälillä")
                    st.info(f"Tämä lisäisi kokonaisaktiivisia pelejä {difference} kertaa")
                else:
                    st.warning(f"{sim_name} ei olisi koskaan aktiivinen rosterissa valitulla aikavälillä")
                    st.info("Tämä pelaaja ei lisäisi arvoa nykyiselle rosterillesi")
                
                # NÄYTÄ PÄIVÄKOHTAINEN ANALYYSI
                st.subheader("📊 Päiväkohtainen vaikutus")
                
                # Suodata vain ne päivät joina uusi pelaaja on aktiivinen
                impact_df = pd.DataFrame(daily_impact_data)
                active_days_df = impact_df[impact_df['Uusi pelaaja aktiivinen'] == True]
                
                if not active_days_df.empty:
                    st.write("Päivät joina uusi pelaaja lisääisi aktiivisen rosterin pelimäärää:")
                    
                    # Luo korostettu taulukko
                    def highlight_positive_difference(val):
                        color = 'lightgreen' if val > 0 else 'white'
                        return f'background-color: {color}'
                    
                    styled_df = active_days_df.style.applymap(highlight_positive_difference, subset=['Ero'])
                    
                    # Näytä vain tärkeät sarakkeet
                    display_df = active_days_df[[
                        'Päivä', 'Aktiiviset ilman', 'Aktiiviset kanssa', 'Ero', 'Sijainti'
                    ]].rename(columns={
                        'Päivä': 'Päivämäärä',
                        'Aktiiviset ilman': 'Ilman uutta pelaajaa',
                        'Aktiiviset kanssa': 'Uuden pelaajan kanssa',
                        'Ero': 'Lisäys',
                        'Sijainti': 'Pelipaikka'
                    })
                    
                    st.dataframe(display_df.style.format({
                        'Ilman uutta pelaajaa': '{:.0f}',
                        'Uuden pelaajan kanssa': '{:.0f}',
                        'Lisäys': '{:+.0f}'
                    }), use_container_width=True)
                    
                    # Lisää yhteenveto
                    total_addition = active_days_df['Ero'].sum()
                    avg_addition = active_days_df['Ero'].mean()
                    
                    col1, col2 = st.columns(2)
                    
                    with col1:
                        st.metric("Kokonaislisäys aktiivisiin peleihin", total_addition)
                    with col2:
                        st.metric("Keskimääräinen lisäys per päivä", f"{avg_addition:.1f}")
                    
                    # Näytä parhaat päivät
                    st.subheader("Parhaat päivät uudelle pelaajalle")
                    best_days = active_days_df.nlargest(3, 'Ero')
                    
                    for _, row in best_days.iterrows():
                        st.info(f"**{row['Päivä'].strftime('%Y-%m-%d')}**: +{row['Ero']:.0f} aktiivista pelaajasta (sijainti: {row['Sijainti']})")
                else:
                    st.info("Uusi pelaaja ei lisäisi aktiivisen rosterin pelimäärää yhtenäkään päivänä valitulla aikavälillä")
