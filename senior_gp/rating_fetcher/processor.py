"""
Main processor for fetching and transforming rating data
"""

import json
import os
from typing import List, Dict, Any, Set
from .api_client import RatingAPIClient
from .models import KlassClassifier
from .exceptions import RatingFetcherError, ProcessingError


def _standard_elo(player: Dict[str, Any]):
    """Return the standard Elo, or None when the record has none."""
    elo = player.get('elo')
    return elo.get('rating') if isinstance(elo, dict) else None


def merge_duplicate_members(players: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Keep one record per member ID, preferring the one with a standard Elo.

    Raises ProcessingError when two records give different standard Elo.
    """
    merged: Dict[Any, Dict[str, Any]] = {}
    for player in players:
        member_id = player.get('id')
        kept = merged.get(member_id)
        if kept is None:
            merged[member_id] = player
            continue
        kept_elo, new_elo = _standard_elo(kept), _standard_elo(player)
        if kept_elo is not None and new_elo is not None and kept_elo != new_elo:
            raise ProcessingError(
                f"Member {member_id} appears twice with different standard Elo: {kept_elo} and {new_elo}"
            )
        if kept_elo is None and new_elo is not None:
            merged[member_id] = player
    return list(merged.values())


def classify_members(players: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Return copies of the players with 'klass' set from standard Elo. Missing Elo gives class E.

    Raises ProcessingError for an unreadable Elo value.
    """
    processed_players = []
    
    for i, player in enumerate(players):
        try:
            # Create a copy to avoid modifying the original
            processed_player = player.copy()
            
            # Extract ELO rating for classification
            elo_data = player.get('elo')
            if elo_data is None:
                elo_data = {}
            if not isinstance(elo_data, dict):
                raise ProcessingError(f"Player {i}: Invalid elo data structure")
            
            rating = elo_data.get('rating', 0)
            if rating is None:
                rating = 0
            if not isinstance(rating, (int, float)):
                raise ProcessingError(f"Player {i}: Invalid rating value: {rating}")
            
            # Add klass classification
            processed_player['klass'] = KlassClassifier.get_klass(int(rating))
            processed_players.append(processed_player)
            
        except KeyError as e:
            raise ProcessingError(f"Player {i}: Missing required field: {e}")
        except Exception as e:
            raise ProcessingError(f"Player {i}: Processing error: {e}")
    
    return processed_players


class RatingProcessor:
    """Main processor class for rating data fetching and transformation"""
    
    def __init__(self, year: int, data_directory: str = "data"):
        """
        Initialize the processor
        
        Args:
            year: 4-digit year parameter
            data_directory: Directory to store the processed data files
        """
        self.year = year
        self.data_directory = data_directory
        self.classifier = KlassClassifier()
        
        # Validate year
        if not isinstance(year, int) or year < 1900 or year > 2100:
            raise RatingFetcherError(f"Invalid year: {year}. Must be a 4-digit integer between 1900 and 2100.")
        
        # Ensure data directory exists
        if not os.path.exists(data_directory):
            try:
                os.makedirs(data_directory, exist_ok=True)
            except OSError as e:
                raise RatingFetcherError(f"Cannot create data directory '{data_directory}': {e}")
    
    def fetch_raw_data(self) -> List[Dict[str, Any]]:
        """
        Fetch raw rating data from the API
        
        Returns:
            List of player dictionaries from the API
            
        Raises:
            RatingFetcherError: If fetching fails
        """
        try:
            with RatingAPIClient() as client:
                return client.fetch_ratings(self.year)
        except Exception as e:
            raise RatingFetcherError(f"Failed to fetch rating data: {e}")
    
    def add_klass_classification(self, players: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Add klass classification to each player based on their ELO rating
        
        Args:
            players: List of player dictionaries from the API
            
        Returns:
            List of player dictionaries with klass field added
            
        Raises:
            ProcessingError: If data processing fails
        """
        return classify_members(players)
    
    def save_to_file(self, data: List[Dict[str, Any]]) -> str:
        """
        Save processed data to JSON file
        
        Args:
            data: Processed player data
            
        Returns:
            Path to the saved file
            
        Raises:
            RatingFetcherError: If file saving fails
        """
        output_file = os.path.join(self.data_directory, f"ratings_list-{self.year}.json")
        
        try:
            with open(output_file, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            
            # Verify file was created and has content
            if not os.path.exists(output_file):
                raise RatingFetcherError(f"Output file was not created: {output_file}")
            
            file_size = os.path.getsize(output_file)
            if file_size == 0:
                raise RatingFetcherError(f"Output file is empty: {output_file}")
            
            return output_file
            
        except IOError as e:
            raise RatingFetcherError(f"Cannot write to file {output_file}: {e}")
        except Exception as e:
            raise RatingFetcherError(f"Unexpected error saving file: {e}")
    
    def _load_january_data(self) -> List[Dict[str, Any]]:
        """
        Load January 1st data either from memory or from file
        
        Returns:
            List of player dictionaries from January 1st
            
        Raises:
            RatingFetcherError: If data cannot be loaded
        """
        # Try to read from existing file first
        january_file = self.get_output_filename()
        if os.path.exists(january_file):
            try:
                with open(january_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    if isinstance(data, list):
                        return data
                    else:
                        raise RatingFetcherError(f"Invalid data format in {january_file}")
            except (IOError, json.JSONDecodeError) as e:
                raise RatingFetcherError(f"Cannot read January data from {january_file}: {e}")
        else:
            # File doesn't exist, try to fetch from API
            try:
                return self.fetch_raw_data()
            except Exception as e:
                raise RatingFetcherError(f"Cannot load January data: file not found and API fetch failed: {e}")
    
    def _extract_member_ids(self, players: List[Dict[str, Any]]) -> Set[str]:
        """
        Extract member IDs from player data
        
        Args:
            players: List of player dictionaries
            
        Returns:
            Set of member IDs as strings
        """
        member_ids = set()
        for player in players:
            member_id = player.get('id')
            if member_id is not None:
                member_ids.add(str(member_id))
        return member_ids
    
    def fetch_remainder_data(self) -> List[Dict[str, Any]]:
        """
        Return today's district members who are not on the January list.

        A failure stops generation, because these members are eligible.
        """
        print("Loading January 1st data...")
        january_data = self._load_january_data()
        january_ids = self._extract_member_ids(january_data)
        print(f"Found {len(january_ids)} members in January data")

        print("Fetching today's rating data...")
        try:
            with RatingAPIClient() as client:
                today_data = client.fetch_ratings_for_today()
        except Exception as e:
            raise RatingFetcherError(f"Cannot fetch today's district list: {e}")

        remainder = {}
        for player in today_data:
            member_id = player.get('id')
            if member_id is not None and str(member_id) not in january_ids:
                remainder[str(member_id)] = {
                    'id': member_id,
                    'fideid': player.get('fideid'),
                    'firstName': player.get('firstName', ''),
                    'lastName': player.get('lastName', ''),
                }
        print(f"Found {len(remainder)} new members since January 1st")
        return [remainder[member_id] for member_id in sorted(remainder)]

    def save_remainder_data(self, members: List[Dict[str, Any]]) -> str:
        """
        Save new members as IDs and as records with FIDE IDs for Rilton matching.

        Args:
            members: Records returned by fetch_remainder_data

        Returns:
            Path to the saved remainder file

        Raises:
            RatingFetcherError: If file saving fails
        """
        remainder_file = os.path.join(self.data_directory, "remainder.json")
        remainder_data = {
            "remainder": [str(member['id']) for member in members],
            "members": members,
        }
        
        try:
            with open(remainder_file, 'w', encoding='utf-8') as f:
                json.dump(remainder_data, f, ensure_ascii=False, indent=2)
            
            print(f"Remainder data saved to: {remainder_file}")
            return remainder_file
            
        except IOError as e:
            raise RatingFetcherError(f"Cannot write remainder file {remainder_file}: {e}")
        except Exception as e:
            raise RatingFetcherError(f"Unexpected error saving remainder file: {e}")
    
    def process(self, fetch_remainder: bool = True) -> str:
        """
        Main processing method that fetches, processes, and saves rating data
        
        Args:
            fetch_remainder: Whether to also fetch and process remainder data
        
        Returns:
            Path to the generated JSON output file
            
        Raises:
            RatingFetcherError: If any step of processing fails
        """
        try:
            # Step 1: Fetch raw data from API
            print(f"Fetching rating data for year {self.year}...")
            raw_data = self.fetch_raw_data()
            
            if not raw_data:
                raise RatingFetcherError("No data received from API")
            
            print(f"Fetched {len(raw_data)} player records")
            
            # Step 2: Add klass classification
            print("Processing player classifications...")
            processed_data = self.add_klass_classification(merge_duplicate_members(raw_data))
            
            # Step 3: Save to file
            print(f"Saving to file...")
            output_file = self.save_to_file(processed_data)
            
            print(f"Successfully processed {len(processed_data)} players")
            print(f"Output saved to: {output_file}")
            
            # Step 4: Process remainder data if requested
            if fetch_remainder:
                print("\nProcessing remainder data...")
                self.save_remainder_data(self.fetch_remainder_data())
            
            return output_file
            
        except RatingFetcherError:
            # Re-raise our custom exceptions
            raise
        except Exception as e:
            # Wrap unexpected exceptions
            raise RatingFetcherError(f"Unexpected error during processing: {e}")
    
    def get_output_filename(self) -> str:
        """
        Get the expected output filename for this year
        
        Returns:
            Full path to the output file
        """
        return os.path.join(self.data_directory, f"ratings_list-{self.year}.json")
    
    def file_exists(self) -> bool:
        """
        Check if the output file already exists
        
        Returns:
            True if file exists, False otherwise
        """
        return os.path.exists(self.get_output_filename())
