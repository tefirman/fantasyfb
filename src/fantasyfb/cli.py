"""
Command-line interface for fantasy football analysis.

This module handles parsing command-line arguments and setting up
default values for the fantasy football analysis script.
"""

import datetime
import optparse
import os


def initialize_inputs():
    """
    Initializing arguments based on command line inputs provided by the user.

    Returns:
        optparse.Values: collection of cleaned input values based on inputs and basic logic.
    """
    parser = optparse.OptionParser()
    parser.add_option(
        "--season",
        action="store",
        type="int",
        dest="season",
        help="season of interest"
    )
    parser.add_option(
        "--week",
        action="store",
        type="int",
        dest="week",
        help="week to project the season from"
    )
    parser.add_option(
        "--name",
        action="store",
        dest="name",
        help="name of team to analyze in the case of multiple teams in a single season",
    )
    parser.add_option(
        "--earliest",
        action="store",
        type="int",
        dest="earliest",
        help="earliest week of stats being considered, e.g. 201807 corresponds to week 7 of the 2018 season",
    )
    parser.add_option(
        "--games",
        action="store",
        type="int",
        dest="games",
        help="number of games to build each player's prior off of",
    )
    parser.add_option(
        "--basaloppstringtime",
        action="store",
        dest="basaloppstringtime",
        help="scaling factors for basal/opponent/depthchart/time factors, comma-separated string of values",
    )
    parser.add_option(
        "--sims", action="store", type="int", dest="sims", help="number of season simulations"
    )
    parser.add_option(
        "--payouts",
        action="store",
        dest="payouts",
        help="comma separated string containing integer payouts for 1st, 2nd, and 3rd",
    )
    parser.add_option(
        "--injurytries",
        action="store",
        type="int",
        dest="injurytries",
        default=10,
        help="number of times to try pulling injury statuses before rolling with it",
    )
    parser.add_option(
        "--bestball",
        action="store_true",
        dest="bestball",
        help="whether to assess the league of interest in the context of bestball (simulates bench contributions better)",
    )
    parser.add_option(
        "--pickups",
        action="store",
        dest="pickups",
        help='assess possible free agent pickups for the players specified ("all" will analyze all possible pickups)',
    )
    parser.add_option(
        "--adds",
        action="store_true",
        dest="adds",
        help="whether to assess possible free agent adds",
    )
    parser.add_option(
        "--drops",
        action="store_true",
        dest="drops",
        help="whether to assess possible drops",
    )
    parser.add_option(
        "--trades",
        action="store",
        dest="trades",
        help='assess possible trades for the players specified ("all" will analyze all possible trades)',
    )
    parser.add_option(
        "--given",
        action="store",
        dest="given",
        help="given players to start with for multi-player trades",
    )
    parser.add_option(
        "--deltas",
        action="store_true",
        dest="deltas",
        help="whether to assess deltas for each matchup of the current week",
    )
    parser.add_option(
        "--output",
        action="store",
        dest="output",
        help="where to save the final projections spreadsheet",
    )

    options, args = parser.parse_args()
    
    # Apply default values and validation
    options = _apply_defaults(options)
    options = _validate_inputs(options)
    
    return options


def _apply_defaults(options):
    """Apply default values to command line options."""
    if not options.season:
        options.season = datetime.datetime.now().year - int(datetime.datetime.now().month < 6)
    
    # Handle basaloppstringtime parsing
    if options.basaloppstringtime:
        options.basaloppstringtime = options.basaloppstringtime.split(",")
        if all([val.isnumeric() for val in options.basaloppstringtime]) and len(options.basaloppstringtime) == 4:
            options.basaloppstringtime = [float(val) for val in options.basaloppstringtime]
        else:
            print("Invalid rate inference parameters, using defaults...")
            options.basaloppstringtime = None
    
    # Handle payouts parsing with team-specific defaults
    if options.payouts:
        options.payouts = options.payouts.split(",")
        if all([val.isnumeric() for val in options.payouts]) and len(options.payouts) == 3:
            options.payouts = [float(val) for val in options.payouts]
        else:
            print("Weird values provided for payouts... Assuming standard payouts...")
            options.payouts = [60.0, 30.0, 10.0]
    elif options.name == "The Algorithm":
        options.payouts = [720, 360, 120]
    elif options.name == "Toothless Wonders":
        options.payouts = [350, 100, 50]
    elif options.name == "The GENIEs":
        options.payouts = [120, 0, 0]
    elif options.name == "The Great Gadsby's":
        options.payouts = [50, 35, 15]
    else:
        options.payouts = [60.0, 30.0, 10.0]
    
    return options


def _validate_inputs(options):
    """Validate and set up output directory."""
    if not options.output:
        options.output = (
            os.path.expanduser("~/Documents/")
            if os.path.exists(os.path.expanduser("~/Documents/"))
            else os.path.expanduser("~/")
        )
        
        # Create team directory if it doesn't exist
        if options.name and not os.path.exists(options.output + options.name.replace(" ", "")):
            os.mkdir(options.output + options.name.replace(" ", ""))
        
        # Create season directory if it doesn't exist
        if options.name and not os.path.exists(
            options.output + options.name.replace(" ", "") + "/" + str(options.season)
        ):
            os.mkdir(
                options.output
                + options.name.replace(" ", "")
                + "/"
                + str(options.season)
            )
        
        if options.name:
            options.output += options.name.replace(" ", "") + "/" + str(options.season)
    
    if options.output[-1] != "/":
        options.output += "/"
    
    return options
