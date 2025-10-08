import streamlit as st
import requests
import pandas as pd
from datetime import datetime

# -- Attempt to hide header/search bar and Streamlit footers --
st.markdown("""
<style>
/* Hide header/bar in sidebar */
div[data-testid="stSidebarHeader"] {
    display: none !important;
    height: 0 !important;
    min-height: 0 !important;
    max-height: 0 !important;
    padding: 0 !important;
    margin: 0 !important;
    border: none !important;
}
/* Optionally hide only the sidebar collapse chevron button */
div[data-testid="stSidebarCollapseButton"] {
    display: none !important;
}
</style>
""", unsafe_allow_html=True)



# ---- TEAM BRANDING CONFIG -----
TEAM_CONFIGS = {
    "Atlanta United FC": {
        "name": "Atlanta United FC",
        "colors": {"primary": "#A2252A", "secondary": "#000000", "accent": "#C8A882"},
        "search_terms": ["atlanta", "united"]
    },
    "Inter Miami CF": {
        "name": "Inter Miami CF", 
        "colors": {"primary": "#F7B5CD", "secondary": "#000000", "accent": "#FFFFFF"},
        "search_terms": ["inter", "miami"]
    },
    "LAFC": {
        "name": "LAFC",
        "colors": {"primary": "#C39E5C", "secondary": "#000000", "accent": "#FFFFFF"},
        "search_terms": ["lafc", "los angeles fc"]
    },
    "New York City FC": {
        "name": "New York City FC",
        "colors": {"primary": "#6CABDD", "secondary": "#041E42", "accent": "#FFFFFF"},
        "search_terms": ["new york city", "nycfc", "nyc fc"]
    },
    "Toronto FC": {
        "name": "Toronto FC",
        "colors": {"primary": "#E31937", "secondary": "#000000", "accent": "#FFFFFF"},
        "search_terms": ["toronto"]
    },
    "Philadelphia Union": {
        "name": "Philadelphia Union",
        "colors": {"primary": "#041E42", "secondary": "#B1985A", "accent": "#FFFFFF"},
        "search_terms": ["philadelphia", "union"]
    },
    "Orlando City SC": {
        "name": "Orlando City SC",
        "colors": {"primary": "#633492", "secondary": "#000000", "accent": "#FFFFFF"},
        "search_terms": ["orlando"]
    },
    "New York Red Bulls": {
        "name": "New York Red Bulls",
        "colors": {"primary": "#C8102E", "secondary": "#000000", "accent": "#FFFFFF"},
        "search_terms": ["red bulls", "new york red"]
    },
    "Nashville SC": {
        "name": "Nashville SC",
        "colors": {"primary": "#ECE83A", "secondary": "#1F2937", "accent": "#FFFFFF"},
        "search_terms": ["nashville"]
    },
    "CF Montréal": {
        "name": "CF Montréal",
        "colors": {"primary": "#000080", "secondary": "#000000", "accent": "#FFFFFF"},
        "search_terms": ["montreal", "impact"]
    },
    "D.C. United": {
        "name": "D.C. United",
        "colors": {"primary": "#000000", "secondary": "#C8102E", "accent": "#FFFFFF"},
        "search_terms": ["dc united", "d.c.", "washington"]
    },
    "Columbus Crew": {
        "name": "Columbus Crew",
        "colors": {"primary": "#FFFF00", "secondary": "#000000", "accent": "#FFFFFF"},
        "search_terms": ["columbus", "crew"]
    },
    "Charlotte FC": {
        "name": "Charlotte FC",
        "colors": {"primary": "#00B2A0", "secondary": "#000000", "accent": "#FFFFFF"},
        "search_terms": ["charlotte"]
    },
    "Chicago Fire FC": {
        "name": "Chicago Fire FC",
        "colors": {"primary": "#C8102E", "secondary": "#000000", "accent": "#FFFFFF"},
        "search_terms": ["chicago", "fire"]
    },
    # Add more if/when needed
}

