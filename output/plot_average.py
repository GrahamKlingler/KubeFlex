import os
import sys
import glob
import pandas as pd
import argparse
from datetime import datetime, timedelta
import plotly.graph_objects as go
from plotly.subplots import make_subplots


# To run this script, run:
# python3 plot_average.py averages

# where averages is the directory containing the CSV files with carbon intensity data.

# The script will read all CSV files in the specified directory, extract the carbon intensity data,

# For start, end date, and output file, you can use the following command:
# python3 plot_average.py averages -s 2023-01-01 -e 2023-12-31

# To view the interactive plot, open the generated HTML file in a web browser.
# xdg-open carbon_intensity_comparison.html

def plot_carbon_intensity_csvs(directory_path, start_date=None, end_date=None, output_file=None):
    """
    Plot all CSV files in a directory containing carbon intensity data on a single interactive graph.
    
    Args:
        directory_path (str): Path to directory containing CSV files
        start_date (str): Optional start date in YYYY-MM-DD format
        end_date (str): Optional end date in YYYY-MM-DD format
        output_file (str): Optional output file path for the HTML plot
    """
    # Find all CSV files in the directory
    csv_files = glob.glob(os.path.join(directory_path, "*.csv"))
    
    if not csv_files:
        print(f"No CSV files found in directory: {directory_path}")
        return
    
    print(f"Found {len(csv_files)} CSV files to plot")
    
    # Create a plotly figure
    fig = make_subplots(specs=[[{"secondary_y": False}]])
    
    # Process each CSV file
    for csv_file in csv_files:
        try:
            # Get filename without extension for the legend
            filename = os.path.basename(csv_file)
            file_label = os.path.splitext(filename)[0]
            
            print(f"Processing {filename}...")
            
            # Read CSV file
            df = pd.read_csv(csv_file)
            
            # Check for required columns - handle both possible column names
            datetime_col = None
            intensity_col = None
            
            if 'Datetime (UTC)' in df.columns:
                datetime_col = 'Datetime (UTC)'
            elif 'Datetime' in df.columns:
                datetime_col = 'Datetime'
            
            if 'Average Carbon Intensity gCO₂eq/kWh (direct)' in df.columns:
                intensity_col = 'Average Carbon Intensity gCO₂eq/kWh (direct)'
            elif 'Carbon intensity gCO₂eq/kWh (direct)' in df.columns:
                intensity_col = 'Carbon intensity gCO₂eq/kWh (direct)'
            
            if not datetime_col or not intensity_col:
                print(f"  Skipping {filename} - required columns not found")
                continue
            
            # Convert datetime string to datetime object
            df[datetime_col] = pd.to_datetime(df[datetime_col])
            
            # Filter by date range if specified
            if start_date:
                start_datetime = pd.to_datetime(start_date)
                df = df[df[datetime_col] >= start_datetime]
                
            if end_date:
                end_datetime = pd.to_datetime(end_date)
                # Add one day to include the end date fully
                end_datetime = end_datetime + timedelta(days=1)
                df = df[df[datetime_col] < end_datetime]
            
            if df.empty:
                print(f"  No data in the specified date range for {filename}")
                continue
                
            # Add trace for this dataset
            fig.add_trace(
                go.Scatter(
                    x=df[datetime_col],
                    y=df[intensity_col],
                    name=file_label,
                    mode='lines',
                    line=dict(width=2),
                    hovertemplate=
                    '<b>%{x}</b><br>' +
                    'Carbon Intensity: %{y:.2f} gCO₂eq/kWh<br>' +
                    '<extra>' + file_label + '</extra>'
                )
            )
                
        except Exception as e:
            print(f"  Error processing {filename}: {str(e)}")
    
    # Check if we have any traces
    if len(fig.data) == 0:
        print("No valid data found in any CSV files. Nothing to plot.")
        return
    
    # Set up the plot appearance
    fig.update_layout(
        title="Carbon Intensity Over Time",
        title_font_size=20,
        xaxis_title="Date & Time (UTC)",
        yaxis_title="Carbon Intensity (gCO₂eq/kWh)",
        legend_title="Data Sources",
        hovermode="closest",
        template="plotly_white",
        height=600,
        width=1000,
    )
    
    # Add date range selector
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
    
    output_file = "carbon_intensity_comparison.html"
    
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
    parser = argparse.ArgumentParser(description="Plot carbon intensity data from all CSV files in a directory")
    parser.add_argument("directory", help="Directory containing CSV files with carbon intensity data")
    parser.add_argument("-s", "--start-date", help="Start date for the plot (YYYY-MM-DD)")
    parser.add_argument("-e", "--end-date", help="End date for the plot (YYYY-MM-DD)")
    parser.add_argument("-o", "--output", help="Output HTML file path")
    
    args = parser.parse_args()
    
    # Check if directory exists
    if not os.path.isdir(args.directory):
        print(f"Error: Directory not found: {args.directory}")
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
    
    plot_carbon_intensity_csvs(
        args.directory,
        start_date=args.start_date,
        end_date=args.end_date,
        output_file=args.output
    )