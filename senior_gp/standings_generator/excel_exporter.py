"""
Excel export functionality for tournament standings.
"""

import os
from collections.abc import Sequence
from datetime import date, datetime
from io import BytesIO
from typing import Dict

import xlsxwriter

from ..chess_results import tournament_url
from ..configuration import RILTON, Tournament
from .models import PlayerDetails, PlayerStanding


def workbook_names(season: int, generated_on: date) -> tuple[str, str]:
    """Return the validation and clean workbook filenames."""
    day = generated_on.strftime('%Y%m%d')
    return f'{season}-gp-standings-validations-{day}.xlsx', f'{season}-gp-standings-{day}.xlsx'


class ExcelExporter:
    """Handles Excel export of tournament standings."""

    def __init__(self, player_standings: Dict[str, Dict[int, PlayerStanding]], season: int,
                 tournaments: Sequence[Tournament] = (), players: Sequence[PlayerDetails] | None = None):
        """
        Initialize the Excel exporter.

        Args:
            player_standings: Dictionary of player standings by klass
            season: Tournament season (4-digit year)
            tournaments: The tournaments the standings count, in order of date
                of play. A first sheet named Turneringar lists them, and the
                class sheets' result columns follow their order. The legacy
                replay passes none, gets no such sheet, and sorts its columns.
            players: Participant identities and January membership details for
                the sortable Spelare sheet. None omits the sheet in legacy exports.
        """
        self.player_standings = player_standings
        self.season = season
        self.tournaments = tuple(tournaments)
        self.players = players

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

        validation_filename, clean_filename = workbook_names(self.season, datetime.now().date())

        # Export detailed validation file
        validation_filepath = os.path.join(output_dir, validation_filename)
        self.export_detailed(validation_filepath)

        # Export clean version
        clean_filepath = os.path.join(output_dir, clean_filename)
        self.export_clean(clean_filepath)

        return validation_filepath, clean_filepath

    def render(self, generated_on: date) -> Dict[str, bytes]:
        """Return the validation and clean workbooks by filename, without writing files."""
        validation_filename, clean_filename = workbook_names(self.season, generated_on)
        workbooks = {}
        for filename, export in ((validation_filename, self.export_detailed),
                                 (clean_filename, self.export_clean)):
            buffer = BytesIO()
            export(buffer)
            workbooks[filename] = buffer.getvalue()
        return workbooks

    def tournament_columns(self, klass: str) -> list[str]:
        """Return the class's result columns: member-system IDs and `rilton` for the pooled Rilton event.

        They follow the order of `self.tournaments`, the date of play. Keys not in it, such as every key in the
        legacy replay, which passes no tournaments, follow in sorted order."""
        keys = set()
        for player in self.player_standings[klass].values():
            keys.update(player.tournament_results.keys())
        order = list(dict.fromkeys('rilton' if tournament.source == RILTON else tournament.id
                                   for tournament in self.tournaments))
        return [key for key in order if key in keys] + sorted(keys - set(order))

    def write_tournaments(self, workbook, header_format, regular_format) -> None:
        """
        Add the Turneringar sheet: each tournament's name, then its member-system
        ID or, for a Rilton section, its chess-results link.
        """
        if not self.tournaments:
            return
        worksheet = workbook.add_worksheet('Turneringar')
        worksheet.write_row(0, 0, ['Turnering', 'Turnerings-ID', 'Länk'], header_format)
        for row_idx, tournament in enumerate(self.tournaments, 1):
            worksheet.write(row_idx, 0, tournament.name, regular_format)
            if tournament.source == RILTON:
                worksheet.write_url(row_idx, 2, tournament_url(tournament.id))
            else:
                worksheet.write_number(row_idx, 1, int(tournament.id), regular_format)
        worksheet.autofit()

    def write_players(self, workbook) -> None:
        """List participants in a table with Excel's sorting and filtering controls."""
        if self.players is None:
            return
        worksheet = workbook.add_worksheet('Spelare')
        headers = ['FIDE-ID', 'Medlems-ID', 'Namn',
                   f'Stockholmsklubb (1 jan {self.season})', f'Rating (1 jan {self.season})']
        rows = [[player.fide_id, player.member_id, player.name, player.january_club, player.january_rating]
                for player in sorted(self.players, key=lambda player: (player.name.casefold(), player.member_id))]
        if rows:
            worksheet.add_table(0, 0, len(rows), len(headers) - 1, {
                'name': 'Spelare', 'columns': [{'header': header} for header in headers], 'data': rows,
            })
        else:
            worksheet.write_row(0, 0, headers)
        worksheet.freeze_panes(1, 0)
        worksheet.autofit()

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
            self.write_tournaments(workbook, header_format, regular_format)

            for klass in ['A', 'B', 'C', 'D', 'E']:
                if not self.player_standings[klass]:
                    continue

                worksheet = workbook.add_worksheet(f'Klass_{klass}')

                tournament_columns = self.tournament_columns(klass)

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

            self.write_players(workbook)

    def export_clean(self, filepath: str) -> None:
        """
        Export formatted standings, tournaments and participant details.
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
            self.write_tournaments(workbook, header_format, regular_format)

            for klass in ['A', 'B', 'C', 'D', 'E']:
                if not self.player_standings[klass]:
                    continue

                worksheet = workbook.add_worksheet(f'Klass_{klass}')

                tournament_columns = self.tournament_columns(klass)

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

            self.write_players(workbook)

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