def get_team_colors(team_name):
    for config_name, config in TEAM_CONFIGS.items():
        if any(term in team_name.lower() for term in config["search_terms"]):
            return config["colors"]
    return TEAM_CONFIGS["Atlanta United FC"]["colors"]

def apply_custom_css(primary_color, secondary_color, accent_color):
    st.markdown(f"""
    <style>
    :root {{
        --bg-primary: white;
        --bg-secondary: #f8f9fa;
        --text-primary: #000000;
        --text-secondary: #6c757d;
        --border-color: #dee2e6;
        --shadow: rgba(0,0,0,0.1);
    }}
    [data-theme="dark"] {{
        --bg-primary: #0e1117;
        --bg-secondary: #262730;
        --text-primary: #ffffff;
        --text-secondary: #a6a6a6;
        --border-color: #3d4043;
        --shadow: rgba(255,255,255,0.1);
    }}
    @media (prefers-color-scheme: dark) {{
        .stApp {{
            --bg-primary: #0e1117;
            --bg-secondary: #262730;
            --text-primary: #ffffff;
            --text-secondary: #a6a6a6;
            --border-color: #3d4043;
            --shadow: rgba(255,255,255,0.1);
        }}
    }}
    .main-header {{
        background: linear-gradient(135deg, {primary_color} 0%, {secondary_color} 100%);
        padding: 2rem;
        border-radius: 10px;
        margin-bottom: 2rem;
        text-align: center;
        color: white !important;
        box-shadow: 0 4px 6px var(--shadow);
    }}
    .main-header h1, .main-header h2, .main-header p {{
        color: white !important;
    }}
    .status-card {{
        background: {primary_color};
        color: white !important;
        padding: 1.5rem;
        border-radius: 10px;
        text-align: center;
        margin: 1rem 0;
        font-size: 1.2em;
        font-weight: bold;
        box-shadow: 0 4px 6px var(--shadow);
    }}
    .status-card h2, .status-card p {{color: white !important;}}
    .metric-card {{
        background: var(--bg-primary);
        border: 2px solid {primary_color};
        border-radius: 10px;
        padding: 1rem;
        margin: 0.5rem 0;
        box-shadow: 0 2px 4px var(--shadow);
        color: var(--text-primary) !important;
    }}
    .metric-card h3 {{color: {primary_color} !important; margin-bottom: 0.5rem;}}
    .metric-card h1 {{color: var(--text-primary) !important; margin: 0.5rem 0;}}
    .metric-card small {{color: var(--text-secondary) !important;}}
    .opponent-card {{
        background: var(--bg-secondary);
        border-left: 4px solid {accent_color};
        padding: 1rem;
        margin: 0.5rem 0;
        border-radius: 5px;
        box-shadow: 0 2px 4px var(--shadow);
        color: var(--text-primary) !important;
    }}
    .opponent-card h4 {{color: var(--text-primary) !important; margin-bottom:0.5rem;}}
    .opponent-card p {{color: var(--text-primary) !important; margin: 0.25rem 0;}}
    .opponent-card strong {{color: {primary_color} !important;}}
    .stSelectbox > div > div > div {{
        background-color: var(--bg-secondary) !important;
        color: var(--text-primary) !important;
    }}
    .stButton > button {{
        background: {primary_color} !important;
        color: white !important;
        border: none !important;
        border-radius: 5px;
        padding: 0.5rem 2rem;
        font-weight: bold;
    }}
    .stButton > button:hover {{
        background: {secondary_color} !important;
    }}
    .sidebar-config {{
        background: var(--bg-secondary);
        border: 1px solid var(--border-color);
        padding: 1rem;
        border-radius: 10px;
        margin-bottom: 1rem;
    }}
    .stDataFrame {{
        background: var(--bg-primary) !important;
    }}
    .stDataFrame [data-testid="metric-container"] {{
        background: var(--bg-primary);
        border: 1px solid var(--border-color);
    }}
    .stMarkdown, .stText {{color: var(--text-primary) !important;}}
    .info-section {{
        background: var(--bg-secondary);
        border: 1px solid var(--border-color);
        padding: 1rem;
        border-radius: 8px;
        margin: 1rem 0;
    }}
    .info-section strong {{color: {primary_color} !important;}}
    .streamlit-expanderHeader {{background: var(--bg-secondary) !important; color: var(--text-primary) !important;}}
    .streamlit-expanderContent {{background: var(--bg-primary) !important; border: 1px solid var(--border-color) !important;}}
    .stSpinner > div {{border-top-color: {primary_color} !important;}}
    .stNumberInput > div > div > input {{
        background: var(--bg-primary) !important;
        color: var(--text-primary) !important;
        border-color: var(--border-color) !important;
    }}
    .stSlider > div > div > div > div {{background: {primary_color} !important;}}
    .stAlert {{background: var(--bg-secondary) !important; border-color: var(--border-color) !important;}}
    </style>
    """, unsafe_allow_html=True)

