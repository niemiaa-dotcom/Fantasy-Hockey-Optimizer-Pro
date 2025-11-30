import streamlit as st
import pandas as pd
import requests
import xml.etree.ElementTree as ET
import time
import altair as alt

# Page Config
st.set_page_config(
    page_title="Fantasy Hockey Analytics (Dynamic)",
    page_icon="🏒",
    layout="wide",
    initial_sidebar_state="expanded"
)

# --- CONFIGURATION ---

# Yahoo ID Mapping (Standard IDs)
# Added '10': 'SHP' for Short Handed Points
STAT_MAP_YAHOO = {
    '1': 'Goals',
    '2': 'Assists',
    '8': 'PPP',
    '10': 'SHP',         # <-- NEW: Short Handed Points
    '14': 'SOG',
    '31': 'Hits',
    '32': 'Blocks',
    '19': 'Wins',
    '22': 'GA',
    '25': 'Saves',
    '27': 'Shutouts'
}

# SCORING SYSTEM
# Added 'SHP': 2.0
SCORING_SYSTEM = {
    'Goals': 4.5,
    'Assists': 3.0,
    'SHP': 2.0,          # <-- NEW: Multiplier added
    'SOG': 0.5,
    'Hits': 0.25,
    'Blocks': 0.5,
    'Wins': 3.0,
    'Saves': 0.3,
    'GA': -1.5,
    'Shutouts': 3.0
}

# --- YAHOO API FUNCTIONS ---

def get_yahoo_access_token():
    """Refreshes the Yahoo Access Token."""
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
        st.error(f"Error fetching Yahoo token: {e}")
        return None

def fetch_league_teams(league_id):
    """Fetches the list of teams for a specific League ID."""
    access_token = get_yahoo_access_token()
    if not access_token:
        return []

    # 465 is the Game Key for NHL 2024-2025.
    league_key = f"465.l.{league_id}"
    
    headers = {'Authorization': f'Bearer {access_token}'}
    url = f"https://fantasysports.yahooapis.com/fantasy/v2/league/{league_key}/standings"

    try:
        r = requests.get(url, headers=headers)
        if r.status_code == 403:
            st.error("Permission denied. Ensure the league is Publicly Viewable or you are a member.")
            return []
        
        r.raise_for_status()
        
        root = ET.fromstring(r.content)
        ns = {'f': 'http://fantasysports.yahooapis.com/fantasy/v2/base.rng'}
        
        teams = []
        for team in root.findall('.//f:team', ns):
            t_key = team.find('f:team_key', ns).text
            t_name = team.find('f:name', ns).text
            teams.append((t_key, t_name))
            
        return teams

    except Exception as e:
        st.error(f"Error fetching teams: {e}")
        return []

def fetch_yahoo_league_stats(team_list):
    """Fetches full season stats AND official Total Points for the provided team list."""
    access_token = get_yahoo_access_token()
    if not access_token:
        return pd.DataFrame()

    headers = {'Authorization': f'Bearer {access_token}'}
    rows = []
    ns = {'f': 'http://fantasysports.yahooapis.com/fantasy/v2/base.rng'}

    my_bar = st.progress(0, text="Fetching live stats...")
    
    for i, (team_key, team_name) in enumerate(team_list):
        url = f"https://fantasysports.yahooapis.com/fantasy/v2/team/{team_key}/stats;type=season"
        
        try:
            r = requests.get(url, headers=headers)
            if r.status_code != 200:
                continue

            root = ET.fromstring(r.content)
            stats_node = root.find('.//f:team_stats/f:stats', ns)
            
            # --- UUSI KOHTA: Haetaan viralliset kokonaispisteet ---
            points_node = root.find('.//f:team_points/f:total', ns)
            official_total_points = float(points_node.text) if points_node is not None else 0.0
            
            row_data = {col: 0 for col in STAT_MAP_YAHOO.values()}
            row_data['Team'] = team_name
            row_data['Official Total FP'] = official_total_points # Tallennetaan virallinen luku

            if stats_node:
                for stat in stats_node.findall('f:stat', ns):
                    stat_id = stat.find('f:stat_id', ns).text
                    stat_val = stat.find('f:value', ns).text
                    if stat_val == '-': stat_val = 0
                    
                    if stat_id in STAT_MAP_YAHOO:
                        col_name = STAT_MAP_YAHOO[stat_id]
                        row_data[col_name] = float(stat_val) if stat_val else 0

            rows.append(row_data)
            
        except Exception:
            pass
        
        my_bar.progress((i + 1) / len(team_list))
        time.sleep(0.1) 

    my_bar.empty()
    df = pd.DataFrame(rows)
    
    # Ensure correct column order
    cols = ['Team', 'Official Total FP', 'Goals', 'Assists', 'PPP', 'SHP', 'SOG', 'Hits', 'Blocks', 'Wins', 'GA', 'Saves', 'Shutouts']
    existing_cols = [c for c in cols if c in df.columns]
    df = df[existing_cols]
    
    return df

