"""The player register uses January data and supports numeric Excel sorting."""

from datetime import date
from io import BytesIO
from xml.etree import ElementTree as ET
from zipfile import ZipFile

from senior_gp.generation import Membership, _player_details
from senior_gp.rating_fetcher.processor import merge_duplicate_members
from senior_gp.standings_generator.excel_exporter import ExcelExporter
from senior_gp.standings_generator.models import PlayerStanding

NS = {'s': 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}


def test_player_sheet_in_both_workbooks_uses_january_data_and_only_participants():
    january = (
        {'id': 1, 'fideid': 101, 'firstName': 'Zara', 'lastName': 'Andersson',
         'club': 'Stockholms SS', 'elo': {'rating': 2100}},
        {'id': 1, 'fideid': 101, 'firstName': 'Zara', 'lastName': 'Andersson',
         'club': 'SS 4 Springare', 'elo': {'rating': 2100}},
        {'id': 2, 'firstName': 'Anna', 'lastName': 'Berg', 'club': 'Stockholms SS', 'elo': None},
        {'id': 4, 'firstName': 'Absent', 'lastName': 'Player', 'elo': {'rating': 2300}},
    )
    joined = ({'id': 3, 'fideid': 103, 'firstName': 'Erik', 'lastName': 'Ny',
               'club': 'Later club', 'elo': {'rating': 1900}},)
    standings = {klass: {} for klass in 'ABCDE'}
    standings['B'][1] = PlayerStanding(1, 'ANDERSSON Zara', 'B', {}, final_rank=1)
    for member_id in (2, 3):
        standings['E'][member_id] = PlayerStanding(member_id, 'Tournament name', 'E', {}, final_rank=1)
    players = _player_details(standings, merge_duplicate_members(list(january)), Membership(january, joined))

    workbooks = ExcelExporter(standings, 2025, players=players).render(date(2026, 10, 28))

    for content in workbooks.values():
        with ZipFile(BytesIO(content)) as archive:
            strings = [''.join(node.itertext()) for node in
                       ET.fromstring(archive.read('xl/sharedStrings.xml')).findall('s:si', NS)]
            sheets = ET.fromstring(archive.read('xl/workbook.xml')).findall('s:sheets/s:sheet', NS)
            sheet_index = next(i for i, sheet in enumerate(sheets, 1) if sheet.attrib['name'] == 'Spelare')
            sheet = ET.fromstring(archive.read(f'xl/worksheets/sheet{sheet_index}.xml'))
            rows = []
            for row in sheet.findall('s:sheetData/s:row', NS)[1:]:
                values = {}
                for cell in row.findall('s:c', NS):
                    value = cell.find('s:v', NS)
                    if value is not None:
                        values[cell.attrib['r'][0]] = (strings[int(value.text)]
                                                      if cell.get('t') == 's' else int(value.text))
                rows.append(values)
            assert rows == [
                {'B': 2, 'C': 'Anna Berg', 'D': 'Stockholms SS', 'E': 0},
                {'A': 103, 'B': 3, 'C': 'Erik Ny'},
                {'A': 101, 'B': 1, 'C': 'Zara Andersson',
                 'D': 'SS 4 Springare; Stockholms SS', 'E': 2100},
            ]
            table = ET.fromstring(archive.read('xl/tables/table1.xml'))
            assert table.find('s:autoFilter', NS).attrib['ref'] == 'A1:E4'
            assert [column.attrib['name'] for column in table.findall('s:tableColumns/s:tableColumn', NS)] == [
                'FIDE-ID', 'Medlems-ID', 'Namn', 'Stockholmsklubb (1 jan 2025)', 'Rating (1 jan 2025)']
            assert sheet.find('s:sheetViews/s:sheetView/s:pane', NS).attrib['ySplit'] == '1'