# ---- DATA FETCHING -----
def fetch_espn_conference_standings(season, timeout_seconds=10):
    data_url = f"https://site.api.espn.com/apis/v2/sports/soccer/usa.1/standings?season={season}"
    headers = {"User-Agent": "Mozilla/5.0"}
    try:
        resp = requests.get(data_url, headers=headers, timeout=timeout_seconds)
        resp.raise_for_status()
        data = resp.json()
    except requests.exceptions.Timeout:
        raise RuntimeError(f"ESPN API request timed out after {timeout_seconds} seconds")
    except requests.exceptions.RequestException as e:
        raise RuntimeError(f"Failed to fetch data from ESPN: {str(e)}")
    output = {}
    for conf in data.get('children', []):
        cname = conf.get("name", "Unknown Conference")
        teams = []
        entries = conf.get('standings', {}).get('entries', [])
        for entry in entries:
            stats_dict = {stat.get('name'): stat.get('value') for stat in entry.get('stats', [])}
            tinfo = entry.get("team", {})
            def to_int(val, d=0):
                try: return int(float(val))
                except: return d
            team = {
                'position': to_int(stats_dict.get('rank'), 99),
                'Team': tinfo.get('displayName', 'N/A'),
                'GP': to_int(stats_dict.get('gamesPlayed')),
                'W': to_int(stats_dict.get('wins')),
                'L': to_int(stats_dict.get('losses')),
                'T': to_int(stats_dict.get('ties')),
                'PTS': to_int(stats_dict.get('points')),
                'GF': to_int(stats_dict.get('pointsFor')),
                'GA': to_int(stats_dict.get('pointsAgainst')),
            }
            team['GD'] = team['GF'] - team['GA']
            team['PPG'] = round(team['PTS'] / team['GP'], 3) if team['GP'] else 0
            teams.append(team)
        teams = sorted(teams, key=lambda t: t['position'])
        output[cname] = pd.DataFrame(teams)
    return output

def find_team_in_standings(standings_df, team_name):
    search_terms = []
    for config_name, config in TEAM_CONFIGS.items():
        if config["name"] == team_name:
            search_terms = config["search_terms"]
            break
    if not search_terms:
        search_terms = [team_name.lower()]
    for term in search_terms:
        exact_match = standings_df[standings_df["Team"].str.lower() == term.lower()]
        if not exact_match.empty:
            return exact_match.iloc[0]
        contains_match = standings_df[standings_df["Team"].str.lower().str.contains(term.lower(), na=False)]
        if not contains_match.empty:
            return contains_match.iloc[0]
    return None

