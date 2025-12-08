import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import argparse
import glob
import os
import numpy as np
from datetime import datetime
from collections import defaultdict

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
            return None, None, None
        
        # Extract directory and filename for labeling
        dir_name = os.path.basename(os.path.dirname(file_path))
        file_name = os.path.basename(file_path).split('.')[0]
        
        # Include directory name in label if it's not the current directory
        if dir_name != '' and dir_name != '.':
            label = f"{dir_name}/{file_name}"
        else:
            label = file_name
        
        return df, label, dir_name
    except Exception as e:
        print(f"Error processing {file_path}: {e}")
        return None, None, None

def calculate_directory_averages(csv_files, columns_to_plot, start_time=None, end_time=None):
    """
    Calculate the average values for each column in each directory.
    Returns:
    - dir_averages: Dictionary of average values {directory: {column: average_value}}
    - dir_data: Dictionary of all data by directory {directory: {column: [values], 'time': [timestamps]}}
    """
    # Group files by directory
    files_by_dir = defaultdict(list)
    for file_path in csv_files:
        dir_name = os.path.basename(os.path.dirname(file_path))
        if dir_name == '' or dir_name == '.':
            dir_name = 'Current Directory'
        files_by_dir[dir_name].append(file_path)
    
    # Calculate averages for each directory
    dir_averages = {}
    dir_data = {}
    
    for dir_name, files in files_by_dir.items():
        # Initialize data collection for this directory
        dir_column_data = defaultdict(list)
        dir_time_data = []
        
        # Process each file in the directory
        for file_path in files:
            df, _, _ = load_and_process_csv(file_path, start_time, end_time)
            if df is not None:
                for column in columns_to_plot:
                    if column in df.columns:
                        dir_column_data[column].extend(df[column].tolist())
                        # Only collect timestamps once per file (they should be the same for all columns)
                        if column == columns_to_plot[0]:
                            dir_time_data.extend(df['Datetime (UTC)'].tolist())
        
        # Calculate averages
        dir_avg = {}
        for column, values in dir_column_data.items():
            if values:  # Check if the list is not empty
                dir_avg[column] = np.mean(values)
            else:
                dir_avg[column] = None
        
        dir_averages[dir_name] = dir_avg
        
        # Store all data for this directory for potential plotting
        data_dict = {column: values for column, values in dir_column_data.items()}
        data_dict['time'] = dir_time_data
        dir_data[dir_name] = data_dict
    
    return dir_averages, dir_data

def display_directory_averages(dir_averages, columns_to_plot):
    """
    Display a table of average values for each directory.
    """
    if not dir_averages:
        print("No data available to calculate averages.")
        return
    
    # Print header
    print("\nDirectory Averages:")
    header = "Directory".ljust(30)
    for column in columns_to_plot:
        short_name = column.split('(')[0].strip()
        if len(short_name) > 20:
            short_name = short_name[:17] + "..."
        header += short_name.ljust(25)
    print(header)
    print("-" * len(header))
    
    # Print averages for each directory
    for dir_name, averages in dir_averages.items():
        line = dir_name.ljust(30)
        for column in columns_to_plot:
            if column in averages and averages[column] is not None:
                line += f"{averages[column]:.2f}".ljust(25)
            else:
                line += "N/A".ljust(25)
        print(line)
    print()

