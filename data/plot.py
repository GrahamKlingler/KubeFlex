import os
import sys
import glob
import pandas as pd
import argparse
from datetime import datetime, timedelta
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from collections import defaultdict


# Define color palette for regions
# Each region gets a distinct color, and all subregions within that region share the same color
REGION_COLORS = {
    'CAL': '#1f77b4',   # Blue
    'CAR': '#ff7f0e',   # Orange
    'CENT': '#2ca02c',  # Green
    'FLA': '#d62728',   # Red
    'HI': '#9467bd',    # Purple
    'MIDA': '#8c564b',  # Brown
    'MIDW': '#e377c2',  # Pink
    'NE': '#7f7f7f',    # Gray
    'NW': '#bcbd22',    # Yellow-green
    'NY': '#17becf',    # Cyan
    'SE': '#ff9896',    # Light red
    'SW': '#c5b0d5',    # Light purple
    'TEN': '#c49c94',   # Light brown
    'TEX': '#f7b6d3',   # Light pink
}

# Default color for regions not in the mapping
DEFAULT_COLOR = '#aec7e8'  # Light blue

# Fixed color palette for legend (Plotly default colors)
COLOR_PALETTE = [
    '#1f77b4',  # Blue
    '#ff7f0e',  # Orange
    '#2ca02c',  # Green
    '#d62728',  # Red
    '#9467bd',  # Purple
    '#8c564b',  # Brown
    '#e377c2',  # Pink
    '#7f7f7f',  # Gray
    '#bcbd22',  # Yellow-green
    '#17becf',  # Cyan
    '#ff9896',  # Light red
    '#c5b0d5',  # Light purple
    '#c49c94',  # Light brown
    '#f7b6d3',  # Light pink
    '#aec7e8',  # Light blue
    '#ffbb78',  # Light orange
    '#98df8a',  # Light green
    '#ff9896',  # Light red
    '#c5b0d5',  # Light purple
    '#ff9896',  # Light red
]

# Color for the minimum slope line
MIN_SLOPE_COLOR = '#000000'  # Black
MIN_SLOPE_WIDTH = 3  # Thicker line for visibility
MIN_SLOPE_OPACITY = 0.5  # Reduced opacity for min slope


def get_region_from_path(file_path):
    """
    Extract region code from file path.
    Assumes structure: .../regions/REGION/subregion.csv
    """
    # Normalize path and split
    normalized_path = os.path.normpath(file_path)
    path_parts = normalized_path.split(os.sep)
    
    # Find 'regions' in the path and get the next directory
    try:
        regions_idx = path_parts.index('regions')
        if regions_idx + 1 < len(path_parts):
            return path_parts[regions_idx + 1]
    except ValueError:
        pass
    
    # Fallback: try to extract from filename (e.g., US-CAL-CISO.csv -> CAL)
    filename = os.path.basename(file_path)
    if filename.startswith('US-') and len(filename.split('-')) >= 3:
        parts = filename.split('-')
        return parts[1]  # Return the region code
    
    return None


def get_region_color(region):
    """Get color for a region, with fallback to default."""
    if region and region in REGION_COLORS:
        return REGION_COLORS[region]
    return DEFAULT_COLOR


def calculate_minimum_slope(all_data_dict, x_column, y_column, start_time, end_time):
    """
    Calculate the minimum slope (forecast) from all subregion data.
    For each timestamp, find which subregion has the minimum value.
    
    Returns:
        min_slope: List of [timestamp, subregion_name, min_value] tuples
        unique_regions: Set of parent regions that appear in the minimum slope
    """
    # Helper function to normalize timestamp to UTC
    def normalize_to_utc(ts):
        """Normalize a timestamp to timezone-aware UTC."""
        if not isinstance(ts, pd.Timestamp):
            ts = pd.to_datetime(ts)
        if ts.tz is None:
            return ts.tz_localize('UTC')
        else:
            return ts.tz_convert('UTC')
    
    # Normalize start_time and end_time
    if start_time is not None:
        start_time = normalize_to_utc(start_time)
    if end_time is not None:
        end_time = normalize_to_utc(end_time)
    
    min_slope = []
    unique_regions = set()
    
    # Get all unique timestamps from all datasets, normalized to UTC
    all_timestamps = set()
    for subregion_name, df in all_data_dict.items():
        if x_column in df.columns:
            for ts in df[x_column].values:
                ts_normalized = normalize_to_utc(ts)
                all_timestamps.add(ts_normalized)
    
    if not all_timestamps:
        return min_slope, unique_regions
    
    # Filter timestamps to the specified range if provided
    if start_time is not None or end_time is not None:
        filtered_timestamps = []
        for ts in all_timestamps:
            if start_time is not None and ts < start_time:
                continue
            if end_time is not None and ts >= end_time:
                continue
            filtered_timestamps.append(ts)
        all_timestamps = filtered_timestamps
    
    # Sort timestamps
    sorted_timestamps = sorted(all_timestamps)
    
    # For each timestamp, find the subregion with minimum value
    for timestamp in sorted_timestamps:
        min_value = None
        min_subregion = None
        
        for subregion_name, df in all_data_dict.items():
            if x_column not in df.columns or y_column not in df.columns:
                continue
            
            # Find row with matching timestamp
            matching_rows = df[df[x_column] == timestamp]
            if matching_rows.empty:
                continue
            
            value = matching_rows[y_column].iloc[0]
            
            # Skip NaN values and zero values
            if pd.isna(value) or value == 0:
                continue
            
            if min_value is None or value < min_value:
                min_value = value
                min_subregion = subregion_name
        
        if min_subregion is not None and min_value is not None:
            min_slope.append([timestamp, min_subregion, min_value])
            # Extract parent region from subregion path (e.g., "path/to/regions/CAL/US-CAL-CISO.csv" -> "CAL")
            # min_subregion is the file path (key from all_data_dict)
            region = get_region_from_path(min_subregion)
            if not region:
                # Fallback: extract from filename
                filename = os.path.basename(min_subregion)
                region = get_region_from_filename(filename)
            if region:
                unique_regions.add(region)
    
    return min_slope, unique_regions


def get_region_from_filename(filename):
    """Extract region code from filename (e.g., US-CAL-CISO.csv -> CAL)."""
    if filename.startswith('US-') and len(filename.split('-')) >= 3:
        parts = filename.split('-')
        return parts[1]  # Return the region code
    return None


def collect_csv_files_from_source(source):
    """Collect CSV files from a source (file or directory)."""
    csv_files = []
    if os.path.isfile(source) and source.endswith('.csv'):
        csv_files.append(source)
    elif os.path.isdir(source):
        # Check if it's a regions directory structure (has subdirectories with CSVs)
        subdir_pattern = os.path.join(source, "*", "*.csv")
        subdir_files = glob.glob(subdir_pattern)
        if subdir_files:
            csv_files.extend(subdir_files)
        else:
            # Regular directory with CSV files
            dir_pattern = os.path.join(source, "*.csv")
            csv_files.extend(glob.glob(dir_pattern))
    else:
        print(f"Warning: {source} is not a valid file or directory, skipping")
    return csv_files