def playoff_scenarios(target_team, ninth_team, season_games):
    pts_target = int(target_team['PTS'])
    pts_9th = int(ninth_team['PTS'])
    gp_target = int(target_team['GP'])
    gp_9th = int(ninth_team['GP'])
    gr_target = season_games - gp_target
    gr_9th = season_games - gp_9th

    # Projected finish for 9th place if they continue at current PPG
    ppg_9th = pts_9th / gp_9th if gp_9th else 0
    projected_9th = pts_9th + gr_9th * ppg_9th

    must_beat = int(projected_9th) + 1

    # ---- WORST CASE (Wins Only) ----
    points_needed_wc = must_beat - pts_target
    wins_needed_wc = (points_needed_wc + 2) // 3 if points_needed_wc > 0 else 0  # ceiling division
    if gr_target <= 0 or wins_needed_wc > gr_target:
        # Not possible with games left, show real number of wins needed for transparency
        wc_possible = "No"
        losses_wc = 0
    else:
        wc_possible = "Yes"
        losses_wc = gr_target - wins_needed_wc

    final_pts_wc = pts_target + 3 * wins_needed_wc
    wc_result = {
        "Wins Needed": wins_needed_wc,
        "Ties Needed": 0,
        "Losses": losses_wc,
        "Final Points": final_pts_wc,
        "Still Possible?": wc_possible
    }

    # ---- BEST CASE (Maximum Ties allowed) ----
    found = False
    for ties in range(gr_target, -1, -1):  # max ties down to 0
        points_needed = must_beat - (pts_target + ties)
        wins_needed = (points_needed + 2) // 3 if points_needed > 0 else 0
        losses = gr_target - wins_needed - ties
        # All counts must be non-negative and not exceed games left
        if 0 <= wins_needed <= gr_target and 0 <= losses <= gr_target and wins_needed + ties + losses == gr_target:
            total_pts = pts_target + 3 * wins_needed + ties
            if total_pts >= must_beat:
                bc_result = {
                    "Wins Needed": wins_needed,
                    "Ties Needed": ties,
                    "Losses": losses,
                    "Final Points": total_pts,
                    "Still Possible?": "Yes"
                }
                found = True
                break
    if not found:
        # Not possible: show the theoretical number of wins needed (could be > games left)
        points_needed = must_beat - pts_target
        wins_needed = (points_needed + 2) // 3 if points_needed > 0 else 0
        ties = 0
        losses = gr_target - wins_needed if wins_needed <= gr_target else 0
        bc_result = {
            "Wins Needed": wins_needed,
            "Ties Needed": ties,
            "Losses": max(losses, 0),  # never negative
            "Final Points": pts_target + 3 * wins_needed,
            "Still Possible?": "No"
        }

    # Best Case wins should never be less than Worst Case wins, and both "No" if impossible
    if wc_result["Still Possible?"] == "No":
        bc_result["Still Possible?"] = "No"
    if bc_result["Wins Needed"] < wc_result["Wins Needed"]:
        bc_result["Wins Needed"] = wc_result["Wins Needed"]
        gr = gr_target
        bc_result["Ties Needed"] = gr - bc_result["Wins Needed"] if bc_result["Wins Needed"] <= gr else 0
        bc_result["Losses"] = max(0, gr - bc_result["Wins Needed"] - bc_result["Ties Needed"])
        bc_result["Final Points"] = pts_target + 3 * bc_result["Wins Needed"] + bc_result["Ties Needed"]

    return wc_result, bc_result, projected_9th

def ninth_place_help_banner(ninth_team, season_games, max_possible_pts):
    """
    Returns (help_msg, delta_pts, max_wins, ties, gr_9th)
    help_msg is ready for HTML/Markdown display.
    """
    pts_9th = int(ninth_team['PTS'])
    gp_9th = int(ninth_team['GP'])
    gr_9th = season_games - gp_9th
    limit_pts = max_possible_pts - 1
    delta_pts = limit_pts - pts_9th

    if delta_pts < 0:
        # Already eliminated, but helper won't trigger if properly gated
        delta_pts = 0

    if delta_pts == 0:
        help_msg = (
            f"9th place (<b>{ninth_team['Team']}</b>) must <b>lose all of their remaining {gr_9th} games</b>.<br>"
            "<b>Even a single tie or win will eliminate your team.</b>"
        )
        max_wins, ties = 0, 0
    else:
        max_wins = delta_pts // 3
        ties = delta_pts % 3
        details = []
        if max_wins > 0:
            details.append(f"{max_wins} wins")
        if ties > 0:
            details.append(f"{ties} ties")
        if not details:
            details = ["only losses"]

        help_msg = (
            f"9th place (<b>{ninth_team['Team']}</b>) must not earn more than "
            f"<b>{delta_pts}</b> more points in their last {gr_9th} games.<br>"
            f"This means <b>no more than {' and '.join(details)}</b>."
        )
    return help_msg, delta_pts, max_wins, ties, gr_9th

