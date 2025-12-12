#!/usr/bin/env python3
"""
Plot Average Carbon Intensity by Day from Benchmark Data

This script:
1. Scans data/outputs/ to find all day directories
2. For each day, extracts carbon intensity data from data/benchmark_data.csv
3. Groups data by policy and calculates average carbon intensity and standard deviation
4. Creates a grouped bar chart with error bars showing statistics for each policy
"""

import os
import sys
import pandas as pd
import plotly.graph_objects as go
from datetime import datetime


def get_season(day_str):
    """
    Determine the season for a given date string (YYYY-MM-DD).
    
    Seasons:
    - Spring: March 1 - May 31
    - Summer: June 1 - August 31
    - Fall (Autumn): September 1 - November 30
    - Winter: December 1 - February 28/29
    
    Args:
        day_str: Date string in format 'YYYY-MM-DD'
    
    Returns:
        Season name: 'Spring', 'Summer', 'Fall', or 'Winter'
    """
    try:
        date_obj = datetime.strptime(day_str, '%Y-%m-%d')
        month = date_obj.month
        
        if month in [3, 4, 5]:  # March, April, May
            return 'Spring'
        elif month in [6, 7, 8]:  # June, July, August
            return 'Summer'
        elif month in [9, 10, 11]:  # September, October, November
            return 'Fall'
        else:  # December, January, February
            return 'Winter'
    except ValueError:
        return 'Unknown'


# Season colors
SEASON_COLORS = {
    'Spring': '#2ca02c',   # Green
    'Summer': '#FFD700',   # Yellow
    'Fall': '#ff7f0e',     # Orange
    'Winter': '#87CEEB',   # Light Blue (Sky Blue)
    'Unknown': '#7f7f7f'   # Gray
}

# Policy names for display
POLICY_NAMES = {
    'Policy1_Carbon_Intensity': 'Immediate Minimum Placement',
    'Policy2_Carbon_Intensity': 'Average Minimum Placement',
    'Policy3_1_Carbon_Intensity': 'Forecast-based Migration (1x)',
    'Policy3_2_Carbon_Intensity': 'Forecast-based Migration (2x)',
    'Policy3_3_Carbon_Intensity': 'Forecast-based Migration (3x)',
}

# Policy colors (matching policy_by_duration chart)
POLICY_COLORS = {
    'Policy1_Carbon_Intensity': '#1f77b4',  # Blue
    'Policy2_Carbon_Intensity': '#ff7f0e',  # Orange
    'Policy3_1_Carbon_Intensity': '#2ca02c',  # Green
    'Policy3_2_Carbon_Intensity': '#d62728',  # Red
    'Policy3_3_Carbon_Intensity': '#9467bd',  # Purple
}

# Policy columns in the CSV
POLICY_COLUMNS = [
    'Policy1_Carbon_Intensity',
    'Policy2_Carbon_Intensity',
    'Policy3_1_Carbon_Intensity',
    'Policy3_2_Carbon_Intensity',
    'Policy3_3_Carbon_Intensity',
]


def get_day_directories(outputs_dir):
    """
    Get all day directories from the outputs directory.
    
    Args:
        outputs_dir: Path to the outputs directory
    
    Returns:
        List of day strings (e.g., ['2020-01-01', '2020-01-26', ...])
    """
    if not os.path.isdir(outputs_dir):
        print(f"Error: Outputs directory not found: {outputs_dir}")
        return []
    
    day_dirs = []
    for item in os.listdir(outputs_dir):
        item_path = os.path.join(outputs_dir, item)
        if os.path.isdir(item_path) and item != 'overall':
            # Check if it's a date format (YYYY-MM-DD)
            try:
                datetime.strptime(item, '%Y-%m-%d')
                day_dirs.append(item)
            except ValueError:
                continue
    
    return sorted(day_dirs)


def calculate_policy_statistics(benchmark_df, day_str):
    """
    Calculate average and standard deviation for each policy for a specific day.
    
    Args:
        benchmark_df: DataFrame containing benchmark data
        day_str: Day string in format 'YYYY-MM-DD'
    
    Returns:
        Dictionary mapping policy names to {'mean', 'std', 'count'}, or None if no data
    """
    # Filter rows where Timestamp starts with the day string
    day_data = benchmark_df[benchmark_df['Timestamp'].str.startswith(day_str)]
    
    if day_data.empty:
        return None
    
    policy_stats = {}
    
    for policy_col in POLICY_COLUMNS:
        if policy_col not in day_data.columns:
            continue
        
        # Extract carbon intensity values (exclude NaN and zero values)
        intensity_values = pd.to_numeric(
            day_data[policy_col],
            errors='coerce'
        ).dropna()
        intensity_values = intensity_values[intensity_values != 0]
        
        if not intensity_values.empty:
            mean_val = intensity_values.mean()
            std_val = intensity_values.std() if len(intensity_values) > 1 else 0.0
            policy_stats[policy_col] = {
                'mean': mean_val,
                'std': std_val,
                'count': len(intensity_values)
            }
    
    return policy_stats if policy_stats else None


