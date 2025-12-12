#!/usr/bin/env python3
"""
Benchmarking Suite for Carbon-Aware Scheduling Policies

This script evaluates the carbon efficiency of three scheduling policies:
- Policy 1: Initial placement only (assign to lowest region at runtime, no migrations)
- Policy 2: Hourly migration (migrate to minimum region every hour)
- Policy 3: Forecast-based (compare forecasts and migrate to optimal region)

The benchmarking runs across weekly intervals and calculates total carbon emissions.
"""

import os
import sys
import pandas as pd
import argparse
from datetime import datetime, timedelta
from collections import defaultdict
import json
import glob
import csv
import plotly.graph_objects as go
from plotly.subplots import make_subplots

# Import functions from plot
sys.path.insert(0, os.path.dirname(__file__))
try:
    from plot import (
        collect_csv_files_from_source,
        get_region_from_path,
        calculate_minimum_slope,
        aggregate_minimum,
        aggregate_average,
        get_region_from_filename
    )
except ImportError as e:
    print(f"Error importing from plot: {e}")
    print("Make sure plot.py is in the same directory")
    sys.exit(1)


def load_region_data(regions_directory, x_column='datetime', y_column='carbon_intensity_direct_avg',
                    start_date=None, end_date=None):
    """
    Load all region data from CSV files.
    
    Returns:
        all_data_dict: Dictionary mapping file_path -> DataFrame
        region_data_dict: Dictionary mapping region -> list of DataFrames
    """
    csv_pattern = os.path.join(regions_directory, "*", "*.csv")
    csv_files = glob.glob(csv_pattern)
    
    all_data_dict = {}
    region_data_dict = defaultdict(list)
    
    for csv_file in csv_files:
        try:
            df = pd.read_csv(csv_file)
            if x_column not in df.columns or y_column not in df.columns:
                continue
            
            # Convert datetime and ensure timezone-aware UTC
            df[x_column] = pd.to_datetime(df[x_column], utc=True)
            # Ensure it's timezone-aware
            if df[x_column].dt.tz is None:
                df[x_column] = df[x_column].dt.tz_localize('UTC')
            else:
                df[x_column] = df[x_column].dt.tz_convert('UTC')
            
            # Filter by date range
            if start_date:
                start_datetime = pd.to_datetime(start_date, utc=True)
                if start_datetime.tz is None:
                    start_datetime = start_datetime.tz_localize('UTC')
                else:
                    start_datetime = start_datetime.tz_convert('UTC')
                df = df[df[x_column] >= start_datetime]
            if end_date:
                end_datetime = pd.to_datetime(end_date, utc=True)
                if end_datetime.tz is None:
                    end_datetime = end_datetime.tz_localize('UTC')
                else:
                    end_datetime = end_datetime.tz_convert('UTC')
                end_datetime = end_datetime + timedelta(days=1)
                df = df[df[x_column] < end_datetime]
            
            # Filter out rows with zero values in the y_column
            if not df.empty:
                df = df[df[y_column] != 0].copy()
                if not df.empty:
                    all_data_dict[csv_file] = df.copy()
                    region = get_region_from_path(csv_file)
                    if region:
                        region_data_dict[region].append(df.copy())
        except Exception as e:
            print(f"Warning: Failed to load {csv_file}: {str(e)}")
    
    return all_data_dict, region_data_dict


def get_subregion_intensity_at_time(all_data_dict, subregion_path, timestamp, x_column, y_column):
    """Get carbon intensity for a specific subregion CSV file at a specific timestamp."""
    if subregion_path not in all_data_dict:
        return None
    
    df = all_data_dict[subregion_path]
    
    # Normalize timestamp for comparison
    if isinstance(timestamp, datetime):
        if not isinstance(timestamp, pd.Timestamp):
            timestamp = pd.to_datetime(timestamp, utc=True)
    if isinstance(timestamp, pd.Timestamp):
        if timestamp.tz is None:
            timestamp = timestamp.tz_localize('UTC')
        else:
            timestamp = timestamp.tz_convert('UTC')
    
    if x_column not in df.columns or y_column not in df.columns:
        return None
    
    if df.empty:
        return None
    
    # Try exact match first
    exact_match = df[df[x_column] == timestamp]
    if not exact_match.empty:
        value = exact_match[y_column].iloc[0]
        # Skip NaN values and zero values
        if not pd.isna(value) and value != 0:
            return float(value)
    
    # Find closest timestamp (within 1 hour)
    time_diffs = (df[x_column] - timestamp).abs()
    if len(time_diffs) == 0:
        return None
    
    closest_idx = time_diffs.idxmin()
    closest_diff = time_diffs.loc[closest_idx]
    
    # If within 1 hour, use that value
    if closest_diff <= timedelta(hours=1):
        value = df.loc[closest_idx, y_column]
        # Skip NaN values and zero values
        if not pd.isna(value) and value != 0:
            return float(value)
    
    return None


def get_region_intensity_at_time(region_data_dict, region, timestamp, x_column, y_column):
    """Get carbon intensity for a region at a specific timestamp."""
    if region not in region_data_dict:
        return None
    
    # Normalize timestamp for comparison
    if isinstance(timestamp, datetime):
        if not isinstance(timestamp, pd.Timestamp):
            timestamp = pd.to_datetime(timestamp, utc=True)
    if isinstance(timestamp, pd.Timestamp):
        if timestamp.tz is None:
            timestamp = timestamp.tz_localize('UTC')
        else:
            timestamp = timestamp.tz_convert('UTC')
    
    for df in region_data_dict[region]:
        if x_column not in df.columns or y_column not in df.columns:
            continue
        
        if df.empty:
            continue
        
        # Try exact match first
        exact_match = df[df[x_column] == timestamp]
        if not exact_match.empty:
            value = exact_match[y_column].iloc[0]
            # Skip NaN values and zero values
            if not pd.isna(value) and value != 0:
                return float(value)
        
        # Find closest timestamp (within 1 hour)
        time_diffs = (df[x_column] - timestamp).abs()
        if len(time_diffs) == 0:
            continue
        
        closest_idx = time_diffs.idxmin()
        closest_diff = time_diffs.loc[closest_idx]
        
        # If within 1 hour, use that value
        if closest_diff <= timedelta(hours=1):
            value = df.loc[closest_idx, y_column]
            # Skip NaN values and zero values
            if not pd.isna(value) and value != 0:
                return float(value)
    
    return None


def calculate_region_average_intensity(region_data_dict, region, start_time, end_time, x_column, y_column):
    """Calculate average carbon intensity for a region over a time period."""
    if region not in region_data_dict:
        return None
    
    values = []
    for df in region_data_dict[region]:
        if x_column not in df.columns or y_column not in df.columns:
            continue
        
        # Filter to time range
        filtered_df = df[(df[x_column] >= start_time) & (df[x_column] < end_time)]
        if not filtered_df.empty:
            # Filter out NaN and zero values
            region_values = filtered_df[y_column].dropna()
            region_values = region_values[region_values != 0].tolist()
            values.extend(region_values)
    
    if values:
        return sum(values) / len(values)
    return None


def simulate_policy_1(all_data_dict, min_slope, start_time, end_time, 
                     workload_duration_hours, x_column, y_column, stdout=False):
    """
    Policy 1: Pick the subregion with the lowest value at the beginning (first timestamp),
    then stay in that subregion for the entire workload duration (no migrations).
    Use actual CSV data from that subregion.
    """
    # Normalize start_time
    if isinstance(start_time, datetime):
        if not isinstance(start_time, pd.Timestamp):
            start_time = pd.to_datetime(start_time, utc=True)
    if isinstance(start_time, pd.Timestamp):
        if start_time.tz is None:
            start_time = start_time.tz_localize('UTC')
        else:
            start_time = start_time.tz_convert('UTC')
    
    if not min_slope:
        return None
    
    # Filter min_slope to workload duration
    workload_end_time = start_time + timedelta(hours=workload_duration_hours)
    filtered_min_slope = []
    for point in min_slope:
        if len(point) >= 3:
            timestamp = point[0]
            # Normalize timestamp
            if isinstance(timestamp, pd.Timestamp):
                if timestamp.tz is None:
                    timestamp = timestamp.tz_localize('UTC')
                else:
                    timestamp = timestamp.tz_convert('UTC')
            else:
                timestamp = pd.to_datetime(timestamp, utc=True)
            
            if start_time <= timestamp < workload_end_time:
                filtered_min_slope.append(point)
    
    if not filtered_min_slope:
        return None
    
    # Find the subregion with the lowest value at the FIRST timestamp
    first_point = filtered_min_slope[0]
    if len(first_point) < 3:
        return None
    
    first_timestamp = first_point[0]
    # Normalize first timestamp
    if isinstance(first_timestamp, pd.Timestamp):
        if first_timestamp.tz is None:
            first_timestamp = first_timestamp.tz_localize('UTC')
        else:
            first_timestamp = first_timestamp.tz_convert('UTC')
    else:
        first_timestamp = pd.to_datetime(first_timestamp, utc=True)
    
    # Find the subregion with minimum value at the first timestamp
    best_subregion_path = None
    best_first_value = None
    
    for point in filtered_min_slope:
        if len(point) >= 3:
            timestamp = point[0]
            # Normalize timestamp
            if isinstance(timestamp, pd.Timestamp):
                if timestamp.tz is None:
                    timestamp = timestamp.tz_localize('UTC')
                else:
                    timestamp = timestamp.tz_convert('UTC')
            else:
                timestamp = pd.to_datetime(timestamp, utc=True)
            
            # Only consider the first timestamp
            if timestamp == first_timestamp:
                subregion_path = point[1]
                value = point[2]
                
                if best_first_value is None or value < best_first_value:
                    best_first_value = value
                    best_subregion_path = subregion_path
    
    if not best_subregion_path:
        return None
    
    # Now use that subregion's CSV data for ALL timestamps in the workload duration
    total_emissions = 0.0
    hours_with_data = 0
    region = get_region_from_path(best_subregion_path)
    subregion_name = os.path.splitext(os.path.basename(best_subregion_path))[0]
    
    for point in filtered_min_slope:
        if len(point) >= 3:
            timestamp = point[0]
            # Normalize timestamp
            if isinstance(timestamp, pd.Timestamp):
                if timestamp.tz is None:
                    timestamp = timestamp.tz_localize('UTC')
                else:
                    timestamp = timestamp.tz_convert('UTC')
            else:
                timestamp = pd.to_datetime(timestamp, utc=True)
            
            # Get actual intensity from the selected subregion's CSV
            intensity = get_subregion_intensity_at_time(
                all_data_dict, best_subregion_path, timestamp, x_column, y_column
            )
            
            if intensity is not None:
                total_emissions += intensity
                hours_with_data += 1
    
    if hours_with_data == 0:
        return None
    
    if stdout:
        print(f"\n      Policy 1 total: {total_emissions:.2f} (avg: {total_emissions / hours_with_data:.2f})")
        print(f"        Subregions used: {subregion_name} ({region or 'Unknown'})")
    
    return {
        'policy': 1,
        'region': region,
        'subregion': best_subregion_path,
        'average_intensity': total_emissions / hours_with_data if hours_with_data > 0 else 0,
        'duration_hours': workload_duration_hours,
        'total_emissions': total_emissions,
        'migrations': 0
    }