# ---------------- Streamlit UI -------------------

st.set_page_config(
    page_title="MLS Playoff Tracker", 
    layout="wide",
    initial_sidebar_state="expanded"
)

# ---- Sidebar Configuration ----
st.sidebar.markdown('<div class="sidebar-config">', unsafe_allow_html=True)
st.sidebar.header("⚙️ Configuration")

current_year = datetime.now().year
VALID_YEARS = [current_year - 2, current_year - 1, current_year]
# Only present past or current years, not future years
season_year = st.sidebar.selectbox(
    "Season Year",
    options=sorted(VALID_YEARS, reverse=True),
    index=0,
    help="MLS Season to track"
)
selected_team = st.sidebar.selectbox(
    "Select Team",
    options=list(TEAM_CONFIGS.keys()),
    index=0,
    help="Choose your team to track"
)
season_games = st.sidebar.number_input(
    "Games per Season",
    min_value=20,
    max_value=50,
    value=34,
    help="Total regular season games per team"
)
api_timeout = st.sidebar.slider(
    "API Timeout (seconds)",
    min_value=5,
    max_value=30,
    value=10,
    help="Timeout for ESPN API requests"
)
st.sidebar.markdown('</div>', unsafe_allow_html=True)

team_config = TEAM_CONFIGS[selected_team]
colors = team_config["colors"]
apply_custom_css(colors["primary"], colors["secondary"], colors["accent"])

# ---- MAIN HEADER ----
st.markdown(f"""
<div class="main-header">
    <h1>🏆 MLS Playoff Tracker</h1>
    <h2>{team_config["name"]} - {season_year} Season</h2>
    <p>Real-time playoff scenarios and standings analysis</p>
</div>
""", unsafe_allow_html=True)

# ---- Manual update button ----
col1, col2, col3 = st.columns([1, 2, 1])
with col2:
    if st.button("🔄 Update Standings", use_container_width=True):
        if 'standings_cache' in st.session_state:
            del st.session_state['standings_cache']

# ---- Fetch standings ----
@st.cache_data(show_spinner=False, ttl=300)
def get_standings_cached(season, timeout):
    return fetch_espn_conference_standings(season, timeout)

