import os
import glob
import pandas as pd
from datetime import datetime

def process_carbon_intensity_csvs(directory_path, file_name):
    """
    Process all CSV files in the specified directory that match the expected format,
    and create a new CSV with datetime and average direct carbon intensity.
    
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
    
    # Dictionary to store carbon intensity values for each datetime
    datetime_to_intensity = {}
    datetime_to_count = {}
    
    # Process each CSV file
    for csv_file in csv_files:
        try:
            print(f"Processing {os.path.basename(csv_file)}...")
            
            # Read CSV file
            df = pd.read_csv(csv_file)
            
            # Check if the required columns exist
            if 'datetime' not in df.columns or 'carbon_intensity_direct_avg' not in df.columns:
                print(f"  Skipping {os.path.basename(csv_file)} - required columns not found")
                continue
            
            # Process each row
            for _, row in df.iterrows():
                datetime_str = row['datetime']
                try:
                    carbon_intensity = float(row['carbon_intensity_direct_avg'])
                    
                    # Add to our data structure
                    if datetime_str in datetime_to_intensity:
                        datetime_to_intensity[datetime_str] += carbon_intensity
                        datetime_to_count[datetime_str] += 1
                    else:
                        datetime_to_intensity[datetime_str] = carbon_intensity
                        datetime_to_count[datetime_str] = 1
                except ValueError:
                    # Skip rows where carbon intensity is not a valid number
                    continue
                    
        except Exception as e:
            print(f"  Error processing {os.path.basename(csv_file)}: {str(e)}")
    
    # Calculate averages
    result_data = []
    for datetime_str in datetime_to_intensity:
        avg_intensity = datetime_to_intensity[datetime_str] / datetime_to_count[datetime_str]
        result_data.append({
            'datetime': datetime_str,
            'average_carbon_intensity_direct': avg_intensity
        })
    
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
    output_file = file_name if file_name else os.path.join(directory_path, "carbon_intensity_summary.csv")
    
    # Save to CSV
    result_df.to_csv(output_file, index=False)
    print(f"\nProcessing complete! Results saved to: {output_file}")
    print(f"Processed data from {len(csv_files)} files with {len(result_data)} unique timestamps")

if __name__ == "__main__":
    import sys
    
    if len(sys.argv) > 2:
        directory_path = sys.argv[1]
        file_name = sys.argv[2]
    else:
        directory_path = input("Enter the directory path containing the CSV files: ")
        file_name = input("Enter the output file path (or press Enter for default): ") or None
    
    process_carbon_intensity_csvs(directory_path, file_name)