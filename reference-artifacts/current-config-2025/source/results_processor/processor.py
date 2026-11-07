import json
import os
import glob
import requests
from datetime import datetime
from typing import Dict, List, Optional, Any
from config.manager import get_tournaments, update_tournament, _save_config, _load_config

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
                
    def fetch_tournament_details(self, tournament_id: str) -> Optional[Dict[str, Any]]:
        """Fetch tournament details from API."""
        url = f"https://member.schack.se/public/api/v1/tournament/tournament/id/{tournament_id}"
        
        try:
            response = requests.get(url, timeout=30)
            response.raise_for_status()
            return response.json()
        except requests.RequestException as e:
            print(f"Error fetching tournament {tournament_id}: {e}")
            return None
            
    def fetch_group_results(self, group_id: int) -> List[Dict[str, Any]]:
        """Fetch results for a specific group."""
        url = f"https://member.schack.se/public/api/v1/tournamentresults/table/id/{group_id}"
        
        try:
            response = requests.get(url, timeout=30)
            response.raise_for_status()
            return response.json()
        except requests.RequestException as e:
            print(f"Error fetching results for group {group_id}: {e}")
            return []
            
    def process_tournament_results(self, tournament_data: Dict[str, Any], tournament_config: Dict[str, Any]) -> None:
        """Process results for a single tournament."""
        tournament_id = tournament_data['id']
        start_date_str = tournament_data['start']
        start_date = datetime.strptime(start_date_str, '%Y-%m-%d')
        
        # Check if tournament has started
        if start_date > datetime.now():
            print(f"Tournament {tournament_id} hasn't started yet, skipping results processing")
            return
            
        # Get all groups from all root classes
        all_results = []
        for root_class in tournament_data.get('rootClasses', []):
            for group in root_class.get('groups', []):
                group_results = self.fetch_group_results(group['id'])
                all_results.extend(group_results)
                
        # Process results for members in our member dict
        processed_results = []
        for result in all_results:
            contender_id = result['contenderId']
            
            if contender_id not in self.member_dict:
                continue  # Skip if not in our member dict
                
            player_info = result['playerInfo']
            processed_result = {
                'contenderId': contender_id,
                'name': f"{player_info['firstName']} {player_info['lastName']}",
                'points': result['points'],
                'secPoints': result['secPoints'],
                'klass': self.member_dict[contender_id]
            }
            processed_results.append(processed_result)
            
        # Save results to file in season directory
        if processed_results:
            start_date_formatted = start_date.strftime('%Y%m%d')
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
            tournament_data = self.fetch_tournament_details(tournament_id)
            if not tournament_data:
                continue

            # Update tournament name if needed
            tournament_name = tournament_data['name']
            if tournament_config.get('name') != tournament_name:
                update_tournament(tournament_id, name=tournament_name)
                config_changed = True
                print(f"Updated tournament name: {tournament_name}")

            # Update DM status if needed
            is_dm = "Stockholmsmästerskapet" in tournament_name
            if tournament_config.get('dm') != is_dm:
                update_tournament(tournament_id, dm=is_dm)
                config_changed = True
                print(f"Updated DM status to {is_dm}")

            # Process results
            self.process_tournament_results(tournament_data, tournament_config)

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