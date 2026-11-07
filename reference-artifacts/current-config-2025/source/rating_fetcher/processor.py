"""
Main processor for fetching and transforming rating data
"""

import json
import os
from typing import List, Dict, Any, Set
from .api_client import RatingAPIClient
from .models import KlassClassifier
from .exceptions import RatingFetcherError, ProcessingError


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
        processed_players = []
        
        for i, player in enumerate(players):
            try:
                # Create a copy to avoid modifying the original
                processed_player = player.copy()
                
                # Extract ELO rating for classification
                elo_data = player.get('elo', {})
                if not isinstance(elo_data, dict):
                    raise ProcessingError(f"Player {i}: Invalid elo data structure")
                
                rating = elo_data.get('rating', 0)
                if not isinstance(rating, (int, float)):
                    raise ProcessingError(f"Player {i}: Invalid rating value: {rating}")
                
                # Add klass classification
                processed_player['klass'] = self.classifier.get_klass(int(rating))
                processed_players.append(processed_player)
                
            except KeyError as e:
                raise ProcessingError(f"Player {i}: Missing required field: {e}")
            except Exception as e:
                raise ProcessingError(f"Player {i}: Processing error: {e}")
        
        return processed_players
    
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
    
    def fetch_remainder_data(self) -> List[str]:
        """
        Fetch today's rating data and compare with January 1st data to find new members
        
        Returns:
            List of member IDs that are present today but not on January 1st
        """
        try:
            # Load January 1st data
            print("Loading January 1st data...")
            january_data = self._load_january_data()
            january_ids = self._extract_member_ids(january_data)
            print(f"Found {len(january_ids)} members in January data")
            
            # Fetch today's data
            print("Fetching today's rating data...")
            with RatingAPIClient() as client:
                today_data = client.fetch_ratings_for_today()
            
            today_ids = self._extract_member_ids(today_data)
            print(f"Found {len(today_ids)} members in today's data")
            
            # Find members present today but not in January
            remainder_ids = today_ids - january_ids
            remainder_list = sorted(list(remainder_ids))
            
            print(f"Found {len(remainder_list)} new members since January 1st")
            return remainder_list
            
        except Exception as e:
            print(f"Error fetching remainder data: {e}")
            print("Writing empty remainder list")
            return []
    
    def save_remainder_data(self, remainder_ids: List[str]) -> str:
        """
        Save remainder data to JSON file
        
        Args:
            remainder_ids: List of member IDs for new members
            
        Returns:
            Path to the saved remainder file
            
        Raises:
            RatingFetcherError: If file saving fails
        """
        remainder_file = os.path.join(self.data_directory, "remainder.json")
        remainder_data = {"remainder": remainder_ids}
        
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
            processed_data = self.add_klass_classification(raw_data)
            
            # Step 3: Save to file
            print(f"Saving to file...")
            output_file = self.save_to_file(processed_data)
            
            print(f"Successfully processed {len(processed_data)} players")
            print(f"Output saved to: {output_file}")
            
            # Step 4: Process remainder data if requested
            if fetch_remainder:
                print("\nProcessing remainder data...")
                remainder_ids = self.fetch_remainder_data()
                self.save_remainder_data(remainder_ids)
            
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