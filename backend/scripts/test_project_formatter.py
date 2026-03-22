#!/usr/bin/env python3
"""
Test script to demonstrate the new Project Intelligence formatter.

This shows how AI agents will now get beautiful, formatted output
when analyzing projects.
"""
import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from core.project_intelligence import analyze, format_project_analysis


def test_formatter():
    """Test the new formatter on a real project."""
    
    # Analyze this project
    workspace = project_root
    print(f"🔍 Analyzing project: {workspace}\n")
    
    model = analyze(workspace)
    
    print("=" * 80)
    print("EXECUTIVE SUMMARY (Brief Mode)")
    print("=" * 80)
    
    # Test brief summary
    from core.project_intelligence.formatter import ProjectFormatter
    formatter = ProjectFormatter(model)
    print(formatter.executive_summary(style="markdown"))
    
    print("\n" + "=" * 80)
    print("ARCHITECTURE OVERVIEW")
    print("=" * 80)
    
    print(formatter.architecture_overview(include_tree=False))
    
    print("\n" + "=" * 80)
    print("RISK ASSESSMENT REPORT")
    print("=" * 80)
    
    print(formatter.risk_assessment_report(detailed=True))
    
    print("\n" + "=" * 80)
    print("FULL FORMATTED ANALYSIS (Convenience Function)")
    print("=" * 80)
    
    # Test convenience function
    full_report = format_project_analysis(
        model,
        include_sections=["summary", "architecture", "risks"],
        style="markdown"
    )
    print(full_report)
    
    print("\n" + "=" * 80)
    print("✅ Formatter test completed successfully!")
    print("=" * 80)


if __name__ == "__main__":
    test_formatter()