def aggregate_minimum(all_data_dict, x_column, y_column, start_time=None, end_time=None):
    """
    Aggregate data by taking minimum at each timestamp.
    
    Returns:
        aggregated_df: DataFrame with x_column and y_column (minimum values)
    """
    # Helper function to normalize timestamp to UTC
    def normalize_to_utc(ts):
        """Normalize a timestamp to timezone-aware UTC."""
        if not isinstance(ts, pd.Timestamp):
            ts = pd.to_datetime(ts)
        if ts.tz is None:
            return ts.tz_localize('UTC')
        else:
            return ts.tz_convert('UTC')
    
    # Get all unique timestamps, ensuring they're timezone-aware in UTC
    all_timestamps = set()
    for df in all_data_dict.values():
        if x_column in df.columns:
            for ts in df[x_column].values:
                ts_normalized = normalize_to_utc(ts)
                all_timestamps.add(ts_normalized)
    
    if not all_timestamps:
        return pd.DataFrame()
    
    # Ensure start_time and end_time are timezone-aware in UTC
    if start_time is not None:
        start_time = normalize_to_utc(start_time)
    
    if end_time is not None:
        end_time = normalize_to_utc(end_time)
    
    # Filter timestamps if range specified
    if start_time is not None or end_time is not None:
        filtered_timestamps = [ts for ts in all_timestamps
                              if (start_time is None or ts >= start_time) and
                                 (end_time is None or ts < end_time)]
        all_timestamps = filtered_timestamps
    
    sorted_timestamps = sorted(all_timestamps)
    result_data = []
    
    for timestamp in sorted_timestamps:
        min_value = None
        for df in all_data_dict.values():
            if x_column not in df.columns or y_column not in df.columns:
                continue
            
            matching_rows = df[df[x_column] == timestamp]
            if matching_rows.empty:
                continue
            
            value = matching_rows[y_column].iloc[0]
            # Skip NaN values and zero values
            if pd.isna(value) or value == 0:
                continue
            
            if min_value is None or value < min_value:
                min_value = value
        
        # Only add if we found a valid (non-zero) minimum value
        if min_value is not None and min_value != 0:
            result_data.append({x_column: timestamp, y_column: min_value})
    
    return pd.DataFrame(result_data)


def extract_minimum_with_source(all_data_dict, x_column, y_column, start_time=None, end_time=None):
    """
    Extract minimum carbon intensity at each timestamp and track which CSV file had the minimum.
    
    Returns:
        extracted_df: DataFrame with columns: datetime, carbon_intensity_direct_avg, source_csv, region, subregion_name
    """
    # Helper function to normalize timestamp to UTC
    def normalize_to_utc(ts):
        """Normalize a timestamp to timezone-aware UTC."""
        if not isinstance(ts, pd.Timestamp):
            ts = pd.to_datetime(ts)
        if ts.tz is None:
            return ts.tz_localize('UTC')
        else:
            return ts.tz_convert('UTC')
    
    # Get all unique timestamps, ensuring they're timezone-aware in UTC
    all_timestamps = set()
    for df in all_data_dict.values():
        if x_column in df.columns:
            for ts in df[x_column].values:
                ts_normalized = normalize_to_utc(ts)
                all_timestamps.add(ts_normalized)
    
    if not all_timestamps:
        return pd.DataFrame()
    
    # Ensure start_time and end_time are timezone-aware in UTC
    if start_time is not None:
        start_time = normalize_to_utc(start_time)
    
    if end_time is not None:
        end_time = normalize_to_utc(end_time)
    
    # Filter timestamps if range specified
    if start_time is not None or end_time is not None:
        filtered_timestamps = [ts for ts in all_timestamps
                              if (start_time is None or ts >= start_time) and
                                 (end_time is None or ts < end_time)]
        all_timestamps = filtered_timestamps
    
    sorted_timestamps = sorted(all_timestamps)
    result_data = []
    
    for timestamp in sorted_timestamps:
        min_value = None
        min_source_csv = None
        min_region = None
        min_subregion_name = None
        
        for csv_file_path, df in all_data_dict.items():
            if x_column not in df.columns or y_column not in df.columns:
                continue
            
            matching_rows = df[df[x_column] == timestamp]
            if matching_rows.empty:
                continue
            
            value = matching_rows[y_column].iloc[0]
            # Skip NaN values and zero values
            if pd.isna(value) or value == 0:
                continue
            
            if min_value is None or value < min_value:
                min_value = value
                min_source_csv = csv_file_path
                # Extract region and subregion name
                min_region = get_region_from_path(csv_file_path)
                min_subregion_name = os.path.splitext(os.path.basename(csv_file_path))[0]
        
        # Only add if we found a valid (non-zero) minimum value
        if min_value is not None and min_value != 0 and min_source_csv is not None:
            result_data.append({
                x_column: timestamp,
                y_column: min_value,
                'source_csv': os.path.basename(min_source_csv),
                'source_path': min_source_csv,
                'region': min_region if min_region else 'Unknown',
                'subregion_name': min_subregion_name
            })
    
    return pd.DataFrame(result_data)


def aggregate_average(all_data_dict, x_column, y_column, start_time=None, end_time=None):
    """
    Aggregate data by taking average at each timestamp.
    
    Returns:
        aggregated_df: DataFrame with x_column and y_column (average values)
    """
    # Helper function to normalize timestamp to UTC
    def normalize_to_utc(ts):
        """Normalize a timestamp to timezone-aware UTC."""
        if not isinstance(ts, pd.Timestamp):
            ts = pd.to_datetime(ts)
        if ts.tz is None:
            return ts.tz_localize('UTC')
        else:
            return ts.tz_convert('UTC')
    
    # Get all unique timestamps, ensuring they're timezone-aware in UTC
    all_timestamps = set()
    for df in all_data_dict.values():
        if x_column in df.columns:
            for ts in df[x_column].values:
                ts_normalized = normalize_to_utc(ts)
                all_timestamps.add(ts_normalized)
    
    if not all_timestamps:
        return pd.DataFrame()
    
    # Ensure start_time and end_time are timezone-aware in UTC
    if start_time is not None:
        start_time = normalize_to_utc(start_time)
    
    if end_time is not None:
        end_time = normalize_to_utc(end_time)
    
    # Filter timestamps if range specified
    if start_time is not None or end_time is not None:
        filtered_timestamps = [ts for ts in all_timestamps
                              if (start_time is None or ts >= start_time) and
                                 (end_time is None or ts < end_time)]
        all_timestamps = filtered_timestamps
    
    sorted_timestamps = sorted(all_timestamps)
    result_data = []
    
    for timestamp in sorted_timestamps:
        values = []
        for df in all_data_dict.values():
            if x_column not in df.columns or y_column not in df.columns:
                continue
            
            matching_rows = df[df[x_column] == timestamp]
            if matching_rows.empty:
                continue
            
            value = matching_rows[y_column].iloc[0]
            # Skip NaN values and zero values
            if not pd.isna(value) and value != 0:
                values.append(value)
        
        if values:
            avg_value = sum(values) / len(values)
            result_data.append({x_column: timestamp, y_column: avg_value})
    
    return pd.DataFrame(result_data)