def simulate_policy_2(all_data_dict, min_slope, start_time, end_time, 
                     workload_duration_hours, x_column, y_column, print_breakdown=True, stdout=False):
    """
    Policy 2: Compare subregions that appear in the min slope.
    For each subregion that has any time as the lowest carbon_intensity_direct_avg,
    calculate the total emissions if we stay in that subregion for the entire workload duration.
    Pick the subregion with the lowest total.
    
    Args:
        print_breakdown: If True, print hourly breakdown (default: True)
    """
    # Normalize start_time
    if isinstance(start_time, datetime):
        if not isinstance(start_time, pd.Timestamp):
            start_time = pd.to_datetime(start_time, utc=True)
    if isinstance(start_time, pd.Timestamp):
        if start_time.tz is None:
            start_time = start_time.tz_localize('UTC')
        else:
            start_time = start_time.tz_convert('UTC')
    
    if not min_slope:
        return None
    
    # Filter min_slope to workload duration and get unique subregions
    workload_end_time = start_time + timedelta(hours=workload_duration_hours)
    unique_subregions = set()
    filtered_min_slope = []
    
    for point in min_slope:
        if len(point) >= 3:
            timestamp = point[0]
            subregion_path = point[1]
            
            # Normalize timestamp
            if isinstance(timestamp, pd.Timestamp):
                if timestamp.tz is None:
                    timestamp = timestamp.tz_localize('UTC')
                else:
                    timestamp = timestamp.tz_convert('UTC')
            else:
                timestamp = pd.to_datetime(timestamp, utc=True)
            
            if start_time <= timestamp < workload_end_time:
                filtered_min_slope.append(point)
                unique_subregions.add(subregion_path)
    
    if not unique_subregions:
        return None
    
    # For each subregion that appears in the min slope, calculate total emissions
    # if we stay in that subregion for the entire workload duration
    subregion_totals = {}
    
    for subregion_path in unique_subregions:
        total_emissions = 0.0
        hours_with_data = 0
        
        # Get timestamps from filtered min_slope
        for point in filtered_min_slope:
            if len(point) >= 3:
                timestamp = point[0]
                # Normalize timestamp
                if isinstance(timestamp, pd.Timestamp):
                    if timestamp.tz is None:
                        timestamp = timestamp.tz_localize('UTC')
                    else:
                        timestamp = timestamp.tz_convert('UTC')
                else:
                    timestamp = pd.to_datetime(timestamp, utc=True)
                
                intensity = get_subregion_intensity_at_time(
                    all_data_dict, subregion_path, timestamp, x_column, y_column
                )
                if intensity is not None:
                    total_emissions += intensity
                    hours_with_data += 1
        
        if hours_with_data > 0:
            subregion_totals[subregion_path] = total_emissions
    
    if not subregion_totals:
        return None
    
    # Find subregion with lowest total
    optimal_subregion = min(subregion_totals.items(), key=lambda x: x[1])[0]
    optimal_total = subregion_totals[optimal_subregion]
    optimal_region = get_region_from_path(optimal_subregion)
    optimal_subregion_name = os.path.splitext(os.path.basename(optimal_subregion))[0]
    
    # Calculate average intensity
    hours_with_data = 0
    for point in filtered_min_slope:
        if len(point) >= 3:
            timestamp = point[0]
            # Normalize timestamp
            if isinstance(timestamp, pd.Timestamp):
                if timestamp.tz is None:
                    timestamp = timestamp.tz_localize('UTC')
                else:
                    timestamp = timestamp.tz_convert('UTC')
            else:
                timestamp = pd.to_datetime(timestamp, utc=True)
            
            intensity = get_subregion_intensity_at_time(
                all_data_dict, optimal_subregion, timestamp, x_column, y_column
            )
            if intensity is not None:
                hours_with_data += 1
    
    avg_intensity = optimal_total / hours_with_data if hours_with_data > 0 else 0
    
    if stdout:
        print(f"\n      Policy 2 total: {optimal_total:.2f} (avg: {avg_intensity:.2f})")
        print(f"        Subregions used: {optimal_subregion_name} ({optimal_region or 'Unknown'})")
    
    return {
        'policy': 2,
        'region': optimal_region,
        'subregion': optimal_subregion,
        'average_intensity': avg_intensity,
        'duration_hours': workload_duration_hours,
        'total_emissions': optimal_total,
        'migrations': 0  # No migrations, just pick best subregion upfront
    }


def simulate_policy_3(all_data_dict, min_slope, breakpoints, start_time, end_time,
                     workload_duration_hours, x_column, y_column, max_migrations=1, stdout=False):
    """
    Policy 3: Optimal sequence with limited number of migrations using dynamic programming.
    Find the optimal path of subregion assignments across timestamps, allowing up to max_migrations transitions.
    
    Uses DP approach:
    - State: (time_index, current_subregion, remaining_migrations)
    - Transition: Stay in current subregion or migrate to another (if migrations remaining)
    - Cost: Emissions from current subregion at each timestamp
    - Goal: Minimize total emissions
    
    Args:
        max_migrations: Maximum number of migrations allowed (default: 1)
    """
    # Normalize start_time
    if isinstance(start_time, datetime):
        if not isinstance(start_time, pd.Timestamp):
            start_time = pd.to_datetime(start_time, utc=True)
    if isinstance(start_time, pd.Timestamp):
        if start_time.tz is None:
            start_time = start_time.tz_localize('UTC')
        else:
            start_time = start_time.tz_convert('UTC')
    
    if not min_slope:
        return None
    
    # Filter min_slope to workload duration
    workload_end_time = start_time + timedelta(hours=workload_duration_hours)
    filtered_min_slope = []
    unique_subregions = set()
    unique_regions = set()
    
    for point in min_slope:
        if len(point) >= 3:
            timestamp = point[0]
            subregion_path = point[1]
            
            # Normalize timestamp
            if isinstance(timestamp, pd.Timestamp):
                if timestamp.tz is None:
                    timestamp = timestamp.tz_localize('UTC')
                else:
                    timestamp = timestamp.tz_convert('UTC')
            else:
                timestamp = pd.to_datetime(timestamp, utc=True)
            
            if start_time <= timestamp < workload_end_time:
                filtered_min_slope.append(point)
                unique_subregions.add(subregion_path)
                region = get_region_from_path(subregion_path)
                if region:
                    unique_regions.add(region)
    
    if not filtered_min_slope:
        return None
    
    # Filter breakpoints to only region-level breakpoints (where region changes)
    region_breakpoints = []
    for bp in breakpoints:
        from_region = bp.get('from_region')
        to_region = bp.get('to_region')
        if from_region and to_region and from_region != to_region:
            bp_ts = bp.get('timestamp')
            if isinstance(bp_ts, pd.Timestamp):
                if bp_ts.tz is None:
                    bp_ts = bp_ts.tz_localize('UTC')
                else:
                    bp_ts = bp_ts.tz_convert('UTC')
            else:
                bp_ts = pd.to_datetime(bp_ts, utc=True)
            
            if start_time <= bp_ts < workload_end_time:
                region_breakpoints.append(bp)
    
    # Get all timestamps from filtered_min_slope (sorted)
    all_timestamps = []
    for point in filtered_min_slope:
        if len(point) >= 3:
            timestamp = point[0]
            # Normalize timestamp
            if isinstance(timestamp, pd.Timestamp):
                if timestamp.tz is None:
                    timestamp = timestamp.tz_localize('UTC')
                else:
                    timestamp = timestamp.tz_convert('UTC')
            else:
                timestamp = pd.to_datetime(timestamp, utc=True)
            all_timestamps.append(timestamp)
    
    all_timestamps = sorted(set(all_timestamps))
    
    if not all_timestamps:
        return None
    
    # Convert unique_subregions to list for indexing
    subregion_list = list(unique_subregions)
    n_timestamps = len(all_timestamps)
    n_subregions = len(subregion_list)
    
    # DP table: dp[time_index][subregion_index][remaining_migrations] = (min_cost, parent_state)
    # parent_state = (prev_time_index, prev_subregion_index, prev_remaining_migrations) or None
    # Use a dictionary for sparse representation
    dp = {}
    parent = {}
    
    # Initialize: for each subregion at time 0 with max_migrations remaining
    for subregion_idx in range(n_subregions):
        subregion_path = subregion_list[subregion_idx]
        timestamp = all_timestamps[0]
        intensity = get_subregion_intensity_at_time(
            all_data_dict, subregion_path, timestamp, x_column, y_column
        )
        if intensity is not None:
            state = (0, subregion_idx, max_migrations)
            dp[state] = intensity
            parent[state] = None
    
    # Fill DP table
    for time_idx in range(1, n_timestamps):
        timestamp = all_timestamps[time_idx]
        
        # For each possible current state
        for prev_subregion_idx in range(n_subregions):
            for prev_remaining in range(max_migrations + 1):
                prev_state = (time_idx - 1, prev_subregion_idx, prev_remaining)
                if prev_state not in dp:
                    continue
                
                prev_cost = dp[prev_state]
                prev_subregion = subregion_list[prev_subregion_idx]
                
                # Option 1: Stay in current subregion
                intensity = get_subregion_intensity_at_time(
                    all_data_dict, prev_subregion, timestamp, x_column, y_column
                )
                if intensity is not None:
                    stay_state = (time_idx, prev_subregion_idx, prev_remaining)
                    new_cost = prev_cost + intensity
                    if stay_state not in dp or new_cost < dp[stay_state]:
                        dp[stay_state] = new_cost
                        parent[stay_state] = prev_state
                
                # Option 2: Migrate to another subregion (if migrations remaining)
                if prev_remaining > 0:
                    for new_subregion_idx in range(n_subregions):
                        if new_subregion_idx == prev_subregion_idx:
                            continue
                        
                        new_subregion = subregion_list[new_subregion_idx]
                        intensity = get_subregion_intensity_at_time(
                            all_data_dict, new_subregion, timestamp, x_column, y_column
                        )
                        if intensity is not None:
                            migrate_state = (time_idx, new_subregion_idx, prev_remaining - 1)
                            new_cost = prev_cost + intensity
                            if migrate_state not in dp or new_cost < dp[migrate_state]:
                                dp[migrate_state] = new_cost
                                parent[migrate_state] = prev_state
    
    # Find optimal solution: minimum cost at final timestamp
    best_final_state = None
    best_cost = float('inf')
    
    for subregion_idx in range(n_subregions):
        for remaining in range(max_migrations + 1):
            final_state = (n_timestamps - 1, subregion_idx, remaining)
            if final_state in dp and dp[final_state] < best_cost:
                best_cost = dp[final_state]
                best_final_state = final_state
    
    if best_final_state is None:
        if stdout:
            print(f"\n      Policy 3: No valid solution found")
        return None
    
    # Reconstruct path
    path_states = []
    current_state = best_final_state
    
    while current_state is not None:
        path_states.append(current_state)
        current_state = parent.get(current_state)
    
    path_states.reverse()  # Reverse to get chronological order
    
    # Build path with (timestamp, subregion_path) pairs
    path = []
    for state in path_states:
        time_idx, subregion_idx, remaining = state
        path.append((all_timestamps[time_idx], subregion_list[subregion_idx]))
    
    # Extract migration points
    migration_points = []
    current_subregion = None
    for timestamp, subregion in path:
        if current_subregion is not None and subregion != current_subregion:
            migration_points.append({
                'timestamp': timestamp,
                'from_subregion': current_subregion,
                'to_subregion': subregion
            })
        current_subregion = subregion
    
    # Create mapping from timestamp to subregion and collect unique subregions used
    timestamp_to_subregion = {}
    unique_subregions_used = set()
    for timestamp, subregion in path:
        timestamp_to_subregion[timestamp] = subregion
        unique_subregions_used.add(subregion)
    
    # Calculate hours with data
    hours_with_data = 0
    for timestamp in all_timestamps:
        current_subregion_path = timestamp_to_subregion.get(timestamp)
        if current_subregion_path is None:
            continue
        
        intensity = get_subregion_intensity_at_time(
            all_data_dict, current_subregion_path, timestamp, x_column, y_column
        )
        
        if intensity is not None:
            hours_with_data += 1
    
    avg_intensity = best_cost / hours_with_data if hours_with_data > 0 else 0
    
    # Print summary
    num_migrations = len(migration_points)
    subregion_names = []
    for subregion_path in sorted(unique_subregions_used):
        subregion_name = os.path.splitext(os.path.basename(subregion_path))[0]
        region = get_region_from_path(subregion_path)
        subregion_names.append(f"{subregion_name} ({region or 'Unknown'})")
    
    if stdout:
        print(f"\n      Policy 3 total: {best_cost:.2f} (avg: {avg_intensity:.2f})")
        if num_migrations == 0:
            print(f"        Subregions used: {', '.join(subregion_names)} (no migrations)")
        else:
            migration_strs = [f"{mp['timestamp'].strftime('%Y-%m-%d %H:%M')}" for mp in migration_points]
            print(f"        Subregions used: {', '.join(subregion_names)} ({num_migrations} migration(s) at: {', '.join(migration_strs)})")
    
    # Get start and end subregions
    start_subregion = path[0][1] if path else None
    end_subregion = path[-1][1] if path else None
    
    return {
        'policy': 3,
        'region': get_region_from_path(start_subregion) if start_subregion else None,
        'subregion': start_subregion,
        'average_intensity': avg_intensity,
        'duration_hours': workload_duration_hours,
        'total_emissions': best_cost,
        'migrations': num_migrations,
        'migration_points': [mp['timestamp'].isoformat() for mp in migration_points] if migration_points else None,
        'end_region': get_region_from_path(end_subregion) if end_subregion else None,
        'end_subregion': end_subregion
    }


