"""List standings changes between the 2025 capture and the expected outputs."""

import json
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
OLD = HERE.parent / "current-config-2025" / "adjusted-reference" / "standings.json"


def load(path):
    """Map class to {member: (rank, total, rilton points)}."""
    data = json.loads(Path(path).read_text())
    return {klass: {p["contender_id"]: (p["final_rank"], p["total_standings_points"],
                                        p["tournament_results"].get("rilton", {}).get("standings_points"),
                                        p["name"])
                    for p in players} for klass, players in data.items()}


def main():
    """Print per-class counts and every changed player."""
    new_path = sys.argv[1] if len(sys.argv) > 1 else HERE / "expected" / "standings.json"
    old, new = load(OLD), load(new_path)
    for klass in old:
        print(f"Class {klass}: {len(old[klass])} -> {len(new[klass])} players")
        for member in sorted(set(old[klass]) | set(new[klass]),
                             key=lambda m: (new[klass].get(m) or old[klass][m])[0]):
            before, after = old[klass].get(member), new[klass].get(member)
            if before is None:
                print(f"  added   {after[3]}: rank {after[0]}, total {after[1]}, rilton {after[2]}")
            elif after is None:
                print(f"  removed {before[3]}")
            elif before[:3] != after[:3]:
                print(f"  changed {after[3]}: rank {before[0]}->{after[0]}, "
                      f"total {before[1]}->{after[1]}, rilton {before[2]}->{after[2]}")


if __name__ == "__main__":
    main()
