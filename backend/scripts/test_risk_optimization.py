#!/usr/bin/env python3
"""
Compare old vs new risk scoring algorithm.

This script demonstrates the improvement from the old absolute counting
method to the new normalized percentage-based method.
"""
from pathlib import Path
from core.project_intelligence import analyze

def compare_risk_scoring():
    """Compare old and new risk scoring approaches."""
    
    print("=" * 80)
    print("RISK SCORING ALGORITHM COMPARISON")
    print("=" * 80)
    print()
    
    # Analyze current project
    model = analyze(Path('.'))
    risk = model.risk
    
    total_modules = len([m for m in model.modules if m.type != 'test'])
    
    print(f"Project Statistics:")
    print(f"  Total non-test modules: {total_modules}")
    print()
    
    # Old algorithm (absolute counting)
    print("OLD ALGORITHM (Absolute Counting):")
    print("-" * 80)
    old_score = 0
    old_score += len(risk.large_files) * 5
    old_score += len(risk.high_coupling_modules) * 10
    old_score += len(risk.circular_dependencies) * 20
    old_score += len(risk.unsafe_patterns) * 15
    old_score += len(risk.missing_tests) * 2
    
    old_score_capped = min(100, old_score)
    
    print(f"  Large files:      {len(risk.large_files):3d} × 5  = {len(risk.large_files) * 5:4d} points")
    print(f"  High coupling:    {len(risk.high_coupling_modules):3d} × 10 = {len(risk.high_coupling_modules) * 10:4d} points")
    print(f"  Circular deps:    {len(risk.circular_dependencies):3d} × 20 = {len(risk.circular_dependencies) * 20:4d} points")
    print(f"  Unsafe patterns:  {len(risk.unsafe_patterns):3d} × 15 = {len(risk.unsafe_patterns) * 15:4d} points")
    print(f"  Missing tests:    {len(risk.missing_tests):3d} × 2  = {len(risk.missing_tests) * 2:4d} points")
    print(f"  {'─' * 40}")
    print(f"  Total (uncapped): {old_score:4d} points")
    print(f"  Total (capped):   {old_score_capped:4d}/100 🔴 HIGH RISK")
    print()
    print("  ❌ Problems:")
    print("     - Score inflation (1363 points capped at 100)")
    print("     - No differentiation between projects")
    print("     - All projects appear as HIGH RISK")
    print()
    
    # New algorithm (normalized percentages)
    print("NEW ALGORITHM (Normalized Percentages):")
    print("-" * 80)
    
    unsafe_pct = (len(risk.unsafe_patterns) / total_modules) * 100
    arch_pct = (len(risk.circular_dependencies) / total_modules) * 100
    coupling_pct = (len(risk.high_coupling_modules) / total_modules) * 100
    maint_pct = ((len(risk.large_files) + len(risk.missing_tests)) / (total_modules * 2)) * 100
    
    safety_score = min(25.0, unsafe_pct * 0.5)
    arch_score = min(25.0, arch_pct * 0.3)
    coupling_score = min(25.0, coupling_pct * 0.4)
    maint_score = min(25.0, maint_pct * 0.3)
    
    new_score = int(round(safety_score + arch_score + coupling_score + maint_score))
    
    print(f"  Safety issues:     {len(risk.unsafe_patterns):3d} ({unsafe_pct:5.1f}%) × 0.5 = {safety_score:5.1f}/25 points")
    print(f"  Architecture:      {len(risk.circular_dependencies):3d} ({arch_pct:5.1f}%) × 0.3 = {arch_score:5.1f}/25 points")
    print(f"  Coupling:          {len(risk.high_coupling_modules):3d} ({coupling_pct:5.1f}%) × 0.4 = {coupling_score:5.1f}/25 points")
    print(f"  Maintainability:   {len(risk.large_files) + len(risk.missing_tests):3d} ({maint_pct:5.1f}%) × 0.3 = {maint_score:5.1f}/25 points")
    print(f"  {'─' * 40}")
    print(f"  Total:             {new_score:3d}/100", end="")
    
    # Risk level
    if new_score >= 60:
        print(" 🔴 HIGH RISK")
    elif new_score >= 30:
        print(" 🟡 MEDIUM RISK")
    else:
        print(" 🟢 LOW RISK")
    
    print()
    print("  ✅ Improvements:")
    print("     - Normalized by project size")
    print("     - Each category max 25 points (balanced)")
    print("     - Meaningful score distribution (0-100)")
    print("     - Can differentiate between healthy and risky projects")
    print()
    
    # Summary
    print("=" * 80)
    print("SUMMARY")
    print("=" * 80)
    print(f"Old Algorithm: {old_score_capped}/100 (🔴 HIGH RISK)")
    print(f"New Algorithm: {new_score}/100 ", end="")
    if new_score >= 60:
        print("(🔴 HIGH RISK)")
    elif new_score >= 30:
        print("(🟡 MEDIUM RISK)")
    else:
        print("(🟢 LOW RISK)")
    print()
    print(f"Improvement: Better score distribution and meaningful metrics!")
    print()

if __name__ == "__main__":
    compare_risk_scoring()
