"""
Rilton Tournament Processor Module

A robust module for processing Rilton tournament data from Excel files and ratings JSON.
"""

from .processor import RiltonProcessor
from .exceptions import RiltonProcessorError


def process_rilton_data(year: int, data_directory: str = "data") -> str:
    """
    Convenience function for processing Rilton data
    
    Args:
        year: 4-digit year parameter
        data_directory: Directory containing the data files
        
    Returns:
        Path to the generated JSON output file
        
    Raises:
        RiltonProcessorError: If processing fails
    """
    processor = RiltonProcessor(year, data_directory)
    return processor.process()


# Module-level exports - preserving the exact same public API
__all__ = ['RiltonProcessor', 'RiltonProcessorError', 'process_rilton_data']