def plot_data(plot_specs, x_column='datetime', y_column='carbon_intensity_direct_avg',
                     start_date=None, end_date=None, output_file=None):
    """
    Plot data from CSV files based on plot specifications.
    
    Args:
        plot_specs (list): List of tuples (plot_type, source) where:
            - plot_type: 'plot', 'plot-min', or 'plot-avg'
            - source: path to CSV file or directory
        x_column (str): Column name to use for x-axis (default: 'datetime')
        y_column (str): Column name to use for y-axis (default: 'carbon_intensity_direct_avg')
        start_date (str): Optional start date in YYYY-MM-DD format (if x-axis is datetime)
        end_date (str): Optional end date in YYYY-MM-DD format (if x-axis is datetime)
        output_file (str): Optional output file path for the HTML plot
    """
    if not plot_specs:
        print("Error: No plot specifications provided")
        return
    
    # Check if we should attempt to use datetime filtering
    use_datetime_filtering = x_column.lower() in ['datetime', 'date', 'time', 'timestamp']
    
    # Convert date strings to datetime if needed
    start_datetime = None
    end_datetime = None
    if use_datetime_filtering:
        if start_date:
            start_datetime = pd.to_datetime(start_date, utc=True)
        if end_date:
            end_datetime = pd.to_datetime(end_date, utc=True) + timedelta(days=1)
    
    # Create a plotly figure
    fig = make_subplots(specs=[[{"secondary_y": False}]])
    
    # Process each plot specification
    print(f"Processing {len(plot_specs)} plot specification(s)...")
    
    # Track all regions and subregions to determine if we should use full color width
    all_regions = set()
    all_subregions = []
    
    # First pass: collect all regions and subregions
    for plot_type, source in plot_specs:
        if plot_type == 'plot':
            csv_files = collect_csv_files_from_source(source)
            for csv_file in csv_files:
                region = get_region_from_path(csv_file)
                if region:
                    all_regions.add(region)
                all_subregions.append((csv_file, region))
    
    # Determine if we should use full color width (only one region)
    use_full_color_width = len(all_regions) == 1
    
    # Create color mapping
    color_index = 0
    subregion_color_map = {}
    
    if use_full_color_width:
        # Assign different colors to each subregion
        for csv_file, region in all_subregions:
            subregion_color_map[csv_file] = COLOR_PALETTE[color_index % len(COLOR_PALETTE)]
            color_index += 1
    else:
        # Use region-based coloring
        region_color_map = {}
        for region in all_regions:
            if region in REGION_COLORS:
                region_color_map[region] = REGION_COLORS[region]
            else:
                region_color_map[region] = COLOR_PALETTE[color_index % len(COLOR_PALETTE)]
                color_index += 1
    
    for plot_type, source in plot_specs:
        print(f"\nProcessing {plot_type}: {source}")
        
        # Collect CSV files from this source
        csv_files = collect_csv_files_from_source(source)
        
        if not csv_files:
            print(f"  Warning: No CSV files found in {source}")
            continue
        
        print(f"  Found {len(csv_files)} CSV file(s)")
        
        if plot_type == 'plot':
            # Plot individual files normally
            for csv_file in csv_files:
                try:
                    df = pd.read_csv(csv_file)
                    
                    if x_column not in df.columns or y_column not in df.columns:
                        print(f"  Skipping {os.path.basename(csv_file)} - missing required columns")
                        continue
                    
                    # Handle datetime conversion
                    if use_datetime_filtering:
                        try:
                            df[x_column] = pd.to_datetime(df[x_column], utc=True)
                            if start_datetime is not None:
                                df = df[df[x_column] >= start_datetime]
                            if end_datetime is not None:
                                df = df[df[x_column] < end_datetime]
                        except Exception as e:
                            print(f"  Warning: Failed to process datetime in {csv_file}: {str(e)}")
                            continue
                    
                    if df.empty:
                        continue
                    
                    # Get region and label
                    region = get_region_from_path(csv_file)
                    filename = os.path.basename(csv_file)
                    file_label = os.path.splitext(filename)[0]
                    display_label = f"{region} - {file_label}" if region else file_label
                    
                    # Determine color based on whether we're using full color width
                    if use_full_color_width and csv_file in subregion_color_map:
                        region_color = subregion_color_map[csv_file]
                    elif not use_full_color_width:
                        region_color = get_region_color(region)
                    else:
                        # Fallback
                        region_color = get_region_color(region)
                    
                    fig.add_trace(
                        go.Scatter(
                            x=df[x_column],
                            y=df[y_column],
                            name=display_label,
                            mode='lines',
                            line=dict(width=2, color=region_color),
                            hovertemplate=
                            f'<b>%{{x}}</b><br>' +
                            f'{y_column}: %{{y:.2f}}<br>' +
                            f'<extra>{display_label}</extra>'
                        )
                    )
                except Exception as e:
                    print(f"  Error processing {csv_file}: {str(e)}")
        
        elif plot_type in ['plot-min', 'plot-avg']:
            # Aggregate directory and plot min/avg
            if not use_datetime_filtering:
                print(f"  Warning: {plot_type} requires datetime-based x-axis. Skipping.")
                continue
            
            # Load all data from this source
            all_data_dict = {}
            for csv_file in csv_files:
                try:
                    df = pd.read_csv(csv_file)
                    if x_column not in df.columns or y_column not in df.columns:
                        continue
                    
                    df[x_column] = pd.to_datetime(df[x_column], utc=True)
                    
                    if start_datetime is not None:
                        df = df[df[x_column] >= start_datetime]
                    if end_datetime is not None:
                        df = df[df[x_column] < end_datetime]
                    
                    if not df.empty:
                        all_data_dict[csv_file] = df
                except Exception as e:
                    print(f"  Warning: Failed to load {csv_file}: {str(e)}")
            
            if not all_data_dict:
                print(f"  No valid data found in {source}")
                continue
            
            # Aggregate
            if plot_type == 'plot-min':
                aggregated_df = aggregate_minimum(all_data_dict, x_column, y_column, start_datetime, end_datetime)
                label = f"Min: {os.path.basename(source.rstrip('/'))}"
                color = MIN_SLOPE_COLOR
                width = MIN_SLOPE_WIDTH
            else:  # plot-avg
                aggregated_df = aggregate_average(all_data_dict, x_column, y_column, start_datetime, end_datetime)
                label = f"Avg: {os.path.basename(source.rstrip('/'))}"
                color = '#ff0000'  # Red for average
                width = 3
            
            if aggregated_df.empty:
                print(f"  No aggregated data generated for {source}")
                continue
            
            # Add opacity for min slope
            line_dict = dict(width=width, color=color)
            if plot_type == 'plot-min':
                # Convert hex color to rgba with opacity
                hex_color = color.lstrip('#')
                rgb = tuple(int(hex_color[i:i+2], 16) for i in (0, 2, 4))
                line_dict['color'] = f'rgba({rgb[0]}, {rgb[1]}, {rgb[2]}, {MIN_SLOPE_OPACITY})'
            
            fig.add_trace(
                go.Scatter(
                    x=aggregated_df[x_column],
                    y=aggregated_df[y_column],
                    name=label,
                    mode='lines',
                    line=line_dict,
                    hovertemplate=
                    f'<b>%{{x}}</b><br>' +
                    f'{y_column}: %{{y:.2f}}<br>' +
                    f'<extra>{label}</extra>'
                )
            )
            print(f"  Added {plot_type} trace with {len(aggregated_df)} data points")
    
    # Check if we have any traces
    if len(fig.data) == 0:
        print("No valid data found in any CSV files. Nothing to plot.")
        return
    
    # Set up the plot appearance
    y_axis_title = y_column.replace('_', ' ').title()
    x_axis_title = x_column.replace('_', ' ').title()
    
    title = f"{y_axis_title} vs {x_axis_title}"
    
    fig.update_layout(
        title=title,
        title_font_size=20,
        xaxis_title=x_axis_title,
        yaxis_title=y_axis_title,
        legend_title="Regions & Subregions",
        hovermode="closest",
        template="plotly_white",
        height=600,
        width=1200,
        colorway=COLOR_PALETTE,  # Set fixed color palette
    )
    
    # Add date range selector if x-axis is time-based
    if use_datetime_filtering:
        fig.update_xaxes(
            rangeslider_visible=True,
            rangeselector=dict(
                buttons=list([
                    dict(count=1, label="1d", step="day", stepmode="backward"),
                    dict(count=7, label="1w", step="day", stepmode="backward"),
                    dict(count=1, label="1m", step="month", stepmode="backward"),
                    dict(count=6, label="6m", step="month", stepmode="backward"),
                    dict(step="all")
                ])
            )
        )
    
    # Set default output file if not provided
    if not output_file:
        safe_y_name = y_column.replace('_', '-')
        output_file = f"regions-{safe_y_name}.html"
    
    # Save interactive plot
    fig.write_html(
        output_file,
        include_plotlyjs=True,
        full_html=True
    )
    print(f"\nInteractive plot saved as {output_file}")
    
    # Save as static image as well
    image_file = os.path.splitext(output_file)[0] + ".png"
    try:
        fig.write_image(image_file)
        print(f"Static image saved as {image_file}")
    except Exception as e:
        print(f"Could not save static image (requires kaleido package): {str(e)}")
        print("You can install it with: pip install kaleido")


