# tests/test_sportsref_integration.py
"""
Test suite for sportsref_nfl integration with real data structures.
"""
import pytest
from unittest.mock import Mock, patch
import pandas as pd
from bs4 import BeautifulSoup

from src.fantasyfb.utils.sportsref_nfl import parse_table


class TestSportsRefIntegration:
    """Test sportsref_nfl functions with realistic HTML structures."""
    
    def test_parse_table_with_sample_html(self):
        """Test parse_table with realistic HTML structure."""
        # Sample HTML that matches Pro Football Reference structure
        html_content = """
        <div id="passing">
            <table>
                <thead>
                    <tr>
                        <th data-stat="player">Player</th>
                        <th data-stat="team">Tm</th>
                        <th data-stat="pass_att">Att</th>
                        <th data-stat="pass_cmp">Cmp</th>
                        <th data-stat="pass_yds">Yds</th>
                        <th data-stat="pass_td">TD</th>
                    </tr>
                </thead>
                <tbody>
                    <tr>
                        <th data-stat="player"><a href="/players/a/AlleJo02.htm" data-append-csv="AlleJo02">Josh Allen</a></th>
                        <td data-stat="team">BUF</td>
                        <td data-stat="pass_att">35</td>
                        <td data-stat="pass_cmp">24</td>
                        <td data-stat="pass_yds">280</td>
                        <td data-stat="pass_td">3</td>
                    </tr>
                    <tr>
                        <th data-stat="player"><a href="/players/b/BradTo00.htm" data-append-csv="BradTo00">Tom Brady</a></th>
                        <td data-stat="team">TB</td>
                        <td data-stat="pass_att">42</td>
                        <td data-stat="pass_cmp">30</td>
                        <td data-stat="pass_yds">325</td>
                        <td data-stat="pass_td">2</td>
                    </tr>
                </tbody>
            </table>
        </div>
        """
        
        soup = BeautifulSoup(html_content, 'html.parser')
        result = parse_table(soup, 'passing')
        
        # Should parse correctly
        assert isinstance(result, pd.DataFrame)
        assert len(result) == 2
        
        # Should extract player IDs
        assert 'player_id' in result.columns
        assert 'AlleJo02' in result.player_id.values
        assert 'BradTo00' in result.player_id.values
        
        # Should convert numeric columns
        assert result.pass_att.dtype in ['int64', 'float64']
        assert result.pass_yds.dtype in ['int64', 'float64']
        
        # Check specific values
        allen_row = result[result.player == 'Josh Allen'].iloc[0]
        assert allen_row.team == 'BUF'
        assert allen_row.pass_att == 35
        assert allen_row.pass_td == 3

