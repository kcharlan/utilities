import requests
import json

# --- Configuration ---
SEASON = 2025
ESPN_API_URL = f"https://site.api.espn.com/apis/v2/sports/soccer/usa.1/standings?season={SEASON}"

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/108.0.0.0 Safari/537.36'
}

def parse_team_stats(team_entry):
    """
    Safely extracts stats and converts them to integers for clean printing.
    """
    stats_dict = {}
    for stat in team_entry.get('stats', []):
        stats_dict[stat.get('name')] = stat.get('value')
    
    team_info = team_entry.get('team', {})

    # Helper function to safely convert a value to an integer
    def to_int(api_value, default=0):
        if api_value is not None:
            try:
                # Convert to float first (to handle "9.0"), then to int
                return int(float(api_value))
            except (ValueError, TypeError):
                return default
        return default

    return {
        'position': to_int(stats_dict.get('rank'), '-'),
        'name': team_info.get('displayName', 'N/A'),
        'gp': to_int(stats_dict.get('gamesPlayed')),
        'w': to_int(stats_dict.get('wins')),
        'l': to_int(stats_dict.get('losses')),
        't': to_int(stats_dict.get('ties')),
        'pts': to_int(stats_dict.get('points'))
    }

try:
    print(f"Fetching MLS standings for the {SEASON} season from ESPN...")
    response = requests.get(ESPN_API_URL, headers=HEADERS)
    response.raise_for_status()

    data = response.json()
    conferences = data.get('children', [])

    print(f"\n--- MLS Standings - {SEASON} (via ESPN) ---\n")
    for conference in conferences:
        conf_name = conference.get('name', 'Unknown Conference')
        print(f"--- {conf_name} ---")
        print(f"{'#':<3} {'Team':<28} {'GP':>3} {'W':>3} {'L':>3} {'T':>3} {'Pts':>4}")
        print("-" * 50)
        
        standings_data = conference.get('standings', {})
        team_entries = standings_data.get('entries', [])
        
        if not team_entries:
            print("Could not find team entries for this conference.")
            continue

        # First, parse all the teams into a list of dictionaries
        parsed_teams = [parse_team_stats(entry) for entry in team_entries]

        # Second, sort that list by the 'position' key
        # We use a default of 99 for any team without a rank to sort them last
        sorted_teams = sorted(parsed_teams, key=lambda x: x.get('position', 99))

        # Finally, print the sorted and correctly formatted teams
        for team in sorted_teams:
            print(f"{team['position']:<3} {team['name']:<28} {team['gp']:>3} {team['w']:>3} {team['l']:>3} {team['t']:>3} {team['pts']:>4}")
        print("\n")

except requests.exceptions.RequestException as e:
    print(f"\nError fetching data from ESPN API: {e}")
except (KeyError, IndexError, TypeError) as e:
    print(f"\nError: Could not parse the data from ESPN. The API structure may have changed. Details: {e}")
