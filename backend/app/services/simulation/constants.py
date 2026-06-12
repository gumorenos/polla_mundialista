"""WC2026 static structure: groups and Round-of-32 bracket pairings."""

from __future__ import annotations

# WC2026 group composition (team IDs from teams.csv)
GROUPS_2026: dict[str, list[str]] = {
    "A": ["USA", "PAN", "NGA", "AUS"],
    "B": ["MEX", "JAM", "CIV", "IRN"],
    "C": ["ARG", "ECU", "HUN", "CMR"],
    "D": ["BRA", "COL", "MLI", "KOR"],
    "E": ["FRA", "ESP", "SVN", "JOR"],
    "F": ["ENG", "POR", "SEN", "UZB"],
    "G": ["GER", "BEL", "EGY", "CAN"],
    "H": ["CRO", "NED", "MAR", "ALB"],
    "I": ["SRB", "TUR", "IRQ", "HON"],
    "J": ["AUT", "DEN", "GHA", "NZL"],
    "K": ["POL", "SCO", "VEN", "JPN"],
    "L": ["RSA", "KSA", "URU", "SUI"],
}

# Round-of-32 bracket pairings expressed as position labels.
# "1X" = group winner of X, "2X" = runner-up of X, "T{n}" = n-th best 3rd-placer.
# Winners of consecutive pairs meet in the Round-of-16, then QF, then SF, then Final.
R32_BRACKET: list[tuple[str, str]] = [
    ("1A", "2B"),  # match 0  → R16-left-1
    ("1C", "T1"),  # match 1  /
    ("1E", "T2"),  # match 2  → R16-left-2
    ("1G", "T3"),  # match 3  /
    ("1I", "2J"),  # match 4  → R16-left-3
    ("1K", "T4"),  # match 5  /
    ("1B", "2C"),  # match 6  → R16-left-4
    ("1D", "T5"),  # match 7  /
    ("1F", "T6"),  # match 8  → R16-right-1
    ("1H", "2I"),  # match 9  /
    ("1J", "2K"),  # match 10 → R16-right-2
    ("1L", "T7"),  # match 11 /
    ("2A", "2L"),  # match 12 → R16-right-3
    ("2D", "2E"),  # match 13 /
    ("2F", "2G"),  # match 14 → R16-right-4
    ("2H", "T8"),  # match 15 /
]

# Round name labels (used in rounds_reached tracking)
ROUND_GROUP_STAGE = "group_stage"
ROUND_R32 = "round_of_32"
ROUND_R16 = "round_of_16"
ROUND_QF  = "quarterfinals"
ROUND_SF  = "semifinals"
ROUND_FINAL = "final"
ROUND_RUNNER_UP = "runner_up"
ROUND_THIRD = "third"
ROUND_FOURTH = "fourth"
ROUND_CHAMPION = "champion"