def find_breakpoints(min_slope):
    """Find breakpoints where the minimum region changes."""
    breakpoints = []
    if not min_slope or len(min_slope) < 2:
        return breakpoints
    
    last_region = None
    last_subregion_path = None
    for point in min_slope:
        if len(point) >= 3:
            timestamp = point[0]
            subregion_path = point[1]
            region = get_region_from_path(subregion_path)
            
            if region and last_region is not None and region != last_region:
                # Extract subregion names from paths
                from_subregion = os.path.splitext(os.path.basename(last_subregion_path))[0] if last_subregion_path else 'Unknown'
                to_subregion = os.path.splitext(os.path.basename(subregion_path))[0] if subregion_path else 'Unknown'
                
                breakpoints.append({
                    'timestamp': timestamp,
                    'from_region': last_region,
                    'to_region': region,
                    'from_subregion': from_subregion,
                    'to_subregion': to_subregion
                })
            
            if region:
                last_region = region
                last_subregion_path = subregion_path
    
    return breakpoints


def load_min_slope_from_csv(min_carbon_csv_path, week_start, week_end, 
                            x_column='datetime', y_column='carbon_intensity_direct_avg'):
    """
    Load min slope data from min_carbon_sources.csv for a specific time period.
    
    Args:
        min_carbon_csv_path: Path to min_carbon_sources.csv
        week_start: Start datetime
        week_end: End datetime
        x_column: Column name for x-axis
        y_column: Column name for y-axis
    
    Returns:
        min_slope: List of [timestamp, source_path, value] tuples
        unique_regions: Set of regions
    """
    if not os.path.isfile(min_carbon_csv_path):
        return [], set()
    
    try:
        df = pd.read_csv(min_carbon_csv_path)
        
        if x_column not in df.columns or y_column not in df.columns:
            return [], set()
        
        # Convert datetime
        df[x_column] = pd.to_datetime(df[x_column], utc=True)
        
        # Filter to time range
        df = df[(df[x_column] >= week_start) & (df[x_column] < week_end)]
        
        if df.empty:
            return [], set()
        
        # Build min_slope from CSV data
        min_slope = []
        unique_regions = set()
        
        for _, row in df.iterrows():
            timestamp = row[x_column]
            value = row[y_column]
            source_path = row.get('source_path', '')
            region = row.get('region', '')
            subregion_name = row.get('subregion_name', '')
            
            # Skip zero values
            if pd.isna(value) or value == 0:
                continue
            
            # Use source_path if available, otherwise construct from region/subregion
            if not source_path and region and subregion_name:
                # Try to construct path
                source_path = f"data/regions/{region}/{subregion_name}.csv"
            
            min_slope.append([timestamp, source_path, value])
            if region:
                unique_regions.add(region)
        
        return min_slope, unique_regions
        
    except Exception as e:
        print(f"Warning: Failed to load min slope from CSV: {str(e)}")
        return [], set()


def benchmark_week(regions_directory, week_start, workload_duration_hours=12,
                 x_column='datetime', y_column='carbon_intensity_direct_avg',
                 output_dir=None, min_carbon_csv_path=None, stdout=False):
    """
    Benchmark all three policies for a specific week.
    
    Args:
        regions_directory: Path to regions directory
        week_start: Start datetime of the week
        workload_duration_hours: Duration of workload in hours
        x_column: Column name for x-axis
        y_column: Column name for y-axis
        output_dir: Optional directory to save plot outputs
        min_carbon_csv_path: Optional path to min_carbon_sources.csv to use for min slope
    
    Returns:
        Dictionary with benchmark results
    """
    week_end = week_start + timedelta(days=7)
    
    # Load data for this week
    all_data_dict, region_data_dict = load_region_data(
        regions_directory, x_column, y_column,
        start_date=week_start, end_date=week_end
    )
    
    if not all_data_dict:
        return None
    
    # Load min slope from CSV if provided, otherwise calculate from regions
    if min_carbon_csv_path and os.path.isfile(min_carbon_csv_path):
        min_slope, unique_regions = load_min_slope_from_csv(
            min_carbon_csv_path, week_start, week_end, x_column, y_column
        )
    else:
        # Calculate minimum slope for the week (full week period)
        min_slope, unique_regions = calculate_minimum_slope(
            all_data_dict, x_column, y_column, week_start, week_end
        )
    
    breakpoints = find_breakpoints(min_slope)
    
    # Filter min_slope to workload duration (first N hours)
    # Normalize all timestamps in min_slope and sort them
    normalized_min_slope = []
    for point in min_slope:
        if len(point) >= 3:
            timestamp = point[0]
            # Normalize timestamp
            if isinstance(timestamp, pd.Timestamp):
                if timestamp.tz is None:
                    timestamp = timestamp.tz_localize('UTC')
                else:
                    timestamp = timestamp.tz_convert('UTC')
            else:
                timestamp = pd.to_datetime(timestamp, utc=True)
            normalized_min_slope.append([timestamp, point[1], point[2]])
    
    # Sort by timestamp and take first workload_duration_hours
    normalized_min_slope.sort(key=lambda x: x[0])
    filtered_min_slope = normalized_min_slope[:workload_duration_hours]
    
    # Also filter breakpoints to workload duration
    filtered_breakpoints = []
    workload_end_time = week_start + timedelta(hours=workload_duration_hours)
    for bp in breakpoints:
        bp_ts = bp.get('timestamp')
        if isinstance(bp_ts, pd.Timestamp):
            if bp_ts.tz is None:
                bp_ts = bp_ts.tz_localize('UTC')
            else:
                bp_ts = bp_ts.tz_convert('UTC')
        else:
            bp_ts = pd.to_datetime(bp_ts, utc=True)
        
        if week_start <= bp_ts < workload_end_time:
            filtered_breakpoints.append(bp)
    
    # Print subregion data table BEFORE running policies
    if filtered_min_slope:
        # Collect all unique subregions from filtered_min_slope
        unique_subregions = {}
        all_timestamps = []
        
        for point in filtered_min_slope:
            if len(point) >= 3:
                timestamp = point[0]
                subregion_path = point[1]
                
                # Normalize timestamp
                if isinstance(timestamp, pd.Timestamp):
                    if timestamp.tz is None:
                        timestamp = timestamp.tz_localize('UTC')
                    else:
                        timestamp = timestamp.tz_convert('UTC')
                else:
                    timestamp = pd.to_datetime(timestamp, utc=True)
                
                all_timestamps.append(timestamp)
                
                # Extract subregion name
                if subregion_path:
                    subregion_name = os.path.splitext(os.path.basename(subregion_path))[0]
                    if subregion_path not in unique_subregions:
                        unique_subregions[subregion_path] = subregion_name
        
        # Remove duplicates and sort timestamps
        all_timestamps = sorted(set(all_timestamps))
        subregion_paths = sorted(unique_subregions.keys())
        
        if all_timestamps and subregion_paths and stdout:
            print(f"\n    Subregion Data Table ({len(all_timestamps)} timestamps, {len(subregion_paths)} subregions):")
            
            # Print header
            header = "Timestamp".ljust(20)
            for subregion_path in subregion_paths:
                subregion_name = unique_subregions[subregion_path]
                header += f"  {subregion_name}".ljust(20)
            print(f"      {header}")
            print(f"      {'-' * len(header)}")
            
            # Print data rows
            for timestamp in all_timestamps:
                ts_str = timestamp.strftime('%Y-%m-%d %H:%M') if isinstance(timestamp, pd.Timestamp) else str(timestamp)
                row = ts_str.ljust(20)
                
                for subregion_path in subregion_paths:
                    # Get value from this subregion's CSV at this timestamp
                    intensity = get_subregion_intensity_at_time(
                        all_data_dict, subregion_path, timestamp, x_column, y_column
                    )
                    
                    if intensity is not None:
                        row += f"  {intensity:>8.2f}".ljust(20)
                    else:
                        row += f"  {'N/A':>8}".ljust(20)
                
                print(f"      {row}")
    
    # Store min slope and breakpoints in results for printing
    results = {
        'week_start': week_start.isoformat(),
        'week_end': week_end.isoformat(),
        'workload_duration_hours': workload_duration_hours,
        'breakpoints': len(filtered_breakpoints),
        'breakpoint_details': filtered_breakpoints,
        'min_slope': filtered_min_slope,
        'unique_regions': list(unique_regions),
        'policies': {}
    }
    
    # Policy 1: Baseline - follow minimum slope
    policy1_result = simulate_policy_1(
        all_data_dict, filtered_min_slope, week_start, week_end, workload_duration_hours,
        x_column, y_column, stdout=stdout
    )
    if policy1_result:
        results['policies'][1] = policy1_result
    
    # Policy 2: Best static subregion
    policy2_result = simulate_policy_2(
        all_data_dict, filtered_min_slope, week_start, week_end,
        workload_duration_hours, x_column, y_column, stdout=stdout
    )
    if policy2_result:
        results['policies'][2] = policy2_result
    
    # Policy 3: Run with 1, 2, and 3 migrations
    for max_migrations in [1, 2, 3]:
        policy3_result = simulate_policy_3(
            all_data_dict, filtered_min_slope, filtered_breakpoints, week_start, week_end,
            workload_duration_hours, x_column, y_column, max_migrations=max_migrations, stdout=stdout
        )
        if policy3_result:
            results['policies'][f'3_{max_migrations}'] = policy3_result
    
    # Calculate min slope total emissions for comparison
    min_slope_total = 0.0
    for point in filtered_min_slope:
        if len(point) >= 3:
            value = point[2]
            if value is not None and not pd.isna(value) and value != 0:
                min_slope_total += value
    
    # Generate and save plot if output directory is specified
    if output_dir and results['policies']:
        plot_path = plot_benchmark_results(
            results, all_data_dict, regions_directory, output_dir,
            x_column, y_column
        )
        if plot_path:
            results['plot_output'] = plot_path
    
    # Note: CSV writing is now done immediately after each benchmark in run_benchmark_suite
    # This function no longer writes to CSV to avoid duplicate writes
    
    return results


