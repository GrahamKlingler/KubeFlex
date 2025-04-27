#!/usr/bin/env python3
"""
CSV to PostgreSQL Transfer Script

This script transfers the contents of all CSV files in a specified directory
to a specified PostgreSQL table.
"""

import os
import glob
import argparse
import csv
import psycopg2
from psycopg2 import sql
import pandas as pd
from tqdm import tqdm
import logging

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)

def connect_to_db(db_params):
    """Connect to PostgreSQL database."""
    try:
        connection = psycopg2.connect(**db_params)
        logger.info("Successfully connected to PostgreSQL database")
        return connection
    except psycopg2.Error as e:
        logger.error(f"Error connecting to PostgreSQL database: {e}")
        raise

def get_table_columns(conn, table_name, schema='public'):
    """Get column names for the specified table."""
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                SELECT column_name 
                FROM information_schema.columns 
                WHERE table_schema = %s AND table_name = %s
                ORDER BY ordinal_position
                """,
                (schema, table_name)
            )
            columns = [row[0] for row in cursor.fetchall()]
            
            if not columns:
                logger.error(f"No columns found for table {schema}.{table_name}")
                raise ValueError(f"Table {schema}.{table_name} does not exist or has no columns")
                
            return columns
    except psycopg2.Error as e:
        logger.error(f"Error fetching table columns: {e}")
        raise

def table_exists(conn, table_name, schema='public'):
    """Check if the specified table exists."""
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                SELECT EXISTS (
                    SELECT FROM information_schema.tables 
                    WHERE table_schema = %s AND table_name = %s
                )
                """,
                (schema, table_name)
            )
            return cursor.fetchone()[0]
    except psycopg2.Error as e:
        logger.error(f"Error checking if table exists: {e}")
        raise

def create_table_from_csv(conn, csv_path, table_name, schema='public'):
    """Create table based on CSV structure if it doesn't exist."""
    try:
        # Read CSV header and sample data to infer types
        df = pd.read_csv(csv_path, nrows=5)
        
        # Create SQL for table creation
        create_table_query = sql.SQL("CREATE TABLE {}.{} (\n").format(
            sql.Identifier(schema), sql.Identifier(table_name)
        )
        
        # Map pandas dtypes to PostgreSQL types
        column_definitions = []
        for column, dtype in df.dtypes.items():
            pg_type = "TEXT"  # default type
            
            if pd.api.types.is_integer_dtype(dtype):
                pg_type = "BIGINT"
            elif pd.api.types.is_float_dtype(dtype):
                pg_type = "DOUBLE PRECISION"
            elif pd.api.types.is_datetime64_any_dtype(dtype):
                pg_type = "TIMESTAMP"
            elif pd.api.types.is_bool_dtype(dtype):
                pg_type = "BOOLEAN"
                
            column_definitions.append(
                sql.SQL("{} {}").format(sql.Identifier(column), sql.SQL(pg_type))
            )
        
        create_table_query += sql.SQL(",\n").join(column_definitions)
        create_table_query += sql.SQL("\n)")
        
        # Execute table creation
        with conn.cursor() as cursor:
            cursor.execute(create_table_query)
            conn.commit()
            logger.info(f"Created table {schema}.{table_name}")
    except Exception as e:
        conn.rollback()
        logger.error(f"Error creating table from CSV: {e}")
        raise

