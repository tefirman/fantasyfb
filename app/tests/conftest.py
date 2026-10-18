import os
import sys

_HERE = os.path.dirname(__file__)
# app/ for fantasyfb_web, src/ for fantasyfb (works without an editable install).
sys.path.insert(0, os.path.abspath(os.path.join(_HERE, "..")))
sys.path.insert(0, os.path.abspath(os.path.join(_HERE, "..", "..", "src")))
