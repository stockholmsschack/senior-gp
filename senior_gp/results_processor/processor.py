import json
import os
import glob
import requests
from datetime import date, datetime
from typing import Dict, List, Optional, Any
from .models import TournamentFetchError, TournamentNotFinishedError

TOURNAMENT_URL = "https://member.schack.se/public/api/v1/tournament/tournament/id/{}"
GROUP_TABLE_URL = "https://member.schack.se/public/api/v1/tournamentresults/table/id/{}"


def has_been_played(tournament_data: Dict[str, Any], today: date) -> bool:
    """
    Return False for a tournament that has not started and True for one that has ended.

    Raises TournamentNotFinishedError for a running tournament, because its results are incomplete.
    """
    start_date = datetime.strptime(tournament_data['start'], '%Y-%m-%d').date()
    if start_date > today:
        return False
    end_date = datetime.strptime(tournament_data.get('end') or tournament_data['start'], '%Y-%m-%d').date()
    if end_date >= today:
        raise TournamentNotFinishedError(
            f"Tournament {tournament_data['id']} ({tournament_data.get('name', '')}) has not finished; "
            f"it ends {end_date}. Remove it or generate after it ends."
        )
    return True


def group_ids(tournament_data: Dict[str, Any]) -> List[int]:
    """Return the IDs of every group in every root class."""
    return [group['id'] for root_class in tournament_data.get('rootClasses', [])
            for group in root_class.get('groups', [])]


def member_results(group_tables: List[List[Dict[str, Any]]], member_classes: Dict[int, str]) -> List[Dict[str, Any]]:
    """Return district members' results from the group tables, with their class."""
    results = []
    for table in group_tables:
        for result in table:
            contender_id = result['contenderId']
            if contender_id not in member_classes:
                continue
            player_info = result['playerInfo']
            results.append({
                'contenderId': contender_id,
                'name': f"{player_info['firstName']} {player_info['lastName']}",
                'points': result['points'],
                'secPoints': result['secPoints'],
                'klass': member_classes[contender_id],
            })
    return results


