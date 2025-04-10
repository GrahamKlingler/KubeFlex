import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import argparse
import glob
import os
from datetime import datetime

def load_and_process_csv(file_path, start_time=None, end_time=None):
    """
    Load and process a single CSV file with optional time filtering.
    """
    try:
        # Read the CSV file
        df = pd.read_csv(file_path)
        
        # Convert datetime string to datetime object
        df['Datetime (UTC)'] = pd.to_datetime(df['Datetime (UTC)'])
        
        # Apply time filters if specified
        if start_time:
            df = df[df['Datetime (UTC)'] >= start_time]
        if end_time:
            df = df[df['Datetime (UTC)'] <= end_time]
            
        # Check if any data remains after filtering
        if df.empty:
            print(f"Warning: No data in {file_path} after applying time filters")
            return None, None
        
        # Extract filename without extension for labeling
        file_name = os.path.basename(file_path).split('.')[0]
        
        return df, file_name
    except Exception as e:
        print(f"Error processing {file_path}: {e}")
        return None, None

def plot_carbon_data(csv_files, columns_to_plot, output_dir=None, show_plot=True, 
                     start_time=None, end_time=None, combined=False):
    """
    Plot carbon data from multiple CSV files.
    If combined is True, plot all columns on the same graph.
    Otherwise, create a separate plot for each column.
    """
    # Map column names to more readable labels
    column_labels = {
        'Carbon intensity gCO₂eq/kWh (direct)': 'Direct Carbon Intensity',
        'Carbon intensity gCO₂eq/kWh (Life cycle)': 'Life Cycle Carbon Intensity',
        'Carbon-free energy percentage (CFE%)': 'Carbon-free Energy %',
        'Renewable energy percentage (RE%)': 'Renewable Energy %'
    }
    
    if combined:
        # Create a single plot with all columns
        plt.figure(figsize=(14, 8))
        
        # Process each CSV file
        for file_path in csv_files:
            df, file_name = load_and_process_csv(file_path, start_time, end_time)
            if df is not None:
                for column in columns_to_plot:
                    label = f"{file_name} - {column_labels.get(column, column)}"
                    plt.plot(df['Datetime (UTC)'], df[column], label=label)
        
        # Format the plot
        plt.xlabel('Time (UTC)')
        plt.ylabel('Value')
        plt.title('Carbon Metrics Over Time')
        plt.grid(True, alpha=0.3)
        plt.legend()
        
        # Format x-axis date labels
        plt.gca().xaxis.set_major_formatter(mdates.DateFormatter('%Y-%m-%d %H:%M'))
        plt.gcf().autofmt_xdate()
        
        plt.tight_layout()
        
        if output_dir:
            output_file = os.path.join(output_dir, 'combined_carbon_metrics.png')
            plt.savefig(output_file)
            print(f"Combined plot saved to {output_file}")
        
        if show_plot:
            plt.show()
    
    else:
        # Create a separate plot for each column
        for column in columns_to_plot:
            plt.figure(figsize=(12, 6))
            
            # Process each CSV file
            for file_path in csv_files:
                df, file_name = load_and_process_csv(file_path, start_time, end_time)
                if df is not None:
                    plt.plot(df['Datetime (UTC)'], df[column], label=file_name)
            
            # Format the plot
            plt.xlabel('Time (UTC)')
            
            # Use the friendly label if available, otherwise use the column name
            y_label = column_labels.get(column, column)
            plt.ylabel(y_label)
            
            # Generate title with time range if specified
            title = f'{y_label} Over Time'
            if start_time and end_time:
                time_range = f"({start_time.strftime('%Y-%m-%d')} to {end_time.strftime('%Y-%m-%d')})"
                title = f'{title} {time_range}'
            
            plt.title(title)
            plt.grid(True, alpha=0.3)
            plt.legend()
            
            # Format x-axis date labels
            plt.gca().xaxis.set_major_formatter(mdates.DateFormatter('%Y-%m-%d %H:%M'))
            plt.gcf().autofmt_xdate()
            
            # Set y-axis to start from 0 for percentage values
            if 'percentage' in column.lower():
                plt.ylim(bottom=0, top=100)
            elif 'carbon intensity' in column.lower():
                plt.ylim(bottom=0)
            
            plt.tight_layout()
            
            # Save the plot if an output directory is specified
            if output_dir:
                # Create a safe filename from the column name
                safe_name = column.replace(' ', '_').replace('/', '_').replace('%', 'pct')
                output_file = os.path.join(output_dir, f"{safe_name}.png")
                plt.savefig(output_file)
                print(f"Plot saved to {output_file}")
            
            # Show the plot if requested
            if show_plot:
                plt.show()
            else:
                plt.close()

