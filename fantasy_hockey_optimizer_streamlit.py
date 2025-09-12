import streamlit as st
import pandas as pd
import requests
from datetime import datetime, timedelta

# --- Helper functions ---

NHL_SCHEDULE_URL = "https://statsapi.web.nhl.com/api/v1/schedule"

def fetch_schedule(start_date, end_date):
    url = f"{NHL_SCHEDULE_URL}?startDate={start_date}&endDate={end_date}"
    r = requests.get(url)
    data = r.json()
    schedule = []
    for date_info in data.get("dates", []):
        game_date = date_info["date"]
        for game in date_info["games"]:
            for team_type in ["away", "home"]:
                team = game[team_type]["team"]["name"]
                team_abbrev = game[team_type]["team"]["triCode"]
                schedule.append({"date": game_date, "team": team, "abbrev": team_abbrev})
    return pd.DataFrame(schedule)

def simulate_lineups(roster, schedule, roster_slots):
    # roster: DataFrame with columns [name, team, positions]
    # schedule: DataFrame with columns [date, team, abbrev]
    # roster_slots: dict like {"C":2, "LW":2, "RW":2, "D":4, "G":2, "UTIL":2}

    results = {p["name"]: {"games": 0, "used": 0, "wasted": 0} for _, p in roster.iterrows()}

    # Build daily simulation
    all_dates = schedule["date"].unique()
    for d in all_dates:
        todays_games = schedule[schedule["date"] == d]
        playing = []
        for _, player in roster.iterrows():
            if player["team"] in list(todays_games["abbrev"]):
                positions = player["positions"].split(",")
                playing.append({"name": player["name"], "positions": positions})
                results[player["name"]]["games"] += 1

        # Fill lineup greedily
        slots_remaining = roster_slots.copy()
        used_players = set()
        for pos in slots_remaining.keys():
            for p in playing:
                if p["name"] not in used_players and pos in p["positions"] and slots_remaining[pos] > 0:
                    results[p["name"]]["used"] += 1
                    used_players.add(p["name"])
                    slots_remaining[pos] -= 1
        # UTIL fill
        if "UTIL" in slots_remaining:
            for p in playing:
                if p["name"] not in used_players and slots_remaining["UTIL"] > 0:
                    results[p["name"]]["used"] += 1
                    used_players.add(p["name"])
                    slots_remaining["UTIL"] -= 1

    for name in results:
        results[name]["wasted"] = results[name]["games"] - results[name]["used"]

    return pd.DataFrame([
        {"player": name, **vals} for name, vals in results.items()
    ])

# --- Streamlit UI ---

st.title("Fantasy Hockey Roster Optimizer")

st.sidebar.header("Simulation settings")
start_date = st.sidebar.date_input("Start date", datetime.today())
end_date = st.sidebar.date_input("End date", datetime.today() + timedelta(days=7))

st.sidebar.markdown("### Roster slots")
def_slot = {"C":2, "LW":2, "RW":2, "D":4, "G":2, "UTIL":2}
slots = {}
for pos, default in def_slot.items():
    slots[pos] = st.sidebar.number_input(f"{pos}", value=default, min_value=0)

st.header("Upload roster")
roster_file = st.file_uploader("Upload CSV (name,team,positions)", type="csv")

extra_player = None
st.header("Test adding a new player")
with st.expander("Add a player manually"):
    add_name = st.text_input("Player name")
    add_team = st.text_input("Team abbrev (e.g., TOR, NYR)")
    add_pos = st.text_input("Positions (comma separated, e.g., C,LW)")
    if add_name and add_team and add_pos:
        extra_player = {"name": add_name, "team": add_team, "positions": add_pos}

if roster_file:
    roster = pd.read_csv(roster_file)
    schedule = fetch_schedule(start_date, end_date)

    st.subheader("Simulation results for current roster")
    results = simulate_lineups(roster, schedule, slots)
    st.dataframe(results)
    total_used = results["used"].sum()
    total_wasted = results["wasted"].sum()
    st.success(f"Yhteensä pelatut pelit: {total_used}, hukatut pelit: {total_wasted}")

    if extra_player:
        st.subheader("Simulation with extra player")
        roster_plus = roster.copy()
        roster_plus = pd.concat([roster_plus, pd.DataFrame([extra_player])], ignore_index=True)
        results_plus = simulate_lineups(roster_plus, schedule, slots)
        st.dataframe(results_plus)
        total_used_plus = results_plus["used"].sum()
        total_wasted_plus = results_plus["wasted"].sum()
        diff = total_used_plus - total_used
        st.info(f"Uuden pelaajan lisääminen muuttaa kokonaissummaa: {total_used} → {total_used_plus} (muutos: {diff:+d} peliä)")