def get_season(month):
    """Get season name from month number."""
    if month in [12, 1, 2]:
        return 'Winter'
    elif month in [3, 4, 5]:
        return 'Spring'
    elif month in [6, 7, 8]:
        return 'Summer'
    else:
        return 'Fall'


def plot_monthly_comparison(month_key, month_data, regions_directory, output_dir,
                           x_column='datetime', y_column='carbon_intensity_direct_avg'):
    """
    Plot comparison of all workload durations for a single month.
    
    Args:
        month_key: String like "2020-01"
        month_data: Dictionary with month information and results for all durations
        regions_directory: Path to regions directory
        output_dir: Directory to save output files
        x_column: Column name for x-axis
        y_column: Column name for y-axis
    """
    if not month_data or 'results' not in month_data or not month_data['results']:
        return None
    
    # Create output directory if it doesn't exist
    os.makedirs(output_dir, exist_ok=True)
    
    # Create figure with subplots
    fig = make_subplots(
        rows=2, cols=2,
        subplot_titles=(
            'Total Emissions by Duration',
            'Policy Comparison by Duration',
            'Efficiency (Emissions per Hour)',
            'Policy Efficiency Comparison'
        ),
        specs=[[{"secondary_y": False}, {"secondary_y": False}],
               [{"secondary_y": False}, {"secondary_y": False}]]
    )
    
    # Collect data for all durations
    durations = []
    policy1_emissions = []
    policy2_emissions = []
    policy3_emissions = []
    policy1_efficiency = []
    policy2_efficiency = []
    policy3_efficiency = []
    
    for result in month_data['results']:
        duration = result['workload_duration_hours']
        durations.append(duration)
        
        policies = result.get('policies', {})
        if 1 in policies:
            policy1_emissions.append(policies[1]['total_emissions'])
            policy1_efficiency.append(policies[1]['total_emissions'] / duration)
        else:
            policy1_emissions.append(None)
            policy1_efficiency.append(None)
        
        if 2 in policies:
            policy2_emissions.append(policies[2]['total_emissions'])
            policy2_efficiency.append(policies[2]['total_emissions'] / duration)
        else:
            policy2_emissions.append(None)
            policy2_efficiency.append(None)
        
        if 3 in policies:
            policy3_emissions.append(policies[3]['total_emissions'])
            policy3_efficiency.append(policies[3]['total_emissions'] / duration)
        else:
            policy3_emissions.append(None)
            policy3_efficiency.append(None)
    
    # Plot 1: Total Emissions by Duration (line chart)
    if any(e is not None for e in policy1_emissions):
        fig.add_trace(
            go.Scatter(x=durations, y=policy1_emissions, name='Policy 1', 
                      mode='lines+markers', line=dict(color='#1f77b4', width=2),
                      marker=dict(size=8)),
            row=1, col=1
        )
    if any(e is not None for e in policy2_emissions):
        fig.add_trace(
            go.Scatter(x=durations, y=policy2_emissions, name='Policy 2',
                      mode='lines+markers', line=dict(color='#ff7f0e', width=2),
                      marker=dict(size=8)),
            row=1, col=1
        )
    if any(e is not None for e in policy3_emissions):
        fig.add_trace(
            go.Scatter(x=durations, y=policy3_emissions, name='Policy 3',
                      mode='lines+markers', line=dict(color='#2ca02c', width=2),
                      marker=dict(size=8)),
            row=1, col=1
        )
    
    # Plot 2: Policy Comparison by Duration (grouped bar chart)
    fig.add_trace(
        go.Bar(x=[f"{d}h" for d in durations], y=policy1_emissions, name='Policy 1',
               marker_color='#1f77b4', showlegend=False),
        row=1, col=2
    )
    fig.add_trace(
        go.Bar(x=[f"{d}h" for d in durations], y=policy2_emissions, name='Policy 2',
               marker_color='#ff7f0e', showlegend=False),
        row=1, col=2
    )
    fig.add_trace(
        go.Bar(x=[f"{d}h" for d in durations], y=policy3_emissions, name='Policy 3',
               marker_color='#2ca02c', showlegend=False),
        row=1, col=2
    )
    
    # Plot 3: Efficiency (Emissions per Hour)
    if any(e is not None for e in policy1_efficiency):
        fig.add_trace(
            go.Scatter(x=durations, y=policy1_efficiency, name='Policy 1',
                      mode='lines+markers', line=dict(color='#1f77b4', width=2),
                      marker=dict(size=8), showlegend=False),
            row=2, col=1
        )
    if any(e is not None for e in policy2_efficiency):
        fig.add_trace(
            go.Scatter(x=durations, y=policy2_efficiency, name='Policy 2',
                      mode='lines+markers', line=dict(color='#ff7f0e', width=2),
                      marker=dict(size=8), showlegend=False),
            row=2, col=1
        )
    if any(e is not None for e in policy3_efficiency):
        fig.add_trace(
            go.Scatter(x=durations, y=policy3_efficiency, name='Policy 3',
                      mode='lines+markers', line=dict(color='#2ca02c', width=2),
                      marker=dict(size=8), showlegend=False),
            row=2, col=1
        )
    
    # Plot 4: Policy Efficiency Comparison (bar chart)
    # Average efficiency across all durations
    avg_eff_1 = sum([e for e in policy1_efficiency if e is not None]) / len([e for e in policy1_efficiency if e is not None]) if any(e is not None for e in policy1_efficiency) else None
    avg_eff_2 = sum([e for e in policy2_efficiency if e is not None]) / len([e for e in policy2_efficiency if e is not None]) if any(e is not None for e in policy2_efficiency) else None
    avg_eff_3 = sum([e for e in policy3_efficiency if e is not None]) / len([e for e in policy3_efficiency if e is not None]) if any(e is not None for e in policy3_efficiency) else None
    
    avg_efficiencies = [e for e in [avg_eff_1, avg_eff_2, avg_eff_3] if e is not None]
    policy_labels = []
    if avg_eff_1 is not None:
        policy_labels.append('Policy 1')
    if avg_eff_2 is not None:
        policy_labels.append('Policy 2')
    if avg_eff_3 is not None:
        policy_labels.append('Policy 3')
    
    if avg_efficiencies:
        fig.add_trace(
            go.Bar(x=policy_labels, y=avg_efficiencies,
                   marker_color=['#1f77b4', '#ff7f0e', '#2ca02c'][:len(avg_efficiencies)],
                   showlegend=False),
            row=2, col=2
        )
    
    # Update layout
    season = month_data['season']
    title = f"Monthly Comparison - {month_key} ({season})"
    
    fig.update_layout(
        title=dict(text=title, x=0.5, xanchor='center'),
        title_font_size=20,
        hovermode="closest",
        template="plotly_white",
        height=1000,
        width=1400,
        showlegend=True
    )
    
    # Update axes
    fig.update_xaxes(title_text="Workload Duration (hours)", row=1, col=1)
    fig.update_yaxes(title_text="Total Emissions", row=1, col=1)
    fig.update_xaxes(title_text="Duration", row=1, col=2)
    fig.update_yaxes(title_text="Total Emissions", row=1, col=2)
    fig.update_xaxes(title_text="Workload Duration (hours)", row=2, col=1)
    fig.update_yaxes(title_text="Emissions per Hour", row=2, col=1)
    fig.update_xaxes(title_text="Policy", row=2, col=2)
    fig.update_yaxes(title_text="Avg Emissions per Hour", row=2, col=2)
    
    # Generate output filename
    output_filename = f"monthly_comparison_{month_key}.html"
    output_path = os.path.join(output_dir, output_filename)
    
    # Save HTML plot
    fig.write_html(
        output_path,
        include_plotlyjs=True,
        full_html=True
    )
    
    return output_path


