import os
import glob
import pandas as pd
import numpy as np
from datetime import datetime

def process_carbon_intensity_csvs(directory_path, file_name):
    """
    Process all CSV files in the specified directory, calculating averages for all numerical metrics.
    
    Args:
        directory_path (str): Path to the directory containing the CSV files
        file_name (str): Path to save the output file
    """
    # Find all CSV files in the directory
    csv_files = glob.glob(os.path.join(directory_path, "*.csv"))
    
    if not csv_files:
        print(f"No CSV files found in {directory_path}")
        return
    
    print(f"Found {len(csv_files)} CSV files to process")
    
    # First, identify all numeric columns by reading the first file
    try:
        first_df = pd.read_csv(csv_files[0])
        # Check if datetime column exists
        if 'datetime' not in first_df.columns:
            print(f"Error: 'datetime' column not found in {os.path.basename(csv_files[0])}")
            return
            
        # Identify numeric columns (excluding datetime and other non-numeric columns)
        numeric_columns = []
        for column in first_df.columns:
            if column != 'datetime' and pd.api.types.is_numeric_dtype(first_df[column].dtype):
                numeric_columns.append(column)
                
        print(f"Found {len(numeric_columns)} numeric columns to average")
        
    except Exception as e:
        print(f"Error reading first CSV file: {str(e)}")
        return
    
    # Dictionary to store values for each datetime and metric
    datetime_to_metrics = {}
    datetime_to_counts = {}
    
    # Process each CSV file
    for csv_file in csv_files:
        try:
            print(f"Processing {os.path.basename(csv_file)}...")
            
            # Read CSV file
            df = pd.read_csv(csv_file)
            
            # Check if datetime column exists
            if 'datetime' not in df.columns:
                print(f"  Skipping {os.path.basename(csv_file)} - 'datetime' column not found")
                continue
            
            # Process each row
            for _, row in df.iterrows():
                datetime_str = row['datetime']
                
                # Initialize data structures for this datetime if needed
                if datetime_str not in datetime_to_metrics:
                    datetime_to_metrics[datetime_str] = {col: 0.0 for col in numeric_columns}
                    datetime_to_counts[datetime_str] = {col: 0 for col in numeric_columns}
                
                # Process each numeric column
                for column in numeric_columns:
                    if column in df.columns:
                        try:
                            # Only process if the value is not NaN
                            if column in row and not pd.isna(row[column]):
                                value = float(row[column])
                                datetime_to_metrics[datetime_str][column] += value
                                datetime_to_counts[datetime_str][column] += 1
                        except (ValueError, TypeError):
                            # Skip invalid values
                            continue
                    
        except Exception as e:
            print(f"  Error processing {os.path.basename(csv_file)}: {str(e)}")
    
    # Calculate averages
    result_data = []
    for datetime_str in datetime_to_metrics:
        row_data = {'datetime': datetime_str}
        
        # Calculate average for each metric
        for column in numeric_columns:
            count = datetime_to_counts[datetime_str][column]
            if count > 0:  # Only calculate average if we have values
                avg_value = datetime_to_metrics[datetime_str][column] / count
                row_data[column] = avg_value
            else:
                row_data[column] = np.nan  # Use NaN for metrics with no values
        
        result_data.append(row_data)
    
    # Create DataFrame from results
    result_df = pd.DataFrame(result_data)
    
    # Sort by datetime
    try:
        result_df['datetime'] = pd.to_datetime(result_df['datetime'])
        result_df = result_df.sort_values('datetime')
    except:
        # If datetime parsing fails, just sort by string
        result_df = result_df.sort_values('datetime')
    
    # Output file path
    output_file = file_name if file_name else os.path.join(directory_path, "average.csv")
    
    # Save to CSV
    result_df.to_csv(output_file, index=False)
    print(f"\nProcessing complete! Results saved to: {output_file}")
    print(f"Processed data from {len(csv_files)} files with {len(result_data)} unique timestamps")
    print(f"Calculated averages for {len(numeric_columns)} metrics")

if __name__ == "__main__":
    import sys
    
    if len(sys.argv) > 2:
        directory_path = sys.argv[1]
        file_name = sys.argv[2]
    elif len(sys.argv) > 1:
        directory_path = sys.argv[1]
        file_name = input("Enter the output file path (or press Enter for default): ") or None
    else:
        directory_path = input("Enter the directory path containing the CSV files: ")
        file_name = input("Enter the output file path (or press Enter for default): ") or None
    
    process_carbon_intensity_csvs(directory_path, file_name)