try:
    with st.spinner("Fetching latest standings from ESPN..."):
        standings_data = get_standings_cached(season_year, api_timeout)

    # For MLS, Eastern Conference
    eastern_df = None
    for conf_name, df in standings_data.items():
        if "east" in conf_name.lower():
            eastern_df = df
            break
    if eastern_df is None or eastern_df.empty:
        st.error("❌ Could not find Eastern Conference data (MLS may not have started yet for this year).")
        st.stop()

    # Find your team
    target_team = find_team_in_standings(eastern_df, selected_team)
    if target_team is None:
        st.error(f"❌ Could not find {selected_team} in standings list.")
        st.stop()
    # Find 9th in table
    if len(eastern_df) > 8:
        ninth_team = eastern_df.iloc[8]
        ninth_colors = get_team_colors(ninth_team["Team"])
    else:
        st.error("❌ Not enough teams in standings data.")
        st.stop()
    # Game remaining calculations
    target_team_gr = season_games - int(target_team['GP'])
    ninth_team_gr = season_games - int(ninth_team['GP'])
    target_team_data = target_team.copy(); target_team_data['GR'] = target_team_gr
    ninth_team_data  = ninth_team.copy();  ninth_team_data['GR']  = ninth_team_gr

    wc, bc, proj9 = playoff_scenarios(target_team_data, ninth_team_data, season_games)

    # ---------- Accurate Elimination/Help/Banner Logic ---------
    max_possible_pts = int(target_team['PTS']) + 3 * target_team_gr
    ninth_curr_pts  = int(ninth_team['PTS'])
    need_help_points = max_possible_pts - ninth_curr_pts + 1  # To have *more* than 9th

    if max_possible_pts < ninth_curr_pts:
        status = "❌ MATHEMATICALLY ELIMINATED"
        status_desc = ("Even if we win all remaining games, "
                       "the 9th place team already has more points.")
        status_color = "#dc3545"
        need_help_block = ""
    elif max_possible_pts < proj9:
        status = "⚠️ NEED HELP FROM OTHER RESULTS"
        status_desc = (f"We must win out, <b>and</b> hope the 9th place team finishes"
                       f" with no more than <b>{max_possible_pts} total points</b>.")
        help_msg, delta_pts, max_wins, ties, gr_9th = ninth_place_help_banner(
        ninth_team, season_games, max_possible_pts
        )
        #need_help_block = (
        #   f"<div class='opponent-card'>"
        #    f"<h4>What the 9th place team must do or worse:</h4>"
        #    f"<p>{help_msg}</p>"
        #    f"</div>"
        need_help_block = (
            f"<h4>What the 9th place team must do or worse:</h4>"
            f"<p>{help_msg}</p>"
        )
        status_color = "#FFA500"
    else:
        if int(target_team['PTS']) > proj9:
            status = "✅ PLAYOFFS CLINCHED!"
            status_desc = "We cannot be overtaken by 9th place, regardless of remaining results."
        else:
            status = "⚡ STILL IN CONTENTION"
            status_desc = "We still control our own destiny."
        status_color = colors["primary"]
        need_help_block = ""

except Exception as e:
    st.error(f"❌ Error fetching data: {str(e)}")
    st.stop()

# BANNER/STATUS
status_card_html = f"""
<div class="status-card" style="background: {status_color};">
    <h2>{status}</h2>
    <p>{status_desc}</p>
    <p>Current Position: #{int(target_team['position'])} in Eastern Conference</p>
"""
if need_help_block:
#    status_card_html += f"<div style='margin-top:1em'>{need_help_block}</div>"
    status_card_html += f"<p>{need_help_block}</p>"

status_card_html += "</div>"

st.markdown(status_card_html, unsafe_allow_html=True)

#st.markdown(f"""
#<div class="status-card" style="background: {status_color};">
#    <h2>{status}</h2>
#    <p>{status_desc}</p>
#    <p>Current Position: #{int(target_team['position'])} in Eastern Conference</p>
#</div>
#""", unsafe_allow_html=True)


# KEY METRICS DASHBOARD
col1, col2, col3, col4 = st.columns(4)
with col1:
    st.markdown(
        f"""<div class="metric-card"><h3>Current Points</h3>
            <h1>{int(target_team['PTS'])}</h1>
            <small>{target_team_gr} games remaining</small></div>
        """, unsafe_allow_html=True)
with col2:
    st.markdown(
        f"""<div class="metric-card"><h3>Points to Safety</h3>
            <h1>{max(0, int(proj9 + 1 - target_team['PTS']))}</h1>
            <small>Projected 9th: {int(proj9)}</small></div>
        """, unsafe_allow_html=True)
with col3:
    st.markdown(
        f"""<div class="metric-card"><h3>Min. Wins Needed</h3>
            <h1>{wc['Wins Needed']}</h1>
            <small>Worst case scenario</small></div>
        """, unsafe_allow_html=True)
with col4:
    st.markdown(
        f"""<div class="metric-card"><h3>PPG Required</h3>
            <h1>{round(max(0, int(proj9 + 1 - target_team['PTS'])) / target_team_gr, 2) if target_team_gr > 0 else 0}</h1>
            <small>Points per game</small></div>
        """, unsafe_allow_html=True)

