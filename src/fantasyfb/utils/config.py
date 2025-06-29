# fantasyfb/utils/config.py
"""
Configuration classes for the fantasy football package.
"""

from dataclasses import dataclass, field

import pandas as pd


@dataclass
class SimulationConfig:
    """Configuration for Monte Carlo simulations."""

    num_sims: int = 10000
    k_factor: float = 20.0
    homefield_advantage: float = 48.0
    travel_penalty: float = 0.004
    bye_week_bonus: float = 25.0
    playoffs_multiplier: float = 1.2
    elo_to_points: float = 0.04


@dataclass
class PlayerConfig:
    """Configuration for player analysis."""

    war_simulations: int = 10000
    earliest: dict[str, int] = field(
        default_factory=lambda: {
            "QB": 202201,
            "RB": 202201,
            "WR": 202201,
            "TE": 202201,
            "K": 202201,
            "DEF": 202201,
        }
    )
    reference_games: dict[str, int] = field(
        default_factory=lambda: {
            "QB": 15,
            "RB": 12,
            "WR": 12,
            "TE": 12,
            "K": 10,
            "DEF": 12,
        }
    )
    weighting_factors: pd.DataFrame = field(
        default_factory=lambda: pd.DataFrame(
            {
                "position": ["QB", "RB", "WR", "TE", "K", "DEF"],
                "basal": [1.0, 1.0, 1.0, 1.0, 1.0, 1.0],
                "opp_elo_weight": [0.5, 0.3, 0.3, 0.3, 0.2, 0.4],
                "string_weight": [0.1, 0.3, 0.3, 0.3, 0.1, 0.1],
                "time_scale": [0.05, 0.05, 0.05, 0.05, 0.05, 0.05],
            }
        )
    )


@dataclass
class ScoringConfig:
    """Standard fantasy football scoring configuration."""

    # Passing
    pass_yds: float = 0.04
    pass_comp: float = 0.0
    pass_td: float = 6.0
    pass_1d: float = 0.0
    pass_300_bonus: float = 0.0
    int_thrown: float = -1.0

    # Rushing
    rush_yds: float = 0.1
    rush_att: float = 0.0
    rush_td: float = 6.0
    rush_1d: float = 0.0
    rush_100_bonus: float = 0.0

    # Receiving
    rec_yds: float = 0.1
    rec: float = 1.0  # PPR
    rec_td: float = 6.0
    rec_1d: float = 0.0
    rec_100_bonus: float = 0.0

    # Special cases
    te_rec_bonus: float = 0.0
    te_1d_bonus: float = 0.0
    two_pt: float = 2.0
    fum_lost: float = -2.0
    ret_yds: float = 0.0
    ret_td: float = 6.0

    # Kicking
    fg_0_19: float = 3.0
    fg_20_29: float = 3.0
    fg_30_39: float = 3.0
    fg_40_49: float = 4.0
    fg_50_plus: float = 5.0
    pat_made: float = 1.0

    # Defense
    sack: float = 1.0
    def_int: float = 2.0
    fum_rec: float = 2.0
    def_td: float = 6.0
    safety: float = 2.0
    blk_kick: float = 2.0
    pts_allow_0: float = 10.0
    pts_allow_1_6: float = 7.0
    pts_allow_7_13: float = 4.0
    pts_allow_14_20: float = 1.0
    pts_allow_21_27: float = 0.0
    pts_allow_28_34: float = -1.0
    pts_allow_35_plus: float = -4.0

    def to_dict(self) -> dict[str, float]:
        """Convert to dictionary format for compatibility."""
        return {
            "Pass Yds": self.pass_yds,
            "Pass Comp": self.pass_comp,
            "Pass TD": self.pass_td,
            "Pass 1D": self.pass_1d,
            "Pass 300+": self.pass_300_bonus,
            "Int Thrown": self.int_thrown,
            "Rush Yds": self.rush_yds,
            "Rush Att": self.rush_att,
            "Rush TD": self.rush_td,
            "Rush 1D": self.rush_1d,
            "Rush 100+": self.rush_100_bonus,
            "Rec Yds": self.rec_yds,
            "Rec": self.rec,
            "Rec TD": self.rec_td,
            "Rec 1D": self.rec_1d,
            "Rec 100+": self.rec_100_bonus,
            "TE Rec Bonus": self.te_rec_bonus,
            "TE 1D Bonus": self.te_1d_bonus,
            "2-PT": self.two_pt,
            "Fum Lost": self.fum_lost,
            "Ret Yds": self.ret_yds,
            "Ret TD": self.ret_td,
            "FG 0-19": self.fg_0_19,
            "FG 20-29": self.fg_20_29,
            "FG 30-39": self.fg_30_39,
            "FG 40-49": self.fg_40_49,
            "FG 50+": self.fg_50_plus,
            "PAT Made": self.pat_made,
            "Sack": self.sack,
            "Int": self.def_int,
            "Fum Rec": self.fum_rec,
            "TD": self.def_td,
            "Safe": self.safety,
            "Blk Kick": self.blk_kick,
            "Pts Allow 0": self.pts_allow_0,
            "Pts Allow 1-6": self.pts_allow_1_6,
            "Pts Allow 7-13": self.pts_allow_7_13,
            "Pts Allow 14-20": self.pts_allow_14_20,
            "Pts Allow 21-27": self.pts_allow_21_27,
            "Pts Allow 28-34": self.pts_allow_28_34,
            "Pts Allow 35+": self.pts_allow_35_plus,
        }