def fetch_yahoo_matchups(league_id, week=None):
    """Fetches matchup data for a specific week based on League ID."""
    access_token = get_yahoo_access_token()
    if not access_token:
        return pd.DataFrame()

    league_key = f"465.l.{league_id}"

    headers = {'Authorization': f'Bearer {access_token}'}
    url = f"https://fantasysports.yahooapis.com/fantasy/v2/league/{league_key}/scoreboard"
    if week:
        url += f";week={week}"

    try:
        r = requests.get(url, headers=headers)
        r.raise_for_status()
        
        root = ET.fromstring(r.content)
        ns = {'f': 'http://fantasysports.yahooapis.com/fantasy/v2/base.rng'}
        
        matchups = root.findall('.//f:matchup', ns)
        data = []
        
        for matchup in matchups:
            teams = matchup.findall('.//f:team', ns)
            if len(teams) != 2:
                continue
                
            team0_name = teams[0].find('f:name', ns).text
            team0_score = float(teams[0].find('.//f:team_points/f:total', ns).text or 0)
            
            team1_name = teams[1].find('f:name', ns).text
            team1_score = float(teams[1].find('.//f:team_points/f:total', ns).text or 0)
            
            # Team 0 perspective
            data.append({
                "Team": team0_name,
                "Opponent": team1_name,
                "Points For": team0_score,
                "Points Against": team1_score,
                "Diff": team0_score - team1_score,
                "Status": "Win" if team0_score > team1_score else ("Loss" if team0_score < team1_score else "Tie")
            })
            
            # Team 1 perspective
            data.append({
                "Team": team1_name,
                "Opponent": team0_name,
                "Points For": team1_score,
                "Points Against": team0_score,
                "Diff": team1_score - team0_score,
                "Status": "Win" if team1_score > team0_score else ("Loss" if team1_score < team0_score else "Tie")
            })
            
        return pd.DataFrame(data)

    except Exception as e:
        st.error(f"Error fetching matchups: {e}")
        return pd.DataFrame()

def fetch_cumulative_matchups(league_id, start_week, end_week):
    """Fetches data over a range of weeks and calculates xRecord."""
    all_weeks_data = []
    
    my_bar = st.progress(0, text=f"Processing weeks {start_week}-{end_week}...")
    total_weeks = end_week - start_week + 1
    
    for i, week in enumerate(range(start_week, end_week + 1)):
        df = fetch_yahoo_matchups(league_id, week=week)
        
        if not df.empty:
            # Calculate Weekly Median
            weekly_threshold = df['Points For'].median()
            
            # Determine Expected Win/Loss based on Median
            df['xW_week'] = (df['Points For'] > weekly_threshold).astype(int)
            df['xL_week'] = (df['Points For'] <= weekly_threshold).astype(int)
            
            df['Week'] = week
            all_weeks_data.append(df)
        
        my_bar.progress((i + 1) / total_weeks)
        time.sleep(0.1)

    my_bar.empty()

    if not all_weeks_data:
        return pd.DataFrame()

    combined_df = pd.concat(all_weeks_data)

    # Aggregation
    summary = combined_df.groupby('Team').agg({
        'Points For': 'sum',
        'Points Against': 'sum',
        'Diff': 'sum',
        'Opponent': lambda x: ', '.join(x.unique()),
        'xW_week': 'sum', 
        'xL_week': 'sum'
    }).reset_index()

    # Real Wins/Losses
    wins = combined_df[combined_df['Status'] == 'Win'].groupby('Team').size()
    losses = combined_df[combined_df['Status'] == 'Loss'].groupby('Team').size()
    ties = combined_df[combined_df['Status'] == 'Tie'].groupby('Team').size()

    summary = summary.set_index('Team')
    summary['W'] = wins
    summary['L'] = losses
    summary['T'] = ties
    summary[['W', 'L', 'T']] = summary[['W', 'L', 'T']].fillna(0).astype(int)
    
    summary = summary.reset_index()
    
    # Formatted Records
    summary['Record'] = summary.apply(lambda x: f"{x['W']}-{x['L']}-{x['T']}", axis=1)
    summary['xRecord'] = summary.apply(lambda x: f"{int(x['xW_week'])}-{int(x['xL_week'])}", axis=1)

    return summary

# --- UI STRUCTURE ---

st.sidebar.title("🏒 League Analytics")
st.sidebar.info("Enter a Yahoo League ID to analyze standings and matchups.")

# 1. LEAGUE ID INPUT
league_id_input = st.sidebar.text_input("Yahoo League ID", value="", placeholder="e.g. 50897")

