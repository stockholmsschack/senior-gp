"""
Main processor class for the Rilton Tournament Processor Module
"""

import json
import os

from .exceptions import RiltonProcessorError
from .data_validator import DataValidator
from .excel_parser import ExcelParser


class RiltonProcessor:
    """Main processor class for Rilton tournament data"""
    
    def __init__(self, season: int, data_directory: str = "data"):
        """
        Initialize the processor
        
        Args:
            season: Season parameter (e.g., 2024 for 2024-2025 season)
            data_directory: Directory containing the data files
        """
        self.season = season
        self.data_directory = data_directory
        self.validator = DataValidator(season, data_directory)
        self.ratings_data = {}
    
    def process(self) -> str:
        """
        Main processing method that combines data from both Excel files
        
        Returns:
            Path to the generated JSON output file
            
        Raises:
            RiltonProcessorError: If processing fails
        """
        try:
            # Validate files exist
            u1800_file, u2200_file, ratings_file = self.validator.validate_files()
            
            # Load ratings data
            self.ratings_data = self.validator.load_ratings_data(ratings_file)
            
            # Create Excel parser with ratings data and season
            excel_parser = ExcelParser(self.ratings_data, self.season)
            
            # Process both Excel files
            u1800_data = excel_parser.process_excel_file(u1800_file)
            u2200_data = excel_parser.process_excel_file(u2200_file)
            
            # Combine data
            combined_data = u1800_data + u2200_data

            # Write output JSON to season directory
            tournaments_dir = os.path.join(os.path.dirname(self.data_directory), "tournaments")
            season_dir = os.path.join(tournaments_dir, str(self.season))
            os.makedirs(season_dir, exist_ok=True)
            
            output_file = os.path.join(season_dir, f"rilton-{self.season}.json")

            with open(output_file, 'w', encoding='utf-8') as f:
                json.dump(combined_data, f, ensure_ascii=False, indent=2)
            
            return output_file
            
        except Exception as e:
            if isinstance(e, RiltonProcessorError):
                raise
            else:
                raise RiltonProcessorError(f"Unexpected error during processing: {e}")