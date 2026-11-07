"""
API client for fetching rating data from Swedish Chess Federation
"""

import requests
import time
from datetime import datetime
from typing import List, Dict, Any
from .exceptions import APIError


class RatingAPIClient:
    """Client for interacting with the Swedish Chess Federation rating API"""
    
    BASE_URL = "https://member.schack.se/public/api/v1/ratinglist/district/5821/date"
    MAX_RETRIES = 3
    RETRY_DELAY = 2  # seconds
    
    def __init__(self, timeout: int = 30):
        """
        Initialize the API client
        
        Args:
            timeout: Request timeout in seconds
        """
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'RatingFetcher/1.0.0',
            'Accept': 'application/json'
        })
    
    def fetch_ratings(self, year: int) -> List[Dict[str, Any]]:
        """
        Fetch rating data for a specific year (January 1st)
        
        Args:
            year: 4-digit year
            
        Returns:
            List of player dictionaries from the API
            
        Raises:
            APIError: If the API call fails after retries
        """
        # Format date as YYYY-01-01
        date_str = f"{year}-01-01"
        return self._fetch_ratings_for_date(date_str)
    
    def fetch_ratings_for_today(self) -> List[Dict[str, Any]]:
        """
        Fetch rating data for today's date
        
        Returns:
            List of player dictionaries from the API
            
        Raises:
            APIError: If the API call fails after retries
        """
        # Format today's date as YYYY-MM-DD
        today_str = datetime.now().strftime("%Y-%m-%d")
        return self._fetch_ratings_for_date(today_str)
    
    def _fetch_ratings_for_date(self, date_str: str) -> List[Dict[str, Any]]:
        """
        Fetch rating data for a specific date
        
        Args:
            date_str: Date in YYYY-MM-DD format
            
        Returns:
            List of player dictionaries from the API
            
        Raises:
            APIError: If the API call fails after retries
        """
        url = f"{self.BASE_URL}/{date_str}/ratingtype/1/category/0"
        
        last_exception = None
        
        for attempt in range(1, self.MAX_RETRIES + 1):
            try:
                response = self.session.get(url, timeout=self.timeout)
                response.raise_for_status()
                
                data = response.json()
                
                if not isinstance(data, list):
                    raise APIError(f"Expected list response, got {type(data)}")
                
                return data
                
            except requests.exceptions.Timeout as e:
                last_exception = e
                error_msg = f"Timeout on attempt {attempt}/{self.MAX_RETRIES}"
                
            except requests.exceptions.ConnectionError as e:
                last_exception = e
                error_msg = f"Connection error on attempt {attempt}/{self.MAX_RETRIES}"
                
            except requests.exceptions.HTTPError as e:
                last_exception = e
                error_msg = f"HTTP error {e.response.status_code} on attempt {attempt}/{self.MAX_RETRIES}"
                
            except requests.exceptions.RequestException as e:
                last_exception = e
                error_msg = f"Request error on attempt {attempt}/{self.MAX_RETRIES}"
                
            except ValueError as e:
                # JSON decode error
                raise APIError(f"Invalid JSON response from API: {e}")
            
            # If this wasn't the last attempt, wait before retrying
            if attempt < self.MAX_RETRIES:
                print(f"Warning: {error_msg}. Retrying in {self.RETRY_DELAY} seconds...")
                time.sleep(self.RETRY_DELAY)
        
        # All retries failed
        raise APIError(f"Failed to fetch rating data after {self.MAX_RETRIES} attempts. Last error: {last_exception}")
    
    def __enter__(self):
        """Context manager entry"""
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit - close session"""
        self.session.close()