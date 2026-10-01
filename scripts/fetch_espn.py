"""Pull ESPN projections and write data/players.json for the calculator.

Runs in GitHub Actions (stdlib only). Uses ESPN's public default PPR
projections. If the league is public (or cookies are provided), it also
pulls league rosters so the page can show Mary's team.
"""

import datetime as dt
import json
import os
import sys
import urllib.error
import urllib.request

SEASON = int(os.environ.get("SEASON", dt.date.today().year))
LEAGUE_ID = os.environ.get("LEAGUE_ID", "1501218329")
MARY_TEAM_HINT = os.environ.get("MARY_TEAM_HINT", "mary").lower()
BASE = "https://lm-api-reads.fantasy.espn.com/apis/v3/games/ffl/seasons"

POS = {1: "QB", 2: "RB", 3: "WR", 4: "TE", 5: "K", 16: "D/ST"}
TEAMS = {
    0: "FA", 1: "ATL", 2: "BUF", 3: "CHI", 4: "CIN", 5: "CLE", 6: "DAL",
    7: "DEN", 8: "DET", 9: "GB", 10: "TEN", 11: "IND", 12: "KC", 13: "LV",
    14: "LAR", 15: "MIA", 16: "MIN", 17: "NE", 18: "NO", 19: "NYG",
    20: "NYJ", 21: "PHI", 22: "ARI", 23: "PIT", 24: "LAC", 25: "SF",
    26: "SEA", 27: "TB", 28: "WSH", 29: "CAR", 30: "JAX", 33: "BAL",
    34: "HOU",
}


def get(url, headers=None):
    h = {"User-Agent": "Mozilla/5.0", "Accept": "application/json"}
    h.update(headers or {})
    cookie = []
    if os.environ.get("ESPN_S2"):
        cookie.append("espn_s2=" + os.environ["ESPN_S2"])
    if os.environ.get("SWID"):
        cookie.append("SWID=" + os.environ["SWID"])
    if cookie:
        h["Cookie"] = "; ".join(cookie)
    req = urllib.request.Request(url, headers=h)
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read().decode("utf-8"))