def copy_csv_to_table(conn, csv_path, table_name, schema='public'):
    """Copy data from a CSV file to the specified table."""
    try:
        # Get table columns to ensure we're matching them
        table_columns = get_table_columns(conn, table_name, schema)
        
        # Read CSV file
        df = pd.read_csv(csv_path)
        
        # Check if CSV columns match table columns (case-insensitive)
        csv_columns_lower = [col.lower() for col in df.columns]
        table_columns_lower = [col.lower() for col in table_columns]
        
        # Get intersection of columns (those that exist in both CSV and table)
        common_columns_indices = [
            i for i, col in enumerate(csv_columns_lower) 
            if col in table_columns_lower
        ]
        
        if not common_columns_indices:
            logger.error(f"No matching columns found between CSV and table")
            return 0
        
        # Get the actual column names from the CSV
        common_columns = [df.columns[i] for i in common_columns_indices]
        
        # Map CSV columns to table columns (preserving table column case)
        column_mapping = {}
        for csv_col in common_columns:
            for table_col in table_columns:
                if csv_col.lower() == table_col.lower():
                    column_mapping[csv_col] = table_col
                    break
        
        # Prepare data for insertion
        data_to_insert = df[common_columns]
        
        # Generate placeholders for each row
        placeholders = sql.SQL(', ').join(
            sql.Placeholder() * len(common_columns)
        )
        
        # Generate column identifiers
        columns = sql.SQL(', ').join(
            sql.Identifier(column_mapping[col]) for col in common_columns
        )
        
        # Create the insert query
        insert_query = sql.SQL("INSERT INTO {}.{} ({}) VALUES ({})").format(
            sql.Identifier(schema),
            sql.Identifier(table_name),
            columns,
            placeholders
        )
        
        # Execute in batches
        batch_size = 1000
        rows_inserted = 0
        
        with conn.cursor() as cursor:
            with tqdm(total=len(data_to_insert), desc=f"Inserting from {os.path.basename(csv_path)}") as progress_bar:
                for i in range(0, len(data_to_insert), batch_size):
                    batch = data_to_insert.iloc[i:i+batch_size]
                    batch_data = [tuple(row) for row in batch.values]
                    cursor.executemany(insert_query, batch_data)
                    conn.commit()
                    rows_inserted += len(batch)
                    progress_bar.update(len(batch))
        
        logger.info(f"Inserted {rows_inserted} rows from {os.path.basename(csv_path)} into {schema}.{table_name}")
        return rows_inserted
        
    except Exception as e:
        conn.rollback()
        logger.error(f"Error copying CSV to table: {e}")
        raise

def process_directory(conn, directory_path, table_name, schema='public'):
    """Process all CSV files in the specified directory."""
    # Check if directory exists
    if not os.path.isdir(directory_path):
        logger.error(f"Directory {directory_path} does not exist")
        raise ValueError(f"Directory {directory_path} does not exist")
    
    # Find all CSV files
    csv_files = glob.glob(os.path.join(directory_path, "*.csv"))
    
    if not csv_files:
        logger.warning(f"No CSV files found in {directory_path}")
        return 0
    
    logger.info(f"Found {len(csv_files)} CSV files to process")
    
    # Check if table exists, create it from first CSV if needed
    if not table_exists(conn, table_name, schema):
        logger.info(f"Table {schema}.{table_name} does not exist, creating it based on first CSV")
        create_table_from_csv(conn, csv_files[0], table_name, schema)
    
    # Process each CSV file
    total_rows = 0
    for csv_file in csv_files:
        try:
            logger.info(f"Processing: {os.path.basename(csv_file)}")
            rows = copy_csv_to_table(conn, csv_file, table_name, schema)
            total_rows += rows
        except Exception as e:
            logger.error(f"Error processing {csv_file}: {e}")
            # Continue with next file
            continue
    
    logger.info(f"Total rows inserted: {total_rows}")
    return total_rows

def main():
    parser = argparse.ArgumentParser(description='Transfer CSV files to PostgreSQL table.')
    
    parser.add_argument('directory', type=str, help='Directory containing CSV files')
    parser.add_argument('table_name', type=str, help='Target table name')
    parser.add_argument('--schema', type=str, default='public', help='Database schema (default: public)')
    
    # Database connection parameters
    parser.add_argument('--host', type=str, default='localhost', help='Database host')
    parser.add_argument('--port', type=int, default=5432, help='Database port')
    parser.add_argument('--dbname', type=str, required=True, help='Database name')
    parser.add_argument('--user', type=str, required=True, help='Database user')
    parser.add_argument('--password', type=str, help='Database password')
    
    parser.add_argument('--log-file', type=str, help='Path to log file')
    
    args = parser.parse_args()
    
    # If log file is specified, add file handler
    if args.log_file:
        file_handler = logging.FileHandler(args.log_file)
        file_handler.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))
        logger.addHandler(file_handler)
    
    # Set up database connection parameters
    db_params = {
        'host': args.host,
        'port': args.port,
        'dbname': args.dbname,
        'user': args.user
    }
    
    if args.password:
        db_params['password'] = args.password
    
    # Connect to database and process files
    try:
        connection = connect_to_db(db_params)
        process_directory(connection, args.directory, args.table_name, args.schema)
        connection.close()
        logger.info("Processing completed successfully")
        return 0
    except Exception as e:
        logger.error(f"Error in main execution: {e}")
        return 1

if __name__ == "__main__":
    exit(main())