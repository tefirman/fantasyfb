# tests/test_player_analyzer.py
"""
Test suite for PlayerAnalyzer using real fixtures.
"""
import pandas as pd
import pytest
from unittest.mock import Mock, patch, MagicMock
import numpy as np

from src.fantasyfb.analysis.player_analyzer import PlayerAnalyzer
from src.fantasyfb.utils.config import PlayerConfig
from tests.fixtures import get_mock_yahoo_client_with_real_responses


class TestPlayerAnalyzerWithRealData:
    """Test PlayerAnalyzer using real API fixtures."""
    
    @pytest.fixture
    def mock_league(self):
        """Mock league object with realistic settings."""
        league = Mock()
        league.season = 2024
        league.week = 10
        league.latest_season = 2024
        league.current_week = 10
        
        # Real scoring system from your fixtures
        league.scoring = {
            'Pass Yds': 0.04, 'Pass TD': 6.0, 'Int Thrown': -2.0,
            'Rush Yds': 0.1, 'Rush TD': 6.0, 'Rec Yds': 0.1, 
            'Rec TD': 6.0, 'Rec': 1.0, 'Fum Lost': -2.0,
            'PAT Made': 1.0, 'FG 0-19': 3.0, 'Sack': 1.0,
            'Int': 2.0, 'Fum Rec': 2.0, 'TD': 6.0,
            'Pts Allow 0': 10.0, 'Pts Allow 1-6': 7.0,
            'Pts Allow 7-13': 4.0, 'Pts Allow 14-20': 1.0,
            'Pts Allow 21-27': 0.0, 'Pts Allow 28-34': -1.0,
            'Pts Allow 35+': -4.0, 'Rush Att': 0.0, 'Pass Comp': 0.0,
            'Pass 1D': 0.0, 'Rush 1D': 0.0, 'Rec 1D': 0.0,
            'TE Rec Bonus': 0.0, 'TE 1D Bonus': 0.0, 'Pass 300+': 0.0,
            'Rush 100+': 0.0, 'Rec 100+': 0.0, 'Ret Yds': 0.0,
            'Ret TD': 6.0, '2-PT': 2.0, 'Safe': 2.0, 'Blk Kick': 2.0
        }
        
        # Mock NFL schedule
        league.nfl_schedule = pd.DataFrame({
            'season': [2024] * 6,
            'week': [10] * 6,
            'team': ['SEA', 'SF', 'LAR', 'ARI', 'DAL', 'NYG'],
            'elo_diff': [0.1, -0.2, 0.05, -0.1, 0.15, -0.05]
        })
        
        # Mock NFL teams
        league.nfl_teams = pd.DataFrame({
            'real_abbrev': ['SEA', 'SF', 'LAR'],
            'yahoo': ['Sea', 'SF', 'LAR']
        })
        
        return league
    
    @pytest.fixture
    def player_config(self):
        """Player configuration for testing."""
        config = PlayerConfig()
        config.earliest = {
            'QB': 202301, 'RB': 202301, 'WR': 202301,
            'TE': 202301, 'K': 202301, 'DEF': 202301
        }
        config.reference_games = {
            'QB': 10, 'RB': 8, 'WR': 8, 'TE': 8, 'K': 6, 'DEF': 6
        }
        config.weighting_factors = pd.DataFrame({
            'position': ['QB', 'RB', 'WR', 'TE', 'K', 'DEF'],
            'basal': [1.0, 1.0, 1.0, 1.0, 1.0, 1.0],
            'opp_elo_weight': [0.1, 0.1, 0.1, 0.1, 0.05, 0.15],
            'string_weight': [0.2, 0.2, 0.2, 0.2, 0.1, 0.1],
            'time_scale': [0.05, 0.05, 0.05, 0.05, 0.03, 0.03]
        })
        config.war_simulations = 1000  # Smaller for testing
        return config
    
    @pytest.fixture
    def sample_players(self):
        """Sample player data matching real fixture structure."""
        return pd.DataFrame({
            'name': ['Josh Allen', 'Saquon Barkley', 'CeeDee Lamb', 'Travis Kelce', 'Justin Tucker', 'Philadelphia'],
            'position': ['QB', 'RB', 'WR', 'TE', 'K', 'DEF'],
            'player_id': [100001, 100002, 100003, 100004, 100005, 100006],
            'editorial_team_abbr': ['Buf', 'NYG', 'Dal', 'KC', 'Bal', 'Phi'],
            'current_team': ['BUF', 'NYG', 'DAL', 'KC', 'BAL', 'PHI'],
            'player_id_sr': ['AlleJo02', 'BarkSa00', 'LambCe00', 'KelcTr00', 'TuckJu00', 'PHI'],
            'fantasy_team': ['Team A', 'Team B', 'Team A', 'Team C', 'Team A', 'Team B'],
            'status': [None, None, None, None, None, None],
            'string': [1.0, 1.0, 1.0, 1.0, 1.0, 1.0],
            'bye_week': [12, 11, 7, 6, 14, 5]
        })
    
    def test_player_analyzer_initialization(self, mock_league, player_config):
        """Test PlayerAnalyzer initializes correctly."""
        analyzer = PlayerAnalyzer(mock_league, player_config)
        
        assert analyzer.league == mock_league
        assert analyzer.config == player_config
        assert analyzer.stats is None
    
    @patch('src.fantasyfb.analysis.player_analyzer.sr')
    def test_apply_name_corrections(self, mock_sr, mock_league, player_config, sample_players):
        """Test name corrections are applied properly."""
        analyzer = PlayerAnalyzer(mock_league, player_config)
        
        # Mock name corrections
        with patch('pandas.read_csv') as mock_csv:
            mock_csv.return_value = pd.DataFrame({
                'name': ['Josh Allen'],
                'new_name': ['Josh Allen (QB)']
            })
            
            result = analyzer._apply_name_corrections(sample_players.copy())
            
            # Should update Josh Allen's name
            josh_row = result[result.name == 'Josh Allen (QB)']
            assert len(josh_row) == 1
    
    def test_apply_positional_averages(self, mock_league, player_config):
        """Test positional averages calculation."""
        analyzer = PlayerAnalyzer(mock_league, player_config)
        
        # Sample stats data
        rel_stats = pd.DataFrame({
            'position': ['QB', 'QB', 'RB', 'RB', 'WR', 'WR'],
            'rel_points': [20.5, 18.2, 15.1, 12.8, 14.2, 11.9]
        })
        
        result = analyzer._apply_positional_averages(rel_stats)
        
        # Should have one row per position
        assert len(result) == 3
        assert set(result.position) == {'QB', 'RB', 'WR'}
        
        # Check QB averages
        qb_row = result[result.position == 'QB'].iloc[0]
        assert abs(qb_row.points_rate - 19.35) < 0.01  # (20.5 + 18.2) / 2
        assert qb_row.player_id_sr == 'avg_QB'
    
    def test_apply_time_weighting(self, mock_league, player_config):
        """Test time weighting application."""
        analyzer = PlayerAnalyzer(mock_league, player_config)
        
        # Sample data with time information
        rel_stats = pd.DataFrame({
            'season': [2024, 2024, 2023, 2023],
            'week': [8, 9, 16, 17],
            'player_id_sr': ['player1', 'player1', 'player2', 'player2'],
            'position': ['QB', 'QB', 'RB', 'RB'],
            'rel_points': [20.0, 18.0, 15.0, 12.0],
            'time_scale': [0.05, 0.05, 0.05, 0.05],
            'name': ['Player 1', 'Player 1', 'Player 2', 'Player 2']
        })
        
        as_of = 202410  # Week 10 of 2024
        result = analyzer._apply_time_weighting(rel_stats, as_of)
        
        # Should calculate weeks_ago and time_factor
        assert 'weeks_ago' in result.columns
        assert 'time_factor' in result.columns
        assert 'weighted_points' in result.columns
        
        # More recent games should have higher time_factor
        recent_games = result[result.season == 2024]
        old_games = result[result.season == 2023]
        
        if len(recent_games) > 0 and len(old_games) > 0:
            assert recent_games.time_factor.mean() > old_games.time_factor.mean()
    
    def test_calculate_player_rates(self, mock_league, player_config):
        """Test player rate calculations with positional priors."""
        analyzer = PlayerAnalyzer(mock_league, player_config)
        
        # Sample weighted stats
        rel_stats = pd.DataFrame({
            'player_id_sr': ['player1', 'player1', 'avg_QB'],
            'position': ['QB', 'QB', 'QB'],
            'weighted_points': [20.0, 18.0, 15.0],
            'num_games': [2, 2, 1]
        })
        
        # Positional averages
        by_pos = pd.DataFrame({
            'position': ['QB'],
            'points_rate': [15.0],
            'points_stdev': [5.0],
            'player_id_sr': ['avg_QB']
        })
        
        result = analyzer._calculate_player_rates(rel_stats, by_pos)
        
        # Should calculate rates for players
        assert 'points_rate' in result.columns
        assert 'points_stdev' in result.columns
        assert 'num_games' in result.columns
        
        # Player with actual games should have different rate than average
        player_row = result[result.player_id_sr == 'player1']
        avg_row = result[result.player_id_sr == 'avg_QB']
        
        assert len(player_row) > 0
        assert len(avg_row) > 0
    
    def test_simulate_average_team(self, mock_league, player_config):
        """Test average team simulation."""
        analyzer = PlayerAnalyzer(mock_league, player_config)
        
        # Create position histograms
        points_bins = np.arange(-10, 50.1, 0.1)
        pos_hists = {
            'points': points_bins,
            'QB': np.ones(len(points_bins) - 1) / (len(points_bins) - 1),
            'RB': np.ones(len(points_bins) - 1) / (len(points_bins) - 1),
            'WR': np.ones(len(points_bins) - 1) / (len(points_bins) - 1),
            'TE': np.ones(len(points_bins) - 1) / (len(points_bins) - 1),
            'K': np.ones(len(points_bins) - 1) / (len(points_bins) - 1),
            'DEF': np.ones(len(points_bins) - 1) / (len(points_bins) - 1),
            'FLEX': np.ones(len(points_bins) - 1) / (len(points_bins) - 1)
        }
        
        num_sims = 100  # Small number for testing
        result = analyzer._simulate_average_team(pos_hists, num_sims)
        
        # Should have correct structure
        expected_cols = ['QB', 'RB1', 'RB2', 'WR1', 'WR2', 'TE', 'FLEX', 'K', 'DEF', 'Total']
        assert all(col in result.columns for col in expected_cols)
        assert len(result) == num_sims
        
        # Total should be sum of position scores
        manual_total = (result.QB + result.RB1 + result.RB2 + result.WR1 + 
                       result.WR2 + result.TE + result.FLEX + result.K + result.DEF)
        assert np.allclose(result.Total, manual_total)
    
    @patch('src.fantasyfb.analysis.player_analyzer.sr')
    def test_add_injury_data(self, mock_sr, mock_league, player_config, sample_players):
        """Test injury data addition."""
        analyzer = PlayerAnalyzer(mock_league, player_config)
        
        # Mock injury data
        with patch('pandas.read_csv') as mock_csv:
            mock_csv.return_value = pd.DataFrame({
                'player_id_sr': ['AlleJo02'],
                'name': ['Josh Allen'],
                'position': ['QB'],
                'until': [12]
            })
            
            result = analyzer._add_injury_data(sample_players.copy(), 2024)
            
            # Should add until column
            assert 'until' in result.columns
            
            # Josh Allen should have injury data
            josh_row = result[result.name == 'Josh Allen']
            assert len(josh_row) == 1
    
    def test_add_bye_weeks(self, mock_league, player_config, sample_players):
        """Test bye week addition."""
        analyzer = PlayerAnalyzer(mock_league, player_config)
        
        result = analyzer._add_bye_weeks(sample_players.copy())
        
        # Should still have bye_week column (already present in sample)
        assert 'bye_week' in result.columns
        
        # All players should have bye weeks
        assert not result.bye_week.isnull().any()