def plot_benchmark_results(result, all_data_dict, regions_directory, output_dir,
                          x_column='datetime', y_column='carbon_intensity_direct_avg'):
    """
    Plot benchmark results for a single assessment.
    
    Args:
        result: Dictionary with benchmark results
        all_data_dict: Dictionary mapping file_path -> DataFrame
        regions_directory: Path to regions directory
        output_dir: Directory to save output files
        x_column: Column name for x-axis
        y_column: Column name for y-axis
    """
    if not result or 'policies' not in result or not result['policies']:
        return None
    
    # Create output directory if it doesn't exist
    os.makedirs(output_dir, exist_ok=True)
    
    # Create figure with subplots: one for time series, one for comparison
    fig = make_subplots(
        rows=1, cols=2,
        subplot_titles=('Carbon Intensity Over Time', 'Policy Comparison'),
        column_widths=[0.7, 0.3]
    )
    
    # Get week start and end
    week_start = pd.to_datetime(result['week_start'], utc=True)
    week_end = pd.to_datetime(result['week_end'], utc=True)
    
    # Plot minimum slope (baseline - Policy 1) in left subplot
    min_slope, _ = calculate_minimum_slope(
        all_data_dict, x_column, y_column, week_start, week_end
    )
    
    if min_slope:
        min_timestamps = [point[0] for point in min_slope if len(point) >= 3]
        min_values = [point[2] for point in min_slope if len(point) >= 3]
        
        # Normalize timestamps
        min_timestamps_normalized = []
        for ts in min_timestamps:
            if isinstance(ts, pd.Timestamp):
                if ts.tz is None:
                    ts = ts.tz_localize('UTC')
                else:
                    ts = ts.tz_convert('UTC')
            min_timestamps_normalized.append(ts)
        
        fig.add_trace(
            go.Scatter(
                x=min_timestamps_normalized,
                y=min_values,
                name='Policy 1 (Baseline - Min Slope)',
                mode='lines',
                line=dict(width=3, color='#000000'),
                opacity=0.5,
                hovertemplate='<b>%{x}</b><br>Min Intensity: %{y:.2f}<br><extra>Policy 1</extra>',
                showlegend=True
            ),
            row=1, col=1
        )
    
    # Policy colors
    policy_colors = {
        1: '#1f77b4',  # Blue
        2: '#ff7f0e',  # Orange
        3: '#2ca02c'   # Green
    }
    
    policy_names = {
        1: 'Policy 1 (Baseline)',
        2: 'Policy 2 (Best Static)',
        3: 'Policy 3 (Optimal Migration)'
    }
    
    # Create bar chart for policy comparison in right subplot
    policy_numbers = []
    total_emissions = []
    policy_labels = []
    migrations_list = []
    
    for policy_num in sorted(result['policies'].keys()):
        policy_result = result['policies'][policy_num]
        policy_numbers.append(policy_num)
        total_emissions.append(policy_result['total_emissions'])
        migrations = policy_result.get('migrations', 0)
        migrations_list.append(migrations)
        policy_labels.append(
            f"Policy {policy_num}<br>" +
            f"Total: {policy_result['total_emissions']:.2f}<br>" +
            f"Migrations: {migrations}<br>" +
            f"Region: {policy_result.get('region', 'N/A')}"
        )
    
    # Add bar chart for policy comparison
    fig.add_trace(
        go.Bar(
            x=[f"P{p}" for p in policy_numbers],
            y=total_emissions,
            name='Total Emissions',
            marker=dict(color=[policy_colors.get(p, '#7f7f7f') for p in policy_numbers]),
            text=[f"{e:.1f}" for e in total_emissions],
            textposition='outside',
            hovertemplate='<b>%{x}</b><br>Total Emissions: %{y:.2f}<br>Migrations: %{customdata}<br><extra></extra>',
            customdata=migrations_list,
            showlegend=False
        ),
        row=1, col=2
    )
    
    # Update layout
    month_str = week_start.strftime('%Y-%m')
    season = get_season(week_start.month)
    title = f"Benchmark Results - {month_str} ({season}) - {result['workload_duration_hours']}h workload"
    
    fig.update_layout(
        title=dict(text=title, x=0.5, xanchor='center'),
        title_font_size=20,
        hovermode="closest",
        template="plotly_white",
        height=600,
        width=1400,
        showlegend=True
    )
    
    # Update axes
    fig.update_xaxes(title_text="Time", row=1, col=1)
    fig.update_yaxes(title_text="Carbon Intensity", row=1, col=1)
    fig.update_xaxes(title_text="Policy", row=1, col=2)
    fig.update_yaxes(title_text="Total Emissions", row=1, col=2)
    
    # Add date range selector for time series
    fig.update_xaxes(
        rangeslider_visible=True,
        rangeselector=dict(
            buttons=list([
                dict(count=1, label="1d", step="day", stepmode="backward"),
                dict(count=3, label="3d", step="day", stepmode="backward"),
                dict(step="all")
            ])
        ),
        row=1, col=1
    )
    
    # Generate output filename
    month_str_safe = week_start.strftime('%Y-%m')
    duration_str = f"{result['workload_duration_hours']}h"
    output_filename = f"benchmark_{month_str_safe}_{duration_str}.html"
    output_path = os.path.join(output_dir, output_filename)
    
    # Save HTML plot
    fig.write_html(
        output_path,
        include_plotlyjs=True,
        full_html=True
    )
    
    # Try to save as PNG
    image_path = os.path.splitext(output_path)[0] + ".png"
    try:
        fig.write_image(image_path)
    except Exception as e:
        # PNG saving requires kaleido, skip if not available
        pass
    
    return output_path


def plot_duration_comparison(duration, duration_results, output_dir):
    """
    Plot comparison of all months for a specific workload duration.
    
    Args:
        duration: Workload duration in hours
        duration_results: List of results for this duration across all months
        output_dir: Directory to save output files
    """
    if not duration_results:
        return None
    
    # Create output directory if it doesn't exist
    os.makedirs(output_dir, exist_ok=True)
    
    # Create figure with subplots
    fig = make_subplots(
        rows=2, cols=2,
        subplot_titles=(
            'Total Emissions by Month',
            'Policy Comparison by Month',
            'Efficiency (Emissions per Hour) by Month',
            'Seasonal Comparison'
        ),
        specs=[[{"secondary_y": False}, {"secondary_y": False}],
               [{"secondary_y": False}, {"secondary_y": False}]]
    )
    
    # Collect data
    months = []
    seasons = []
    policy1_emissions = []
    policy2_emissions = []
    policy3_emissions = []
    policy1_efficiency = []
    policy2_efficiency = []
    policy3_efficiency = []
    
    for dr in duration_results:
        month_key = dr['month_key']
        month_data = dr['month_data']
        result = dr['result']
        
        months.append(month_key)
        seasons.append(month_data['season'])
        
        policies = result.get('policies', {})
        if 1 in policies:
            policy1_emissions.append(policies[1]['total_emissions'])
            policy1_efficiency.append(policies[1]['total_emissions'] / duration)
        else:
            policy1_emissions.append(None)
            policy1_efficiency.append(None)
        
        if 2 in policies:
            policy2_emissions.append(policies[2]['total_emissions'])
            policy2_efficiency.append(policies[2]['total_emissions'] / duration)
        else:
            policy2_emissions.append(None)
            policy2_efficiency.append(None)
        
        if 3 in policies:
            policy3_emissions.append(policies[3]['total_emissions'])
            policy3_efficiency.append(policies[3]['total_emissions'] / duration)
        else:
            policy3_emissions.append(None)
            policy3_efficiency.append(None)
    
    # Plot 1: Total Emissions by Month
    if any(e is not None for e in policy1_emissions):
        fig.add_trace(
            go.Scatter(x=months, y=policy1_emissions, name='Policy 1',
                      mode='lines+markers', line=dict(color='#1f77b4', width=2),
                      marker=dict(size=6)),
            row=1, col=1
        )
    if any(e is not None for e in policy2_emissions):
        fig.add_trace(
            go.Scatter(x=months, y=policy2_emissions, name='Policy 2',
                      mode='lines+markers', line=dict(color='#ff7f0e', width=2),
                      marker=dict(size=6)),
            row=1, col=1
        )
    if any(e is not None for e in policy3_emissions):
        fig.add_trace(
            go.Scatter(x=months, y=policy3_emissions, name='Policy 3',
                      mode='lines+markers', line=dict(color='#2ca02c', width=2),
                      marker=dict(size=6)),
            row=1, col=1
        )
    
    # Plot 2: Policy Comparison by Month (grouped bar)
    fig.add_trace(
        go.Bar(x=months, y=policy1_emissions, name='Policy 1',
               marker_color='#1f77b4', showlegend=False),
        row=1, col=2
    )
    fig.add_trace(
        go.Bar(x=months, y=policy2_emissions, name='Policy 2',
               marker_color='#ff7f0e', showlegend=False),
        row=1, col=2
    )
    fig.add_trace(
        go.Bar(x=months, y=policy3_emissions, name='Policy 3',
               marker_color='#2ca02c', showlegend=False),
        row=1, col=2
    )
    
    # Plot 3: Efficiency by Month
    if any(e is not None for e in policy1_efficiency):
        fig.add_trace(
            go.Scatter(x=months, y=policy1_efficiency, name='Policy 1',
                      mode='lines+markers', line=dict(color='#1f77b4', width=2),
                      marker=dict(size=6), showlegend=False),
            row=2, col=1
        )
    if any(e is not None for e in policy2_efficiency):
        fig.add_trace(
            go.Scatter(x=months, y=policy2_efficiency, name='Policy 2',
                      mode='lines+markers', line=dict(color='#ff7f0e', width=2),
                      marker=dict(size=6), showlegend=False),
            row=2, col=1
        )
    if any(e is not None for e in policy3_efficiency):
        fig.add_trace(
            go.Scatter(x=months, y=policy3_efficiency, name='Policy 3',
                      mode='lines+markers', line=dict(color='#2ca02c', width=2),
                      marker=dict(size=6), showlegend=False),
            row=2, col=1
        )
    
    # Plot 4: Seasonal Comparison
    season_order = ['Winter', 'Spring', 'Summer', 'Fall']
    season_avg_1 = {}
    season_avg_2 = {}
    season_avg_3 = {}
    
    for season in season_order:
        season_emissions_1 = [policy1_emissions[i] for i, s in enumerate(seasons) if s == season and policy1_emissions[i] is not None]
        season_emissions_2 = [policy2_emissions[i] for i, s in enumerate(seasons) if s == season and policy2_emissions[i] is not None]
        season_emissions_3 = [policy3_emissions[i] for i, s in enumerate(seasons) if s == season and policy3_emissions[i] is not None]
        
        season_avg_1[season] = sum(season_emissions_1) / len(season_emissions_1) if season_emissions_1 else None
        season_avg_2[season] = sum(season_emissions_2) / len(season_emissions_2) if season_emissions_2 else None
        season_avg_3[season] = sum(season_emissions_3) / len(season_emissions_3) if season_emissions_3 else None
    
    seasons_with_data = [s for s in season_order if season_avg_1.get(s) is not None]
    if seasons_with_data:
        avg_1 = [season_avg_1[s] for s in seasons_with_data]
        avg_2 = [season_avg_2[s] for s in seasons_with_data]
        avg_3 = [season_avg_3[s] for s in seasons_with_data]
        
        fig.add_trace(
            go.Bar(x=seasons_with_data, y=avg_1, name='Policy 1',
                   marker_color='#1f77b4', showlegend=False),
            row=2, col=2
        )
        fig.add_trace(
            go.Bar(x=seasons_with_data, y=avg_2, name='Policy 2',
                   marker_color='#ff7f0e', showlegend=False),
            row=2, col=2
        )
        fig.add_trace(
            go.Bar(x=seasons_with_data, y=avg_3, name='Policy 3',
                   marker_color='#2ca02c', showlegend=False),
            row=2, col=2
        )
    
    # Update layout
    title = f"Duration Comparison - {duration}h Workload"
    
    fig.update_layout(
        title=dict(text=title, x=0.5, xanchor='center'),
        title_font_size=20,
        hovermode="closest",
        template="plotly_white",
        height=1000,
        width=1400,
        showlegend=True
    )
    
    # Update axes
    fig.update_xaxes(title_text="Month", row=1, col=1)
    fig.update_yaxes(title_text="Total Emissions", row=1, col=1)
    fig.update_xaxes(title_text="Month", row=1, col=2)
    fig.update_yaxes(title_text="Total Emissions", row=1, col=2)
    fig.update_xaxes(title_text="Month", row=2, col=1)
    fig.update_yaxes(title_text="Emissions per Hour", row=2, col=1)
    fig.update_xaxes(title_text="Season", row=2, col=2)
    fig.update_yaxes(title_text="Avg Total Emissions", row=2, col=2)
    
    # Generate output filename
    output_filename = f"duration_comparison_{duration}h.html"
    output_path = os.path.join(output_dir, output_filename)
    
    # Save HTML plot
    fig.write_html(
        output_path,
        include_plotlyjs=True,
        full_html=True
    )
    
    return output_path


