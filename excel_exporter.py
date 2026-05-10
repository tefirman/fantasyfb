"""
Excel export functionality for fantasy football projections.

This module handles creating formatted Excel spreadsheets with multiple tabs
for rosters, standings, schedule, and analysis results.
"""

import pandas as pd
from typing import Optional


class FantasyExcelExporter:
    """
    Handles Excel export with formatting for fantasy football data.
    """
    
    def __init__(self, output_path: str):
        """
        Initialize Excel writer and formatting.
        
        Args:
            output_path: Full path to output Excel file
        """
        self.writer = pd.ExcelWriter(output_path, engine="xlsxwriter")
        self.workbook = self.writer.book
        
        # Define common formats
        self.center_format = self.workbook.add_format()
        self.center_format.set_align("center")
        self.center_format.set_align("vcenter")
        
        self.money_format = self.workbook.add_format({"num_format": "$0.00"})
        self.money_format.set_align("center")
        self.money_format.set_align("vcenter")
        
        self.percent_format = self.workbook.add_format({"num_format": "0.0%"})
        self.percent_format.set_align("center")
        self.percent_format.set_align("vcenter")
    
    def _autofit_sheet(self, df: pd.DataFrame, sheet_name: str, freeze_cols: int = 1):
        """
        Apply autofit formatting to a sheet.
        
        Args:
            df: DataFrame that was written to the sheet
            sheet_name: Name of the sheet
            freeze_cols: Number of columns to freeze
        """
        worksheet = self.writer.sheets[sheet_name]
        
        for idx, col in enumerate(df.columns):
            series = df[col]
            max_len = min(
                max((series.astype(str).map(len).max(), len(str(series.name)))) + 1, 50
            )
            
            # Apply appropriate formatting based on column name
            if "earnings" in col or sheet_name == "Deltas" and col != "team":
                worksheet.set_column(idx, idx, max_len, self.money_format)
            elif "per_game_" in col or col.endswith("_factor"):
                worksheet.set_column(idx, idx, max_len, self.center_format, {"hidden": True})
            elif col.replace("my_", "").replace("their_", "").replace("_delta", "").replace(
                "_1", ""
            ).replace("_2", "") in [
                "playoffs", "playoff_bye", "winner", "runner_up", "third",
                "pct_rostered"
            ]:
                worksheet.set_column(idx, idx, max_len, self.percent_format)
            else:
                worksheet.set_column(idx, idx, max_len, self.center_format)
        
        # Add autofilter
        worksheet.autofilter(
            "A1:"
            + (
                chr(64 + (df.shape[1] - 1) // 26) + chr(65 + (df.shape[1] - 1) % 26)
            ).replace("@", "")
            + str(df.shape[0] + 1)
        )
        
        # Freeze panes
        worksheet.freeze_panes(1, freeze_cols)
    
    def export_rosters(self, rosters_df: pd.DataFrame):
        """Export rosters with WAR conditional formatting."""
        columns = [
            "name", "position", "current_team", "points_avg", "points_stdev",
            "WAR", "fantasy_team", "num_games", "matchup_factor",
            "status", "bye_week", "until", "starter",
            "injured", "pct_rostered"
        ]

        # Round numeric columns
        df = rosters_df.copy()
        for col in ["points_avg", "points_stdev", "WAR", "matchup_factor"]:
            if col in df.columns:
                df[col] = round(df[col].astype(float), 3)
        
        df[columns].to_excel(self.writer, sheet_name="Rosters", index=False)
        self._autofit_sheet(df[columns], "Rosters")
        
        # Add WAR conditional formatting
        worksheet = self.writer.sheets["Rosters"]
        worksheet.conditional_format(
            "F2:F" + str(len(df) + 1),
            {
                "type": "3_color_scale",
                "min_color": "#FF6347",
                "mid_color": "#FFD700", 
                "max_color": "#3CB371",
            },
        )
    
    def export_available(self, available_df: pd.DataFrame):
        """Export available players with WAR conditional formatting."""
        columns = [
            "name", "position", "current_team", "points_avg", "points_stdev",
            "WAR", "num_games", "matchup_factor",
            "status", "bye_week", "until", "pct_rostered"
        ]

        # Round numeric columns
        df = available_df.copy()
        for col in ["points_avg", "points_stdev", "WAR", "matchup_factor"]:
            if col in df.columns:
                df[col] = round(df[col].astype(float), 3)
        
        df[columns].to_excel(self.writer, sheet_name="Available", index=False)
        self._autofit_sheet(df[columns], "Available")
        
        # Add WAR conditional formatting
        worksheet = self.writer.sheets["Available"]
        worksheet.conditional_format(
            "F2:F" + str(len(df) + 1),
            {
                "type": "3_color_scale",
                "min_color": "#FF6347",
                "mid_color": "#FFD700",
                "max_color": "#3CB371",
            },
        )
    
    def export_schedule(self, schedule_df: pd.DataFrame):
        """Export schedule with win probability formatting."""
        columns = [
            "week", "team_1", "team_2", "win_1", "win_2", "points_avg_1", 
            "points_stdev_1", "points_avg_2", "points_stdev_2", "me"
        ]
        
        df = schedule_df[columns].copy()
        df.to_excel(self.writer, sheet_name="Schedule", index=False)
        self._autofit_sheet(df, "Schedule", freeze_cols=3)
        
        # Add win probability conditional formatting
        worksheet = self.writer.sheets["Schedule"]
        worksheet.conditional_format(
            "D2:E" + str(len(df) + 1),
            {
                "type": "3_color_scale",
                "min_color": "#FF6347",
                "mid_color": "#FFD700",
                "max_color": "#3CB371",
            },
        )
    
    def export_standings(self, standings_df: pd.DataFrame):
        """Export standings with playoff probability formatting."""
        columns = [
            "team", "wins_avg", "wins_stdev", "points_avg", "points_stdev",
            "per_game_avg", "per_game_stdev", "per_game_fano", "playoffs",
            "playoff_bye", "winner", "runner_up", "third", "earnings"
        ]

        df = standings_df[columns].copy()
        df.to_excel(self.writer, sheet_name="Standings", index=False)
        self._autofit_sheet(df, "Standings")

        worksheet = self.writer.sheets["Standings"]

        worksheet.conditional_format(
            "I2:M" + str(len(df) + 1),
            {
                "type": "3_color_scale",
                "min_color": "#FF6347",
                "mid_color": "#FFD700",
                "max_color": "#3CB371",
            },
        )

        worksheet.conditional_format(
            "N2:N" + str(len(df) + 1),
            {
                "type": "3_color_scale",
                "min_color": "#FF6347",
                "mid_color": "#FFD700",
                "max_color": "#3CB371",
            },
        )

    def export_analysis(self, data_df: pd.DataFrame, sheet_name: str,
                       freeze_cols: int = 1):
        """Export analysis results (pickups, adds, drops, trades)."""
        df = data_df.copy()
        df.to_excel(self.writer, sheet_name=sheet_name, index=False)
        self._autofit_sheet(df, sheet_name, freeze_cols)

        worksheet = self.writer.sheets[sheet_name]

        playoff_start_col = "J" if sheet_name == "Trades" else "I" if sheet_name in ["Pickups", "Adds"] else "H"
        playoff_end_col = "N" if sheet_name == "Trades" else "M" if sheet_name in ["Pickups", "Adds"] else "L"

        worksheet.conditional_format(
            f"{playoff_start_col}2:{playoff_end_col}" + str(len(df) + 1),
            {
                "type": "3_color_scale",
                "min_color": "#FF6347",
                "mid_color": "#FFD700",
                "max_color": "#3CB371",
            },
        )

        earnings_col = "O" if sheet_name == "Trades" else "N" if sheet_name in ["Pickups", "Adds"] else "M"
        worksheet.conditional_format(
            f"{earnings_col}2:{earnings_col}" + str(len(df) + 1),
            {
                "type": "3_color_scale",
                "min_color": "#FF6347",
                "mid_color": "#FFD700",
                "max_color": "#3CB371",
            },
        )
    
    def export_deltas(self, deltas_df: pd.DataFrame):
        """Export per-game deltas with full conditional formatting."""
        df = deltas_df.copy()
        df.to_excel(self.writer, sheet_name="Deltas", index=False)
        self._autofit_sheet(df, "Deltas")
        
        worksheet = self.writer.sheets["Deltas"]
        worksheet.conditional_format(
            "B2:" + chr(ord("A") + df.shape[1]) + str(df.shape[0] + 1),
            {
                "type": "3_color_scale",
                "min_color": "#FF6347",
                "mid_color": "#FFD700",
                "max_color": "#3CB371",
            },
        )
    
    def close(self):
        """Close the Excel writer."""
        self.writer.close()
