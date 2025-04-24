# Flexible CSV Plotting Script

A versatile Python script for creating interactive visualizations from CSV data files with customizable axes.

## Overview

This tool enables you to create interactive plots from CSV files, with complete flexibility over which columns to use for the x and y axes. It's particularly useful for analyzing time-series data with multiple metrics, such as carbon intensity measurements, power consumption data, or any other numerical data stored in CSV format.

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