def plot_benchmark_data(csv_path, x_column, y_column, group_by=None, output_file=None):
    """
    Plot benchmark data from benchmark_data.csv.
    
    Args:
        csv_path (str): Path to benchmark_data.csv
        x_column (str): Column name to use for x-axis
        y_column (str): Column name to use for y-axis
        group_by (str): Optional grouping column (e.g., 'Duration', 'day', or policy difference column)
        output_file (str): Optional output file path for the HTML plot
    """
    if not os.path.isfile(csv_path):
        print(f"Error: CSV file not found: {csv_path}")
        return
    
    print(f"Loading benchmark data from {csv_path}...")
    
    # Read CSV file
    try:
        # Read the file and handle potential malformed header
        with open(csv_path, 'r') as f:
            first_line = f.readline().strip()
            # Check if header is concatenated with first data row
            if 'Policy3_3_Carbon_Intensity' in first_line and '2020-' in first_line:
                # Header is malformed - fix it
                import re
                # Find where the data starts (look for timestamp pattern after last column name)
                match = re.search(r'(Policy3_3_Carbon_Intensity)(\d{4}-\d{2}-\d{2})', first_line)
                if match:
                    # Reconstruct header and first data row
                    header_end = match.end(1)
                    fixed_header = first_line[:header_end]
                    first_data_row = first_line[header_end:]
                    # Read remaining lines
                    remaining_lines = f.readlines()
                    # Create corrected content
                    from io import StringIO
                    corrected_content = fixed_header + '\n' + first_data_row + '\n' + ''.join(remaining_lines)
                    df = pd.read_csv(StringIO(corrected_content))
                else:
                    # Fallback: try reading normally
                    f.seek(0)
                    df = pd.read_csv(f)
            else:
                # Header looks fine, read normally
                f.seek(0)
                df = pd.read_csv(f)
        
        # Strip whitespace from column names
        df.columns = df.columns.str.strip()
    except Exception as e:
        print(f"Error reading CSV file: {str(e)}")
        import traceback
        traceback.print_exc()
        return
    
    if df.empty:
        print("Error: CSV file is empty")
        return
    
    # Get all policy difference columns
    policy_diff_columns = [col for col in df.columns if 'Difference' in col]
    
    print(f"Found {len(df)} rows before filtering")
    print(f"Policy difference columns: {', '.join(policy_diff_columns)}")
    
    # Filter out rows where any Policy Difference is < 0 or > 1
    initial_count = len(df)
    for col in policy_diff_columns:
        # Convert to numeric, handling any non-numeric values
        df[col] = pd.to_numeric(df[col], errors='coerce')
        # Filter: keep only rows where value is between 0 and 1 (inclusive)
        mask = (df[col] >= 0) & (df[col] <= 1) | df[col].isna()
        df = df[mask].copy()
    
    filtered_count = len(df)
    print(f"Filtered out {initial_count - filtered_count} rows with policy differences outside [0, 1]")
    print(f"Remaining rows: {filtered_count}")
    
    if df.empty:
        print("Error: No data remaining after filtering")
        return
    
    # Validate columns exist
    if x_column not in df.columns:
        print(f"Error: Column '{x_column}' not found in CSV")
        print(f"Available columns: {', '.join(df.columns)}")
        return
    
    if y_column not in df.columns:
        print(f"Error: Column '{y_column}' not found in CSV")
        print(f"Available columns: {', '.join(df.columns)}")
        return
    
    # Convert Timestamp to datetime if it exists
    if 'Timestamp' in df.columns:
        df['Timestamp'] = pd.to_datetime(df['Timestamp'], utc=True, errors='coerce')
    
    # Handle special grouping cases
    if group_by:
        if group_by.lower() in ['day', 'date']:
            # Extract day from timestamp
            if 'Timestamp' in df.columns:
                df['Day'] = df['Timestamp'].dt.date
                group_by = 'Day'
            else:
                print(f"Warning: Cannot group by day - 'Timestamp' column not found")
                group_by = None
        elif group_by.lower() == 'duration':
            # Ensure Duration column exists
            if 'Duration' not in df.columns:
                print(f"Warning: Cannot group by duration - 'Duration' column not found")
                group_by = None
    
    # Create figure
    fig = go.Figure()
    
    # If grouping is specified, create separate traces for each group
    if group_by and group_by in df.columns:
        groups = df[group_by].unique()
        print(f"Grouping by '{group_by}': {len(groups)} groups")
        
        for group in sorted(groups):
            group_df = df[df[group_by] == group]
            if group_df.empty:
                continue
            
            # Sort by x_column for proper line plotting
            group_df = group_df.sort_values(by=x_column)
            
            # Handle datetime x-axis
            x_data = group_df[x_column]
            if pd.api.types.is_datetime64_any_dtype(x_data):
                x_data = pd.to_datetime(x_data)
            
            fig.add_trace(
                go.Scatter(
                    x=x_data,
                    y=group_df[y_column],
                    name=f"{group_by}={group}",
                    mode='lines+markers',
                    line=dict(width=2),
                    marker=dict(size=4),
                    hovertemplate=
                    f'<b>%{{x}}</b><br>' +
                    f'{y_column}: %{{y:.4f}}<br>' +
                    f'{group_by}: {group}<br>' +
                    '<extra></extra>'
                )
            )
    else:
        # No grouping - plot all data as a single trace
        df_sorted = df.sort_values(by=x_column)
        
        x_data = df_sorted[x_column]
        if pd.api.types.is_datetime64_any_dtype(x_data):
            x_data = pd.to_datetime(x_data)
        
        fig.add_trace(
            go.Scatter(
                x=x_data,
                y=df_sorted[y_column],
                name=y_column,
                mode='lines+markers',
                line=dict(width=2),
                marker=dict(size=4),
                hovertemplate=
                f'<b>%{{x}}</b><br>' +
                f'{y_column}: %{{y:.4f}}<br>' +
                '<extra></extra>'
            )
        )
    
    # Set up the plot appearance
    y_axis_title = y_column.replace('_', ' ').title()
    x_axis_title = x_column.replace('_', ' ').title()
    
    title = f"{y_axis_title} vs {x_axis_title}"
    if group_by:
        title += f" (Grouped by {group_by})"
    
    fig.update_layout(
        title=title,
        title_font_size=20,
        xaxis_title=x_axis_title,
        yaxis_title=y_axis_title,
        legend_title=group_by if group_by else "Series",
        hovermode="closest",
        template="plotly_white",
        height=600,
        width=1200,
    )
    
    # Add date range selector if x-axis is time-based
    if pd.api.types.is_datetime64_any_dtype(df[x_column]):
        fig.update_xaxes(
            rangeslider_visible=True,
            rangeselector=dict(
                buttons=list([
                    dict(count=1, label="1d", step="day", stepmode="backward"),
                    dict(count=7, label="1w", step="day", stepmode="backward"),
                    dict(count=1, label="1m", step="month", stepmode="backward"),
                    dict(count=6, label="6m", step="month", stepmode="backward"),
                    dict(step="all")
                ])
            )
        )
    
    # Set default output file if not provided
    if not output_file:
        safe_y_name = y_column.replace('_', '-')
        safe_x_name = x_column.replace('_', '-')
        group_suffix = f"_grouped-{group_by.replace('_', '-')}" if group_by else ""
        output_file = f"benchmark_{safe_x_name}_vs_{safe_y_name}{group_suffix}.html"
    
    # Ensure output goes to outputs directory
    csv_dir = os.path.dirname(os.path.abspath(csv_path))
    if 'outputs' in csv_dir:
        # CSV is already in outputs, use that directory
        output_dir = csv_dir
    else:
        # CSV is elsewhere, create outputs directory next to it
        output_dir = os.path.join(csv_dir, 'outputs')
    
    os.makedirs(output_dir, exist_ok=True)
    
    # If output_file is absolute, use it as-is, otherwise put it in output_dir
    if os.path.isabs(output_file):
        output_path = output_file
    else:
        output_path = os.path.join(output_dir, output_file)
    
    # Save interactive plot
    fig.write_html(
        output_path,
        include_plotlyjs=True,
        full_html=True
    )
    print(f"\nInteractive plot saved as {output_path}")
    
    # Save as static image as well
    image_file = os.path.splitext(output_path)[0] + ".png"
    try:
        fig.write_image(image_file)
        print(f"Static image saved as {image_file}")
    except Exception as e:
        print(f"Could not save static image (requires kaleido package): {str(e)}")
        print("You can install it with: pip install kaleido")