# 2. LOAD LEAGUE BUTTON
if st.sidebar.button("Load League"):
    if league_id_input:
        with st.spinner("Fetching league details..."):
            teams = fetch_league_teams(league_id_input)
            if teams:
                st.session_state['league_id'] = league_id_input
                st.session_state['league_teams'] = teams
                # Clear old data when loading a new league
                if 'live_yahoo_stats' in st.session_state: del st.session_state['live_yahoo_stats']
                if 'matchup_data_cumulative' in st.session_state: del st.session_state['matchup_data_cumulative']
                st.sidebar.success(f"Loaded {len(teams)} teams!")
            else:
                st.sidebar.error("Could not load teams. Check ID or Privacy settings.")
    else:
        st.sidebar.warning("Please enter an ID.")

# Display current league info
if 'league_teams' in st.session_state:
    st.sidebar.markdown(f"**Active League:** {st.session_state['league_id']}")
    st.sidebar.markdown(f"**Teams:** {len(st.session_state['league_teams'])}")

if st.sidebar.button("Clear Cache"):
    st.cache_data.clear()
    for key in list(st.session_state.keys()):
        del st.session_state[key]
    st.rerun()

# --- MAIN APP ---

if 'league_teams' not in st.session_state:
    st.title("Welcome to Fantasy Analytics")
    st.markdown("""
    ### How to use:
    1. Enter your **Yahoo League ID** in the sidebar.
    2. Click **Load League**.
    3. Use the tabs below to analyze the data.
    
    *Note: This app only works for public leagues or leagues where the owner of the API keys is a member.*
    """)