def plot_policy_by_duration_from_csv(csv_path, output_base_dir=None):
    """
    Create policy_by_duration plots using Carbon Intensity instead of Difference.
    
    Args:
        csv_path: Path to benchmark_data.csv file
        output_base_dir: Base directory for output (default: data/outputs)
    """
    if not os.path.isfile(csv_path):
        print(f"Error: CSV file not found: {csv_path}")
        return
    
    df = pd.read_csv(csv_path)
    
    if df.empty:
        print("Error: CSV file is empty")
        return
    
    # Get policy carbon intensity columns
    policy_intensity_columns = [col for col in df.columns if 'Carbon_Intensity' in col]
    policy_intensity_columns = sorted(policy_intensity_columns)  # Sort for consistent ordering
    
    if not policy_intensity_columns:
        print("Error: No policy carbon intensity columns found in CSV")
        return
    
    print(f"Found {len(df)} rows")
    print(f"Policy carbon intensity columns: {', '.join(policy_intensity_columns)}")
    
    # Convert Timestamp to datetime
    if 'Timestamp' not in df.columns:
        print("Error: 'Timestamp' column not found")
        return
    
    df['Timestamp'] = pd.to_datetime(df['Timestamp'], utc=True, errors='coerce')
    df = df.dropna(subset=['Timestamp'])
    df['Day'] = df['Timestamp'].dt.date
    
    # Set up output directory
    if output_base_dir is None:
        csv_dir = os.path.dirname(os.path.abspath(csv_path))
        if 'outputs' in csv_dir:
            output_base_dir = csv_dir
        else:
            output_base_dir = os.path.join(csv_dir, 'outputs')
    os.makedirs(output_base_dir, exist_ok=True)
    
    # Policy colors (matching the color palette)
    policy_colors = {
        'Policy1_Carbon_Intensity': '#1f77b4',  # Blue
        'Policy2_Carbon_Intensity': '#ff7f0e',  # Orange
        'Policy3_1_Carbon_Intensity': '#2ca02c',  # Green
        'Policy3_2_Carbon_Intensity': '#d62728',  # Red
        'Policy3_3_Carbon_Intensity': '#9467bd',  # Purple
    }
    
    policy_names = {
        'Policy1_Carbon_Intensity': 'Immediate Minimum Placement',
        'Policy2_Carbon_Intensity': 'Average Minimum Placement',
        'Policy3_1_Carbon_Intensity': 'Forecast-based Migration (1x)',
        'Policy3_2_Carbon_Intensity': 'Forecast-based Migration (2x)',
        'Policy3_3_Carbon_Intensity': 'Forecast-based Migration (3x)',
    }
    
    # Group by day
    days = sorted(df['Day'].unique())
    print(f"\nCreating graphs for {len(days)} day(s)...")
    
    durations = [6, 12, 18, 24, 30, 36, 42, 48]
    
    for day in days:
        day_df = df[df['Day'] == day].copy()
        if day_df.empty:
            continue
        
        day_str = day.strftime('%Y-%m-%d')
        day_dir = os.path.join(output_base_dir, day_str)
        os.makedirs(day_dir, exist_ok=True)
        
        print(f"\nProcessing {day_str} ({len(day_df)} rows)...")
        
        # Create bar chart: 8 columns (durations), 5 subcolumns (policies)
        fig_bar = go.Figure()
        
        # Prepare data for grouped bar chart
        duration_labels = [f"{d}h" for d in durations]
        
        # Collect all values to determine y-axis range
        all_values = []
        
        for i, policy_col in enumerate(policy_intensity_columns):
            policy_values = []
            for duration in durations:
                duration_data = day_df[day_df['Duration'] == duration]
                if not duration_data.empty:
                    # Convert to numeric and filter out NaN/empty values
                    intensity_values = pd.to_numeric(duration_data[policy_col], errors='coerce')
                    intensity_values = intensity_values.dropna()
                    if not intensity_values.empty:
                        # Average the carbon intensities for this duration
                        avg_intensity = intensity_values.mean()
                        policy_values.append(avg_intensity)
                        all_values.append(avg_intensity)
                    else:
                        policy_values.append(None)
                else:
                    policy_values.append(None)
            
            fig_bar.add_trace(
                go.Bar(
                    name=policy_names.get(policy_col, policy_col),
                    x=duration_labels,
                    y=policy_values,
                    marker_color=policy_colors.get(policy_col, '#7f7f7f'),
                    hovertemplate=
                    f'<b>%{{x}}</b><br>' +
                    f'{policy_names.get(policy_col, policy_col)}: %{{y:.2f}}<br>' +
                    '<extra></extra>'
                )
            )
        
        # Calculate dynamic y-axis range based on data with balanced scaling
        # Filter out None values
        valid_values = [v for v in all_values if v is not None]
        if valid_values:
            min_val = min(valid_values)
            max_val = max(valid_values)
            value_range = max_val - min_val
            if value_range == 0:
                # All values are the same, add small padding
                if min_val > 0:
                    padding = min_val * 0.1  # 10% of the value
                else:
                    padding = 10  # Small fixed padding
                y_min = max(0, min_val - padding)
                y_max = max_val + padding
            else:
                # Add 10% padding on each side to balance the chart
                padding = value_range * 0.1
                y_min = max(0, min_val - padding)
                y_max = max_val + padding
        else:
            # Fallback if no values
            y_min = 0
            y_max = 1000
        
        fig_bar.update_layout(
            title=f'Policy Carbon Intensity by Duration - {day_str}',
            xaxis=dict(
                title='Duration (hours)',
                type='category'
            ),
            yaxis=dict(
                title='Carbon Intensity',
                range=[y_min, y_max]
            ),
            barmode='group',
            legend=dict(
                title='Policy',
                orientation="v",
                yanchor="top",
                y=1,
                xanchor="left",
                x=1.02
            ),
            template="plotly_white",
            height=600,
            width=1200,
        )
        
        bar_output = os.path.join(day_dir, f"policy_by_duration_{day_str}.html")
        fig_bar.write_html(bar_output, include_plotlyjs=True, full_html=True)
        print(f"  Bar chart (by duration) saved: {bar_output}")
        
        # Save bar chart as PNG
        bar_png_output = os.path.join(day_dir, f"policy_by_duration_{day_str}.png")
        try:
            fig_bar.write_image(bar_png_output)
            print(f"  Bar chart (by duration) PNG saved: {bar_png_output}")
        except Exception as e:
            print(f"  Could not save bar chart (by duration) PNG (requires kaleido package): {str(e)}")


def identify_breakpoints_from_csv(min_carbon_csv_path):
    """
    Load min_carbon_sources.csv and identify breakpoints where REGION changes (not subregion).
    
    Args:
        min_carbon_csv_path: Path to min_carbon_sources.csv file
    
    Returns:
        breakpoint_dates: Set of dates (datetime.date objects) where breakpoints occur
        breakpoint_details: List of dictionaries with breakpoint information
    """
    if not os.path.isfile(min_carbon_csv_path):
        print(f"Warning: {min_carbon_csv_path} not found. Falling back to first week of each month.")
        return set(), []
    
    print(f"Loading breakpoints from {min_carbon_csv_path}...")
    
    try:
        df = pd.read_csv(min_carbon_csv_path)
        
        # Ensure datetime column exists
        if 'datetime' not in df.columns:
            print(f"Error: 'datetime' column not found in {min_carbon_csv_path}")
            return set(), []
        
        # Convert datetime column
        df['datetime'] = pd.to_datetime(df['datetime'], utc=True)
        
        # Ensure region and subregion_name columns exist
        if 'region' not in df.columns:
            print(f"Error: 'region' column not found in {min_carbon_csv_path}")
            return set(), []
        
        if 'subregion_name' not in df.columns:
            print(f"Error: 'subregion_name' column not found in {min_carbon_csv_path}")
            return set(), []
        
        # Sort by datetime
        df = df.sort_values('datetime').reset_index(drop=True)
        
        # Identify breakpoints where REGION changes (not subregion)
        breakpoint_dates = set()
        breakpoint_details = []
        
        last_region = None
        last_subregion = None
        for idx in range(len(df)):
            current_region = df.iloc[idx].get('region', 'Unknown')
            current_subregion = df.iloc[idx].get('subregion_name', 'Unknown')
            current_timestamp = df.iloc[idx]['datetime']
            current_date = current_timestamp.date()
            
            # Check if REGION changed (and it's not the first row)
            if last_region is not None and current_region != last_region:
                breakpoint_dates.add(current_date)
                breakpoint_details.append({
                    'timestamp': current_timestamp,
                    'date': current_date,
                    'from_region': last_region,
                    'to_region': current_region,
                    'from_subregion': last_subregion,
                    'to_subregion': current_subregion
                })
            
            last_region = current_region
            last_subregion = current_subregion
        
        print(f"  Found {len(breakpoint_dates)} unique days with region breakpoints")
        print(f"  Total region breakpoints: {len(breakpoint_details)}")
        
        return breakpoint_dates, breakpoint_details
        
    except Exception as e:
        print(f"Error loading {min_carbon_csv_path}: {str(e)}")
        print("Falling back to first week of each month.")
        return set(), []


