import os
import sys
import glob
import pandas as pd
import argparse
from datetime import datetime, timedelta
import plotly.graph_objects as go
from plotly.subplots import make_subplots


def plot_csv_data(directory_path, x_column='datetime', y_column='carbon_intensity_direct_avg', 
                  start_date=None, end_date=None, output_file=None):
    """
    Plot data from CSV files using any specified x and y columns.
    
    Args:
        directory_path (str): Path to directory containing CSV files
        x_column (str): Column name to use for x-axis (default: 'datetime')
        y_column (str): Column name to use for y-axis (default: 'carbon_intensity_direct_avg')
        start_date (str): Optional start date in YYYY-MM-DD format (if x-axis is datetime)
        end_date (str): Optional end date in YYYY-MM-DD format (if x-axis is datetime)
        output_file (str): Optional output file path for the HTML plot
    """
    # Find all CSV files in the directory
    csv_files = glob.glob(os.path.join(directory_path, "*.csv"))
    
    if not csv_files:
        print(f"No CSV files found in directory: {directory_path}")
        return
    
    print(f"Found {len(csv_files)} CSV files to plot")
    print(f"Plotting {y_column} against {x_column}")
    
    # Create a plotly figure
    fig = make_subplots(specs=[[{"secondary_y": False}]])
    
    # Check if we should attempt to use datetime filtering
    use_datetime_filtering = x_column.lower() in ['datetime', 'date', 'time', 'timestamp']
    
    # Process each CSV file
    for csv_file in csv_files:
        try:
            # Get filename without extension for the legend
            filename = os.path.basename(csv_file)
            file_label = os.path.splitext(filename)[0]
            
            print(f"Processing {filename}...")
            
            # Read CSV file
            df = pd.read_csv(csv_file)
            
            # Check for required columns
            if x_column not in df.columns:
                print(f"  Skipping {filename} - x-axis column '{x_column}' not found")
                continue
                
            if y_column not in df.columns:
                print(f"  Skipping {filename} - y-axis column '{y_column}' not found")
                continue
            
            # Handle datetime conversion if the x-axis is time-based
            if use_datetime_filtering:
                try:
                    # Convert to datetime and normalize timezone handling
                    # This handles formats like "2020-01-13 16:00:00+00:00"
                    df[x_column] = pd.to_datetime(df[x_column], utc=True)
                    
                    # Filter by date range if specified
                    if start_date:
                        start_datetime = pd.to_datetime(start_date, utc=True)
                        df = df[df[x_column] >= start_datetime]
                        
                    if end_date:
                        end_datetime = pd.to_datetime(end_date, utc=True)
                        # Add one day to include the end date fully
                        end_datetime = end_datetime + timedelta(days=1)
                        df = df[df[x_column] < end_datetime]
                except Exception as e:
                    print(f"  Warning: Failed to process {x_column} in {filename}: {str(e)}")
                    print("  Proceeding without datetime filtering")
            
            if df.empty:
                print(f"  No data in the specified range for {filename}")
                continue
                
            # Add trace for this dataset
            fig.add_trace(
                go.Scatter(
                    x=df[x_column],
                    y=df[y_column],
                    name=file_label,
                    mode='lines',
                    line=dict(width=2),
                    hovertemplate=
                    f'<b>%{{x}}</b><br>' +
                    f'{y_column}: %{{y:.2f}}<br>' +
                    f'<extra>{file_label}</extra>'
                )
            )
                
        except Exception as e:
            print(f"  Error processing {filename}: {str(e)}")
    
    # Check if we have any traces
    if len(fig.data) == 0:
        print("No valid data found in any CSV files. Nothing to plot.")
        return
    
    # Set up the plot appearance
    y_axis_title = y_column.replace('_', ' ').title()
    x_axis_title = x_column.replace('_', ' ').title()
    
    fig.update_layout(
        title=f"{y_axis_title} vs {x_axis_title}",
        title_font_size=20,
        xaxis_title=x_axis_title,
        yaxis_title=y_axis_title,
        legend_title="Data Sources",
        hovermode="closest",
        template="plotly_white",
        height=600,
        width=1000,
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
        output_file = f"{y_column}.html"
    
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

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Plot data from CSV files with flexible x and y axes")
    parser.add_argument("directory", help="Directory containing CSV files with data to plot")
    parser.add_argument("-x", "--x-column", default="datetime", 
                        help="Column name to use for x-axis (default: 'datetime')")
    parser.add_argument("-y", "--y-column", default="carbon_intensity_direct_avg", 
                        help="Column name to use for y-axis (default: 'carbon_intensity_direct_avg')")
    parser.add_argument("-s", "--start-date", help="Start date for the plot (YYYY-MM-DD) if x-axis is datetime")
    parser.add_argument("-e", "--end-date", help="End date for the plot (YYYY-MM-DD) if x-axis is datetime")
    parser.add_argument("-o", "--output", help="Output HTML file path")
    parser.add_argument("-l", "--list-columns", action="store_true", 
                        help="List all available columns in the CSV files and exit")
    
    args = parser.parse_args()
    
    # Check if directory exists
    if not os.path.isdir(args.directory):
        print(f"Error: Directory not found: {args.directory}")
        sys.exit(1)
    
    # If list-columns is specified, show available columns from the first CSV and exit
    if args.list_columns:
        csv_files = glob.glob(os.path.join(args.directory, "*.csv"))
        if not csv_files:
            print(f"No CSV files found in directory: {args.directory}")
            sys.exit(1)
        
        try:
            first_csv = csv_files[0]
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
        start = pd.to_datetime(args.start_date)
        end = pd.to_datetime(args.end_date)
        if end < start:
            print("Error: End date must be after start date")
            sys.exit(1)
    
    plot_csv_data(
        args.directory,
        x_column=args.x_column,
        y_column=args.y_column,
        start_date=args.start_date,
        end_date=args.end_date,
        output_file=args.output
    )