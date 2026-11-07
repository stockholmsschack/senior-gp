"""
Main processor for generating tournament standings.
"""

import json
import os
import re
from typing import Dict, List, Optional
from collections import defaultdict

from .models import Tournament, TournamentResult, PlayerStanding
from .exceptions import StandingsGeneratorError, TournamentDataError, ConfigurationError
from .excel_exporter import ExcelExporter


# GP awards 10 to 1 points to the top 10 places. DM awards 15 to 1 points to the top 15.
GP_PLACES = 10
DM_PLACES = 15


def final_order_key(player: PlayerStanding) -> tuple[int, int]:
    """Order by total points descending, then by positive-scoring event count ascending."""
    scoring_events = sum(1 for result in player.tournament_results.values() if result.standings_points > 0)
    return (-player.total_standings_points, scoring_events)


class StandingsProcessor:
    """Processes tournament data and generates standings."""
    
    def __init__(self, season: int, tournament_filter: Optional[List[str]] = None):
        """
        Initialize the standings processor.
        
        Args:
            season: Tournament season to process
            tournament_filter: Optional list of tournament IDs to include
        """
        self.season = season
        self.tournament_filter = set(tournament_filter) if tournament_filter else None
        self.tournaments: Dict[str, Tournament] = {}
        self.player_standings: Dict[str, Dict[int, PlayerStanding]] = {
            klass: {} for klass in ['A', 'B', 'C', 'D', 'E']
        }
        
    def process_standings(self) -> Dict[str, Dict[int, PlayerStanding]]:
        """
        Main method to process all tournament standings.
        
        Returns:
            Dictionary of player standings by klass
        """
        print(f"Processing standings for season {self.season}")
        
        # Load tournament metadata
        self._load_tournaments_config()
        
        # Process Rilton tournament
        self._process_rilton_tournament()
        
        # Process other tournaments
        self._process_other_tournaments()
        
        # Calculate final standings
        self.calculate_final_standings()
        
        print("Standings processing completed successfully!")
        return self.player_standings

    def process_and_export(self, output_dir: str = 'output') -> tuple[str, str]:
        """
        Process standings and export to Excel files.

        Args:
            output_dir: Directory to save Excel files

        Returns:
            Tuple of (detailed_filepath, clean_filepath)
        """
        # Process the standings
        player_standings = self.process_standings()

        # Export to Excel - pass season to exporter
        exporter = ExcelExporter(player_standings, self.season)
        detailed_path, clean_path = exporter.export_all(output_dir)

        print(f"Excel files exported:")
        print(f"  - Detailed: {detailed_path}")
        print(f"  - Clean: {clean_path}")

        return detailed_path, clean_path

    def _load_tournaments_config(self) -> None:
        """Load tournament configuration from config/tournaments.json."""
        config_path = os.path.join('config', 'tournaments.json')
        
        if not os.path.exists(config_path):
            raise ConfigurationError(f"Tournament config file not found: {config_path}")
        
        try:
            with open(config_path, 'r', encoding='utf-8') as f:
                config_data = json.load(f)
            
            for tournament_data in config_data.get('tournaments', []):
                tournament = Tournament(
                    id=tournament_data['id'],
                    name=tournament_data['name'],
                    year=tournament_data['season'],  # Map season to year for Tournament model
                    dm=tournament_data.get('dm', False)
                )
                self.tournaments[tournament.id] = tournament
                
            print(f"Loaded {len(self.tournaments)} tournaments from config")
            
        except (json.JSONDecodeError, KeyError) as e:
            raise ConfigurationError(f"Invalid tournament config format: {e}")
    
    def _process_rilton_tournament(self) -> None:
        """Process Rilton tournament data."""
        # Check tournament filter - skip if Rilton not included
        if self.tournament_filter and 'rilton' not in self.tournament_filter:
            print("Skipping Rilton tournament (not in filter)")
            return
        
        season_dir = os.path.join('tournaments', str(self.season))
        rilton_file = os.path.join(season_dir, f'rilton-{self.season}.json')
        
        if not os.path.exists(rilton_file):
            print(f"Warning: Rilton file not found: {rilton_file}. Skipping Rilton tournament.")
            return
        
        try:
            with open(rilton_file, 'r', encoding='utf-8') as f:
                rilton_data = json.load(f)
            
            print(f"Processing Rilton tournament with {len(rilton_data)} players")
            self.add_rilton(rilton_data)
            print("Rilton tournament processed successfully")
            
        except (json.JSONDecodeError, IOError, TournamentDataError) as e:
            print(f"Warning: Rilton left out: {e}")
    
    def add_rilton(self, records: List[dict]) -> None:
        """Rank pooled Rilton records within each class and award GP points."""
        players_by_klass = defaultdict(list)
        for player_data in records:
            try:
                tournament_data = player_data['tournament_data']
                result = TournamentResult(
                    contender_id=player_data['contenderId'],
                    name=tournament_data['Name'],
                    klass=player_data['klass'],
                    points=float(tournament_data['Pts']),
                    tie_break_1=float(tournament_data.get('BH/C1', 0)),
                    tie_break_2=float(tournament_data.get('BH', 0)),
                    tie_break_3=float(tournament_data.get('PS', 0)),
                    penalty=bool(player_data.get('penalty', False)),
                )
            except (KeyError, ValueError, TypeError) as e:
                raise TournamentDataError(f"Invalid Rilton result row {player_data!r}: {e}")
            players_by_klass[result.klass].append(result)

        for players in players_by_klass.values():
            players.sort(key=lambda p: (-p.points, -p.tie_break_1, -p.tie_break_2, -p.tie_break_3))
            # A penalized player keeps the place, and nobody receives its points
            for rank, player in enumerate(players, 1):
                player.rank = rank
                if player.penalty:
                    player.standings_points = -1
                elif rank <= GP_PLACES:
                    player.standings_points = GP_PLACES + 1 - rank
            for player in players:
                self._add_player_result('rilton', player)
    
    def _process_other_tournaments(self) -> None:
        """Process other tournament files."""
        season_dir = os.path.join('tournaments', str(self.season))
        
        if not os.path.exists(season_dir):
            print(f"Season directory not found: {season_dir}")
            return
        
        # Find tournament files matching pattern YYYYMMDD-<tournament_id>.json
        pattern = re.compile(r'^\d{8}-(\d+)\.json$')
        tournament_files = []
        
        for filename in os.listdir(season_dir):
            match = pattern.match(filename)
            if match:
                tournament_id = match.group(1)
                tournament_files.append((filename, tournament_id))
        
        # Sort by filename for consistent processing order
        tournament_files.sort()
        
        print(f"Found {len(tournament_files)} other tournament files")
        
        for filename, tournament_id in tournament_files:
            # Apply tournament filter if specified
            if self.tournament_filter and tournament_id not in self.tournament_filter:
                print(f"Skipping tournament {tournament_id} (not in filter)")
                continue
                
            self._process_tournament_file(filename, tournament_id)
    
    def _process_tournament_file(self, filename: str, tournament_id: str) -> None:
        """Process a single tournament file."""
        season_dir = os.path.join('tournaments', str(self.season))
        filepath = os.path.join(season_dir, filename)
        
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                tournament_data = json.load(f)
            
            print(f"Processing tournament {tournament_id} ({filename}) with {len(tournament_data)} players")
            is_dm = self.tournaments.get(tournament_id, Tournament('', '', 0)).dm
            self.add_member_event(tournament_id, tournament_data, DM_PLACES if is_dm else GP_PLACES)
            print(f"Tournament {tournament_id} processed successfully")
            
        except (json.JSONDecodeError, IOError, TournamentDataError) as e:
            print(f"Warning: tournament {tournament_id} left out: {e}")
    
    def add_member_event(self, tournament_id: str, records: List[dict], places: int) -> None:
        """Rank one member-system event within each class. Place 1 scores `places` points, and each later place one fewer."""
        players_by_klass = defaultdict(list)
        for player_data in records:
            try:
                result = TournamentResult(
                    contender_id=player_data['contenderId'],
                    name=player_data['name'],
                    klass=player_data['klass'],
                    points=float(player_data['points']),
                    tie_break_1=float(player_data.get('secPoints', 0))
                )
            except (KeyError, ValueError, TypeError) as e:
                raise TournamentDataError(f"Invalid result row in tournament {tournament_id} {player_data!r}: {e}")
            players_by_klass[result.klass].append(result)

        for players in players_by_klass.values():
            players.sort(key=lambda p: (-p.points, -p.tie_break_1))
            for rank, player in enumerate(players, 1):
                player.rank = rank
                if rank <= places:
                    player.standings_points = places + 1 - rank
            for player in players:
                self._add_player_result(tournament_id, player)
    
    def _add_player_result(self, tournament_key: str, result: TournamentResult) -> None:
        """Add a player's tournament result to their overall standing."""
        klass = result.klass
        contender_id = result.contender_id
        
        if contender_id not in self.player_standings[klass]:
            self.player_standings[klass][contender_id] = PlayerStanding(
                contender_id=contender_id,
                name=result.name,
                klass=klass,
                tournament_results={}
            )
        
        self.player_standings[klass][contender_id].tournament_results[tournament_key] = result
    
    def calculate_final_standings(self) -> None:
        """Total each player's points and assign final ranks within each klass."""
        for klass in self.player_standings:
            players = list(self.player_standings[klass].values())
            
            # Recalculate total standings points and sort
            for player in players:
                player.total_standings_points = sum(
                    max(result.standings_points, 0)
                    for result in player.tournament_results.values()
                )
            
            # Fewer events with positive points break a tie; equal players share a rank
            players.sort(key=lambda p: (*final_order_key(p), p.name.casefold(), p.contender_id))
            previous = None
            for position, player in enumerate(players, 1):
                if previous and final_order_key(player) == final_order_key(previous):
                    player.final_rank = previous.final_rank
                else:
                    player.final_rank = position
                previous = player
            
            print(f"Klass {klass}: {len(players)} players processed")