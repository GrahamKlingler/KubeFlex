import os
import pandas as pd

# Configuration
input_folder = "avg/"  # <- Change this to your folder path
output_file = "output_min_by_datetime.csv"
datetime_column = "datetime"
target_column = "carbon_intensity_direct_avg"

# Collect all CSV files from the folder
csv_files = [os.path.join(input_folder, f) for f in os.listdir(input_folder) if f.endswith(".csv")]

# Read and concatenate all CSV files
df_list = [pd.read_csv(file) for file in csv_files]
combined_df = pd.concat(df_list, ignore_index=True)

# Convert datetime column to datetime type if it's not already
combined_df[datetime_column] = pd.to_datetime(combined_df[datetime_column])

# Sort by datetime and value, then drop duplicates to keep the row with the minimum value
sorted_df = combined_df.sort_values(by=[datetime_column, target_column])
result_df = sorted_df.drop_duplicates(subset=datetime_column, keep="first")

# Write result to CSV
result_df.to_csv(output_file, index=False)

print(f"Output written to {output_file}")
