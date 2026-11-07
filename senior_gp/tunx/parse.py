from __future__ import annotations

import struct
from typing import Optional, cast

from .constants import (
    BYE_RESULT_CODES,
    CONFIG_MARKER,
    CONFIG_OFFSET_CURRENT_ROUND,
    CONFIG_OFFSET_PLAYER_COUNT,
    CONFIG_OFFSET_TIEBREAK_COUNT,
    CONFIG_OFFSET_TIEBREAKS,
    CONFIG_OFFSET_TOTAL_ROUNDS,
    FULL_POINT_BYE,
    HEADER_SIZE,
    MAGIC,
    MAX_TIEBREAKS,
    METADATA,
    METADATA_OFFSET,
    NOT_PAIRED,
    PAIRINGS_END_MARKER,
    PAIRINGS_MARKER,
    PAIRING_RECORD_SIZE,
    PLAYER_MARKER,
    PLAYER_NUMERIC_BLOCK_SIZE,
    PLAYER_NUMERIC_OFFSET_FIDE_ID,
    PLAYER_NUMERIC_OFFSET_FIDE_RATING,
    PLAYER_NUMERIC_OFFSET_NATIONAL_RATING,
    PLAYER_STRINGS,
    PLAYER_STRING_COUNT,
    RESULT_CODE,
)
from .reader import BinaryReader
from .types import (
    Arbiter,
    Pairing,
    ParseError,
    Player,
    RawTournament,
    Result,
    ResultKind,
    Round,
    Title,
    Tournament,
)

VALID_TITLES = {"CM", "FM", "GM", "IM", "WCM", "WFM", "WGM", "WIM"}

# (white result, black result) for each decided game code
GAME_RESULTS: dict[int, tuple[ResultKind, ResultKind]] = {
    RESULT_CODE["WHITE_WINS"]: ("win", "loss"),
    RESULT_CODE["DRAW"]: ("draw", "draw"),
    RESULT_CODE["BLACK_WINS"]: ("loss", "win"),
    RESULT_CODE["WHITE_WINS_FORFEIT"]: ("forfeit-win", "forfeit-loss"),
    RESULT_CODE["BLACK_WINS_FORFEIT"]: ("forfeit-loss", "forfeit-win"),
    RESULT_CODE["DOUBLE_LOSS"]: ("double-loss", "double-loss"),
}


def _find_marker(buffer: bytes, marker: int) -> int:
    offset = buffer.find(marker.to_bytes(4, "little"))
    if offset == -1:
        raise ParseError(f"Section marker 0x{marker:08X} not found")
    return offset


def _non_empty(value: str) -> Optional[str]:
    return value if value else None


def _to_title(value: str) -> Optional[Title]:
    return cast(Optional[Title], value if value in VALID_TITLES else None)


