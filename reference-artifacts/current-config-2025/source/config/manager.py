import json
import os
from datetime import datetime
from typing import List, Dict, Optional

CONFIG_FILE = os.path.join(os.path.dirname(__file__), 'tournaments.json')

def _load_config() -> Dict:
    """Load tournament config from JSON file."""
    if not os.path.exists(CONFIG_FILE):
        return {"tournaments": []}
    
    with open(CONFIG_FILE, 'r') as f:
        return json.load(f)

def _save_config(data: Dict) -> None:
    """Save tournament config to JSON file."""
    with open(CONFIG_FILE, 'w') as f:
        json.dump(data, f, ensure_ascii=False, indent=4)

def _auto_detect_dm(name: Optional[str]) -> bool:
    """Auto-detect DM status based on tournament name."""
    if not name:
        return False
    return "Stockholmsmästerskapet" in name

def get_tournament_ids() -> List[str]:
    """Get list of tournament IDs for API calls."""
    config = _load_config()
    return [t["id"] for t in config["tournaments"]]

def get_tournaments() -> List[Dict]:
    """Get full tournament list with metadata."""
    config = _load_config()
    return config["tournaments"]

def add_tournament(tournament_id: str, name: Optional[str] = None, season: Optional[int] = None, dm: Optional[bool] = None) -> bool:
    """Add new tournament."""
    config = _load_config()
    
    # Check if ID already exists
    if any(t["id"] == tournament_id for t in config["tournaments"]):
        return False
    
    # Auto-detect DM if not explicitly provided
    if dm is None:
        dm = _auto_detect_dm(name)
    
    tournament = {
        "id": str(tournament_id),  # Ensure string
        "name": name,
        "season": season or datetime.now().year,
        "dm": dm
    }
    
    config["tournaments"].append(tournament)
    _save_config(config)
    return True

def remove_tournament(tournament_id: str) -> bool:
    """Remove tournament by ID."""
    config = _load_config()
    original_count = len(config["tournaments"])
    
    config["tournaments"] = [t for t in config["tournaments"] if t["id"] != tournament_id]
    
    if len(config["tournaments"]) < original_count:
        _save_config(config)
        return True
    return False

def update_tournament(tournament_id: str, name: Optional[str] = None, season: Optional[int] = None, dm: Optional[bool] = None) -> bool:
    """Update tournament name/season/dm status."""
    config = _load_config()
    
    for tournament in config["tournaments"]:
        if tournament["id"] == tournament_id:
            if name is not None:
                tournament["name"] = name
            if season is not None:
                tournament["season"] = season
            if dm is not None:
                tournament["dm"] = dm
            _save_config(config)
            return True
    return False


def delete_all_tournaments_for_season(season: int) -> int:
    """Delete all tournaments for a specific season. Returns count of deleted tournaments."""
    config = _load_config()
    original_count = len(config["tournaments"])

    config["tournaments"] = [t for t in config["tournaments"] if t["season"] != season]
    deleted_count = original_count - len(config["tournaments"])

    if deleted_count > 0:
        _save_config(config)

    return deleted_count

def delete_all_tournaments() -> bool:
    """Delete all tournaments."""
    config = {"tournaments": []}
    _save_config(config)
    return True