def plot_daily_averages(outputs_dir, benchmark_csv_path, output_dir=None):
    """
    Create a grouped bar chart of average carbon intensity by day and policy with standard deviation.
    
    Args:
        outputs_dir: Path to the outputs directory
        benchmark_csv_path: Path to benchmark_data.csv
        output_dir: Directory to save the output (default: outputs_dir/overall)
    """
    # Load benchmark data
    if not os.path.isfile(benchmark_csv_path):
        print(f"Error: Benchmark CSV not found: {benchmark_csv_path}")
        return
    
    print(f"Loading benchmark data from {benchmark_csv_path}...")
    try:
        benchmark_df = pd.read_csv(benchmark_csv_path)
        # Convert Timestamp to string for filtering
        benchmark_df['Timestamp'] = benchmark_df['Timestamp'].astype(str)
        print(f"Loaded {len(benchmark_df)} rows")
    except Exception as e:
        print(f"Error loading benchmark CSV: {e}")
        return
    
    # Get all day directories
    day_dirs = get_day_directories(outputs_dir)
    
    if not day_dirs:
        print(f"Error: No day directories found in {outputs_dir}")
        return
    
    print(f"Found {len(day_dirs)} day directories")
    print(f"Processing days: {', '.join(day_dirs)}")
    print()
    
    # Calculate statistics for each day and policy
    all_day_stats = {}
    for day_str in day_dirs:
        print(f"Processing {day_str}...")
        policy_stats = calculate_policy_statistics(benchmark_df, day_str)
        if policy_stats:
            all_day_stats[day_str] = policy_stats
            for policy_col, stats in policy_stats.items():
                policy_name = POLICY_NAMES.get(policy_col, policy_col)
                print(f"  {policy_name}:")
                print(f"    Average: {stats['mean']:.2f} gCO₂eq")
                print(f"    Std Dev: {stats['std']:.2f} gCO₂eq")
                print(f"    Samples: {stats['count']}")
        else:
            print(f"  Warning: No data found for {day_str}")
        print()
    
    if not all_day_stats:
        print("Error: No valid data found for any day")
        return
    
    # Create line chart
    fig = go.Figure()
    
    days = sorted(all_day_stats.keys())
    
    # Collect all values to determine y-axis range
    all_values = []
    
    # Create numeric positions for x-axis with offsets for each policy to avoid overlap
    # Use numeric positions (0, 1, 2, ...) and add small offsets for each policy
    num_days = len(days)
    base_positions = list(range(num_days))
    
    # Offset each policy by a larger amount to prevent error bar overlap
    # With category type, offsets need to be larger relative to category spacing
    # Spread across 5 policies with more separation
    policy_offsets = [-0.2, -0.1, 0.0, 0.1, 0.2]  # 5 policies, centered around 0
    
    # Create a lighter color by mixing with white (approximate 30% opacity effect)
    def lighten_color(hex_color, factor=0.7):
        """Lighten a hex color by mixing with white"""
        hex_color = hex_color.lstrip('#')
        rgb = tuple(int(hex_color[i:i+2], 16) for i in (0, 2, 4))
        light_rgb = tuple(int(c + (255 - c) * (1 - factor)) for c in rgb)
        return f'rgb({light_rgb[0]}, {light_rgb[1]}, {light_rgb[2]})'
    
    # Create a trace for each policy
    for i, policy_col in enumerate(POLICY_COLUMNS):
        policy_name = POLICY_NAMES.get(policy_col, policy_col)
        policy_values = []
        policy_stds = []
        
        # Calculate offset positions for this policy
        offset = policy_offsets[i]
        policy_x_positions = [pos + offset for pos in base_positions]
        
        for day in days:
            if policy_col in all_day_stats[day]:
                stats = all_day_stats[day][policy_col]
                policy_values.append(stats['mean'])
                policy_stds.append(stats['std'])
                all_values.append(stats['mean'])
            else:
                policy_values.append(None)
                policy_stds.append(0)
        
        # Get policy color and create a lighter version for error bars
        policy_color = POLICY_COLORS.get(policy_col, '#1f77b4')
        error_color = lighten_color(policy_color, factor=0.7)
        
        # Add line trace for this policy with error bars
        # Store day labels for hover template
        day_labels_for_hover = days
        
        fig.add_trace(
            go.Scatter(
                name=policy_name,
                x=policy_x_positions,  # Use offset positions
                y=policy_values,
                mode='lines+markers',
                line=dict(
                    color=policy_color,
                    width=2
                ),
                marker=dict(
                    color=policy_color,
                    size=8
                ),
                error_y=dict(
                    type='data',
                    array=policy_stds,
                    visible=True,
                    color=error_color,  # Use lighter color instead of opacity
                    thickness=1,
                    width=2
                ),
                customdata=day_labels_for_hover,  # Store actual day labels
                hovertemplate=
                f'<b>%{{customdata}}</b><br>' +
                f'{policy_name}: %{{y:.2f}} gCO₂eq<br>' +
                'Std Dev: %{error_y.array:.2f} gCO₂eq<br>' +
                '<extra></extra>'
            )
        )
    
    # Calculate dynamic y-axis range based on data with balanced scaling
    # Filter out None values
    valid_values = [v for v in all_values if v is not None]
    if valid_values:
        max_val = max(valid_values)
        value_range = max_val
        if value_range == 0:
            # All values are zero, use small default range
            y_min = 0
            y_max = 10
        else:
            # Add 10% padding on top, always start at 0
            padding = value_range * 0.1
            y_min = 0
            y_max = max_val + padding
    else:
        # Fallback if no values
        y_min = 0
        y_max = 1000
    
    # Reduce number of x-axis ticks (show every nth day)
    num_ticks = min(10, num_days)  # Show at most 10 ticks
    tick_step = max(1, num_days // num_ticks)
    tick_positions = base_positions[::tick_step]
    tick_labels = [days[i] for i in tick_positions]
    
    fig.update_layout(
        title=dict(
            text='Average Carbon Intensity by Day and Policy',
            font=dict(color='#000000')
        ),
        xaxis=dict(
            title=dict(
                text='Day',
                font=dict(color='#000000')
            ),
            tickmode='array',
            tickvals=tick_positions,
            ticktext=tick_labels,
            tickangle=-45,
            type='linear',  # Use linear instead of category to allow proper offsetting
            tickfont=dict(color='#000000')
        ),
        yaxis=dict(
            title=dict(
                text='Average Carbon Emissions (gCO₂eq)',
                font=dict(color='#000000')
            ),
            range=[y_min, y_max],
            tickfont=dict(color='#000000')
        ),
        legend=dict(
            title=dict(
                text='Policy',
                font=dict(color='#000000')
            ),
            font=dict(color='#000000'),
            orientation="v",
            yanchor="top",
            y=1,
            xanchor="left",
            x=1.02
        ),
        template="plotly_white",
        height=600,
        width=1200,
        hovermode='closest',
        font=dict(color='#000000'),
    )
    
    # Set output directory
    if output_dir is None:
        output_dir = os.path.join(outputs_dir, 'overall')
    os.makedirs(output_dir, exist_ok=True)
    
    # Save bar chart
    output_html = os.path.join(output_dir, "average_carbon_intensity_by_day.html")
    fig.write_html(output_html, include_plotlyjs=True, full_html=True)
    print(f"Bar chart saved: {output_html}")
    
    # Save as PNG
    output_png = os.path.join(output_dir, "average_carbon_intensity_by_day.png")
    try:
        fig.write_image(output_png)
        print(f"Bar chart PNG saved: {output_png}")
    except Exception as e:
        print(f"Could not save PNG (requires kaleido package): {str(e)}")
        print("You can install it with: pip install kaleido")
    
    print(f"\n✓ Chart created with data from {len(all_day_stats)} days")


if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(
        description="Plot average carbon intensity by day and policy from benchmark_data.csv",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Use default paths (data/outputs and data/benchmark_data.csv)
  %(prog)s

  # Specify custom paths
  %(prog)s --outputs-dir custom/outputs --benchmark-csv custom/benchmark_data.csv
        """
    )
    parser.add_argument(
        "--outputs-dir",
        dest="outputs_dir",
        default="data/outputs",
        help="Path to outputs directory (default: data/outputs)"
    )
    parser.add_argument(
        "--benchmark-csv",
        dest="benchmark_csv",
        default="data/benchmark_data.csv",
        help="Path to benchmark_data.csv (default: data/benchmark_data.csv)"
    )
    parser.add_argument(
        "--output-dir",
        dest="output_dir",
        default=None,
        help="Directory to save output (default: outputs_dir/overall)"
    )
    
    args = parser.parse_args()
    
    # Convert relative paths to absolute if needed
    script_dir = os.path.dirname(os.path.abspath(__file__))
    
    outputs_dir = args.outputs_dir
    if not os.path.isabs(outputs_dir):
        outputs_dir = os.path.join(script_dir, outputs_dir)
    
    benchmark_csv_path = args.benchmark_csv
    if not os.path.isabs(benchmark_csv_path):
        benchmark_csv_path = os.path.join(script_dir, benchmark_csv_path)
    
    output_dir = args.output_dir
    if output_dir and not os.path.isabs(output_dir):
        output_dir = os.path.join(script_dir, output_dir)
    
    plot_daily_averages(outputs_dir, benchmark_csv_path, output_dir)