def parse(input_bytes: bytes | bytearray | memoryview) -> Tournament:
    """Parse a TUNX file, or raise ParseError naming the fault."""
    data = bytes(input_bytes)

    if len(data) < HEADER_SIZE:
        raise ParseError("File too short to be a TUNX file", 0)
    magic = struct.unpack_from("<I", data, 0)[0]
    if magic != MAGIC:
        raise ParseError(f"Invalid magic: expected 0x{MAGIC:x}, got 0x{magic:x}", 0)

    header_bytes = data[:HEADER_SIZE]
    config_marker_offset = _find_marker(data, CONFIG_MARKER)
    player_marker_offset = _find_marker(data, PLAYER_MARKER)
    pairings_marker_offset = _find_marker(data, PAIRINGS_MARKER)
    if not METADATA_OFFSET <= config_marker_offset < player_marker_offset < pairings_marker_offset:
        raise ParseError("Sections are out of order")

    metadata_reader = BinaryReader(data[METADATA_OFFSET:config_marker_offset], METADATA_OFFSET)
    metadata_strings: list[str] = []
    while metadata_reader.remaining >= 2:
        metadata_strings.append(metadata_reader.read_string())

    config_bytes = data[config_marker_offset:player_marker_offset]
    config_reader = BinaryReader(config_bytes[4:], config_marker_offset + 4)

    def config_u16(offset: int) -> int:
        config_reader.seek(offset)
        return config_reader.read_u16le()

    total_rounds = config_u16(CONFIG_OFFSET_TOTAL_ROUNDS)
    current_round = config_u16(CONFIG_OFFSET_CURRENT_ROUND)
    player_count = config_u16(CONFIG_OFFSET_PLAYER_COUNT)
    tiebreak_count = config_u16(CONFIG_OFFSET_TIEBREAK_COUNT)
    if total_rounds == 0 or player_count == 0:
        raise ParseError(f"Tournament has {total_rounds} rounds and {player_count} players", config_marker_offset)
    if current_round > total_rounds or tiebreak_count > MAX_TIEBREAKS:
        raise ParseError("Invalid round or tie-break settings", config_marker_offset)
    tiebreak_codes = [config_u16(CONFIG_OFFSET_TIEBREAKS + 2 * index) for index in range(tiebreak_count)]

    player_section_start = player_marker_offset + 4
    player_reader = BinaryReader(data[player_section_start:pairings_marker_offset], player_section_start)
    player_strings: list[list[str]] = []
    player_numeric_bytes: list[bytes] = []
    for _ in range(player_count):
        player_strings.append([player_reader.read_string() for _ in range(PLAYER_STRING_COUNT)])
        player_numeric_bytes.append(player_reader.read_bytes(PLAYER_NUMERIC_BLOCK_SIZE))
    if player_reader.remaining:
        raise ParseError(f"{player_reader.remaining} unexplained bytes after the last player",
                         player_section_start + player_reader.offset)

    players: list[Player] = []
    for index, strings in enumerate(player_strings):
        numeric_block = player_numeric_bytes[index]
        fide_rating = struct.unpack_from("<H", numeric_block, PLAYER_NUMERIC_OFFSET_FIDE_RATING)[0]
        national_rating = struct.unpack_from("<H", numeric_block, PLAYER_NUMERIC_OFFSET_NATIONAL_RATING)[0]
        fide_id = struct.unpack_from("<I", numeric_block, PLAYER_NUMERIC_OFFSET_FIDE_ID)[0]

        players.append(
            Player(
                academic_title=_non_empty(strings[PLAYER_STRINGS["ACADEMIC_TITLE"]]),
                club=_non_empty(strings[PLAYER_STRINGS["CLUB"]]),
                federation=_non_empty(strings[PLAYER_STRINGS["FEDERATION"]]),
                fide_id=fide_id if fide_id > 0 else None,
                first_name=strings[PLAYER_STRINGS["FIRST_NAME"]],
                national_id=_non_empty(strings[PLAYER_STRINGS["NATIONAL_ID"]]),
                pairing_number=index + 1,
                rating=fide_rating or national_rating or None,
                results=[],
                surname=strings[PLAYER_STRINGS["SURNAME"]],
                title=_to_title(strings[PLAYER_STRINGS["TITLE"]]),
            )
        )

    pairing_section_start = pairings_marker_offset + 4
    rounds, pairing_bytes, pairings_end = _parse_rounds(data, pairing_section_start, total_rounds, players)

    def get_metadata(index: int) -> str:
        return metadata_strings[index] if index < len(metadata_strings) else ""

    arbiters: list[Arbiter] = []
    chief = _non_empty(get_metadata(METADATA["CHIEF_ARBITER"]))
    deputy = _non_empty(get_metadata(METADATA["DEPUTY_ARBITER"]))
    if chief is not None:
        arbiters.append(Arbiter(name=chief, role="chief"))
    if deputy is not None:
        arbiters.append(Arbiter(name=deputy, role="deputy"))

    raw = RawTournament(
        config_bytes=config_bytes,
        header_bytes=header_bytes,
        metadata_strings=metadata_strings,
        pairing_bytes=pairing_bytes,
        pairings_section=data[pairings_marker_offset:pairings_end],
        player_numeric_bytes=player_numeric_bytes,
        player_strings=player_strings,
    )

    return Tournament(
        _raw=raw,
        arbiters=arbiters,
        city=_non_empty(get_metadata(METADATA["CITY"])),
        current_round=current_round,
        federation=_non_empty(get_metadata(METADATA["FEDERATION"])),
        name=get_metadata(METADATA["NAME"]),
        players=players,
        rounds=rounds,
        subtitle=_non_empty(get_metadata(METADATA["SUBTITLE_SHORT"])),
        tiebreak_codes=tiebreak_codes,
        time_control=_non_empty(get_metadata(METADATA["TIME_CONTROL"])),
        total_rounds=total_rounds,
        venue=_non_empty(get_metadata(METADATA["VENUE"])),
    )