def current_week():
    try:
        d = get(f"{BASE}/{SEASON}")
        wk = d.get("currentScoringPeriod", {}).get("id")
        if wk:
            return int(wk)
    except Exception as e:  # noqa: BLE001
        print("season lookup failed:", e)
    # Fallback: NFL week 1 starts the Thursday after Labor Day (approx).
    sept1 = dt.date(SEASON, 9, 1)
    labor = sept1 + dt.timedelta(days=(7 - sept1.weekday()) % 7)
    wk1 = labor + dt.timedelta(days=3)
    return max(1, min(18, (dt.date.today() - wk1).days // 7 + 1))


def fetch_players(week):
    flt = {
        "players": {
            "filterSlotIds": {"value": [0, 2, 4, 6, 17, 16]},
            "filterStatsForTopScoringPeriodIds": {
                "value": 2,
                "additionalValue": [
                    f"00{SEASON}", f"10{SEASON}", f"11{SEASON}{week}",
                ],
            },
            "sortPercOwned": {"sortAsc": False, "sortPriority": 1},
            "limit": 1200,
        }
    }
    url = (f"{BASE}/{SEASON}/segments/0/leaguedefaults/3"
           f"?scoringPeriodId={week}&view=kona_player_info")
    d = get(url, {"x-fantasy-filter": json.dumps(flt)})
    return d.get("players", d if isinstance(d, list) else [])


def stat(stats, source, split, period=None):
    for s in stats:
        if s.get("seasonId") != SEASON:
            continue
        if s.get("statSourceId") != source or s.get("statSplitTypeId") != split:
            continue
        if period is not None and s.get("scoringPeriodId") != period:
            continue
        return float(s.get("appliedTotal") or 0)
    return None


def fetch_league():
    url = (f"{BASE}/{SEASON}/segments/0/leagues/{LEAGUE_ID}"
           "?view=mTeam&view=mRoster&view=mSettings")
    try:
        return get(url)
    except urllib.error.HTTPError as e:
        print(f"league fetch skipped: HTTP {e.code} (league private?)")
    except Exception as e:  # noqa: BLE001
        print("league fetch skipped:", e)
    return None


def main():
    week = current_week()
    print("season", SEASON, "week", week)
    raw = fetch_players(week)
    print("players returned:", len(raw))

    players = []
    for item in raw:
        p = item.get("player", item)
        stats = p.get("stats") or []
        season_proj = stat(stats, 1, 0)
        week_proj = stat(stats, 1, 1, week)
        actual = stat(stats, 0, 0) or 0.0
        if season_proj is None and week_proj is None:
            continue
        players.append({
            "id": p.get("id"),
            "n": p.get("fullName"),
            "pos": POS.get(p.get("defaultPositionId"), "?"),
            "tm": TEAMS.get(p.get("proTeamId"), "?"),
            "inj": p.get("injuryStatus") or "",
            "own": round((p.get("ownership") or {}).get("percentOwned", 0), 1),
            "w": round(week_proj or 0.0, 2),
            "sp": round(season_proj or 0.0, 2),
            "act": round(actual, 2),
        })

    # Diagnostics: is ESPN's season projection full-season or remaining-only?
    # Full-season style => season_proj ~ actual + remaining weeks * weekly.
    played = max(0, week - 1)
    sample = [p for p in players if p["act"] > 30 and p["w"] > 5][:40]
    full_err = rem_err = 0.0
    for p in sample:
        remaining = (18 - played) * p["w"]
        full_err += abs(p["sp"] - (p["act"] + remaining))
        rem_err += abs(p["sp"] - remaining)
    method = "season_minus_actual" if full_err <= rem_err else "season_as_is"
    if played == 0:
        method = "season_as_is"
    print(f"ROS check on {len(sample)} players: full-style err {full_err:.0f},"
          f" remaining-style err {rem_err:.0f} -> {method}")
    for p in sample[:8]:
        print("  ", p["n"], "season", p["sp"], "actual", p["act"], "wk", p["w"])

    for p in players:
        ros = p["sp"] - p["act"] if method == "season_minus_actual" else p["sp"]
        p["ros"] = round(max(ros, 0.0), 2)

    out = {
        "updated": dt.datetime.now(dt.timezone.utc).isoformat(timespec="minutes"),
        "season": SEASON,
        "week": week,
        "scoring": "ESPN default PPR projections",
        "rosMethod": method,
        "players": players,
        "league": None,
    }

    lg = fetch_league()
    if lg and lg.get("teams"):
        teams = []
        for t in lg["teams"]:
            name = t.get("name") or f"{t.get('location', '')} {t.get('nickname', '')}".strip()
            roster = [e.get("playerId") for e in (t.get("roster") or {}).get("entries", [])]
            teams.append({"id": t.get("id"), "name": name, "roster": roster})
        mary = next((t["id"] for t in teams if MARY_TEAM_HINT in t["name"].lower()), None)
        size = sum(
            v for k, v in (lg.get("settings", {}).get("rosterSettings", {})
                           .get("lineupSlotCounts", {}) or {}).items()
        )
        # Publish only Mary's team; the page is public and other rosters aren't needed.
        out["league"] = {"teams": [t for t in teams if t["id"] == mary],
                         "maryTeamId": mary, "rosterSize": size or None}
        print("league teams:", len(teams), "mary team id:", mary)

    if len(players) < 100:
        print("Too few players; refusing to overwrite data.", file=sys.stderr)
        sys.exit(1)

    os.makedirs("data", exist_ok=True)
    with open("data/players.json", "w") as f:
        json.dump(out, f, separators=(",", ":"))
    print("wrote", len(players), "players")


if __name__ == "__main__":
    main()