# --- Standings snapshot: always show 9th above user if you're below them
st.subheader("📊 Current Standings Snapshot")
comparison_data = [
    {
        "Team": target_team["Team"], 
        "Pos": int(target_team['position']), 
        "PTS": int(target_team["PTS"]),
        "GP": int(target_team["GP"]),
        "W": int(target_team["W"]),
        "L": int(target_team["L"]), 
        "T": int(target_team["T"]),
        "GD": int(target_team["GD"]),
        "PPG": round(target_team["PPG"], 2),
        "GR": target_team_gr
    },
    {
        "Team": f"{ninth_team['Team']} (9th)", 
        "Pos": int(ninth_team['position']), 
        "PTS": int(ninth_team["PTS"]),
        "GP": int(ninth_team["GP"]),
        "W": int(ninth_team["W"]),
        "L": int(ninth_team["L"]),
        "T": int(ninth_team["T"]), 
        "GD": int(ninth_team["GD"]),
        "PPG": round(ninth_team["PPG"], 2),
        "GR": ninth_team_gr
    }
]
standings_comparison = pd.DataFrame(comparison_data).sort_values('Pos')
standings_comparison['Position'] = standings_comparison['Pos'].apply(lambda x: f"#{x}")
standings_comparison = standings_comparison.drop('Pos', axis=1)
columns_order = ['Position', 'Team', 'PTS', 'GP', 'W', 'L', 'T', 'GD', 'PPG', 'GR']
standings_comparison = standings_comparison[columns_order]
st.dataframe(standings_comparison.set_index("Team"), use_container_width=True)

# --- Playoff scenarios
st.subheader("🎯 Playoff Scenarios")
col1, col2 = st.columns(2)
with col1:
    st.markdown(
        f"""<div class="opponent-card"><h4>🔥 Worst Case (Wins Only)</h4>
        <p><strong>Wins Needed:</strong> {wc['Wins Needed']}</p>
        <p><strong>Can Have Losses:</strong> {wc['Losses']}</p>
        <p><strong>Final Points:</strong> {wc['Final Points']}</p>
        <p><strong>Possible:</strong> {wc['Still Possible?']}</p></div>
        """, unsafe_allow_html=True)
with col2:
    st.markdown(
        f"""<div class="opponent-card"><h4>✨ Best Case (With Ties)</h4>
        <p><strong>Wins Needed:</strong> {bc['Wins Needed']}</p>
        <p><strong>Ties Needed:</strong> {bc['Ties Needed']}</p>
        <p><strong>Final Points:</strong> {bc['Final Points']}</p>
        <p><strong>Possible:</strong> {bc['Still Possible?']}</p></div>
        """, unsafe_allow_html=True)

# --- 9th team info
st.subheader(f"🎖️ The Competition: {ninth_team['Team']}")
st.markdown(f"""
<div class="opponent-card" style="border-left-color: {ninth_colors['primary']};">
    <p><strong>Current Points:</strong> {int(ninth_team['PTS'])} points</p>
    <p><strong>Projected Finish:</strong> {int(proj9)} points</p>
    <p><strong>Points Per Game:</strong> {round(ninth_team['PPG'], 2)}</p>
    <p><strong>Games Remaining:</strong> {ninth_team_gr}</p>
</div>
""", unsafe_allow_html=True)

# --- Footer info and API URL expander
st.markdown("---")
now = datetime.now().strftime('%Y-%m-%d %H:%M:%S EST')
st.markdown(f"""
<div class="info-section">
<strong>ℹ️ Additional Info:</strong><br>
• Projections assume 9th place team continues at current PPG pace<br>
• Standings update in real-time from ESPN<br>
• Data as of: {now}<br>
• Season: {season_year} ({season_games} games per team)
</div>
""", unsafe_allow_html=True)
with st.expander("🔧 Technical Details"):
    st.write(f"**Data Source:** ESPN MLS API")
    st.code(f"https://site.api.espn.com/apis/v2/sports/soccer/usa.1/standings?season={season_year}")
    st.write(f"**Cache TTL:** 5 minutes")
    st.write(f"**API Timeout:** {api_timeout} seconds")