def run_benchmark_suite(regions_directory, start_year=2020, end_year=2022,
                       x_column='datetime', y_column='carbon_intensity_direct_avg',
                       output_file=None, max_duration_hours=48, min_carbon_csv_path=None, stdout=False):
    """
    Run benchmarking suite on days with breakpoints (from min_carbon_sources.csv) or first week of each month.
    Results are grouped by month (timestamp) first, then by duration.
    
    Args:
        regions_directory: Path to regions directory
        start_year: Start year for benchmarking
        end_year: End year for benchmarking
        x_column: Column name for x-axis
        y_column: Column name for y-axis
        output_file: Optional output JSON file path
        max_duration_hours: Maximum workload duration to test (default: 48)
        min_carbon_csv_path: Path to min_carbon_sources.csv file (default: data/min_carbon_sources.csv)
    """
    import pytz
    
    # Default path for min_carbon_sources.csv
    if min_carbon_csv_path is None:
        # Try to find it relative to regions_directory
        regions_dir = os.path.dirname(regions_directory) if os.path.isfile(regions_directory) else regions_directory
        min_carbon_csv_path = os.path.join(regions_dir, 'min_carbon_sources.csv')
        # If not found, try in data directory
        if not os.path.isfile(min_carbon_csv_path):
            script_dir = os.path.dirname(os.path.abspath(__file__))
            min_carbon_csv_path = os.path.join(script_dir, 'min_carbon_sources.csv')
    
    # Identify breakpoints from CSV
    breakpoint_dates, breakpoint_details = identify_breakpoints_from_csv(min_carbon_csv_path)
    
    if stdout:
        print(f"Starting benchmark suite...")
        print(f"  Regions directory: {regions_directory}")
        print(f"  Years: {start_year}-{end_year}")
        if breakpoint_dates:
            print(f"  Testing days with REGION breakpoints: {len(breakpoint_dates)} unique days")
            print(f"  (Only benchmarking on days where region changes, not subregion changes)")
        else:
            print(f"  Testing first week of each month (no region breakpoints found)")
        print(f"  Workload durations: 6-hour intervals up to 48 hours (6, 12, 18, 24, 30, 36, 42, 48) (up to {max_duration_hours} hours)")
        print(f"  Metric: {y_column}")
        print()
    
    # Generate workload durations: 6-hour intervals up to 48 hours (6, 12, 18, 24, 30, 36, 42, 48)
    workload_durations = list(range(6, 49, 6))  # [6, 12, 18, 24, 30, 36, 42, 48]
    # Filter to only include durations up to max_duration_hours
    workload_durations = [d for d in workload_durations if d <= max_duration_hours]
    
    # Generate test periods based on breakpoints or first week of each month
    test_periods = []
    
    if breakpoint_dates:
        # Filter breakpoint dates so no two are within 21 days (3 weeks) of each other
        sorted_bp_dates = sorted([d for d in breakpoint_dates if start_year <= d.year <= end_year])
        filtered_bp_dates = []
        
        for bp_date in sorted_bp_dates:
            # Check if this date is within 21 days of any already selected date
            too_close = False
            for selected_date in filtered_bp_dates:
                days_diff = abs((bp_date - selected_date).days)
                if days_diff < 21:
                    too_close = True
                    break
            
            if not too_close:
                filtered_bp_dates.append(bp_date)
        
        # Use filtered breakpoint dates - create a week starting from each breakpoint date
        for bp_date in filtered_bp_dates:
            week_start = datetime.combine(bp_date, datetime.min.time()).replace(tzinfo=pytz.UTC)
            week_end = week_start + timedelta(days=7)
            test_periods.append({
                'year': bp_date.year,
                'month': bp_date.month,
                'day': bp_date.day,
                'season': get_season(bp_date.month),
                'week_start': week_start,
                'week_end': week_end,
                'is_breakpoint': True,
                'breakpoint_date': bp_date
            })
    else:
        # Fallback: Generate first week of each month in the range
        for year in range(start_year, end_year + 1):
            for month in range(1, 13):
                # First day of the month
                first_day = datetime(year, month, 1, tzinfo=pytz.UTC)
                # First week (7 days)
                week_end = first_day + timedelta(days=7)
                test_periods.append({
                    'year': year,
                    'month': month,
                    'day': 1,
                    'season': get_season(month),
                    'week_start': first_day,
                    'week_end': week_end,
                    'is_breakpoint': False,
                    'breakpoint_date': None
                })
    
    if stdout:
        print(f"Found {len(test_periods)} test periods to analyze")
        if breakpoint_dates:
            print(f"  Breakpoint dates: {len(breakpoint_dates)} unique days")
        print()
    
    # Create outputs directory
    output_dir = os.path.join(os.path.dirname(regions_directory), 'outputs')
    os.makedirs(output_dir, exist_ok=True)
    
    # Initialize CSV file with header if it doesn't exist
    csv_path = os.path.join(output_dir, 'benchmark_data.csv')
    if not os.path.isfile(csv_path):
        with open(csv_path, 'w', newline='') as f:
            writer = csv.writer(f)
            writer.writerow([
                'Timestamp', 'Duration',
                'Policy1_Difference', 'Policy2_Difference', 
                'Policy3_1_Difference', 'Policy3_2_Difference', 'Policy3_3_Difference',
                'Policy1_Carbon_Intensity', 'Policy2_Carbon_Intensity',
                'Policy3_1_Carbon_Intensity', 'Policy3_2_Carbon_Intensity', 'Policy3_3_Carbon_Intensity'
            ])
    
    if stdout:
        print(f"Output directory: {output_dir}")
        print()
    
    # Group results by month (timestamp) first
    results_by_month = {}
    all_results = []
    
    # Run benchmarks for each test period, testing all durations
    for period_info in test_periods:
        year = period_info['year']
        month = period_info['month']
        day = period_info.get('day', 1)
        season = period_info['season']
        week_start = period_info['week_start']
        week_end = period_info['week_end']
        is_breakpoint = period_info.get('is_breakpoint', False)
        breakpoint_date = period_info.get('breakpoint_date')
        
        month_str = f"{year}-{month:02d}"
        # For breakpoints, include the day in the key to make it unique
        if is_breakpoint and breakpoint_date:
            month_key = f"{year}-{month:02d}-{day:02d}"
            period_label = f"BREAKPOINT: {breakpoint_date.strftime('%Y-%m-%d')} ({season})"
        else:
            month_key = f"{year}-{month:02d}"
            period_label = f"MONTH: {month_str} ({season})"
        
        if stdout:
            print("=" * 80)
            print(f"{period_label} - {week_start.strftime('%Y-%m-%d')} to {week_end.strftime('%Y-%m-%d')}")
            print("=" * 80)
            print()
        
        month_results = []
        
        # Extract the date from week_start for creating multiple start times
        if isinstance(week_start, pd.Timestamp):
            test_date = week_start.date()
        elif isinstance(week_start, datetime):
            test_date = week_start.date()
        else:
            # Convert to datetime if needed
            if hasattr(week_start, 'date'):
                test_date = week_start.date()
            else:
                test_date = pd.to_datetime(week_start, utc=True).date()
        
        # Define 4 start times: 00:00, 06:00, 12:00, 18:00
        start_hours = [0, 6, 12, 18]
        
        # Test all durations for this month
        for duration in workload_durations:
            if stdout:
                print(f"  Duration: {duration} hours")
            
            # Track results for this duration to print summary once
            duration_results = []
            
            # Run 4 iterations at different times of day
            for start_hour in start_hours:
                # Create start time for this iteration
                iteration_start = datetime.combine(test_date, datetime.min.time().replace(hour=start_hour)).replace(tzinfo=pytz.UTC)
                
                if stdout:
                    print(f"    Iteration at {start_hour:02d}:00")
                
                result = benchmark_week(
                    regions_directory, iteration_start, duration,
                    x_column, y_column, output_dir=None,  # We'll create monthly plots instead
                    min_carbon_csv_path=min_carbon_csv_path, stdout=stdout
                )
                
                if result:
                    # Add metadata
                    result['year'] = year
                    result['month'] = month
                    result['season'] = season
                    result['workload_duration_hours'] = duration
                    duration_results.append(result)
                    month_results.append(result)
                    all_results.append(result)
                    
                    # Write to CSV immediately after computation
                    # Calculate min slope total emissions for comparison
                    filtered_min_slope = result.get('min_slope', [])
                    min_slope_total = 0.0
                    for point in filtered_min_slope:
                        if len(point) >= 3:
                            value = point[2]
                            if value is not None and not pd.isna(value) and value != 0:
                                min_slope_total += value
                    
                    # Prepare CSV row data
                    timestamp_str = iteration_start.strftime('%Y-%m-%d %H:%M:%S') if isinstance(iteration_start, pd.Timestamp) else iteration_start.isoformat()
                    duration_hours = duration
                    
                    # Get policy emissions and calculate differences
                    policy1_emissions = result['policies'].get(1, {}).get('total_emissions', None)
                    policy2_emissions = result['policies'].get(2, {}).get('total_emissions', None)
                    policy3_1_emissions = result['policies'].get('3_1', {}).get('total_emissions', None)
                    policy3_2_emissions = result['policies'].get('3_2', {}).get('total_emissions', None)
                    policy3_3_emissions = result['policies'].get('3_3', {}).get('total_emissions', None)
                    
                    # Calculate ratio differences: min_slope_emissions / policy_emissions
                    # This represents optimal output / produced output (ratio between 0-1)
                    def calc_difference(policy_emissions, min_slope_emissions):
                        if policy_emissions is None or min_slope_emissions is None or policy_emissions == 0:
                            return None
                        return min_slope_emissions / policy_emissions
                    
                    policy1_diff = calc_difference(policy1_emissions, min_slope_total)
                    policy2_diff = calc_difference(policy2_emissions, min_slope_total)
                    policy3_1_diff = calc_difference(policy3_1_emissions, min_slope_total)
                    policy3_2_diff = calc_difference(policy3_2_emissions, min_slope_total)
                    policy3_3_diff = calc_difference(policy3_3_emissions, min_slope_total)
                    
                    # Write to CSV immediately (file already initialized with header)
                    with open(csv_path, 'a', newline='') as f:
                        writer = csv.writer(f)
                        # Write data row
                        writer.writerow([
                            timestamp_str,
                            duration_hours,
                            f"{policy1_diff:.4f}" if policy1_diff is not None else "",
                            f"{policy2_diff:.4f}" if policy2_diff is not None else "",
                            f"{policy3_1_diff:.4f}" if policy3_1_diff is not None else "",
                            f"{policy3_2_diff:.4f}" if policy3_2_diff is not None else "",
                            f"{policy3_3_diff:.4f}" if policy3_3_diff is not None else "",
                            f"{policy1_emissions:.2f}" if policy1_emissions is not None else "",
                            f"{policy2_emissions:.2f}" if policy2_emissions is not None else "",
                            f"{policy3_1_emissions:.2f}" if policy3_1_emissions is not None else "",
                            f"{policy3_2_emissions:.2f}" if policy3_2_emissions is not None else "",
                            f"{policy3_3_emissions:.2f}" if policy3_3_emissions is not None else ""
                        ])
            
            # Print summary for this duration (once after all 4 iterations)
            if stdout and duration_results:
                # Use the first result for breakpoint info (they should be similar)
                first_result = duration_results[0]
                breakpoints = first_result.get('breakpoint_details', [])
                if breakpoints:
                    print(f"    Breakpoints: {len(breakpoints)} identified")
                    for i, bp in enumerate(breakpoints[:10], 1):  # Print first 10
                        ts = bp.get('timestamp')
                        from_region = bp.get('from_region', 'Unknown')
                        to_region = bp.get('to_region', 'Unknown')
                        from_subregion = bp.get('from_subregion', 'Unknown')
                        to_subregion = bp.get('to_subregion', 'Unknown')
                        ts_str = ts.strftime('%Y-%m-%d %H:%M') if isinstance(ts, pd.Timestamp) else str(ts)
                        print(f"      {i}. {ts_str}: {from_region} ({from_subregion}) -> {to_region} ({to_subregion})")
                    if len(breakpoints) > 10:
                        print(f"      ... ({len(breakpoints) - 10} more breakpoints)")
                else:
                    print(f"    Breakpoints: None identified")
                
                # Print summary for this duration
                print(f"\n    Policy results (4 iterations completed):")
                if first_result['policies']:
                    for policy_num in sorted(first_result['policies'].keys()):
                        # Calculate average across all 4 iterations
                        avg_emissions = sum(r['policies'].get(policy_num, {}).get('total_emissions', 0) for r in duration_results) / len(duration_results)
                        avg_migrations = sum(r['policies'].get(policy_num, {}).get('migrations', 0) for r in duration_results) / len(duration_results)
                        print(f"    Policy {policy_num}: {avg_emissions:.2f} avg emissions, "
                              f"{avg_migrations:.2f} avg migrations")
                else:
                    print(f"    No policy results")
            
            if stdout:
                print()
        
        # Store results for this month
        if month_results:
            results_by_month[month_key] = {
                'year': year,
                'month': month,
                'season': season,
                'week_start': week_start,
                'week_end': week_end,
                'results': month_results
            }
            
            # Generate monthly comparison plot
            plot_monthly_comparison(month_key, results_by_month[month_key], 
                                  regions_directory, output_dir, x_column, y_column)
        
        if stdout:
            print()
    
    # Generate duration comparison plots (all months for each duration)
    if stdout:
        print("=" * 80)
        print("GENERATING DURATION COMPARISON PLOTS")
        print("=" * 80)
        print()
    
    for duration in workload_durations:
        # Collect all results for this duration across all months
        duration_results = []
        for month_key, month_data in results_by_month.items():
            for result in month_data['results']:
                if result['workload_duration_hours'] == duration:
                    duration_results.append({
                        'month_key': month_key,
                        'month_data': month_data,
                        'result': result
                    })
        
        if duration_results:
            plot_duration_comparison(duration, duration_results, output_dir)
    
    # Generate policy_by_duration plots using Carbon Intensity
    if stdout:
        print("=" * 80)
        print("GENERATING POLICY BY DURATION PLOTS (CARBON INTENSITY)")
        print("=" * 80)
        print()
    
    # Create policy_by_duration plots from the CSV file
    csv_path = os.path.join(output_dir, 'benchmark_data.csv')
    if os.path.isfile(csv_path):
        plot_policy_by_duration_from_csv(csv_path, output_dir)
    else:
        if stdout:
            print(f"Warning: CSV file not found at {csv_path}, skipping policy_by_duration plots")
    
    # Continue with summary statistics...
    
    # Calculate summary statistics by duration and season
    if stdout:
        print("=" * 80)
        print("BENCHMARK SUMMARY")
        print("=" * 80)
    
    # Organize results by duration and season
    results_by_duration = defaultdict(lambda: defaultdict(list))
    results_by_season = defaultdict(lambda: defaultdict(list))
    
    for result in all_results:
        duration = result.get('workload_duration_hours', 0)
        season = result.get('season', 'Unknown')
        
        for policy_num, policy_result in result.get('policies', {}).items():
            results_by_duration[duration][policy_num].append(policy_result)
            results_by_season[season][policy_num].append(policy_result)
    
    # Print summary by duration
    if stdout:
        print("\n" + "=" * 80)
        print("SUMMARY BY WORKLOAD DURATION")
        print("=" * 80)
        
        for duration in sorted(workload_durations):
            if duration not in results_by_duration:
                continue
            
            print(f"\nDuration: {duration} hours")
            print(f"{'Policy':<10} {'Avg Emissions':<20} {'Total Migrations':<20} {'Avg Migrations':<20} {'Samples':<10}")
            print("-" * 90)
            
            for policy_num in sorted([1, 2, 3]):
                if policy_num not in results_by_duration[duration]:
                    continue
                
                policy_results = results_by_duration[duration][policy_num]
                avg_emissions = sum(r['total_emissions'] for r in policy_results) / len(policy_results)
                total_migrations = sum(r['migrations'] for r in policy_results)
                avg_migrations = total_migrations / len(policy_results) if policy_results else 0
                
                print(f"{policy_num:<10} {avg_emissions:<20.2f} {total_migrations:<20} {avg_migrations:<20.2f} {len(policy_results):<10}")
        
        # Print summary by season
        print("\n" + "=" * 80)
        print("SUMMARY BY SEASON")
        print("=" * 80)
        
        for season in ['Winter', 'Spring', 'Summer', 'Fall']:
            if season not in results_by_season:
                continue
            
            print(f"\n{season}:")
            print(f"{'Policy':<10} {'Avg Emissions':<20} {'Total Migrations':<20} {'Avg Migrations':<20} {'Samples':<10}")
            print("-" * 90)
            
            for policy_num in sorted([1, 2, 3]):
                if policy_num not in results_by_season[season]:
                    continue
                
                policy_results = results_by_season[season][policy_num]
                avg_emissions = sum(r['total_emissions'] for r in policy_results) / len(policy_results)
                total_migrations = sum(r['migrations'] for r in policy_results)
                avg_migrations = total_migrations / len(policy_results) if policy_results else 0
                
                print(f"{policy_num:<10} {avg_emissions:<20.2f} {total_migrations:<20} {avg_migrations:<20.2f} {len(policy_results):<10}")
    
    # Overall comparison
    overall_totals = defaultdict(float)
    overall_migrations = defaultdict(int)
    overall_samples = defaultdict(int)
    
    for result in all_results:
        for policy_num, policy_result in result.get('policies', {}).items():
            overall_totals[policy_num] += policy_result['total_emissions']
            overall_migrations[policy_num] += policy_result['migrations']
            overall_samples[policy_num] += 1
    
    if stdout:
        print("\n" + "=" * 80)
        print("OVERALL COMPARISON")
        print("=" * 80)
        print(f"\n{'Policy':<10} {'Total Emissions':<20} {'Avg Emissions':<20} {'Total Migrations':<20} {'Avg Migrations':<20} {'Samples':<10}")
        print("-" * 100)
        
        for policy_num in sorted([1, 2, 3]):
            if policy_num not in overall_totals:
                continue
            
            total = overall_totals[policy_num]
            samples = overall_samples[policy_num]
            migrations = overall_migrations[policy_num]
            avg = total / samples if samples > 0 else 0
            avg_migrations = migrations / samples if samples > 0 else 0
            
            print(f"{policy_num:<10} {total:<20.2f} {avg:<20.2f} {migrations:<20} {avg_migrations:<20.2f} {samples:<10}")
        
        # Find best policy overall
        if overall_totals:
            best_policy = min(overall_totals.items(), key=lambda x: x[1])[0]
            print(f"\nBest Policy (lowest total emissions): Policy {best_policy}")
            print(f"  Total emissions: {overall_totals[best_policy]:.2f}")
            print(f"  Average emissions: {overall_totals[best_policy] / overall_samples[best_policy]:.2f}")
    
    # Save results to file
    if output_file:
        summary = {
            'benchmark_config': {
                'regions_directory': regions_directory,
                'start_year': start_year,
                'end_year': end_year,
                'workload_durations': workload_durations,
                'x_column': x_column,
                'y_column': y_column,
                'max_duration_hours': max_duration_hours
            },
            'summary_statistics': {
                'overall_totals': dict(overall_totals),
                'overall_migrations': dict(overall_migrations),
                'overall_samples': dict(overall_samples),
                'by_duration': {
                    str(d): {
                        str(p): {
                            'avg_emissions': sum(r['total_emissions'] for r in results_by_duration[d][p]) / len(results_by_duration[d][p]) if results_by_duration[d][p] else 0,
                            'total_migrations': sum(r['migrations'] for r in results_by_duration[d][p]),
                            'samples': len(results_by_duration[d][p])
                        } for p in results_by_duration[d].keys()
                    } for d in sorted(workload_durations) if d in results_by_duration
                },
                'by_season': {
                    s: {
                        str(p): {
                            'avg_emissions': sum(r['total_emissions'] for r in results_by_season[s][p]) / len(results_by_season[s][p]) if results_by_season[s][p] else 0,
                            'total_migrations': sum(r['migrations'] for r in results_by_season[s][p]),
                            'samples': len(results_by_season[s][p])
                        } for p in results_by_season[s].keys()
                    } for s in ['Winter', 'Spring', 'Summer', 'Fall'] if s in results_by_season
                }
            },
            'detailed_results': all_results
        }
        
        with open(output_file, 'w') as f:
            json.dump(summary, f, indent=2, default=str)
        
        if stdout:
            print(f"\nDetailed results saved to: {output_file}")
    
    return all_results


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Benchmark carbon-aware scheduling policies across weekly intervals",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Benchmark first week of each month in 2020-2022 with multiple durations
  %(prog)s data/regions --start-year 2020 --end-year 2022

  # Test up to 192 hours (will test 4, 8, 12, 16, 24, 32, 48, 64, 96, 192)
  %(prog)s data/regions --max-duration 192

  # Save results to JSON file
  %(prog)s data/regions --output benchmark_results.json
        """
    )
    parser.add_argument(
        "regions_directory",
        help="Directory containing region subdirectories with CSV files"
    )
    parser.add_argument(
        "--start-year",
        type=int,
        default=2020,
        help="Start year for benchmarking (default: 2020)"
    )
    parser.add_argument(
        "--end-year",
        type=int,
        default=2022,
        help="End year for benchmarking (default: 2022)"
    )
    parser.add_argument(
        "--max-duration",
        type=int,
        dest="max_duration_hours",
        default=48,
        help="Maximum workload duration to test in hours (default: 48, will test 6, 12, 18, 24, 30, 36, 42, 48)"
    )
    parser.add_argument(
        "-x", "--x-axis",
        dest="x_column",
        default="datetime",
        help="Column name for x-axis (default: 'datetime')"
    )
    parser.add_argument(
        "-y", "--y-axis",
        dest="y_column",
        default="carbon_intensity_direct_avg",
        help="Column name for y-axis (default: 'carbon_intensity_direct_avg')"
    )
    parser.add_argument(
        "-o", "--output",
        dest="output_file",
        help="Output JSON file path for detailed results"
    )
    parser.add_argument(
        "--min-carbon-csv",
        dest="min_carbon_csv",
        help="Path to min_carbon_sources.csv file (default: data/min_carbon_sources.csv relative to regions directory)"
    )
    parser.add_argument(
        "--stdout",
        action="store_true",
        help="Print output to stdout (default: False, only writes to CSV)"
    )
    
    args = parser.parse_args()
    
    if not os.path.isdir(args.regions_directory):
        print(f"Error: Directory not found: {args.regions_directory}")
        sys.exit(1)
    
    run_benchmark_suite(
        args.regions_directory,
        start_year=args.start_year,
        end_year=args.end_year,
        x_column=args.x_column,
        y_column=args.y_column,
        output_file=args.output_file,
        max_duration_hours=args.max_duration_hours,
        min_carbon_csv_path=args.min_carbon_csv,
        stdout=args.stdout
    )

