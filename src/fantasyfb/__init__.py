# fantasyfb/__init__.py
"""
Fantasy Football Analysis Package

A comprehensive package for analyzing fantasy football leagues using
Monte Carlo simulations, WAR calculations, and advanced statistical modeling.
"""

from .analysis.simulator import SeasonSimulator
from .analysis.trades import TradeAnalyzer
from .core.league import League
from .core.player import Player
from .data.yahoo_client import YahooClient

__version__ = "0.1.0"
__author__ = "Taylor Firman"

# Main exports
__all__ = [
    "League",
    "Player",
    "SeasonSimulator",
    "TradeAnalyzer",
    "YahooClient"
]
