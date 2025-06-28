#!/usr/bin/env python3
"""
Test runner script for the fantasyfb package.

This script provides convenient ways to run different test suites
and check test coverage.
"""

import sys
import subprocess
from pathlib import Path
import argparse


def run_command(cmd, description=""):
    """Run a command and return success status."""
    if description:
        print(f"\n🔍 {description}")
    
    print(f"Running: {' '.join(cmd)}")
    result = subprocess.run(cmd, capture_output=True, text=True)
    
    if result.stdout:
        print(result.stdout)
    if result.stderr:
        print(result.stderr, file=sys.stderr)
    
    return result.returncode == 0


def check_fixtures():
    """Check if real API fixtures are available."""
    fixtures_dir = Path("tests/fixtures")
    required_fixtures = [
        "user_leagues_real.json",
        "league_settings_real.json"
    ]
    
    missing = []
    for fixture in required_fixtures:
        if not (fixtures_dir / fixture).exists():
            missing.append(fixture)
    
    if missing:
        print("❌ Missing required fixtures:")
        for fixture in missing:
            print(f"   - {fixture}")
        print("\n💡 Run 'python capture_fixtures.py' to generate fixtures")
        return False
    
    print("✅ All required fixtures found")
    return True


def run_basic_tests():
    """Run basic tests without real fixtures."""
    print("🧪 Running basic tests (no real fixtures required)...")
    
    cmd = [
        sys.executable, "-m", "pytest", 
        "tests/", 
        "-v",
        "-m", "not real_api",
        "--tb=short"
    ]
    
    return run_command(cmd, "Basic test suite")


def run_fixture_tests():
    """Run tests that use real fixtures."""
    if not check_fixtures():
        return False
    
    print("🔬 Running tests with real fixtures...")
    
    cmd = [
        sys.executable, "-m", "pytest",
        "tests/",
        "-v", 
        "-m", "real_api",
        "--tb=short"
    ]
    
    return run_command(cmd, "Real fixture tests")


def run_all_tests():
    """Run all tests."""
    print("🚀 Running complete test suite...")
    
    if not check_fixtures():
        print("⚠️  Some tests will be skipped due to missing fixtures")
    
    cmd = [
        sys.executable, "-m", "pytest",
        "tests/",
        "-v",
        "--tb=short"
    ]
    
    return run_command(cmd, "Complete test suite")


def run_fast_tests():
    """Run only fast tests."""
    print("⚡ Running fast tests only...")
    
    cmd = [
        sys.executable, "-m", "pytest",
        "tests/",
        "-v",
        "-m", "not slow",
        "--tb=short"
    ]
    
    return run_command(cmd, "Fast tests")


def run_integration_tests():
    """Run integration tests."""
    print("🔗 Running integration tests...")
    
    cmd = [
        sys.executable, "-m", "pytest",
        "tests/",
        "-v",
        "-m", "integration",
        "--tb=short"
    ]
    
    return run_command(cmd, "Integration tests")


def run_with_coverage():
    """Run tests with coverage report."""
    print("📊 Running tests with coverage...")
    
    # Install pytest-cov if not available
    try:
        import pytest_cov
    except ImportError:
        print("Installing pytest-cov...")
        subprocess.run([sys.executable, "-m", "pip", "install", "pytest-cov"])
    
    cmd = [
        sys.executable, "-m", "pytest",
        "tests/",
        "--cov=src/fantasyfb",
        "--cov-report=term-missing",
        "--cov-report=html:htmlcov",
        "-v"
    ]
    
    success = run_command(cmd, "Tests with coverage")
    
    if success:
        print("\n📈 Coverage report saved to htmlcov/index.html")
    
    return success


def lint_code():
    """Run code linting."""
    print("🧹 Running code linting...")
    
    # Check if ruff is available as a command
    try:
        result = subprocess.run([sys.executable, "-m", "ruff", "--version"], 
                              capture_output=True, text=True)
        if result.returncode == 0:
            # Run ruff check
            cmd = [sys.executable, "-m", "ruff", "check", "src/", "tests/"]
            run_command(cmd, "Ruff linting")
        else:
            print("⚠️  ruff not available, skipping linting")
    except (subprocess.SubprocessError, FileNotFoundError):
        print("⚠️  ruff not installed, skipping linting")
    
    # Check if black is available as a command
    try:
        result = subprocess.run([sys.executable, "-m", "black", "--version"], 
                              capture_output=True, text=True)
        if result.returncode == 0:
            cmd = [sys.executable, "-m", "black", "--check", "src/", "tests/"]
            run_command(cmd, "Black formatting check")
        else:
            print("⚠️  black not available, skipping format check")
    except (subprocess.SubprocessError, FileNotFoundError):
        print("⚠️  black not installed, skipping format check")


def validate_fixtures():
    """Validate that fixtures have correct structure."""
    if not check_fixtures():
        return False
    
    print("🔍 Validating fixture structures...")
    
    cmd = [sys.executable, "tests/fixtures.py"]
    return run_command(cmd, "Fixture validation")


def main():
    """Main test runner."""
    parser = argparse.ArgumentParser(description="Test runner for fantasyfb package")
    parser.add_argument(
        "test_type", 
        nargs="?",
        default="all",
        choices=["all", "basic", "fixtures", "fast", "integration", "coverage", "lint", "validate"],
        help="Type of tests to run"
    )
    parser.add_argument(
        "--check-fixtures", 
        action="store_true",
        help="Only check if fixtures are available"
    )
    
    args = parser.parse_args()
    
    if args.check_fixtures:
        success = check_fixtures()
        sys.exit(0 if success else 1)
    
    print(f"🎯 fantasyfb test runner")
    print(f"Test type: {args.test_type}")
    
    success = True
    
    if args.test_type == "basic":
        success = run_basic_tests()
    elif args.test_type == "fixtures":
        success = run_fixture_tests()
    elif args.test_type == "fast":
        success = run_fast_tests()
    elif args.test_type == "integration":
        success = run_integration_tests()
    elif args.test_type == "coverage":
        success = run_with_coverage()
    elif args.test_type == "lint":
        lint_code()
    elif args.test_type == "validate":
        success = validate_fixtures()
    elif args.test_type == "all":
        success = run_all_tests()
        if success:
            lint_code()
    
    if success:
        print("\n✅ Tests completed successfully!")
    else:
        print("\n❌ Some tests failed!")
        sys.exit(1)


if __name__ == "__main__":
    main()