def plot_carbon_data(csv_files, columns_to_plot, output_dir=None, show_plot=True, 
                     start_time=None, end_time=None, combined=False, plot_averages=False):
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
    
    # Calculate directory averages if requested
    if plot_averages:
        dir_averages, dir_data = calculate_directory_averages(
            csv_files, columns_to_plot, start_time, end_time
        )
    
    # Group files by directory for better organization of the legend
    files_by_dir = defaultdict(list)
    for file_path in csv_files:
        dir_name = os.path.basename(os.path.dirname(file_path))
        if dir_name == '' or dir_name == '.':
            dir_name = 'Current Directory'
        files_by_dir[dir_name].append(file_path)
    
    if combined:
        # Create a single plot with all columns
        plt.figure(figsize=(14, 8))
        
        # Plot individual file data
        for dir_name, files in files_by_dir.items():
            for file_path in files:
                df, file_label, _ = load_and_process_csv(file_path, start_time, end_time)
                if df is not None:
                    for column in columns_to_plot:
                        label = f"{file_label} - {column_labels.get(column, column)}"
                        plt.plot(df['Datetime (UTC)'], df[column], alpha=0.5, linewidth=1, label=label)
        
        # Plot directory averages if requested
        if plot_averages:
            for dir_name, sample_data in dir_averages.items():
                for column in columns_to_plot:
                    if column in sample_data and sample_data[column] is not None:
                        # Plot horizontal line for the average
                        avg_value = sample_data[column]
                        label = f"AVG {dir_name} - {column_labels.get(column, column)}"
                        
                        # Find time range for this directory
                        if dir_name in dir_data and 'time' in dir_data[dir_name] and dir_data[dir_name]['time']:
                            times = sorted(dir_data[dir_name]['time'])
                            plt.hlines(avg_value, times[0], times[-1], 
                                      linestyles='dashed', linewidth=2, 
                                      label=label)
        
        # Format the plot
        plt.xlabel('Time (UTC)')
        plt.ylabel('Value')
        plt.title('Carbon Metrics Over Time')
        plt.grid(True, alpha=0.3)
        
        # Place legend outside the plot to avoid overlap
        plt.legend(bbox_to_anchor=(1.05, 1), loc='upper left', borderaxespad=0.)
        
        # Format x-axis date labels
        plt.gca().xaxis.set_major_formatter(mdates.DateFormatter('%Y-%m-%d %H:%M'))
        plt.gcf().autofmt_xdate()
        
        plt.tight_layout()
        
        if output_dir:
            output_file = os.path.join(output_dir, 'combined_carbon_metrics.png')
            plt.savefig(output_file, bbox_inches='tight')
            print(f"Combined plot saved to {output_file}")
        
        if show_plot:
            plt.show()
    
    else:
        # Create a separate plot for each column
        for column in columns_to_plot:
            plt.figure(figsize=(14, 8))
            
            # Process each directory
            for dir_name, files in files_by_dir.items():
                # Plot individual file data
                for file_path in files:
                    df, file_label, _ = load_and_process_csv(file_path, start_time, end_time)
                    if df is not None:
                        plt.plot(df['Datetime (UTC)'], df[column], alpha=0.5, linewidth=1, label=file_label)
                
                # Plot directory average if requested
                if plot_averages and dir_name in dir_averages and column in dir_averages[dir_name]:
                    avg_value = dir_averages[dir_name][column]
                    if avg_value is not None:
                        # Find time range for this directory
                        if dir_name in dir_data and 'time' in dir_data[dir_name] and dir_data[dir_name]['time']:
                            times = sorted(dir_data[dir_name]['time'])
                            plt.hlines(avg_value, times[0], times[-1], 
                                      linestyles='dashed', linewidth=2, 
                                      label=f"AVG {dir_name}")
            
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
            
            # Place legend outside the plot to avoid overlap
            plt.legend(bbox_to_anchor=(1.05, 1), loc='upper left', borderaxespad=0.)
            
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
                # output_file = os.path.join(output_dir, f"{safe_name}.png")
                output_file = os.path.join(output_dir, f"year_round_percentage.png")
                plt.savefig(output_file, bbox_inches='tight')
                print(f"Plot saved to {output_file}")
            
            # Show the plot if requested
            if show_plot:
                plt.show()
            else:
                plt.close()

def collect_csv_files(directories=None, files=None):
    """
    Collect CSV files from multiple sources:
    - A list of directories
    - A list of file patterns
    Returns a list of file paths.
    """
    files_to_process = []
    
    # Process directories
    if directories:
        for directory in directories:
            dir_path = os.path.abspath(directory)
            if not os.path.isdir(dir_path):
                print(f"Warning: {dir_path} is not a valid directory")
                continue
            
            csv_pattern = os.path.join(dir_path, "*.csv")
            matched_files = glob.glob(csv_pattern)
            
            if not matched_files:
                print(f"Warning: No CSV files found in {dir_path}")
            else:
                files_to_process.extend(matched_files)
    
    # Process file patterns
    if files:
        for file_pattern in files:
            matched_files = glob.glob(file_pattern)
            if matched_files:
                files_to_process.extend(matched_files)
            else:
                print(f"Warning: No files found matching '{file_pattern}'")
    
    return files_to_process

