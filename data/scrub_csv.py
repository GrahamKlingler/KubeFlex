import csv
import argparse
from datetime import datetime

def transform_csv(input_file):
    # Columns to retain and transform
    columns_to_keep = [
        'datetime', 'timestamp', 'carbon_intensity_avg', 'carbon_intensity_direct_avg',
        'carbon_intensity_production_avg', 'carbon_intensity_discharge_avg',
        'carbon_intensity_import_avg', 'total_production_avg', 'total_storage_avg',
        'total_discharge_avg', 'total_import_avg', 'total_export_avg', 'total_consumption_avg',
        'power_origin_percent_fossil_avg', 'power_origin_percent_renewable_avg',
        'power_production_percent_fossil_avg', 'power_production_percent_renewable_avg',
        'power_production_nuclear_avg', 'power_production_geothermal_avg',
        'power_production_biomass_avg', 'power_production_coal_avg',
        'power_production_wind_avg', 'power_production_solar_avg',
        'power_production_hydro_avg', 'power_production_gas_avg',
        'power_production_oil_avg', 'power_production_unknown_avg',
        'power_consumption_nuclear_avg', 'power_consumption_geothermal_avg',
        'power_consumption_biomass_avg', 'power_consumption_coal_avg',
        'power_consumption_wind_avg', 'power_consumption_solar_avg',
        'power_consumption_hydro_avg', 'power_consumption_gas_avg',
        'power_consumption_oil_avg', 'power_consumption_unknown_avg',
        'power_consumption_battery_discharge_avg', 'power_consumption_hydro_discharge_avg',
        'power_net_discharge_battery_avg'
    ]

    output_file = input_file.split('/')[-1]
    source_value = output_file.split('.')[0]  # Extracting the source from the filename

    with open(input_file, mode='r', newline='', encoding='utf-8') as infile:
        reader = csv.DictReader(infile)

        with open(output_file, mode='w', newline='', encoding='utf-8') as outfile:
            fieldnames = columns_to_keep + ['source']
            writer = csv.DictWriter(outfile, fieldnames=fieldnames)
            writer.writeheader()

            for row in reader:
                new_row = {}
                for col in columns_to_keep:
                    value = row.get(col, '').strip()
                    new_row[col] = value if value else ''
                if 'datetime' in new_row:
                    try:
                        new_row['datetime'] = datetime.fromisoformat(new_row['datetime']).isoformat()
                    except ValueError:
                        pass  # leave as is if not parsable
                new_row['source'] = source_value
                writer.writerow(new_row)

def main():
    parser = argparse.ArgumentParser(description="Transform CSV file to required format.")
    parser.add_argument('input_file', help='Path to the input CSV file')

    args = parser.parse_args()
    transform_csv(args.input_file)

if __name__ == '__main__':
    main()
