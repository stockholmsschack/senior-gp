"""
Excel export functionality for tournament standings.
"""

import os
from datetime import datetime
from typing import Dict

import xlsxwriter

from .models import PlayerStanding


class ExcelExporter:
    """Handles Excel export of tournament standings."""

    def __init__(self, player_standings: Dict[str, Dict[int, PlayerStanding]], season: int):
        """
        Initialize the Excel exporter.

        Args:
            player_standings: Dictionary of player standings by klass
            season: Tournament season (4-digit year)
        """
        self.player_standings = player_standings
        self.season = season

    def export_all(self, output_dir: str = 'output') -> tuple[str, str]:
        """
        Export both detailed and clean Excel files.

        Args:
            output_dir: Directory to save Excel files

        Returns:
            Tuple of (detailed_filepath, clean_filepath)
        """
        # Ensure output directory exists
        os.makedirs(output_dir, exist_ok=True)

        today = datetime.now().strftime('%Y%m%d')

        # Export detailed validation file
        validation_filename = f'{self.season}-gp-standings-validations-{today}.xlsx'
        validation_filepath = os.path.join(output_dir, validation_filename)
        self.export_detailed(validation_filepath)

        # Export clean version
        clean_filename = f'{self.season}-gp-standings-{today}.xlsx'
        clean_filepath = os.path.join(output_dir, clean_filename)
        self.export_clean(clean_filepath)

        return validation_filepath, clean_filepath

    def export_detailed(self, filepath: str) -> None:
        """
        Export detailed validation Excel file with all tournament data.
        Values of -1 are displayed as 0 in red. Natural 0s are shown in black.

        Args:
            filepath: Path to save the Excel file
        """
        with xlsxwriter.Workbook(filepath) as workbook:
            # Shared formats
            header_format = workbook.add_format({'font_name': 'Calibri', 'bold': True})
            regular_format = workbook.add_format({'font_name': 'Calibri'})
            neg_one_format = workbook.add_format({'font_name': 'Calibri', 'font_color': 'red'})
            bold_neg_one_format = workbook.add_format({'font_name': 'Calibri', 'bold': True, 'font_color': 'red'})

            for klass in ['A', 'B', 'C', 'D', 'E']:
                if not self.player_standings[klass]:
                    continue

                worksheet = workbook.add_worksheet(f'Klass_{klass}')

                # Get all tournament keys for columns
                all_tournaments = set()
                for player in self.player_standings[klass].values():
                    all_tournaments.update(player.tournament_results.keys())

                tournament_columns = sorted(all_tournaments)

                # Build headers
                headers = ['Rank', 'ContenderID', 'Name', 'Klass']
                for tournament_key in tournament_columns:
                    headers += [
                        f'{tournament_key}_Points',
                        f'{tournament_key}_TB1',
                        f'{tournament_key}_TB2',
                        f'{tournament_key}_TB3',
                        f'{tournament_key}_Standings',
                    ]
                headers.append('Sigma')

                worksheet.write_row(0, 0, headers, header_format)

                for row_idx, player in enumerate(
                        sorted(self.player_standings[klass].values(), key=lambda p: p.final_rank), 1
                ):
                    col_idx = 0

                    def write_cell(value, bold=False):
                        nonlocal col_idx
                        if value == -1:
                            fmt = bold_neg_one_format if bold else neg_one_format
                            worksheet.write(row_idx, col_idx, 0, fmt)
                        elif value is None:
                            worksheet.write_blank(row_idx, col_idx, None, regular_format)
                        else:
                            fmt = header_format if bold else regular_format
                            worksheet.write(row_idx, col_idx, value, fmt)
                        col_idx += 1

                    write_cell(player.final_rank)
                    write_cell(player.contender_id)
                    write_cell(player.name)
                    write_cell(player.klass)

                    for tournament_key in tournament_columns:
                        if tournament_key in player.tournament_results:
                            result = player.tournament_results[tournament_key]
                            write_cell(result.points)
                            write_cell(result.tie_break_1)
                            write_cell(result.tie_break_2)
                            write_cell(result.tie_break_3)
                            write_cell(result.standings_points)
                        else:
                            for _ in range(5):
                                write_cell(None)

                    write_cell(player.total_standings_points, bold=True)

                worksheet.autofit()

    def export_clean(self, filepath: str) -> None:
        """
        Export clean formatted Excel file with tournament standings only.
        Values of -1 are displayed as 0 in red. Natural 0s are shown in black.
        Uses xlsxwriter for formatting.

        Args:
            filepath: Path to save the Excel file
        """
        with xlsxwriter.Workbook(filepath) as workbook:
            # Shared formats (created once, reused across all sheets)
            header_format = workbook.add_format({'font_name': 'Calibri', 'bold': True})
            regular_format = workbook.add_format({'font_name': 'Calibri'})
            neg_one_format = workbook.add_format({'font_name': 'Calibri', 'font_color': 'red'})
            bold_neg_one_format = workbook.add_format({'font_name': 'Calibri', 'bold': True, 'font_color': 'red'})

            for klass in ['A', 'B', 'C', 'D', 'E']:
                if not self.player_standings[klass]:
                    continue

                worksheet = workbook.add_worksheet(f'Klass_{klass}')

                # Get all tournament keys and create headers (preserve exact logic)
                all_tournaments = set()
                for player in self.player_standings[klass].values():
                    all_tournaments.update(player.tournament_results.keys())

                tournament_columns = sorted(all_tournaments)

                # Create headers with proper labeling
                headers = ['Rank', 'ContenderID', 'Name']
                tournament_counter = 1

                for tournament_key in tournament_columns:
                    if tournament_key == 'rilton':
                        headers.append('R')
                    else:
                        headers.append(str(tournament_counter))
                        tournament_counter += 1

                headers.append('Σ')

                # Write headers
                worksheet.write_row(0, 0, headers, header_format)

                # Write player data
                for row_idx, player in enumerate(sorted(self.player_standings[klass].values(),
                                                        key=lambda p: p.final_rank), 1):

                    # Basic player info
                    worksheet.write(row_idx, 0, player.final_rank, regular_format)
                    worksheet.write(row_idx, 1, player.contender_id, regular_format)
                    worksheet.write(row_idx, 2, player.name, regular_format)

                    # Tournament standings
                    col_idx = 3
                    for tournament_key in tournament_columns:
                        if tournament_key in player.tournament_results:
                            standings = player.tournament_results[tournament_key].standings_points
                            if standings == -1:
                                worksheet.write(row_idx, col_idx, 0, neg_one_format)
                            else:
                                worksheet.write(row_idx, col_idx, round(standings, 2), regular_format)
                        else:
                            worksheet.write(row_idx, col_idx, '', regular_format)
                        col_idx += 1

                    # Sigma column (total standings points)
                    sigma = player.total_standings_points
                    if sigma == -1:
                        worksheet.write(row_idx, col_idx, 0, bold_neg_one_format)
                    else:
                        worksheet.write(row_idx, col_idx, round(sigma, 2), header_format)

                # Auto-adjust column widths
                worksheet.autofit()

    def get_tournament_summary(self) -> Dict[str, int]:
        """
        Get summary statistics of processed tournaments.
        
        Returns:
            Dictionary with klass names and player counts
        """
        summary = {}
        for klass in ['A', 'B', 'C', 'D', 'E']:
            summary[f'Klass_{klass}'] = len(self.player_standings[klass])

        return summary