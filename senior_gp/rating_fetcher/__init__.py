"""
Rating Fetcher Module

A robust module for fetching and preprocessing rating data from the Swedish Chess Federation API.
"""

from .processor import RatingProcessor
from .exceptions import RatingFetcherError, APIError
from typing import Dict, List, Any


def fetch_rating_data(year: int, data_directory: str = "data", process_rilton: bool = False, fetch_remainder: bool = True) -> str:
    """
    Convenience function for fetching and processing rating data
    
    Args:
        year: 4-digit year parameter
        data_directory: Directory to store the processed data files
        process_rilton: Whether to automatically run rilton processor after fetching
        fetch_remainder: Whether to also fetch remainder data (new members since Jan 1st)
        
    Returns:
        Path to the generated JSON output file
        
    Raises:
        RatingFetcherError: If fetching or processing fails
    """
    processor = RatingProcessor(year, data_directory)
    output_file = processor.process(fetch_remainder=fetch_remainder)
    
    if process_rilton:
        try:
            from ..rilton_processor import process_rilton_data
            rilton_output = process_rilton_data(year, data_directory)
            return f"Rating data: {output_file}, Rilton data: {rilton_output}"
        except ImportError:
            raise RatingFetcherError("Cannot import rilton_processor for chained processing")
        except Exception as e:
            raise RatingFetcherError(f"Error in chained rilton processing: {e}")
    
    return output_file


# Module-level exports
__all__ = ['RatingProcessor', 'RatingFetcherError', 'APIError', 'fetch_rating_data']