class ResultsProcessor:
    def __init__(self, season: Optional[int] = None):
        self.season = season or datetime.now().year
        self.base_dir = os.path.dirname(os.path.dirname(__file__))
        self.data_dir = os.path.join(self.base_dir, 'data')
        self.tournaments_dir = os.path.join(self.base_dir, 'tournaments')
        self.member_dict = {}
        
    def load_member_data(self) -> None:
        """Load member data from ratings list and remainder files."""
        # Load ratings list
        ratings_file = os.path.join(self.data_dir, f'ratings_list-{self.season}.json')
        if not os.path.exists(ratings_file):
            raise FileNotFoundError(f"Ratings file not found: {ratings_file}")
            
        with open(ratings_file, 'r', encoding='utf-8') as f:
            ratings_data = json.load(f)
            
        # Create member dict from ratings list
        for member in ratings_data:
            self.member_dict[member['id']] = member['klass']
            
        # Load remainder members
        remainder_file = os.path.join(self.data_dir, 'remainder.json')
        if os.path.exists(remainder_file):
            with open(remainder_file, 'r', encoding='utf-8') as f:
                remainder_data = json.load(f)
                
            # Add remainder members with class "E"
            for member_id in remainder_data.get('remainder', []):
                self.member_dict[int(member_id)] = "E"
                
    def clean_tournaments_directory(self) -> None:
        """Remove files from season tournaments directory."""
        season_dir = os.path.join(self.tournaments_dir, str(self.season))
        pattern = os.path.join(season_dir, f'{self.season}*.json*')
        files_to_remove = glob.glob(pattern)
        
        for file_path in files_to_remove:
            try:
                os.remove(file_path)
                print(f"Removed: {file_path}")
            except OSError as e:
                print(f"Error removing {file_path}: {e}")
                
    def fetch_tournament_details(self, tournament_id: str) -> Dict[str, Any]:
        """Fetch tournament details from API."""
        return self._fetch_json(TOURNAMENT_URL.format(tournament_id), f"tournament {tournament_id}")
            
    def fetch_group_results(self, group_id: int) -> List[Dict[str, Any]]:
        """Fetch results for a specific group."""
        return self._fetch_json(GROUP_TABLE_URL.format(group_id), f"results for group {group_id}")

    def _fetch_json(self, url: str, description: str) -> Any:
        """Fetch JSON, raising TournamentFetchError on any failure."""
        try:
            response = requests.get(url, timeout=30)
            response.raise_for_status()
            return response.json()
        except (requests.RequestException, ValueError) as e:
            raise TournamentFetchError(f"Cannot fetch {description}: {e}")
            
    def process_tournament_results(self, tournament_data: Dict[str, Any], tournament_config: Dict[str, Any]) -> None:
        """Process results for a single tournament."""
        tournament_id = tournament_data['id']
        if not has_been_played(tournament_data, datetime.now().date()):
            print(f"Tournament {tournament_id} starts {tournament_data['start']}; skipped until it has been played")
            return

        group_tables = [self.fetch_group_results(group_id) for group_id in group_ids(tournament_data)]
        processed_results = member_results(group_tables, self.member_dict)
            
        # Save results to file in season directory
        if processed_results:
            start_date_formatted = datetime.strptime(tournament_data['start'], '%Y-%m-%d').strftime('%Y%m%d')
            filename = f"{start_date_formatted}-{tournament_id}.json"
            
            # Create season directory if it doesn't exist
            season_dir = os.path.join(self.tournaments_dir, str(self.season))
            os.makedirs(season_dir, exist_ok=True)
            
            filepath = os.path.join(season_dir, filename)
            
            with open(filepath, 'w', encoding='utf-8') as f:
                json.dump(processed_results, f, ensure_ascii=False, indent=2)
                
            print(f"Saved {len(processed_results)} results to {filename}")
        else:
            print(f"No results found for tournament {tournament_id}")

    def process_all_tournaments(self) -> None:
        """Process all tournaments for the specified season."""
        # Only the 2025 capture replay calls this, with the capture's saved `config` package
        from config.manager import get_tournaments, update_tournament

        # Load member data first
        self.load_member_data()
        print(f"Loaded {len(self.member_dict)} members")

        # Clean tournaments directory
        self.clean_tournaments_directory()

        # Get tournaments from config and filter by season
        all_tournaments = get_tournaments()
        tournaments = [t for t in all_tournaments if t.get('season') == self.season]

        if not tournaments:
            print(f"No tournaments found for season {self.season}")
            return

        print(f"Found {len(tournaments)} tournaments for season {self.season}")
        config_changed = False

        for tournament_config in tournaments:
            tournament_id = tournament_config['id']
            print(f"Processing tournament {tournament_id}...")

            # Fetch tournament details
            # Leave out a tournament that cannot be fetched or has a malformed row
            try:
                tournament_data = self.fetch_tournament_details(tournament_id)
                tournament_name = tournament_data['name']
            except (TournamentFetchError, KeyError, TypeError) as e:
                print(f"Warning: tournament {tournament_id} left out: {e}")
                continue

            # Update tournament name if needed
            if tournament_config.get('name') != tournament_name:
                update_tournament(tournament_id, name=tournament_name)
                config_changed = True
                print(f"Updated tournament name: {tournament_name}")

            # The configured scoring type is the operator's choice; never recompute it here

            try:
                self.process_tournament_results(tournament_data, tournament_config)
            except (TournamentFetchError, KeyError, TypeError) as e:
                print(f"Warning: tournament {tournament_id} left out: {e}")

        if config_changed:
            print("Tournament configuration updated")
            
    def run(self) -> None:
        """Main entry point for processing."""
        print(f"Starting results processing for season {self.season}")
        try:
            self.process_all_tournaments()
            print("Processing completed successfully")
        except Exception as e:
            print(f"Error during processing: {e}")
            raise


def process_results(season: Optional[int] = None) -> None:
    """Convenient function to process results."""
    processor = ResultsProcessor(season)
    processor.run()