else:
    tab1, tab2 = st.tabs(["🏆 League Standings (Points)", "⚔️ Matchup Analysis"])

    # --- TAB 1: CATEGORY POINTS ---
    with tab1:
        st.header("🏆 League Standings & Category Points")
        st.markdown("Fantasy Points (FP) distribution based on live stats.")

        cat_points_df = pd.DataFrame()

        if st.button("🔄 Refresh Live Data"):
             yahoo_df = fetch_yahoo_league_stats(st.session_state['league_teams'])
             if not yahoo_df.empty:
                 st.session_state['live_yahoo_stats'] = yahoo_df
                 st.success("Data updated!")
        
        if 'live_yahoo_stats' in st.session_state:
            cat_points_df = st.session_state['live_yahoo_stats'].copy()
        else:
            st.info("Click the button above to fetch data.")

        # Calculations & Visuals
        if not cat_points_df.empty:
            
            # Alustetaan sarakkeet erittelyä varten
            cat_points_df["Calculated Breakdown"] = 0.0 # Tätä käytetään vain kaavion tarkistukseen
            cat_points_df["Goalies (FP)"] = 0.0
            
            skater_fp_cols = []
            goalie_cats = {'Wins', 'Saves', 'GA', 'Shutouts'}

            # Lasketaan kategoriakohtaiset pisteet VAIN erittelyä/kaaviota varten
            for cat, multiplier in SCORING_SYSTEM.items():
                if cat in cat_points_df.columns:
                    points = cat_points_df[cat] * multiplier
                    cat_points_df["Calculated Breakdown"] += points
                    
                    if cat in goalie_cats:
                        cat_points_df["Goalies (FP)"] += points
                    else:
                        col_name = f"{cat} (FP)"
                        cat_points_df[col_name] = points
                        skater_fp_cols.append(col_name)

            # Järjestetään VIRALLISTEN pisteiden mukaan
            if 'Official Total FP' in cat_points_df.columns:
                cat_points_df = cat_points_df.sort_values("Official Total FP", ascending=False).reset_index(drop=True)
                total_col_name = "Official Total FP"
            else:
                # Fallback jos vanha data
                cat_points_df = cat_points_df.sort_values("Calculated Breakdown", ascending=False).reset_index(drop=True)
                total_col_name = "Calculated Breakdown"

            display_cols = ["Team", total_col_name] + skater_fp_cols + ["Goalies (FP)"]
            numeric_cols_to_format = [total_col_name] + skater_fp_cols + ["Goalies (FP)"]

            st.subheader("Total Fantasy Points Breakdown (Official Yahoo Stats)")
            st.dataframe(
                cat_points_df[display_cols].style.format("{:.1f}", subset=numeric_cols_to_format), 
                use_container_width=True
            )

            # Chart
            plot_vars = skater_fp_cols + ["Goalies (FP)"]
            df_long = cat_points_df.melt(id_vars=["Team"], value_vars=plot_vars, var_name="Category_Label", value_name="Fantasy Points")
            df_long["Category"] = df_long["Category_Label"].str.replace(" (FP)", "")
            cat_totals = df_long.groupby("Category")["Fantasy Points"].sum().reset_index().sort_values("Fantasy Points", ascending=False)
            category_order = cat_totals["Category"].tolist()

            chart = alt.Chart(df_long).mark_bar().encode(
                y=alt.X("Team:N", sort="-x", axis=alt.Axis(title="Team")),
                x=alt.X("Fantasy Points:Q", stack="zero", axis=alt.Axis(title="Fantasy Points")),
                color=alt.Color("Category:N", scale=alt.Scale(domain=category_order), legend=alt.Legend(title="Category")),
                tooltip=[alt.Tooltip("Team", title="Team"), alt.Tooltip("Category", title="Category"), alt.Tooltip("Fantasy Points", title="Points", format=".1f")]
            ).properties(height=600)
            st.altair_chart(chart, use_container_width=True)

    # --- TAB 2: MATCHUP CENTER ---
    with tab2:
        st.header("⚔️ Matchup Analysis")
        st.caption(f"Analyzing League ID: {st.session_state['league_id']}")

        # Controls
        col_ctrl1, col_ctrl2 = st.columns([3, 1], vertical_alignment="bottom")
        
        with col_ctrl1:
            week_range = st.slider("Select Week Range", min_value=1, max_value=26, value=st.session_state.get('matchup_range', (1, 4)))
        
        with col_ctrl2:
            run_search = st.button("Fetch Matchup Data", use_container_width=True)

        if run_search:
            start_w, end_w = week_range
            with st.spinner(f"Fetching data for weeks {start_w}-{end_w}..."):
                matchup_df = fetch_cumulative_matchups(st.session_state['league_id'], start_week=start_w, end_week=end_w)
                st.session_state['matchup_data_cumulative'] = matchup_df
                st.session_state['matchup_range'] = week_range

        st.markdown("---")
        
        if 'matchup_data_cumulative' in st.session_state and not st.session_state['matchup_data_cumulative'].empty:
            df = st.session_state['matchup_data_cumulative']
            current_range = st.session_state.get('matchup_range', (0,0))
            
            st.subheader(f"Results: Weeks {current_range[0]} - {current_range[1]}")
            
            if 'xW_week' not in df.columns:
                st.warning("Old data detected. Please click 'Fetch Matchup Data' again.")
                display_cols = ["Team", "Record", "Points For", "Points Against", "Diff"]
            else:
                display_cols = ["Team", "Record", "xRecord", "Points For", "Points Against", "Diff", "Luck"]
                df['W_int'] = df['Record'].apply(lambda x: int(x.split('-')[0]))
                df['Luck'] = df['W_int'] - df['xW_week']

            def color_diff(val):
                color = '#4caf50' if val > 0 else ('#f44336' if val < 0 else 'gray')
                return f'color: {color}; font-weight: bold'

            def color_luck(val):
                if val > 0: return 'color: #2e7d32; font-weight: bold; background-color: #e8f5e9'
                elif val < 0: return 'color: #c62828; font-weight: bold; background-color: #ffebee'
                else: return 'color: gray'

            st.dataframe(
                df[display_cols].style
                .format({"Points For": "{:.1f}", "Points Against": "{:.1f}", "Diff": "{:+.1f}", "Luck": "{:+d}"})
                .applymap(color_diff, subset=['Diff'])
                .applymap(color_luck, subset=['Luck'] if 'Luck' in df.columns else []),
                use_container_width=True,
                hide_index=True
            )
            
            if 'xRecord' in display_cols:
                st.caption("""
                **xRecord (Expected Record):** Shows what your record would be if you played against the "League Median" score every week.
                **Luck:** Positive (+) means you won more games than your point total typically deserves (Good matchup luck). Negative (-) means you lost despite scoring well.
                """)

            # Chart
            st.markdown("#### 📈 Offense (PF) vs Defense/Luck (PA)")
            chart = alt.Chart(df).mark_circle(size=200).encode(
                x=alt.X('Points For', title='Points For (PF)', scale=alt.Scale(zero=False)),
                y=alt.Y('Points Against', title='Points Against (PA)', scale=alt.Scale(zero=False)),
                color=alt.Color('Diff', title='Point Diff', scale=alt.Scale(scheme='redyellowgreen')),
                tooltip=['Team', 'Record', 'xRecord', 'Points For', 'Points Against', 'Diff', 'Luck']
            ).properties(height=500).interactive()
            
            text = chart.mark_text(align='left', baseline='middle', dx=12, fontSize=12).encode(text='Team')
            mean_pf = alt.Chart(df).mark_rule(color='gray', strokeDash=[5,5]).encode(x='mean(Points For)')
            mean_pa = alt.Chart(df).mark_rule(color='gray', strokeDash=[5,5]).encode(y='mean(Points Against)')

            st.altair_chart(chart + text + mean_pf + mean_pa, use_container_width=True)

        elif 'matchup_data_cumulative' in st.session_state:
            st.info("No data found for the selected range.")