@dataclass
class RosterConfig:
    """Roster configuration."""

    qb: int = 1
    rb: int = 2
    wr: int = 2
    te: int = 1
    flex_wr_rb_te: int = 1
    k: int = 1
    def_: int = 1
    bench: int = 6
    ir: int = 1

    def to_dataframe(self) -> pd.DataFrame:
        """Convert to DataFrame format for compatibility."""
        return pd.DataFrame(
            {
                "position": ["QB", "RB", "WR", "TE", "W/R/T", "K", "DEF", "BN", "IR"],
                "count": [
                    self.qb,
                    self.rb,
                    self.wr,
                    self.te,
                    self.flex_wr_rb_te,
                    self.k,
                    self.def_,
                    self.bench,
                    self.ir,
                ],
            }
        )


@dataclass
class LeagueConfig:
    """Main league configuration."""

    # Sub-configurations
    simulation_config: SimulationConfig = field(default_factory=SimulationConfig)
    player_config: PlayerConfig = field(default_factory=PlayerConfig)
    scoring_config: ScoringConfig = field(default_factory=ScoringConfig)
    roster_config: RosterConfig = field(default_factory=RosterConfig)

    # League settings
    num_teams: int = 12
    playoff_start_week: int = 14
    num_playoff_teams: int = 6
    playoff_weeks: int = 3

    # Default payouts (60/30/10 split)
    default_payouts: list[float] = field(default_factory=lambda: [600.0, 300.0, 100.0])

    # League type
    league_type: str = "redraft"  # redraft, dynasty, bestball
    platform: str = "yahoo"  # yahoo, espn, sleeper

    @classmethod
    def for_bestball(cls, platform: str = "draftkings") -> "LeagueConfig":
        """Create configuration for best ball leagues."""
        config = cls()
        config.league_type = "bestball"
        config.platform = platform

        if platform.lower() in ["dk", "draftkings"]:
            config.playoff_start_week = 14
            config.num_playoff_teams = 2
            config.scoring_config = ScoringConfig(
                pass_yds=0.04,
                pass_td=4.0,
                pass_300_bonus=3.0,
                int_thrown=-1.0,
                rush_yds=0.1,
                rush_td=6.0,
                rush_100_bonus=3.0,
                rec_yds=0.1,
                rec=1.0,
                rec_td=6.0,
                rec_100_bonus=3.0,
                fum_lost=-1.0,
            )
            config.roster_config = RosterConfig(
                qb=1, rb=2, wr=3, te=1, flex_wr_rb_te=1, k=0, def_=0, bench=12
            )
        elif platform.lower() == "underdog":
            config.playoff_start_week = 14
            config.num_playoff_teams = 2
            config.scoring_config = ScoringConfig(
                pass_yds=0.04,
                pass_td=4.0,
                int_thrown=-1.0,
                rush_yds=0.1,
                rush_td=6.0,
                rec_yds=0.1,
                rec=0.5,
                rec_td=6.0,
                fum_lost=-2.0,
            )
            config.roster_config = RosterConfig(
                qb=1, rb=2, wr=3, te=1, flex_wr_rb_te=1, k=0, def_=0, bench=10
            )

        return config

    @classmethod
    def for_sfb(cls) -> "LeagueConfig":
        """Create configuration for Scott Fish Bowl."""
        config = cls()
        config.league_type = "sfb"
        config.num_teams = 12
        config.playoff_start_week = 14
        config.num_playoff_teams = 6

        # SFB14 scoring
        config.scoring_config = ScoringConfig(
            pass_yds=0.02,
            pass_td=6.0,
            rush_yds=0.1,
            rush_att=0.25,
            rush_td=6.0,
            rush_1d=0.5,
            rec_yds=0.1,
            rec=0.75,
            rec_td=6.0,
            rec_1d=0.5,
            te_rec_bonus=0.75,
            te_1d_bonus=1.0,
            ret_yds=0.2,
            ret_td=10.0,
            two_pt=2.0,
            fg_0_19=2.0,
            fg_20_29=2.5,
            fg_30_39=3.5,
            fg_40_49=4.5,
            fg_50_plus=5.5,
            pat_made=3.3,
        )

        # SFB14 roster
        config.roster_config = RosterConfig(
            qb=1, rb=1, wr=1, te=1, flex_wr_rb_te=5, k=1, def_=0, bench=11
        )

        return config