def _parse_rounds(
    data: bytes, offset: int, total_rounds: int, players: list[Player]
) -> tuple[list[Round], list[bytes], int]:
    """
    Split pairing records into rounds and record each player's results.

    A game record covers both players. An unpaired player has a separate
    record. A round ends when every player has appeared once. The pairings
    end at PAIRINGS_END_MARKER. Returns the rounds, the raw records,
    and the offset of the end marker.
    """
    end_marker = PAIRINGS_END_MARKER.to_bytes(4, "little")
    rounds: list[Round] = []
    pairing_bytes: list[bytes] = []
    pairings: list[Pairing] = []
    seen: set[int] = set()
    while data[offset:offset + 4] != end_marker:
        round_number = len(rounds) + 1
        if round_number > total_rounds:
            raise ParseError("Pairing records follow the last round", offset)
        if offset + PAIRING_RECORD_SIZE > len(data):
            raise ParseError(f"Pairings end without an end marker in round {round_number}", offset)
        record = data[offset:offset + PAIRING_RECORD_SIZE]
        pairing = _parse_pairing(record, round_number, len(pairings) + 1, players, offset)
        for number in (pairing.white, pairing.black):
            if number in seen:
                raise ParseError(f"Player {number} appears twice in round {round_number}", offset)
            if number:
                seen.add(number)
        pairings.append(pairing)
        pairing_bytes.append(record)
        offset += PAIRING_RECORD_SIZE
        if len(seen) == len(players):
            rounds.append(Round(number=round_number, pairings=pairings))
            pairings, seen = [], set()
    if pairings:
        raise ParseError(f"Round {len(rounds) + 1} pairs {len(seen)} of {len(players)} players", offset)
    return rounds, pairing_bytes, offset


def _parse_pairing(record: bytes, round_number: int, board: int, players: list[Player], offset: int) -> Pairing:
    """Decode one pairing and add any decided result to the player or players."""
    white, black, code = struct.unpack_from("<HHH", record, 0)
    where = f"Round {round_number}, player {white}"
    if not 1 <= white <= len(players):
        raise ParseError(f"Round {round_number}: invalid player number {white}", offset)
    white_player = players[white - 1]

    if black in BYE_RESULT_CODES:
        if code not in BYE_RESULT_CODES[black]:
            raise ParseError(f"{where}: unknown result code {code} for opponent number {black}", offset)
        kind: ResultKind = "bye" if black == FULL_POINT_BYE else "unpaired"
        white_player.results.append(Result(kind=kind, round=round_number))
        return Pairing(black=0, board=board, white=white, code=code, result=kind)

    if not 1 <= black <= len(players) or black == white:
        raise ParseError(f"{where}: invalid opponent number {black}", offset)
    if code == RESULT_CODE["NO_RESULT"]:
        return Pairing(black=black, board=board, white=white, code=code)
    if code not in GAME_RESULTS:
        raise ParseError(f"{where} against player {black}: unknown result code {code}", offset)
    white_kind, black_kind = GAME_RESULTS[code]
    white_player.results.append(Result(kind=white_kind, round=round_number, color="white", opponent=black))
    players[black - 1].results.append(Result(kind=black_kind, round=round_number, color="black", opponent=white))
    return Pairing(black=black, board=board, white=white, code=code, result=white_kind)