def process_subdirectory(subdir_path, columns_to_plot, output_dir, show_plot, 
                         start_time, end_time, combined, plot_averages):
    """
    Process a single subdirectory and generate plots.
    """
    print(f"\nProcessing subdirectory: {subdir_path}")
    
    # Get CSV files in this subdirectory
    csv_pattern = os.path.join(subdir_path, "*.csv")
    files = glob.glob(csv_pattern)
    
    if not files:
        print(f"No CSV files found in {subdir_path}")
        return
    
    print(f"Found {len(files)} CSV files")
    
    # Create subdirectory-specific output directory if needed
    subdir_name = os.path.basename(subdir_path)
    subdir_output = os.path.join(output_dir, subdir_name) if output_dir else None
    
    if subdir_output and not os.path.exists(subdir_output):
        os.makedirs(subdir_output)
    
    # Calculate and display directory averages if requested
    if plot_averages:
        dir_averages, _ = calculate_directory_averages(
            files, columns_to_plot, start_time, end_time
        )
        display_directory_averages(dir_averages, columns_to_plot)
    
    # Plot the data
    plot_carbon_data(
        files,
        columns_to_plot,
        subdir_output,
        show_plot,
        start_time,
        end_time,
        combined,
        plot_averages
    )

def main():
    parser = argparse.ArgumentParser(description='Graph carbon data from CSV files.')
    
    # Input options
    input_group = parser.add_argument_group('Input Options')
    input_group.add_argument('--files', '-f', nargs='+', help='CSV files to process. Supports wildcards (e.g., *.csv).')
    input_group.add_argument('--directory', '-d', help='Directory containing CSV files to process (deprecated, use --directories instead).')
    input_group.add_argument('--directories', '-D', nargs='+', help='Directories containing CSV files to process. Multiple directories can be specified.')
    input_group.add_argument('--data-root', '-r', default='/data', 
                            help='Root data directory containing subdirectories to process automatically (default: /data)')
    input_group.add_argument('--process-subdirs', action='store_true',
                            help='Process each subdirectory in the data root directory separately')
    
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
    parser.add_argument('--output-dir', '-o', default='output', help='Output directory for saving plots (default: output)')
    parser.add_argument('--no-display', action='store_true', help='Do not display the plots')
    parser.add_argument('--combined', action='store_true', 
                        help='Combine all metrics into a single plot instead of separate plots')
    
    # Directory average options
    parser.add_argument('--show-averages', action='store_true',
                        help='Display a table of average values for each directory')
    parser.add_argument('--plot-averages', action='store_true',
                        help='Plot average lines for each directory on the graph')
    
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
    
    # Prepare the list of columns to plot
    columns_to_plot = args.columns
    
    # Add custom columns if specified
    if args.custom_columns:
        columns_to_plot.extend(args.custom_columns)
    
    # Create output directory if specified and doesn't exist
    if args.output_dir and not os.path.exists(args.output_dir):
        os.makedirs(args.output_dir)
    
    # Process each subdirectory separately if requested
    if args.process_subdirs:
        data_root = os.path.abspath(args.data_root)
        print(f"Processing all subdirectories in {data_root}")
        
        # Check if data root directory exists
        if not os.path.isdir(data_root):
            print(f"Error: Data root directory {data_root} does not exist")
            return
        
        # Get all subdirectories
        subdirs = [os.path.join(data_root, d) for d in os.listdir(data_root) 
                   if os.path.isdir(os.path.join(data_root, d))]
        
        if not subdirs:
            print(f"No subdirectories found in {data_root}")
            return
        
        print(f"Found {len(subdirs)} subdirectories to process")
        
        # Process each subdirectory
        for subdir in subdirs:
            process_subdirectory(
                subdir,
                columns_to_plot,
                args.output_dir,
                not args.no_display,
                start_time,
                end_time,
                args.combined,
                args.plot_averages or args.show_averages
            )
    else:
        # Handle backward compatibility for --directory
        directories = args.directories or []
        if args.directory:
            directories.append(args.directory)
        
        # Collect all files to process
        files_to_process = collect_csv_files(
            directories=directories,
            files=args.files
        )
        
        if not files_to_process:
            print("Error: No input files to process")
            return
        
        # Calculate and display directory averages if requested
        if args.show_averages:
            dir_averages, _ = calculate_directory_averages(
                files_to_process,
                columns_to_plot,
                start_time,
                end_time
            )
            display_directory_averages(dir_averages, columns_to_plot)
        
        # Plot the data
        plot_carbon_data(
            files_to_process,
            columns_to_plot,
            args.output_dir,
            not args.no_display,
            start_time,
            end_time,
            args.combined,
            args.plot_averages
        )

if __name__ == "__main__":
    main()