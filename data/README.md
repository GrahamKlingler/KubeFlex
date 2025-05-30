# Flexible CSV Plotting Script

A versatile Python script for creating interactive visualizations from CSV data files with customizable axes.

## Overview

This tool enables you to create interactive plots from CSV files, with complete flexibility over which columns to use for the x and y axes. It's particularly useful for analyzing time-series data with multiple metrics, such as carbon intensity measurements, power consumption data, or any other numerical data stored in CSV format.

## Listed Values:
1. datetime
  2. timestamp
  3. carbon_intensity_avg
  4. carbon_intensity_direct_avg
  5. carbon_intensity_production_avg
  6. carbon_intensity_discharge_avg
  7. carbon_intensity_import_avg
  8. total_production_avg
  9. total_storage_avg
 10. total_discharge_avg
 11. total_import_avg
 12. total_export_avg
 13. total_consumption_avg
 14. power_origin_percent_fossil_avg
 15. power_origin_percent_renewable_avg
 16. power_production_percent_fossil_avg
 17. power_production_percent_renewable_avg
 18. power_production_nuclear_avg
 19. power_production_geothermal_avg
 20. power_production_biomass_avg
 21. power_production_coal_avg
 22. power_production_wind_avg
 23. power_production_solar_avg
 24. power_production_hydro_avg
 25. power_production_gas_avg
 26. power_production_oil_avg
 27. power_production_unknown_avg
 28. power_consumption_nuclear_avg
 29. power_consumption_geothermal_avg
 30. power_consumption_biomass_avg
 31. power_consumption_coal_avg
 32. power_consumption_wind_avg
 33. power_consumption_solar_avg
 34. power_consumption_hydro_avg
 35. power_consumption_gas_avg
 36. power_consumption_oil_avg

## Features

- **Flexible axis selection**: Plot any column against any other column
- **Multiple file support**: Overlay data from multiple CSV files on a single plot
- **Interactive visualization**: Generated HTML plots include zoom, pan, and hover functionality
- **Date range filtering**: Filter time-series data by date range
- **Column discovery**: List available columns in your CSV files
- **Timezone-aware**: Properly handles datetime values with timezone information
- **Export options**: Save plots as interactive HTML or static PNG images

## Requirements

- Python 3.6+
- Required packages:
  - pandas
  - plotly
  - kaleido (optional, for PNG export)

Install dependencies:
```
pip install pandas plotly
pip install kaleido  # Optional, for PNG export
```

## Usage

### Basic Usage

```
python plot_average.py data_directory
```

This will use the default columns (`datetime` for x-axis and `carbon_intensity_direct_avg` for y-axis).

### Custom Column Selection

```
python plot_average.py data_directory -x column_name_x -y column_name_y
```

### List Available Columns

```
python plot_average.py data_directory -l
```

### Date Range Filtering

```
python plot_average.py data_directory -s 2023-01-01 -e 2023-12-31
```

### Custom Output File

```
python plot_average.py data_directory -o my_plot.html
```

## Arguments

| Argument | Short | Description |
|----------|-------|-------------|
| `--x-column` | `-x` | Column to use for x-axis (default: "datetime") |
| `--y-column` | `-y` | Column to use for y-axis (default: "carbon_intensity_direct_avg") |
| `--start-date` | `-s` | Start date for filtering (format: YYYY-MM-DD) |
| `--end-date` | `-e` | End date for filtering (format: YYYY-MM-DD) |
| `--output` | `-o` | Output HTML file path |
| `--list-columns` | `-l` | List all available columns in the first CSV file |

## Example Commands

### Plot Power Production vs. Time
```
python plot_average.py ./data -y power_production_wind_avg
```

### Compare Renewable vs. Fossil Fuel Production
```
python plot_average.py ./data -x power_production_percent_renewable_avg -y power_production_percent_fossil_avg
```

### Plot Carbon Intensity for a Specific Time Period
```
python plot_average.py ./data -y carbon_intensity_direct_avg -s 2023-01-01 -e 2023-03-31
```

## Output

The script generates:
1. An interactive HTML file with the plot
2. A static PNG image (if kaleido is installed)

## Data Format

The script is designed to work with CSV files containing:
- Any numerical data columns
- A datetime column (if time-series visualization is needed)
- Supports timezone information in datetime strings (e.g., "2020-01-13 16:00:00+00:00")

## Troubleshooting

- **No CSV files found**: Verify the directory path is correct
- **Column not found**: Use the `-l` flag to list available columns
- **Timezone errors**: The script automatically handles datetime columns with timezone information
- **PNG export fails**: Install kaleido with `pip install kaleido`


# Reading/Writing to db

The following commands run with a clean installation of Postgresql:latest,12>

## Run these commands:

Once data is compiled in CSV format (seen in /avg), place your file in a directory and run:
```
python3 upload_data.py [--dbname] [--user] [--port] [--host] directory table_name
```
If `table_name` does not exist, one will be created.

Accessing the database can be done with:
```
psql -h [host] -p [port] -U [user] 
```