def main():
    parser = argparse.ArgumentParser(description='Graph carbon data from CSV files.')
    
    # Input options
    input_group = parser.add_mutually_exclusive_group(required=True)
    input_group.add_argument('--files', '-f', nargs='+', help='CSV files to process. Supports wildcards (e.g., *.csv).')
    input_group.add_argument('--directory', '-d', help='Directory containing CSV files to process.')
    
    # Column selection
    parser.add_argument('--columns', '-c', nargs='+', 
                        default=['Carbon intensity gCO₂eq/kWh (direct)'],
                        help='Columns to plot (multiple allowed). Available columns: '
                             'Carbon intensity gCO₂eq/kWh (direct), '
                             'Carbon intensity gCO₂eq/kWh (Life cycle), '
                             'Carbon-free energy percentage (CFE%), '
                             'Renewable energy percentage (RE%)')
    
    # Custom column handling
    parser.add_argument('--custom-columns', nargs='+', 
                        help='Custom column names to plot that are not in the predefined list')
    
    # Time filtering
    parser.add_argument('--start-time', help='Start time filter (YYYY-MM-DD [HH:MM:SS])')
    parser.add_argument('--end-time', help='End time filter (YYYY-MM-DD [HH:MM:SS])')
    
    # Output options
    parser.add_argument('--output-dir', '-o', help='Output directory for saving plots')
    parser.add_argument('--no-display', action='store_true', help='Do not display the plots')
    parser.add_argument('--combined', action='store_true', 
                        help='Combine all metrics into a single plot instead of separate plots')
    
    args = parser.parse_args()
    
    # Process start and end times if provided
    start_time = None
    end_time = None
    
    if args.start_time:
        try:
            start_time = pd.to_datetime(args.start_time)
        except:
            print(f"Error parsing start time: {args.start_time}. Using format YYYY-MM-DD [HH:MM:SS]")
            return
    
    if args.end_time:
        try:
            end_time = pd.to_datetime(args.end_time)
        except:
            print(f"Error parsing end time: {args.end_time}. Using format YYYY-MM-DD [HH:MM:SS]")
            return
    
    # Collect all files to process
    files_to_process = []
    
    if args.directory:
        # Get all CSV files in the specified directory
        dir_path = os.path.abspath(args.directory)
        if not os.path.isdir(dir_path):
            print(f"Error: {dir_path} is not a valid directory")
            return
        
        csv_pattern = os.path.join(dir_path, "*.csv")
        files_to_process = glob.glob(csv_pattern)
        
        if not files_to_process:
            print(f"Error: No CSV files found in {dir_path}")
            return
    else:
        # Expand file wildcards from command line arguments
        for file_pattern in args.files:
            matched_files = glob.glob(file_pattern)
            if matched_files:
                files_to_process.extend(matched_files)
            else:
                print(f"Warning: No files found matching '{file_pattern}'")
    
    if not files_to_process:
        print("Error: No input files to process")
        return
    
    # Prepare the list of columns to plot
    columns_to_plot = args.columns
    
    # Add custom columns if specified
    if args.custom_columns:
        columns_to_plot.extend(args.custom_columns)
    
    # Create output directory if specified and doesn't exist
    if args.output_dir and not os.path.exists(args.output_dir):
        os.makedirs(args.output_dir)
    
    # Plot the data
    plot_carbon_data(
        files_to_process,
        columns_to_plot,
        args.output_dir,
        not args.no_display,
        start_time,
        end_time,
        args.combined
    )

if __name__ == "__main__":
    main()