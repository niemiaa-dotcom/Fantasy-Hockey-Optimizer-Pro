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
    
    # UUSI: Pelaaja poistettavaksi
    remove_sim_player = st.selectbox(
        "Pelaaja poistettavaksi rosterista (valinnainen)",
        [""] + list(st.session_state['roster']['name'])
    )

    if st.button("Suorita simulaatio"):
        if sim_name and sim_team and sim_positions:
            
            # Luo simulaatiorosteri
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

# --- UUSI OSIO: ANALYYSI PELIPAITTAISIN ---
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
