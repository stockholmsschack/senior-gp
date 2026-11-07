"""
File validation utilities for the Rilton Tournament Processor Module
"""

import os
import json
from typing import Dict, List, Any

from .exceptions import RiltonProcessorError
from .models import FileValidationResult, RatingsData


class DataValidator:
    """Handles file validation and data loading for Rilton processor"""
    
    def __init__(self, year: int, data_directory: str):
        self.year = year
        self.data_directory = data_directory
    
    def validate_files(self) -> FileValidationResult:
        """
        Validate that all required files exist.

        Returns:
            Tuple of (u1800_file, u2200_file, ratings_file) paths

        Raises:
            RiltonProcessorError: If any required files are missing
        """
        u1800_file = self._find_case_insensitive_file(
            ["rilton", "u1800", str(self.year)]
        )
        u2200_file = self._find_case_insensitive_file(
            ["rilton", "u2200", str(self.year)]
        )

        # Check for ratings JSON file (case-sensitive, as filenames usually are)
        ratings_file = os.path.join(self.data_directory, f"ratings_list-{self.year}.json")
        if not os.path.exists(ratings_file):
            raise RiltonProcessorError(
                f"Required file not found: ratings_list-{self.year}.json in {self.data_directory}"
            )

        return u1800_file, u2200_file, ratings_file
    
    def _find_case_insensitive_file(self, substrings: List[str]) -> str:
        """
        Find a file matching the given substrings (case-insensitive)
        
        Args:
            substrings: List of substrings that must all be present in filename
            
        Returns:
            Full path to the matching file
            
        Raises:
            RiltonProcessorError: If no matching file is found
        """
        for filename in os.listdir(self.data_directory):
            lower_filename = filename.lower()
            if all(s in lower_filename for s in substrings) and lower_filename.endswith(".xls"):
                return os.path.join(self.data_directory, filename)
        
        raise RiltonProcessorError(
            f"Required file not found: pattern containing {substrings} in {self.data_directory}"
        )
    
    def load_ratings_data(self, ratings_file: str) -> RatingsData:
        """
        Load and index ratings data by fideid
        
        Args:
            ratings_file: Path to the ratings JSON file
            
        Returns:
            Dictionary mapping fideid to player data
            
        Raises:
            RiltonProcessorError: If file cannot be loaded or parsed
        """
        try:
            with open(ratings_file, 'r', encoding='utf-8') as f:
                ratings_list = json.load(f)
            
            if not isinstance(ratings_list, list):
                raise RiltonProcessorError("Ratings file must contain a JSON array")
            
            ratings_data: RatingsData = {}
            for player in ratings_list:
                if not isinstance(player, dict) or 'fideid' not in player:
                    continue
                fideid = player['fideid']
                if fideid:
                    ratings_data[fideid] = player
            
            return ratings_data
                    
        except json.JSONDecodeError as e:
            raise RiltonProcessorError(f"Invalid JSON in ratings file: {e}")
        except Exception as e:
            raise RiltonProcessorError(f"Error loading ratings file: {e}")