def plot_all_benchmark_graphs(csv_path, output_base_dir=None):
    """
    Create comprehensive benchmark graphs organized by day.
    For each day, creates:
    1. Bar chart: 8 columns (durations), 5 subcolumns (policies), y-axis = difference
    2. Scatter plot: x=timestamp, y=difference, colored by policy
    """
    if not os.path.isfile(csv_path):
        print(f"Error: CSV file not found: {csv_path}")
        return
    
    print(f"Loading benchmark data from {csv_path}...")
    
    # Read CSV file (reuse the same logic from plot_benchmark_data)
    try:
        with open(csv_path, 'r') as f:
            first_line = f.readline().strip()
            if 'Policy3_3_Carbon_Intensity' in first_line and '2020-' in first_line:
                import re
                match = re.search(r'(Policy3_3_Carbon_Intensity)(\d{4}-\d{2}-\d{2})', first_line)
                if match:
                    header_end = match.end(1)
                    fixed_header = first_line[:header_end]
                    first_data_row = first_line[header_end:]
                    remaining_lines = f.readlines()
                    from io import StringIO
                    corrected_content = fixed_header + '\n' + first_data_row + '\n' + ''.join(remaining_lines)
                    df = pd.read_csv(StringIO(corrected_content))
                else:
                    f.seek(0)
                    df = pd.read_csv(f)
            else:
                f.seek(0)
                df = pd.read_csv(f)
        
        df.columns = df.columns.str.strip()
    except Exception as e:
        print(f"Error reading CSV file: {str(e)}")
        return
    
    if df.empty:
        print("Error: CSV file is empty")
        return
    
    # Get policy carbon intensity columns (for duration chart)
    policy_intensity_columns = [col for col in df.columns if 'Carbon_Intensity' in col]
    policy_intensity_columns = sorted(policy_intensity_columns)  # Sort for consistent ordering
    
    # Get policy difference columns (for timestamp chart and overall scatter plot)
    policy_diff_columns = [col for col in df.columns if 'Difference' in col]
    policy_diff_columns = sorted(policy_diff_columns)  # Sort for consistent ordering
    
    if not policy_intensity_columns:
        print("Error: No policy carbon intensity columns found in CSV")
        return
    
    print(f"Found {len(df)} rows")
    print(f"Policy carbon intensity columns: {', '.join(policy_intensity_columns)}")
    if policy_diff_columns:
        print(f"Policy difference columns: {', '.join(policy_diff_columns)}")
    
    # Convert carbon intensity columns to numeric (no filtering needed for carbon intensity)
    for col in policy_intensity_columns:
        df[col] = pd.to_numeric(df[col], errors='coerce')
    
    # Convert and filter difference columns (for timestamp chart)
    if policy_diff_columns:
        initial_count = len(df)
        for col in policy_diff_columns:
            df[col] = pd.to_numeric(df[col], errors='coerce')
            mask = (df[col] >= 0) & (df[col] <= 1) | df[col].isna()
            df = df[mask].copy()
        
        filtered_count = len(df)
        print(f"Filtered out {initial_count - filtered_count} rows with policy differences outside [0, 1]")
        print(f"Remaining rows: {filtered_count}")
    
    if df.empty:
        print("Error: CSV file is empty")
        return
    
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
            # CSV is already in outputs, use that directory
            output_base_dir = csv_dir
        else:
            # CSV is elsewhere, create outputs directory next to it
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
        'Policy1_Carbon_Intensity': 'Policy 1',
        'Policy2_Carbon_Intensity': 'Policy 2',
        'Policy3_1_Carbon_Intensity': 'Policy 3 (1 migration)',
        'Policy3_2_Carbon_Intensity': 'Policy 3 (2 migrations)',
        'Policy3_3_Carbon_Intensity': 'Policy 3 (3 migrations)',
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
        
        # 1. Create bar chart: 8 columns (durations), 5 subcolumns (policies)
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
                        # Calculate average carbon intensity per hour (gCO₂eq/kWh)
                        # Divide total carbon intensity by duration to get average per hour
                        avg_intensity = intensity_values.mean() / duration
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
                    marker_color=policy_colors.get(policy_col, COLOR_PALETTE[i % len(COLOR_PALETTE)]),
                    hovertemplate=
                    f'<b>%{{x}}</b><br>' +
                    f'{policy_names.get(policy_col, policy_col)}: %{{y:.2f}} gCO₂eq/kWh<br>' +
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
            # Fallback if no values (typical carbon intensity per hour is around 100-500 gCO₂eq/kWh)
            y_min = 0
            y_max = 500
        
        fig_bar.update_layout(
            title=f'Policy Average Carbon Intensity by Duration - {day_str}',
            xaxis=dict(
                title='Duration (hours)',
                type='category'
            ),
            yaxis=dict(
                title='Average Carbon Intensity (gCO₂eq/kWh)',
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
        
        # 2. Create bar chart grouped by timestamp: x=timestamp, y=difference, colored by policy
        fig_bar_timestamp = go.Figure()
        
        # Get unique timestamps and sort them
        unique_timestamps = sorted(day_df['Timestamp'].unique())
        # Format timestamps for display (HH:MM format)
        timestamp_labels = [ts.strftime('%H:%M') for ts in unique_timestamps]
        
        # Collect all values for y-axis scaling
        all_timestamp_values = []
        
        for i, policy_col in enumerate(policy_diff_columns):
            policy_values = []
            for timestamp in unique_timestamps:
                timestamp_data = day_df[(day_df['Timestamp'] == timestamp) & 
                                       (day_df[policy_col].notna()) & 
                                       (day_df[policy_col] >= 0) & 
                                       (day_df[policy_col] <= 1)]
                if not timestamp_data.empty:
                    # Average the differences for this timestamp
                    avg_diff = timestamp_data[policy_col].mean()
                    if not pd.isna(avg_diff):
                        policy_values.append(avg_diff)
                        all_timestamp_values.append(avg_diff)
                    else:
                        policy_values.append(0)
                else:
                    policy_values.append(0)
            
            fig_bar_timestamp.add_trace(
                go.Bar(
                    name=policy_names.get(policy_col, policy_col),
                    x=timestamp_labels,
                    y=policy_values,
                    marker_color=policy_colors.get(policy_col, COLOR_PALETTE[i % len(COLOR_PALETTE)]),
                    hovertemplate=
                    f'<b>%{{x}}</b><br>' +
                    f'{policy_names.get(policy_col, policy_col)}: %{{y:.4f}}<br>' +
                    '<extra></extra>'
                )
            )
        
        # Calculate dynamic y-axis range based on data
        if all_timestamp_values:
            min_val = min(all_timestamp_values)
            max_val = max(all_timestamp_values)
            value_range = max_val - min_val
            if value_range == 0:
                if min_val > 0.05:
                    padding = min_val * 0.1
                else:
                    padding = 0.01
                y_min = max(0, min_val - padding)
                y_max = min(1, max_val + padding)
            else:
                padding = value_range * 0.05
                y_min = max(0, min_val - padding)
                y_max = min(1, max_val + padding)
        else:
            y_min = 0
            y_max = 1.1
        
        fig_bar_timestamp.update_layout(
            title=f'Policy Differences by Timestamp - {day_str}',
            xaxis=dict(
                title='Timestamp (HH:MM)',
                type='category'
            ),
            yaxis=dict(
                title='Policy Efficency (0-1)',
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
        
        bar_timestamp_output = os.path.join(day_dir, f"policy_by_time_{day_str}.html")
        fig_bar_timestamp.write_html(bar_timestamp_output, include_plotlyjs=True, full_html=True)
        print(f"  Bar chart (by time) saved: {bar_timestamp_output}")
        
        # Save bar chart (by time) as PNG
        bar_timestamp_png_output = os.path.join(day_dir, f"policy_by_time_{day_str}.png")
        try:
            fig_bar_timestamp.write_image(bar_timestamp_png_output)
            print(f"  Bar chart (by time) PNG saved: {bar_timestamp_png_output}")
        except Exception as e:
            print(f"  Could not save bar chart (by time) PNG (requires kaleido package): {str(e)}")
    
    print(f"\n✓ All graphs created in {output_base_dir}")
    
    # Create overall scatter plot
    print(f"\nCreating overall scatter plot...")
    overall_dir = os.path.join(output_base_dir, 'overall')
    os.makedirs(overall_dir, exist_ok=True)
    
    fig_overall = go.Figure()
    
    for i, policy_col in enumerate(policy_diff_columns):
        policy_data = df[df[policy_col].notna() & (df[policy_col] >= 0) & (df[policy_col] <= 1)]
        if not policy_data.empty:
            fig_overall.add_trace(
                go.Scatter(
                    x=policy_data['Timestamp'],
                    y=policy_data[policy_col],
                    name=policy_names.get(policy_col, policy_col),
                    mode='markers',
                    marker=dict(
                        size=6,
                        color=policy_colors.get(policy_col, COLOR_PALETTE[i % len(COLOR_PALETTE)]),
                        opacity=0.6
                    ),
                    hovertemplate=
                    f'<b>%{{x|%Y-%m-%d %H:%M:%S}}</b><br>' +
                    f'{policy_names.get(policy_col, policy_col)}: %{{y:.4f}}<br>' +
                    '<extra></extra>'
                )
            )
    
    # Calculate dynamic y-axis range for overall plot
    all_overall_values = []
    for policy_col in policy_diff_columns:
        policy_data = df[df[policy_col].notna() & (df[policy_col] >= 0) & (df[policy_col] <= 1)]
        if not policy_data.empty:
            all_overall_values.extend(policy_data[policy_col].tolist())
    
    if all_overall_values:
        min_val = min(all_overall_values)
        max_val = max(all_overall_values)
        value_range = max_val - min_val
        if value_range == 0:
            if min_val > 0.05:
                padding = min_val * 0.1
            else:
                padding = 0.01
            y_min = max(0, min_val - padding)
            y_max = min(1, max_val + padding)
        else:
            padding = value_range * 0.05
            y_min = max(0, min_val - padding)
            y_max = min(1, max_val + padding)
    else:
        y_min = 0
        y_max = 1.1
    
    fig_overall.update_layout(
        title='Policy Differences Over Time (All Days)',
        xaxis_title='Timestamp',
        yaxis_title='Policy Efficency (0-1)',
        yaxis=dict(range=[y_min, y_max]),
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
        hovermode='closest'
    )
    
    # Format x-axis to show normal time format (DD:MM:YYYY style)
    # Calculate appropriate tick interval based on data range
    if not df.empty and 'Timestamp' in df.columns:
        time_range = df['Timestamp'].max() - df['Timestamp'].min()
        days_span = time_range.days
        
        # Determine tick interval based on data span
        if days_span <= 7:
            dtick = "D1"  # Daily ticks
            tickformat = '%d-%m-%Y'
        elif days_span <= 30:
            dtick = "D3"  # Every 3 days
            tickformat = '%d-%m-%Y'
        elif days_span <= 90:
            dtick = "D7"  # Weekly ticks
            tickformat = '%d-%m-%Y'
        elif days_span <= 180:
            dtick = "M1"  # Monthly ticks
            tickformat = '%d-%m-%Y'
        else:
            dtick = "M2"  # Every 2 months
            tickformat = '%d-%m-%Y'
    else:
        dtick = "D7"  # Default to weekly
        tickformat = '%d-%m-%Y'
    
    fig_overall.update_xaxes(
        type='date',
        tickformat=tickformat,
        dtick=dtick,
        tickangle=-45,  # Rotate labels to avoid crowding
        rangeslider_visible=True,
        rangeselector=dict(
            buttons=list([
                dict(count=1, label="1d", step="day", stepmode="backward"),
                dict(count=7, label="1w", step="day", stepmode="backward"),
                dict(count=1, label="1m", step="month", stepmode="backward"),
                dict(count=6, label="6m", step="month", stepmode="backward"),
                dict(step="all")
            ])
        )
    )
    
    overall_output = os.path.join(overall_dir, "benchmark_scatter_plot_overall.html")
    fig_overall.write_html(overall_output, include_plotlyjs=True, full_html=True)
    print(f"  Overall scatter plot saved: {overall_output}")
    
    # Save overall scatter plot as PNG
    overall_png_output = os.path.join(overall_dir, "benchmark_scatter_plot_overall.png")
    try:
        fig_overall.write_image(overall_png_output)
        print(f"  Overall scatter plot PNG saved: {overall_png_output}")
    except Exception as e:
        print(f"  Could not save overall scatter plot PNG (requires kaleido package): {str(e)}")
    
    print(f"\n✓ Overall graphs created in {overall_dir}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Plot carbon emissions data from region CSV files or benchmark data",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Plot benchmark data
  %(prog)s --plot-benchmark data/outputs/benchmark_data.csv --x-axis Duration --y-axis Policy1_Difference

  # Plot benchmark data grouped by Duration
  %(prog)s --plot-benchmark data/outputs/benchmark_data.csv --x-axis Timestamp --y-axis Policy1_Difference --group-by Duration

  # Plot benchmark data grouped by day
  %(prog)s --plot-benchmark data/outputs/benchmark_data.csv --x-axis Duration --y-axis Policy3_1_Difference --group-by day

  # Create all benchmark graphs organized by day
  %(prog)s --plot-benchmark data/outputs/benchmark_data.csv --all

  # Plot individual CSV files
  %(prog)s --plot file1.csv --plot file2.csv

  # Plot all CSVs in a directory
  %(prog)s --plot data/regions

  # Aggregate directory and plot minimum
  %(prog)s --plot-min data/regions/CAL

  # Aggregate directory and plot average
  %(prog)s --plot-avg data/regions/CAL

  # Combine multiple plot types
  %(prog)s --plot file1.csv --plot-min data/regions/CAL --plot-avg data/regions/CAR

  # Plot with date range
  %(prog)s --plot data/regions --start 2020-01-01 --end 2020-12-31

  # Extract minimum values with source CSV information
  %(prog)s --extract-min data/regions --extract-min-output min_values.csv

  # Extract minimum with date range
  %(prog)s --extract-min data/regions --start 2020-01-01 --end 2020-12-31
        """
    )
    parser.add_argument(
        "--plot",
        action="append",
        dest="plot_sources",
        default=[],
        help="CSV file or directory to plot individually (can be used multiple times)"
    )
    parser.add_argument(
        "--plot-min",
        action="append",
        dest="plot_min_sources",
        default=[],
        help="Directory to aggregate and plot minimum (can be used multiple times)"
    )
    parser.add_argument(
        "--plot-avg",
        action="append",
        dest="plot_avg_sources",
        default=[],
        help="Directory to aggregate and plot average (can be used multiple times)"
    )
    parser.add_argument(
        "-x", "--x-axis", "--x_column",
        dest="x_column",
        default="datetime",
        help="Column name to use for x-axis (default: 'datetime')"
    )
    parser.add_argument(
        "-y", "--y-axis", "--y_column",
        dest="y_column",
        default="carbon_intensity_direct_avg",
        help="Column name to use for y-axis (default: 'carbon_intensity_direct_avg')"
    )
    parser.add_argument(
        "--start",
        dest="start_date",
        help="Start date for the plot (YYYY-MM-DD) if x-axis is datetime"
    )
    parser.add_argument(
        "--end",
        dest="end_date",
        help="End date for the plot (YYYY-MM-DD) if x-axis is datetime"
    )
    parser.add_argument(
        "-o", "--output",
        dest="output",
        help="Output HTML file path"
    )
    parser.add_argument(
        "-l", "--list-columns",
        action="store_true",
        help="List all available columns in the CSV files and exit"
    )
    parser.add_argument(
        "--extract-min",
        dest="extract_min_source",
        help="Directory containing CSV files. Extracts minimum carbon_intensity_direct_avg at each timestamp and outputs CSV with source file information"
    )
    parser.add_argument(
        "--extract-min-output",
        dest="extract_min_output",
        default="extracted_minimum.csv",
        help="Output CSV file path for --extract-min (default: extracted_minimum.csv)"
    )
    parser.add_argument(
        "--plot-benchmark",
        dest="plot_benchmark_csv",
        help="Path to benchmark_data.csv file to plot"
    )
    parser.add_argument(
        "--group-by",
        dest="group_by",
        help="Column name to group data by (e.g., 'Duration', 'day', 'Policy1_Difference')"
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="Create comprehensive benchmark graphs organized by day (bar charts and scatter plots)"
    )
    
    args = parser.parse_args()
    
    # Handle --all flag (runs independently of other plotting)
    if args.all:
        if not args.plot_benchmark_csv:
            print("Error: --all requires --plot-benchmark to be specified")
            print("Example: --plot-benchmark data/outputs/benchmark_data.csv --all")
            sys.exit(1)
        
        if not os.path.isfile(args.plot_benchmark_csv):
            print(f"Error: CSV file not found: {args.plot_benchmark_csv}")
            sys.exit(1)
        
        # Use --output as base directory if provided, otherwise auto-detect
        output_dir = args.output if args.output else None
        plot_all_benchmark_graphs(args.plot_benchmark_csv, output_dir)
        sys.exit(0)
    
    # Handle --plot-benchmark flag (runs independently of other plotting)
    if args.plot_benchmark_csv:
        if not os.path.isfile(args.plot_benchmark_csv):
            print(f"Error: CSV file not found: {args.plot_benchmark_csv}")
            sys.exit(1)
        
        # For benchmark plotting, x-axis and y-axis should be specified
        # Warn if using defaults (which are meant for region plotting)
        x_col = args.x_column
        y_col = args.y_column
        
        if x_col == "datetime":
            print("Warning: Using default x-axis 'datetime'. Specify --x-axis for benchmark data.")
            print("Example columns: 'Timestamp', 'Duration', 'Policy1_Difference', etc.")
        
        if y_col == "carbon_intensity_direct_avg":
            print("Warning: Using default y-axis 'carbon_intensity_direct_avg'. Specify --y-axis for benchmark data.")
            print("Example columns: 'Policy1_Difference', 'Policy2_Difference', 'Policy1_Carbon_Intensity', etc.")
        
        plot_benchmark_data(
            csv_path=args.plot_benchmark_csv,
            x_column=x_col,
            y_column=y_col,
            group_by=args.group_by,
            output_file=args.output
        )
        sys.exit(0)
    
    # Handle --extract-min flag (runs independently of plotting)
    if args.extract_min_source:
        if not os.path.isdir(args.extract_min_source):
            print(f"Error: Directory not found: {args.extract_min_source}")
            sys.exit(1)
        
        # Collect all CSV files from the directory
        csv_files = collect_csv_files_from_source(args.extract_min_source)
        if not csv_files:
            print(f"Error: No CSV files found in {args.extract_min_source}")
            sys.exit(1)
        
        print(f"Extracting minimum values from {len(csv_files)} CSV files...")
        
        # Load all data
        all_data_dict = {}
        for csv_file in csv_files:
            try:
                df = pd.read_csv(csv_file)
                if args.x_column not in df.columns or args.y_column not in df.columns:
                    print(f"Warning: Skipping {csv_file} - missing required columns")
                    continue
                
                # Convert datetime if needed
                if args.x_column.lower() in ['datetime', 'date', 'time', 'timestamp']:
                    df[args.x_column] = pd.to_datetime(df[args.x_column], utc=True)
                    
                    # Filter by date range if provided
                    if args.start_date:
                        start_datetime = pd.to_datetime(args.start_date, utc=True)
                        df = df[df[args.x_column] >= start_datetime]
                    if args.end_date:
                        end_datetime = pd.to_datetime(args.end_date, utc=True) + timedelta(days=1)
                        df = df[df[args.x_column] < end_datetime]
                
                # Filter out rows with zero values in the y_column
                if not df.empty:
                    df = df[df[args.y_column] != 0].copy()
                    if not df.empty:
                        all_data_dict[csv_file] = df
            except Exception as e:
                print(f"Warning: Failed to load {csv_file}: {str(e)}")
        
        if not all_data_dict:
            print("Error: No valid data found in CSV files")
            sys.exit(1)
        
        # Extract minimum with source information
        start_datetime = pd.to_datetime(args.start_date, utc=True) if args.start_date else None
        end_datetime = pd.to_datetime(args.end_date, utc=True) + timedelta(days=1) if args.end_date else None
        
        extracted_df = extract_minimum_with_source(
            all_data_dict, args.x_column, args.y_column, start_datetime, end_datetime
        )
        
        if extracted_df.empty:
            print("No data extracted")
            sys.exit(1)
        
        # Save to CSV
        extracted_df.to_csv(args.extract_min_output, index=False)
        print(f"Extracted {len(extracted_df)} rows to {args.extract_min_output}")
        print(f"\nColumns: {', '.join(extracted_df.columns)}")
        print(f"\nFirst few rows:")
        print(extracted_df.head(10).to_string())
        print(f"\nSummary:")
        print(f"  Total timestamps: {len(extracted_df)}")
        print(f"  Unique regions: {extracted_df['region'].nunique()}")
        print(f"  Unique source files: {extracted_df['source_csv'].nunique()}")
        print(f"\nRegion distribution:")
        print(extracted_df['region'].value_counts().to_string())
        
        sys.exit(0)
    
    # Build plot specifications list
    plot_specs = []
    for source in args.plot_sources:
        plot_specs.append(('plot', source))
    for source in args.plot_min_sources:
        plot_specs.append(('plot-min', source))
    for source in args.plot_avg_sources:
        plot_specs.append(('plot-avg', source))
    
    if not plot_specs:
        print("Error: At least one of --plot, --plot-min, --plot-avg, or --extract-min must be specified")
        parser.print_help()
        sys.exit(1)
    
    # Collect CSV files for validation and list-columns
    all_csv_files = []
    for plot_type, source in plot_specs:
        csv_files = collect_csv_files_from_source(source)
        all_csv_files.extend(csv_files)
    
    if not all_csv_files:
        print(f"Error: No CSV files found in specified sources")
        sys.exit(1)
    
    # If list-columns is specified, show available columns from the first CSV and exit
    if args.list_columns:
        try:
            first_csv = all_csv_files[0]
            df = pd.read_csv(first_csv)
            print(f"\nAvailable columns in {os.path.basename(first_csv)}:")
            for i, col in enumerate(df.columns, 1):
                print(f"{i:3d}. {col}")
            sys.exit(0)
        except Exception as e:
            print(f"Error reading CSV file: {str(e)}")
            sys.exit(1)
    
    # Validate date format if provided
    if args.start_date:
        try:
            pd.to_datetime(args.start_date)
        except:
            print(f"Error: Invalid start date format. Please use YYYY-MM-DD format.")
            sys.exit(1)
            
    if args.end_date:
        try:
            pd.to_datetime(args.end_date)
        except:
            print(f"Error: Invalid end date format. Please use YYYY-MM-DD format.")
            sys.exit(1)
    
    # Make sure end date is after start date if both are provided
    if args.start_date and args.end_date:
        start_dt = pd.to_datetime(args.start_date)
        end_dt = pd.to_datetime(args.end_date)
        if end_dt < start_dt:
            print("Error: End date must be after start date")
            sys.exit(1)
    
    plot_data(
        plot_specs,
        x_column=args.x_column,
        y_column=args.y_column,
        start_date=args.start_date,
        end_date=args.end_date,
        output_file=args.output,
    )

