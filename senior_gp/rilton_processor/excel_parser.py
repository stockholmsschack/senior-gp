"""
Excel parsing utilities for the Rilton Tournament Processor Module
"""

import os
import xlrd
from typing import Dict, List, Any, Set

from .exceptions import RiltonProcessorError
from .models import ProcessedData, RatingsData
from .pooling import match_members


class ExcelParser:
    """Handles Excel file parsing and data extraction"""
    
    # Unicode fraction map from original basic.py
    UNICODE_FRACTIONS = {
        '½': 0.5,
        '⅓': 1/3,
        '⅔': 2/3,
        '¼': 0.25,
        '¾': 0.75,
        '⅕': 0.2,
        '⅖': 0.4,
        '⅗': 0.6,
        '⅘': 0.8,
        '⅙': 1/6,
        '⅚': 5/6,
        '⅛': 0.125,
        '⅜': 0.375,
        '⅝': 0.625,
        '⅞': 0.875,
    }
    
    def __init__(self, ratings_data: RatingsData, year: int):
        self.rating = None
        self.ratings_data = ratings_data
        self.year = year
    
    def validate_tournament_header(self, sheet, file_path: str):
        """
        Validate that A1 contains the correct tournament header
        
        Args:
            sheet: xlrd sheet object
            file_path: Path to Excel file (to extract rating)
            
        Raises:
            RiltonProcessorError: If A1 header doesn't match expected format
        """
        # Extract rating from filename
        filename = os.path.basename(file_path).lower()
        if 'u1800' in filename:
            self.rating = '1800'
        elif 'u2200' in filename:
            self.rating = '2200'
        else:
            raise RiltonProcessorError(f"Cannot determine rating category from filename: {file_path}")
        
        # Check A1 cell
        if sheet.nrows == 0 or sheet.ncols == 0:
            raise RiltonProcessorError(f"Excel file is empty: {file_path}")
        
        a1_value = sheet.cell_value(0, 0)  # Row 0, Column 0 = A1
        expected_header = f"Rilton U{self.rating} {self.year}/{self.year + 1}"
        
        if not isinstance(a1_value, str) or a1_value.strip() != expected_header:
            raise RiltonProcessorError(
                f"Invalid tournament header in {file_path}. "
                f"Expected: '{expected_header}', Found: '{a1_value}'"
            )
    
    def parse_unicode_fraction(self, value: Any) -> Any:
        """
        Parse unicode fractions from cell values
        
        Args:
            value: Cell value that might contain unicode fractions
            
        Returns:
            Converted numeric value or original value
        """
        if not isinstance(value, str):
            return value
        value = value.strip()
        if not value:
            return value

        for frac_char, frac_val in self.UNICODE_FRACTIONS.items():
            if frac_char in value:
                try:
                    parts = value.split(frac_char)
                    whole = int(parts[0]) if parts[0] else 0
                    return whole + frac_val
                except ValueError:
                    return value
        try:
            return float(value)
        except ValueError:
            return value
    
    def find_header_row(self, sheet) -> int:
        """
        Find the row containing headers (first row after "Rank" in column A)
        
        Args:
            sheet: xlrd sheet object
            
        Returns:
            Row index of the header row
            
        Raises:
            RiltonProcessorError: If "Rank" row not found
        """
        for row_idx in range(sheet.nrows):
            cell_value = sheet.cell_value(row_idx, 0)  # Column A (index 0)
            if isinstance(cell_value, str) and "Rank" in cell_value:
                return row_idx  # Return next row as header row
        
        raise RiltonProcessorError("Could not find 'Rank' row in Excel file")
    
    def find_fide_column(self, sheet, header_row: int) -> int:
        """
        Find the column containing "Fide-No."
        
        Args:
            sheet: xlrd sheet object
            header_row: Row index of headers
            
        Returns:
            Column index of Fide-No. column
            
        Raises:
            RiltonProcessorError: If "Fide-No." column not found
        """
        row_values = sheet.row_values(header_row)
        for col_idx, value in enumerate(row_values):
            if isinstance(value, str) and "Fide-No" in value:
                return col_idx
        
        raise RiltonProcessorError("Could not find 'Fide-No.' column in Excel file")
    
    def process_excel_file(self, file_path: str) -> ProcessedData:
        """Return district members' rows from one section file, with their rating data."""
        return match_members(self.read_rows(file_path), self.ratings_data)

    def read_rows(self, file_path: str) -> List[Dict[str, Any]]:
        """
        Return every player row of one section file, keyed by column header.

        Raises:
            RiltonProcessorError: If file cannot be processed
        """
        try:
            workbook = xlrd.open_workbook(file_path)
            sheet = workbook.sheet_by_index(0)
            
            # Validate tournament header in A1
            self.validate_tournament_header(sheet, file_path)
            
            # Find header row and Fide column
            header_row = self.find_header_row(sheet)
            fide_col = self.find_fide_column(sheet, header_row)
            
            # Get all headers
            raw_headers = sheet.row_values(header_row)
            headers = []
            for i, h in enumerate(raw_headers):
                if h == "" and i == 2:
                    headers.append("title")
                else:
                    headers.append(h)
            
            # Define field processing rules
            force_int_fields: Set[str] = {"Fide-No.", "Rank", "Rtg"}
            parse_fraction_fields: Set[str] = {"Pts", "PS", "BH/C1", "BH"}
            
            rows: List[Dict[str, Any]] = []
            
            # Process data rows
            for row_idx in range(header_row + 1, sheet.nrows):
                row = sheet.row_values(row_idx)
                if not any(cell != "" and cell is not None for cell in row):
                    continue
                
                row_dict = dict(zip(headers, row[:len(headers)]))
                
                # Process special fields
                for key in headers:
                    val = row_dict.get(key)
                    
                    if key in force_int_fields:
                        try:
                            if isinstance(val, str):
                                val = float(val.strip())
                            row_dict[key] = int(val)
                        except (ValueError, TypeError):
                            continue
                    
                    elif key in parse_fraction_fields:
                        row_dict[key] = self.parse_unicode_fraction(val)
                
                rows.append(row_dict)
            
            return rows
            
        except Exception as e:
            raise RiltonProcessorError(f"Error processing Excel file {file_path}: {e}")
