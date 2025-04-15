# Carbon Data Grapher

A Python utility for visualizing carbon intensity and renewable energy data from multiple CSV files.

## Overview

This tool helps visualize and compare carbon metrics across multiple data files or time periods. It's designed to work with CSV files containing time-series data of carbon intensity, carbon-free energy percentage, and renewable energy percentage.

### Setup

1. Install the required dependencies:

```
pip install pandas matplotlib
```

2. Download the `carbon_grapher.py` script

## Usage

### Basic Usage

```bash
# Plot files individually
python carbon_grapher.py --files data1.csv data2.csv

# Process all CSVs in a directory
python carbon_grapher.py --directory ./carbon_data/
```

Corresponding dataset locations can be found at `https://portal.electricitymaps.com/datasets/US`

### Sample Usage
Refers to the `/data` directory to display data from a state's metrics over the first day of the year.
```bash
python3 chart_data.py --start-time "2024-01-01" --end-time "2024-01-01 23:59:59" --directory ./data/
```

### Command Line Options

| Option | Description |
|--------|-------------|
| `--files`, `-f` | CSV files to process. Supports wildcards (e.g., *.csv) |
| `--directory`, `-d` | Directory containing CSV files to process |
| `--columns`, `-c` | Columns to plot (multiple allowed) |
| `--custom-columns` | Custom column names not in the predefined list |
| `--start-time` | Start time filter (YYYY-MM-DD [HH:MM:SS]) |
| `--end-time` | End time filter (YYYY-MM-DD [HH:MM:SS]) |
| `--output-dir`, `-o` | Output directory for saving plots |
| `--no-display` | Do not display the plots (useful for batch processing) |
| `--combined` | Combine all metrics into a single plot |

### Available Default Columns

- `Carbon intensity gCO₂eq/kWh (direct)` - Direct carbon emissions
- `Carbon intensity gCO₂eq/kWh (Life cycle)` - Life cycle carbon emissions
- `Carbon-free energy percentage (CFE%)` - Percentage of carbon-free energy
- `Renewable energy percentage (RE%)` - Percentage of renewable energy

### Examples

#### Plot data from a specific time period

```bash
python carbon_grapher.py --start-time "2024-01-01" --end-time "2024-01-31" --directory ./data/
```

#### Plot multiple metrics on separate graphs

```bash
python carbon_grapher.py --columns "Carbon intensity gCO₂eq/kWh (direct)" "Renewable energy percentage (RE%)" --directory ./data/
```

#### Combine multiple metrics on one graph

```bash
python carbon_grapher.py --files *.csv --columns "Carbon intensity gCO₂eq/kWh (direct)" "Renewable energy percentage (RE%)" --combined
```

#### Save plots to a directory without displaying them

```bash
python carbon_grapher.py --directory ./data/ --output-dir ./plots/ --no-display 
```

#### Plot custom columns from your CSV

```bash
python carbon_grapher.py --directory ./data/ --custom-columns "Your Custom Column Name" "Another Custom Column"
```

## Input Data Format

The script expects CSV files with the following structure:

```
Datetime (UTC),Country,Zone name,Zone id,Carbon intensity gCO₂eq/kWh (direct),Carbon intensity gCO₂eq/kWh (Life cycle),Carbon-free energy percentage (CFE%),Renewable energy percentage (RE%),Data source,Data estimated,Data estimation method
2024-01-01 00:00:00,USA,Duke Energy Progress East,US-CAR-CPLE,230.43,286.46,58.57,2.83,eia.gov,false,
```

At minimum, the CSV must contain:
- A column named `Datetime (UTC)` with datetime values
- At least one of the carbon/energy metrics columns to plot

## Output

- Interactive plots displayed in a window (unless `--no-display` is used)
- PNG image files saved to the specified output directory (when `--output-dir` is provided)

## Troubleshooting

### Common Issues

1. **No data after applying time filters**
   - Check that your start/end times fall within the range of data in your CSV files
   - Verify the datetime format matches YYYY-MM-DD [HH:MM:SS]

2. **Missing columns error**
   - Ensure your CSV files contain the columns you're trying to plot
   - Use `--custom-columns` for columns not in the default list

3. **No files found**
   - Check that the specified directory contains CSV files
   - Verify file paths and permissions

## License

This tool is provided as open-source software under the MIT License.

## Acknowledgments

This tool was created to visualize carbon intensity and renewable energy data from various energy providers.